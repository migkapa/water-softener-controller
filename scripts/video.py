#!/usr/bin/env python3
"""Short presentation video of the controller (about 21 s, 1280 x 720, H.264).

Run with the Python that ships inside KiCad; `python3 scripts/build.py --video`
does that.  Needs ffmpeg on the PATH and the enclosure models written by
`--product`.

The film: schematic and copper as dark "blueprints", the bare board turning,
the enclosure closing round it, a turn of the finished unit, the wiring door
coming off, a look through the cover, and a closing card.  Every 3D frame is a
KiCad ray-traced render of the real board inside the enclosure models; frames
are cached, so a second run only renders what changed.

    video.py [--cache DIR] [--storyboard]      # --storyboard: a sheet of 12 stills, no film
    video.py --closing 'LABEL|HEADLINE|LINE BELOW' --out FILE.mp4 [--crf 19]
                                               # a cut with a different closing card (/ = line break)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import enclosure as E  # noqa: E402

W, H, FPS = 1280, 720, 30
ROOT = E.ROOT
FILM = os.path.join(E.OUT, 'water_softener_controller.mp4')
ACCENT = (96, 208, 240)
WHITE = (240, 244, 248)
SOFT = (150, 164, 180)

# ---- timeline (seconds) ---------------------------------------------------------
T_SCH, T_CU, T_BRD = 2.2, 2.2, 2.6            # schematic, copper, bare board
# the product sequence: time, tilt, turn, exploded 0..1, door off 0..1, see-through 0..1
KEYS = [
    (0.0, -66, -36, 1, 0, 0),
    (0.4, -66, -35, 1, 0, 0),
    (2.2, -54, -29, 0, 0, 0),
    (2.7, -52, -27, 0, 0, 0),
    (5.5, -52, 22, 0, 0, 0),
    (6.2, -44, 16, 0, 0, 0),
    (7.1, -40, 11, 0, 1, 0),
    (8.1, -40, 7, 0, 1, 0),
    (8.6, -36, 4, 0, 0, 0),
    (9.6, -14, 0, 0, 0, 1),
    (10.8, -12, 0, 0, 0, 1),
    (12.1, -52, -27, 0, 0, 0),
    (14.0, -52, -23, 0, 0, 0),
]
T_PROD = KEYS[-1][0]
T0_CU, T0_BRD, T0_PROD = T_SCH, T_SCH + T_CU, T_SCH + T_CU + T_BRD
TOTAL = T0_PROD + T_PROD
FADE = 0.35                                    # cross-fade between sections

# captions: start, end, label, headline, line below
CAPTIONS = [
    (0.0, T0_CU, '01 · SCHEMATIC', '111 parts on\nfive sheets', 'ESP32-C6, 12 V valve drive,\nflow, salt and leak inputs'),
    (T0_CU, T0_BRD, '02 · BOARD', '120 × 80 mm,\nfour layers', 'Routed by a script,\ndesign rules clean'),
    (T0_BRD, T0_PROD, '02 · BOARD', 'Everything on\none side', 'Wi-Fi 6, BLE, 802.15.4,\nrelay, real-time clock'),
    (T0_PROD, T0_PROD + 2.9, '03 · ENCLOSURE', 'Three shells,\nfour screws', 'Checked for collisions\nagainst the real board'),
    (T0_PROD + 2.9, T0_PROD + 6.3, 'REV A DESIGN', 'Water Softener\nController', 'Wall mount · 12 V\n127 × 118 × 29 mm'),
    (T0_PROD + 6.3, T0_PROD + 8.7, 'WIRING BAY', 'Plug-in terminals,\nevery pin labelled', 'Motor, flow meter, salt sensor,\nleak probe, relay'),
    (T0_PROD + 8.7, T0_PROD + 11.5, 'INSIDE', 'Display, keys\nand light line up\nwith the board', 'OLED, three keys,\nstatus LED, sounder'),
    (T0_PROD + 11.5, TOTAL + 1, 'DESIGNED IN CODE', 'Schematic, board,\nenclosure, this film', 'KiCad · OpenSCAD · Python'),
]

LIGHTS = ['--light-camera', '0.2', '--light-side', '0.55', '--light-top', '0.42', '--light-bottom', '0.2',
          '--light-side-elevation', '30']
PRODUCT_PIVOT = '0,-1.55,0'       # the enclosure's middle is 15.5 mm below the board's
GAIN_X, GAIN_Y = 0.050, 0.0893    # share of the frame one unit of --pan moves the picture, at zoom 1
CENTRE = (0.67, 0.475)            # where the model sits in the frame; the text has the left side


# ---- small maths -------------------------------------------------------------------
def pchip(ts, vs, t):
    """Smooth interpolation through key values without overshoot; rests at both ends."""
    ts, vs = np.asarray(ts, float), np.asarray(vs, float)
    h = np.diff(ts)
    d = np.diff(vs) / h
    m = np.zeros(len(ts))
    for k in range(1, len(ts) - 1):
        if d[k - 1] * d[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    t = np.clip(np.asarray(t, float), ts[0], ts[-1])
    k = np.clip(np.searchsorted(ts, t, 'right') - 1, 0, len(ts) - 2)
    s = (t - ts[k]) / h[k]
    return ((2 * s ** 3 - 3 * s ** 2 + 1) * vs[k] + (s ** 3 - 2 * s ** 2 + s) * h[k] * m[k]
            + (-2 * s ** 3 + 3 * s ** 2) * vs[k + 1] + (s ** 3 - s ** 2) * h[k] * m[k + 1])


def smooth(a, b, x):
    x = min(max((x - a) / (b - a), 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ---- what is in the scene at a given moment -------------------------------------------
def product_state(tau):
    cols = list(zip(*KEYS))
    rx, rz, e, d, x = (float(pchip(cols[0], c, tau)) for c in cols[1:])
    e, d, x = (min(max(v, 0.0), 1.0) for v in (e, d, x))
    show, offsets, opacity = [], {}, {}
    for g in E.CLOSED:
        ox, oy, oz = (e * v for v in E.EXPLODE.get(g, (0, 0, 0)))
        op = 1.0
        if g in ('door', 'door_screw'):
            oy -= 16 * d
            oz += 44 * d
            op *= 1 - smooth(0.5, 1.0, d)
        if g in ('cover', 'door'):
            op *= 1 - 0.78 * x
        if op < 0.03:
            continue
        show.append(g)
        offsets[g] = (round(ox, 2), round(oy, 2), round(oz, 2))
        opacity[g] = round(op, 2)
    fill = 0.62 + 0.16 * e + 0.12 * x
    return dict(show=show, offsets=offsets, opacity=opacity, rot=(round(rx, 2), round(rz, 2)),
                pivot=PRODUCT_PIVOT, fill=round(fill, 3), wide=0.54)


def board_state(tau):
    u = smooth(0, T_BRD, tau)
    return dict(show=['oled', 'sounder'], offsets={}, opacity={}, rot=(round(-50 + 3 * u, 2), round(-42 + 30 * u, 2)),
                pivot='0,0,0', fill=0.62, wide=round(0.56 + 0.03 * u, 3))


def scene_key(st):
    return json.dumps([st['show'], st['offsets'], st['opacity']], sort_keys=True)


# ---- KiCad renders ----------------------------------------------------------------------
class Renderer:
    def __init__(self, cache):
        import build as B
        self.B, self.env, self.cache = B, B.kicad_env(), cache
        os.makedirs(cache, exist_ok=True)
        self.board = os.path.join(ROOT, '_view.kicad_pcb')
        self.loaded = None
        self.fits = {}
        self.fit_file = os.path.join(cache, 'fits.json')
        if os.path.exists(self.fit_file):
            self.fits = json.load(open(self.fit_file))

    def scene(self, st):
        key = scene_key(st)
        if key != self.loaded:
            E.view_board(self.board, st['show'], st['offsets'], st['opacity'])
            self.loaded = key

    def camera(self, st, zoom, pan):
        return ['--side', 'top', '--perspective', '--pivot', st['pivot'], '--rotate', '%.2f,0,%.2f' % st['rot'],
                '--zoom', '%.4f' % zoom, '--pan', '%.4f,%.4f,0' % tuple(pan)]

    def outline(self, st, zoom, pan):
        tmp = os.path.join(self.cache, 'probe.png')
        self.B.cli('pcb', 'render', '-o', tmp, '-w', '656', '-h', '376', '--background', 'transparent',
                   '--quality', 'basic', *self.camera(st, zoom, pan), self.board, env=self.env)
        a = np.array(Image.open(tmp).convert('RGBA'))[:, :, 3] > 0
        ys, xs = np.nonzero(a)
        h, w = a.shape
        return xs.min() / w, (xs.max() + 1) / w, ys.min() / h, (ys.max() + 1) / h

    def fit(self, st, start=None):
        """Zoom and pan that put the model right of centre at the wanted size."""
        key = hashlib.md5(json.dumps([scene_key(st), st['rot'], st['pivot'], st['fill'], st['wide'],
                                      CENTRE]).encode()).hexdigest()
        if key in self.fits:
            return self.fits[key]
        self.scene(st)
        zoom, pan = start or (0.5, (0.0, 0.0))
        best = None
        for _ in range(12):
            x0, x1, y0, y1 = self.outline(st, zoom, pan)
            if min(x0, y0) < 0.01 or max(x1, y1) > 0.99:
                zoom *= 0.75
                continue
            s = min(st['fill'] / (y1 - y0), st['wide'] / (x1 - x0))
            cx, cy = (x0 + x1) / 2 - CENTRE[0], (y0 + y1) / 2 - CENTRE[1]
            err = abs(s - 1) + 2 * abs(cx) + 2 * abs(cy)
            if best is None or err < best[0]:
                best = (err, zoom, list(pan))
            if abs(s - 1) < 0.015 and abs(cx) < 0.006 and abs(cy) < 0.006:
                break
            pan = (pan[0] - 0.8 * cx / (GAIN_X * zoom), pan[1] + 0.8 * cy / (GAIN_Y * zoom))
            zoom *= s ** 0.7
        self.fits[key] = [best[1], best[2]]
        json.dump(self.fits, open(self.fit_file, 'w'))
        return self.fits[key]

    def frame(self, st, zoom, pan):
        """Ray-traced RGBA frame for a scene and camera (cached on disk)."""
        key = hashlib.md5(json.dumps([scene_key(st), st['rot'], st['pivot'], round(zoom, 4),
                                      [round(p, 4) for p in pan], LIGHTS, W, H]).encode()).hexdigest()
        path = os.path.join(self.cache, '3d_%s.png' % key)
        if not os.path.exists(path):
            self.scene(st)
            self.B.cli('pcb', 'render', '-o', path, '-w', str(W + 16), '-h', str(H + 16),
                       '--background', 'transparent', '--quality', 'high', '--floor', *LIGHTS,
                       *self.camera(st, zoom, pan), self.board, env=self.env)
            if not os.path.exists(path):
                raise SystemExit('PROBLEM: KiCad did not render a frame')
        return path

    def close(self):
        for junk in ('_view.kicad_pcb', '_view.kicad_prl', '_view.kicad_pro', 'fp-info-cache'):
            if os.path.exists(os.path.join(ROOT, junk)):
                os.remove(os.path.join(ROOT, junk))


def camera_track(R, state_fn, duration, step=0.35):
    """Fitted zoom and pan for every frame of a section: fit at intervals, then smooth."""
    n = int(round(duration * FPS))
    times = np.arange(n) / FPS
    marks = np.unique(np.concatenate([np.arange(0, duration, step), [duration]]))
    fits, last = [], None
    for t in marks:
        z, p = R.fit(state_fn(float(t)), last)
        fits.append((z, p[0], p[1]))
        last = (z, (p[0], p[1]))
    fits = np.array(fits)
    track = np.stack([np.interp(times, marks, fits[:, k]) for k in range(3)], axis=1)
    kernel = np.exp(-0.5 * (np.arange(-12, 13) / 4.0) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(track, ((12, 12), (0, 0)), mode='edge')
    return np.stack([np.convolve(padded[:, k], kernel, 'valid') for k in range(3)], axis=1)


# ---- 2D layers --------------------------------------------------------------------------
def backdrop():
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W * 0.60) / (W * 0.62)) ** 2 + ((yy - H * 0.50) / (H * 0.78)) ** 2)
    g = np.clip(1 - r, 0, 1) ** 1.6
    dark, glow = np.array([13, 16, 21]), np.array([56, 68, 84])
    return Image.fromarray((dark + (glow - dark) * g[:, :, None]).astype(np.uint8), 'RGB')


def blueprint(path):
    """A drawing on white paper as light lines for a dark background (keeps the hues)."""
    a = np.asarray(Image.open(path).convert('RGB'), dtype=np.float32)
    paper = np.percentile(a.reshape(-1, 3), 90, axis=0)
    n = np.clip(a / paper, 0, 1)
    ink = 1 - n.min(axis=2)
    top = n.max(axis=2, keepdims=True)
    hue = np.where(top > 0.25, n / np.maximum(top, 1e-3), 0.82)        # black ink becomes pale grey
    rgb = (0.7 * hue + 0.3) * 255
    out = np.dstack([rgb, np.clip(ink * 1.4, 0, 1)[:, :, None] * 255]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


def drift(layer, u, start, end):
    """Slow move across a large drawing: boxes are (centre x, centre y, width) as shares of it."""
    cx, cy, w = (start[k] + (end[k] - start[k]) * smooth(0, 1, u) for k in range(3))
    bw = w * layer.width
    bh = bw * H / W
    box = (cx * layer.width - bw / 2, cy * layer.height - bh / 2, cx * layer.width + bw / 2, cy * layer.height + bh / 2)
    return layer.resize((W, H), Image.LANCZOS, box=box)


def font(size, weight='demi'):
    choices = {'demi': [('/System/Library/Fonts/Avenir Next.ttc', 2), ('/System/Library/Fonts/HelveticaNeue.ttc', 1)],
               'medium': [('/System/Library/Fonts/Avenir Next.ttc', 5), ('/System/Library/Fonts/HelveticaNeue.ttc', 10)],
               'regular': [('/System/Library/Fonts/Avenir Next.ttc', 7), ('/System/Library/Fonts/HelveticaNeue.ttc', 0)]}
    for path, index in choices[weight] + [('/System/Library/Fonts/Supplemental/Arial.ttf', 0)]:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


class Titles:
    def __init__(self):
        self.label, self.head, self.sub = font(19, 'demi'), font(46, 'demi'), font(23, 'medium')
        # soft shade behind the text column so it reads over any picture
        yy, xx = np.mgrid[0:H, 0:W]
        shade = np.clip(1 - xx / (W * 0.52), 0, 1) ** 1.3 * np.clip((yy - H * 0.22) / (H * 0.45), 0, 1)
        self.shade = np.dstack([np.zeros((H, W, 3)), shade * 215]).astype(np.uint8)
        self.layers = {}

    def block(self, label, head, sub):
        """One caption as a transparent layer, set on the bottom left."""
        key = (label, head, sub)
        if key not in self.layers:
            layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            hb = d.multiline_textbbox((0, 0), head, font=self.head, spacing=6)
            sb = d.multiline_textbbox((0, 0), sub, font=self.sub, spacing=8)
            y = H - 64 - (sb[3] - sb[1]) - 22 - (hb[3] - hb[1]) - 20 - 24
            d.rectangle((60, y + 3, 64, y + 21), fill=ACCENT + (255,))
            d.text((76, y), label, font=self.label, fill=ACCENT + (255,))
            y += 24 + 20
            d.multiline_text((60, y - hb[1]), head, font=self.head, fill=WHITE + (255,), spacing=6)
            y += (hb[3] - hb[1]) + 22
            d.multiline_text((61, y - sb[1]), sub, font=self.sub, fill=SOFT + (255,), spacing=8)
            self.layers[key] = layer
        return self.layers[key]

    def draw(self, frame, t):
        frame = frame.convert('RGBA')
        frame.alpha_composite(Image.fromarray(self.shade, 'RGBA'))
        for t0, t1, label, head, sub in CAPTIONS:
            a = min(smooth(t0, t0 + 0.3, t), 1 - smooth(t1 - 0.25, t1, t))
            if a <= 0:
                continue
            layer = self.block(label, head, sub)
            if a < 1:
                layer = layer.copy()
                layer.putalpha(layer.getchannel('A').point(lambda v: int(v * a)))
            rise = int(round(10 * (1 - smooth(t0, t0 + 0.35, t))))
            frame.alpha_composite(layer, (0, rise))
        d = ImageDraw.Draw(frame)
        d.rectangle((0, H - 3, int(W * t / TOTAL), H), fill=ACCENT + (255,))
        return frame.convert('RGB')


# ---- the film -----------------------------------------------------------------------------
class Film:
    def __init__(self, cache):
        self.R = Renderer(cache)
        self.bg = backdrop()
        self.titles = Titles()
        self.sch = blueprint(os.path.join(ROOT, 'output', 'sheets', '3-mcu.png'))
        self.cu = blueprint(os.path.join(ROOT, 'output', 'pcb', 'copper_outer_layers.png'))
        self.tracks = {}

    def track(self, name):
        if name not in self.tracks:
            fn, dur = (board_state, T_BRD) if name == 'board' else (product_state, T_PROD)
            self.tracks[name] = camera_track(self.R, fn, dur)
        return self.tracks[name]

    def flat(self, layer, u, start, end, wipe=None):
        img = self.bg.convert('RGBA')
        pic = drift(layer, u, start, end)
        xx = np.arange(W)[None, :]
        mask = np.clip((xx / W - 0.04) / 0.42, 0.16, 1.0)        # fainter on the left, under the text
        if wipe is not None and wipe < 1:                       # reveal from the left
            mask = mask * np.clip((wipe * (W + 300) - xx) / 300, 0, 1)
        a = np.asarray(pic.getchannel('A'), dtype=np.float32) * mask
        pic.putalpha(Image.fromarray(a.astype(np.uint8), 'L'))
        img.alpha_composite(pic)
        return img.convert('RGB')

    def solid(self, name, tau, exact=False):
        fn, dur = (board_state, T_BRD) if name == 'board' else (product_state, T_PROD)
        tau = min(max(tau, 0.0), dur - 1.0 / FPS)
        st = fn(tau)
        if exact:
            zoom, pan = self.R.fit(st)
        else:
            z, px, py = self.track(name)[int(round(tau * FPS))]
            zoom, pan = float(z), (float(px), float(py))
        im = Image.open(self.R.frame(st, zoom, pan)).convert('RGBA')
        if im.size != (W, H):
            im = im.resize((W, H), Image.LANCZOS)
        img = self.bg.convert('RGBA')
        img.alpha_composite(im)
        return img.convert('RGB')

    def section(self, t, exact=False):
        if t < T0_CU:
            return self.flat(self.sch, t / T_SCH, (0.50, 0.50, 0.94), (0.50, 0.47, 0.72), wipe=t / 0.7)
        if t < T0_BRD:
            return self.flat(self.cu, (t - T0_CU) / T_CU, (0.50, 0.50, 0.97), (0.56, 0.44, 0.70))
        if t < T0_PROD:
            return self.solid('board', t - T0_BRD, exact)
        return self.solid('product', t - T0_PROD, exact)

    def picture(self, t, exact=False):
        img = self.section(t, exact)
        for cut in (T0_CU, T0_BRD, T0_PROD):                    # cross-fade out of the previous section
            if cut <= t < cut + FADE:
                before = self.section(cut - 1.0 / FPS, exact)
                img = Image.blend(before, img, smooth(cut, cut + FADE, t))
        if t < 0.3:
            img = Image.blend(self.bg, img, smooth(0, 0.3, t))
        return self.titles.draw(img, t)


def encode(frames, out, crf='16'):
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', os.path.join(frames, 'f_%05d.png'),
           '-c:v', 'libx264', '-preset', 'slow', '-crf', crf, '-pix_fmt', 'yuv420p', '-profile:v', 'high',
           '-level:v', '4.0', '-g', str(FPS * 2), '-color_primaries', 'bt709', '-color_trc', 'bt709',
           '-colorspace', 'bt709', '-movflags', '+faststart',
           # no tool tags in the container or the stream
           '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:v', '+bitexact',
           '-bsf:v', 'filter_units=remove_types=6', '-metadata', 'title=Water Softener Controller', out]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        print(res.stderr[-800:])
        raise SystemExit('PROBLEM: ffmpeg failed')
    subprocess.run(['xattr', '-c', out], capture_output=True)


def main():
    if not shutil.which('ffmpeg'):
        raise SystemExit('PROBLEM: ffmpeg not found')
    if not os.path.exists(os.path.join(E.D3, 'cover.wrl')):
        raise SystemExit('PROBLEM: no enclosure models yet, run build.py --product first')
    cache = os.path.join(tempfile.gettempdir(), 'water_softener_video')
    if '--cache' in sys.argv:
        cache = sys.argv[sys.argv.index('--cache') + 1]
    out = FILM
    if '--out' in sys.argv:
        out = os.path.abspath(sys.argv[sys.argv.index('--out') + 1])
    if '--closing' in sys.argv:
        label, head, line = sys.argv[sys.argv.index('--closing') + 1].split('|')
        CAPTIONS[-1] = CAPTIONS[-1][:2] + (label, head.replace('/', '\n'), line.replace('/', '\n'))
    film = Film(cache)
    try:
        if '--storyboard' in sys.argv:
            marks = [1.2, T0_CU + 1.2, T0_BRD + 1.4] + [T0_PROD + v for v in (0.5, 1.3, 2.7, 4.2, 5.5, 7.3, 8.1, 9.9, 13.0)]
            sheet = Image.new('RGB', (W * 2, H * 3 // 2 * 2), 'black')
            for i, t in enumerate(marks):
                im = film.picture(t, exact=True).resize((W // 2, H // 2), Image.LANCZOS)
                sheet.paste(im, ((i % 4) * W // 2, (i // 4) * H // 2))
            sheet = sheet.crop((0, 0, W * 2, H // 2 * 3))
            sheet.save(os.path.join(cache, 'storyboard.png'))
            print('storyboard:', os.path.join(cache, 'storyboard.png'))
            return
        frames = os.path.join(cache, 'frames_' + os.path.splitext(os.path.basename(out))[0])
        shutil.rmtree(frames, ignore_errors=True)
        os.makedirs(frames)
        n = int(round(TOTAL * FPS))
        for i in range(n):
            film.picture(i / FPS).save(os.path.join(frames, 'f_%05d.png' % i), compress_level=1)
            if i % 30 == 0:
                print('frame %d of %d' % (i, n), flush=True)
        encode(frames, out, sys.argv[sys.argv.index('--crf') + 1] if '--crf' in sys.argv else '16')
        shutil.rmtree(frames, ignore_errors=True)
        print('film: %s (%.1f s, %d frames, %.1f MB)' % (
            os.path.relpath(out, ROOT), n / FPS, n, os.path.getsize(out) / 1e6))
    finally:
        film.R.close()


if __name__ == '__main__':
    main()
