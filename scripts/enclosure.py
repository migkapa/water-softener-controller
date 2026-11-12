#!/usr/bin/env python3
"""Enclosure, clearance check and product views.

Run with the Python that ships inside KiCad (it provides `pcbnew` and numpy);
`python3 scripts/build.py --product` does that.  Needs OpenSCAD on the PATH.

Steps: write enclosure/board.scad from the board layout, build every part of
enclosure/enclosure.scad to STL, check the parts against the real board for
collisions, then render the assembled product with KiCad's ray tracer.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import numpy as np  # noqa: E402

import pcb_layout as L  # noqa: E402

NAME = 'water_softener'
PCB = os.path.join(ROOT, NAME + '.kicad_pcb')
ENC = os.path.join(ROOT, 'enclosure')
STL = os.path.join(ENC, 'stl')
D3 = os.path.join(ROOT, '3d', 'enclosure')
OUT = os.path.join(ROOT, 'output', 'product')
OX, OY = L.ORIGIN
Z_TOP = 1.59            # height of the board's top surface in KiCad's STL export
PCB_T = 1.6

# terminal blocks, left to right: reference, ways, name, pin labels
TERMINALS = [
    ('J2', 2, '12V IN', ['+', '-']),
    ('J6', 2, 'MOTOR', ['1', '2']),
    ('J8', 2, 'AUX 12V', ['+', 'SW']),
    ('J9', 4, 'VALVE POS', ['5V', 'HM', 'EN', 'G']),
    ('J10', 3, 'FLOW', ['5V', 'P', 'G']),
    ('J11', 4, 'SALT', ['5V', 'D', 'A', 'G']),
    ('J12', 2, 'LEAK', ['P', 'G']),
    ('J7', 3, 'RELAY', ['NC', 'NO', 'C']),
]

# parts to print or cut: file name, what it is
PRINTED = [
    ('base', 'rear shell'),
    ('cover', 'front shell'),
    ('door', 'wiring bay door'),
    ('button', 'button, 3 needed'),
    ('lightpipe', 'light pipe, clear'),
    ('lens', 'display window, 1.5 mm smoked acrylic'),
]

# models used in the renders: group -> [(part, colour, transparency, shininess)]
BODY = (0.66, 0.67, 0.68)
INK = (0.10, 0.11, 0.13)
GROUPS = {
    'base': [('base', (0.24, 0.26, 0.29), 0, 0.2)],
    'cover': [('cover', BODY, 0, 0.25), ('ink_front', INK, 0, 0.05), ('ink_strip', INK, 0, 0.05)],
    'door': [('door', BODY, 0, 0.25), ('ink_door', INK, 0, 0.05)],
    'door_screw': [('door_screw', (0.42, 0.43, 0.45), 0, 0.5)],
    'lens': [('lens', (0.03, 0.03, 0.04), 0.55, 0.9), ('lens_mask', (0.02, 0.02, 0.025), 0, 0.6)],
    'buttons': [('buttons', (0.20, 0.36, 0.52), 0, 0.3)],
    'lightpipe': [('lightpipe', (0.93, 0.95, 0.97), 0.25, 0.8)],
    'oled': [('oled_board', (0.05, 0.16, 0.42), 0, 0.3), ('oled_header', (0.06, 0.06, 0.06), 0, 0.2),
             ('oled_pins', (0.85, 0.68, 0.25), 0, 0.8), ('oled_glass', (0.02, 0.02, 0.03), 0, 0.9),
             ('oled_active', (0.03, 0.05, 0.08), 0, 0.9), ('display_on', (0.75, 0.95, 1.0), 0, 0.1)],
    'plugs': [('plug_bodies', (0.16, 0.50, 0.24), 0, 0.3), ('plug_metal', (0.75, 0.76, 0.78), 0, 0.8)],
    'screws': [('rear_screws', (0.42, 0.43, 0.45), 0, 0.5)],
    'sounder': [('sounder', (0.05, 0.05, 0.05), 0, 0.3)],
}
EVERYTHING = list(GROUPS)


def rot(dx, dy, deg):
    """Footprint-local offset (y down) to board axes for a KiCad rotation."""
    import math
    a = math.radians(deg)
    return (dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a))


def centre(ref, dx, dy):
    x, y, r = L.P[ref]
    ox, oy = rot(dx, dy, r)
    return [round(x + ox, 3), round(y + oy, 3)]


def write_board_scad():
    """Positions the enclosure depends on, taken from the board layout."""
    assert L.P['J3'][0] > L.BOARD_W - 10 and L.P['J1'][0] < 20, 'USB-C or jack moved off its edge'
    assert [t[2] for t in TERMINALS] == [t[0] for t in L.LEGENDS], 'terminal names differ from the board'
    hdr = centre('J4', 0, 3.81)
    rows = []
    for ref, ways, name, pins in TERMINALS:
        assert L.P[ref][2] == 0
        rows.append('    [%s, %d, "%s", [%s]],' % (L.P[ref][0], ways, name, ', '.join('"%s"' % p for p in pins)))
    text = '\n'.join([
        '// Written by scripts/enclosure.py from scripts/pcb_layout.py.  Do not edit.',
        'pcb_w = %s;' % L.BOARD_W,
        'pcb_h = %s;' % L.BOARD_H,
        'holes = %s;' % [list(L.P[h][:2]) for h in ('H1', 'H2', 'H3', 'H4')],
        '// DOWN, UP, SET: centres of the tact switches',
        'buttons = %s;' % [centre(s, 3.25, 2.25) for s in ('SW4', 'SW3', 'SW2')],
        'led = %s;' % centre('D6', 0, 0),
        'buzzer = %s;' % centre('LS1', 2.5, 0),
        'reset = %s;' % centre('SW1', 0, 0),
        '// OLED module: centre of its 4-pin socket and of the visible display area',
        'oled_hdr = %s;' % hdr,
        'oled_view = %s;' % [hdr[0], hdr[1] + 10.5],
        'usb_y = %s;' % L.P['J3'][1],
        'jack_y = %s;' % L.P['J1'][1],
        '// terminal blocks: x of pin 1, ways, name, pin labels',
        'terminals = [', *rows, '];', ''])
    with open(os.path.join(ENC, 'board.scad'), 'w') as fh:
        fh.write(text)


# ---- geometry ----------------------------------------------------------------------
def scad(part, path):
    exe = shutil.which('openscad') or '/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD'
    res = subprocess.run([exe, '--backend', 'Manifold', '--export-format', 'binstl', '-D', 'part="%s"' % part,
                          '-o', path, os.path.join(ENC, 'enclosure.scad')], capture_output=True, text=True)
    if res.returncode or not os.path.exists(path):
        print(res.stderr[-600:])
        raise SystemExit('PROBLEM: OpenSCAD failed on part %s' % part)
    if 'WARNING' in res.stderr:
        print('OpenSCAD warning in %s: %s' % (part, [l for l in res.stderr.splitlines() if 'WARNING' in l][:3]))


def load_stl(path):
    raw = open(path, 'rb').read()
    if raw[:5] == b'solid' and b'facet' in raw[:400]:
        v = [[float(t) for t in line.split()[1:4]] for line in raw.decode('ascii', 'ignore').splitlines()
             if line.strip().startswith('vertex')]
        return np.array(v, dtype=float).reshape(-1, 3, 3)
    n = int(np.frombuffer(raw[80:84], '<u4')[0])
    rec = np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    return np.frombuffer(raw[84:84 + n * 50], dtype=rec)['v'].astype(float)


def write_wrl(path, shapes):
    """VRML for KiCad's 3D viewer (which reads VRML in units of 2.54 mm)."""
    with open(path, 'w') as fh:
        fh.write('#VRML V2.0 utf8\n')
        for tris, colour, transp, shine in shapes:
            pts, idx = np.unique(np.round(tris.reshape(-1, 3), 4), axis=0, return_inverse=True)
            idx = idx.reshape(-1, 3)
            fh.write('Shape { appearance Appearance { material Material { diffuseColor %.3f %.3f %.3f '
                     'specularColor %.2f %.2f %.2f shininess %.2f transparency %.2f } }\n'
                     % (colour[0], colour[1], colour[2], shine, shine, shine, shine, transp))
            fh.write(' geometry IndexedFaceSet { solid FALSE creaseAngle 0.5 coord Coordinate { point [\n')
            fh.write(',\n'.join('%.4f %.4f %.4f' % tuple(p / 2.54) for p in pts))
            fh.write('] }\n coordIndex [\n')
            fh.write(',\n'.join('%d,%d,%d,-1' % tuple(t) for t in idx))
            fh.write('] } }\n')


def build_parts():
    """Run OpenSCAD for every part.  Returns {part: triangles}."""
    for d in (STL, D3, OUT):
        os.makedirs(d, exist_ok=True)
    tris = {}
    tmp = tempfile.mkdtemp(prefix='enc')
    printed = [p for p, _ in PRINTED]
    needed = sorted(set(printed) | {p for g in GROUPS.values() for p, *_ in g})
    for part in needed:
        path = os.path.join(STL if part in printed else tmp, part + '.stl')
        scad(part, path)
        tris[part] = load_stl(path)
    shutil.rmtree(tmp)
    for group, shapes in GROUPS.items():
        write_wrl(os.path.join(D3, group + '.wrl'), [(tris[p], c, t, s) for p, c, t, s in shapes])
    return tris


def write_parts_list(tris):
    """Everything needed to assemble one unit, besides the populated board."""
    import csv
    ways = {}
    for _, n, _, _ in TERMINALS:
        ways[n] = ways.get(n, 0) + 1
    rows = [('Item', 'Qty', 'Make', 'Description')]
    for part, what in PRINTED:
        lo, hi = tris[part].reshape(-1, 3).min(0), tris[part].reshape(-1, 3).max(0)
        size = '%.1f x %.1f x %.1f mm' % tuple(hi - lo)
        make = 'cut from sheet' if part == 'lens' else '3D print'
        rows.append((part, 3 if part == 'button' else 1, make, '%s, %s (enclosure/stl/%s.stl)' % (
            what.split(',')[0], size, part)))
    rows += [
        ('display', 1, 'buy', '0.96 in I2C OLED module, 128 x 64, 4-pin header GND-VCC-SCL-SDA, 27.3 x 27.8 mm board'),
        ('board screw', 4, 'buy', 'M3 x 12 pan head machine screw, from the rear into the cover posts'),
        ('door screw', 1, 'buy', 'M3 x 8 countersunk machine screw'),
        ('threaded insert', 5, 'buy', 'M3 heat-set insert for a 4.0 mm hole, up to 5.7 mm long (4 cover posts, 1 door)'),
    ]
    for n in sorted(ways):
        rows.append(('terminal plug, %d-way' % n, ways[n], 'buy', 'Phoenix Contact MC 1,5/%d-ST-3,5' % n))
    rows.append(('wall screw', 3, 'buy', '4 mm screw, pan head up to 9 mm across and 3.4 mm high, with wall plugs'))
    with open(os.path.join(OUT, 'assembly_parts.csv'), 'w', newline='') as fh:
        csv.writer(fh, quoting=csv.QUOTE_ALL).writerows(rows)
    both = np.concatenate([tris['base'].reshape(-1, 3), tris['cover'].reshape(-1, 3)])
    return tuple(both.max(0) - both.min(0))


# ---- clearance check -----------------------------------------------------------------
CELL = 0.2
X0, Y0 = -10.0, -125.0          # grid origin in enclosure coordinates (x right, y up)
NX, NY = 720, 700


class Solid:
    """Closed mesh sampled as vertical crossings on a fine grid."""

    def __init__(self, tris):
        cells, zs = [], []
        jx, jy = 0.0137, 0.0071          # keeps grid points off triangle edges
        for a, b, c in tris:
            n = np.cross(b - a, c - a)
            if abs(n[2]) < 1e-12:
                continue
            lo = np.minimum(np.minimum(a, b), c)
            hi = np.maximum(np.maximum(a, b), c)
            i0 = max(int(np.ceil((lo[0] - X0 - jx) / CELL)), 0)
            i1 = min(int(np.floor((hi[0] - X0 - jx) / CELL)), NX - 1)
            j0 = max(int(np.ceil((lo[1] - Y0 - jy) / CELL)), 0)
            j1 = min(int(np.floor((hi[1] - Y0 - jy) / CELL)), NY - 1)
            if i1 < i0 or j1 < j0:
                continue
            ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing='ij')
            px = X0 + jx + ii * CELL
            py = Y0 + jy + jj * CELL
            d = n[2]
            w0 = ((b[0] - px) * (c[1] - py) - (b[1] - py) * (c[0] - px)) / d
            w1 = ((c[0] - px) * (a[1] - py) - (c[1] - py) * (a[0] - px)) / d
            w2 = 1 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if m.any():
                cells.append((ii[m] * NY + jj[m]).ravel())
                zs.append((w0[m] * a[2] + w1[m] * b[2] + w2[m] * c[2]).ravel())
        cells = np.concatenate(cells)
        zs = np.concatenate(zs)
        order = np.lexsort((zs, cells))
        self.cells = cells[order]
        self.keys = self.cells * 1000.0 + (zs[order] + 100.0)

    def below(self, cell, z):
        """Number of surface crossings under each point."""
        return np.searchsorted(self.keys, cell * 1000.0 + (z + 100.0)) - np.searchsorted(self.cells, cell)

    def inside(self, pts, margin=0.0):
        """True where a point lies inside the solid, or within `margin` of it."""
        hit = np.zeros(len(pts), dtype=bool)
        steps = [(0.0, 0.0)]
        if margin > 0:
            steps += [(margin * dx, margin * dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
        for dx, dy in steps:
            i = np.floor((pts[:, 0] + dx - X0) / CELL + 0.5).astype(np.int64)
            j = np.floor((pts[:, 1] + dy - Y0) / CELL + 0.5).astype(np.int64)
            ok = (i >= 0) & (i < NX) & (j >= 0) & (j < NY)
            cell = np.where(ok, i * NY + j, 0)
            lo = self.below(cell, pts[:, 2] - margin - 0.02)
            hi = self.below(cell, pts[:, 2] + margin + 0.02)
            if margin > 0:
                near = (lo % 2 == 1) | (hi != lo)
            else:
                near = (lo % 2 == 1) & (hi == lo)      # strictly inside, clear of the surface
            hit |= near & ok
        return hit


def sample(tris, step=0.25):
    """Points spread over the surface of a mesh."""
    out = [tris.reshape(-1, 3)]
    e = np.maximum(np.linalg.norm(tris[:, 1] - tris[:, 0], axis=1),
                   np.maximum(np.linalg.norm(tris[:, 2] - tris[:, 1], axis=1),
                              np.linalg.norm(tris[:, 0] - tris[:, 2], axis=1)))
    n = np.ceil(e / step).astype(int)
    for k in np.unique(n):
        if k < 2:
            continue
        t = tris[n == k]
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing='ij')
        m = i + j <= k
        u, v = i[m] / k, j[m] / k
        w = 1 - u - v
        out.append((t[:, None, 0] * w[None, :, None] + t[:, None, 1] * u[None, :, None]
                    + t[:, None, 2] * v[None, :, None]).reshape(-1, 3))
    return np.concatenate(out)


def box_points(x0, y0, x1, y1, z0, z1, step=0.25):
    """Surface points of a box given in board coordinates (y down)."""
    xs = np.arange(x0, x1 + step / 2, step)
    ys = np.arange(y0, y1 + step / 2, step)
    zs = np.arange(z0, z1 + step / 2, step)
    pts = []
    for z in (z0, z1):
        gx, gy = np.meshgrid(xs, ys)
        pts.append(np.column_stack([gx.ravel(), -gy.ravel(), np.full(gx.size, z)]))
    for y in (y0, y1):
        gx, gz = np.meshgrid(xs, zs)
        pts.append(np.column_stack([gx.ravel(), np.full(gx.size, -y), gz.ravel()]))
    for x in (x0, x1):
        gy, gz = np.meshgrid(ys, zs)
        pts.append(np.column_stack([np.full(gy.size, x), -gy.ravel(), gz.ravel()]))
    return np.concatenate(pts)


def board_points(B, env):
    """Point clouds of the bare board and of its parts, in enclosure coordinates."""
    tmp = tempfile.mkdtemp(prefix='brd')
    clouds = {}
    for key, flag in (('board', '--no-components'), ('parts', '--no-board-body')):
        path = os.path.join(tmp, key + '.stl')
        B.cli('pcb', 'export', 'stl', '--force', '--subst-models', flag, '-o', path, PCB, env=env)
        t = load_stl(path)
        t = t - np.array([OX, -OY, Z_TOP])          # STL: page x, minus page y, z from the underside
        clouds[key] = sample(t)
    shutil.rmtree(tmp)
    for junk in (NAME + '.kicad_prl', 'fp-info-cache'):
        if os.path.exists(os.path.join(ROOT, junk)):
            os.remove(os.path.join(ROOT, junk))
    # parts that only have a box model (not in KiCad's STEP-based export)
    extra = []
    for ref, (_, size, (cx, cy), _) in L.BODIES.items():
        x, y, r = L.P[ref]
        ox, oy = rot(cx, cy, r)
        sx, sy = (size[0], size[1]) if r % 180 == 0 else (size[1], size[0])
        extra.append(box_points(x + ox - sx / 2, y + oy - sy / 2, x + ox + sx / 2, y + oy + sy / 2, 0, size[2]))
    x, y, r = L.P['U3']                             # module: carrier and shield can
    assert r == 0
    extra.append(box_points(x - 6.6, y - 11.0, x + 6.6, y + 5.6, 0, 2.4))
    clouds['parts'] = np.concatenate([clouds['parts']] + extra)
    return clouds


def where(pts):
    """Short description of where a group of points is."""
    lo, hi = pts.min(0), pts.max(0)
    return 'x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f' % (lo[0], hi[0], -hi[1], -lo[1], lo[2], hi[2])


def clusters(pts, size=6.0):
    """Split points into coarse spatial groups for reporting."""
    keys = np.floor(pts[:, :2] / size).astype(int)
    groups = {}
    for k in np.unique(keys, axis=0):
        groups[tuple(k)] = pts[(keys == k).all(1)]
    return list(groups.values())


def clearance(tris, B, env):
    """Collision check of the enclosure against the board and of the parts against each other."""
    solids = {p: Solid(tris[p]) for p in ('base', 'cover', 'door', 'lens')}
    clouds = board_points(B, env)
    # the sounder model has untrimmed leads; they are cut to 2.5 mm after soldering
    bx, by = centre('LS1', 2.5, 0)
    parts = clouds['parts']
    leads = (np.abs(parts[:, 0] - bx) < 7) & (np.abs(parts[:, 1] + by) < 7) & (parts[:, 2] < -PCB_T - 2.5)
    clouds['parts'] = parts[~leads]
    clouds['OLED module'] = np.concatenate([sample(tris[p]) for p in ('oled_board', 'oled_header', 'oled_glass')])
    clouds['plugs'] = sample(tris['plug_bodies'])
    clouds['buttons'] = sample(tris['buttons'])
    clouds['light pipe'] = sample(tris['lightpipe'])
    for p in ('cover', 'door', 'lens'):
        clouds[p] = sample(tris[p], 0.4)
    checks = [   # cloud, solids, margin: 0 = must not intersect, > 0 = must stay that far away
        ('board', ('base', 'cover'), 0.0), ('parts', ('base', 'cover', 'door', 'lens'), 0.3),
        ('OLED module', ('cover', 'lens'), 0.3), ('plugs', ('base', 'cover', 'door'), 0.3),
        ('buttons', ('cover', 'door', 'base'), 0.0), ('light pipe', ('cover', 'base'), 0.0),
        ('cover', ('base',), 0.0), ('door', ('cover', 'base'), 0.0), ('lens', ('cover',), 0.0)]
    lines, bad = [], 0
    for cloud, against, margin in checks:
        pts = clouds[cloud]
        for s in against:
            hit = solids[s].inside(pts, margin)
            what = 'intersects' if margin == 0 else 'is closer than %.1f mm to' % margin
            if hit.any():
                bad += 1
                for g in clusters(pts[hit]):
                    lines.append('PROBLEM: %s %s the %s at %s (%d points)' % (cloud, what, s, where(g), len(g)))
            else:
                lines.append('ok: %s %s' % (cloud, 'clear of the %s' % s if margin == 0
                                             else 'at least %.1f mm from the %s' % (margin, s)))
    # headroom over the tallest parts
    top = clouds['parts'][:, 2].max()
    lines.append('tallest part on the board: %.1f mm above the board surface' % top)
    with open(os.path.join(OUT, 'clearance.txt'), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    for line in lines:
        if line.startswith('PROBLEM'):
            print(line)
    print('clearance check: %d checks, %d with problems' % (sum(len(c[1]) for c in checks), bad))
    return bad == 0


# ---- renders -----------------------------------------------------------------------
def view_board(path, show, offsets=None, opacity=None):
    """Copy of the board with the enclosure parts attached as 3D models."""
    import pcbnew
    offsets, opacity = offsets or {}, opacity or {}
    b = pcbnew.LoadBoard(PCB)
    for fp in list(b.GetFootprints()):
        if fp.GetReference() == 'LS1' and 'sounder' in show:
            fp.Models().clear()             # KiCad's model has untrimmed leads
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference('MECH1')
    fp.SetValue('enclosure')
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(OX), pcbnew.FromMM(OY)))
    fp.SetAttributes(pcbnew.FP_THROUGH_HOLE)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    b.Add(fp)
    for group in show:
        m = pcbnew.FP_3DMODEL()
        m.m_Filename = os.path.join(D3, group + '.wrl')
        m.m_Offset = pcbnew.VECTOR3D(*offsets.get(group, (0, 0, 0)))
        m.m_Opacity = opacity.get(group, 1.0)
        fp.Add3DModel(m)
    pcbnew.SaveBoard(path, b)


CLOSED = ['base', 'cover', 'door', 'door_screw', 'lens', 'buttons', 'lightpipe', 'oled', 'plugs', 'screws', 'sounder']
EXPLODE = {'screws': (0, 0, -62), 'base': (0, 0, -36), 'oled': (0, 0, 10), 'plugs': (0, -26, 0),
           'buttons': (0, 0, 32), 'lightpipe': (0, 0, 32), 'cover': (0, 0, 70), 'lens': (0, 0, 86),
           'door': (0, 0, 86), 'door_screw': (0, 0, 102)}
# softer light from the sides so the parts under the lifted cover are not lost in its shadow
FILL = ['--light-camera', '0.25', '--light-side', '0.75', '--light-top', '0.45', '--light-bottom', '0.3',
        '--light-side-elevation', '25']
PERSP = ['--side', 'top', '--perspective', '--floor', '--rotate']
VIEWS = [
    # file, groups shown, offsets, opacity, camera, share of the frame to fill
    ('product_front.png', CLOSED, {}, {}, ['--side', 'top'], 0.80),
    ('product_angle.png', CLOSED, {}, {}, PERSP + ['-52,0,-28'], 0.80),
    ('product_left.png', CLOSED, {}, {}, PERSP + ['-58,0,38'], 0.80),
    ('product_wiring.png', [g for g in CLOSED if g not in ('door', 'door_screw')], {}, {},
     PERSP + ['-40,0,-14'], 0.82),
    ('product_open.png', ['base', 'oled', 'plugs', 'sounder'], {}, {}, PERSP + ['-46,0,-24'], 0.82),
    ('product_exploded.png', CLOSED, EXPLODE, {}, PERSP + ['-68,0,-34'] + FILL, 0.88),
    ('product_xray.png', CLOSED, {}, {'cover': 0.3, 'door': 0.3}, ['--side', 'top'], 0.80),
    ('product_rear.png', CLOSED, {}, {}, ['--side', 'bottom', '--perspective', '--rotate', '-32,0,22'], 0.80),
]
BACKDROP = ((246, 247, 249), (212, 216, 222))        # top and bottom of the background
PAN = 0.05625        # one unit of --pan moves the picture this share of its width at zoom 1


def measure(B, env, board, camera, zoom, pan):
    """Outline of the model in a small test render, as shares of the frame."""
    from PIL import Image
    tmp = os.path.join(tempfile.gettempdir(), 'probe_%d.png' % os.getpid())
    B.cli('pcb', 'render', '-o', tmp, '-w', '480', '-h', '360', '--background', 'transparent',
          '--quality', 'basic', *[c for c in camera if c != '--floor'], '--zoom', '%.4f' % zoom,
          '--pan', '%.4f,%.4f,0' % pan, board, env=env)
    a = np.array(Image.open(tmp).convert('RGBA'))[:, :, 3] > 0
    os.remove(tmp)
    ys, xs = np.nonzero(a)
    return xs.min() / 480.0, (xs.max() + 1) / 480.0, ys.min() / 360.0, (ys.max() + 1) / 360.0


def frame(B, env, board, camera, fill):
    """Zoom and pan that centre the model.  KiCad frames the bare board, not the enclosure."""
    zoom, pan, best = 0.3, (0.0, 0.0), None
    for _ in range(14):
        x0, x1, y0, y1 = measure(B, env, board, camera, zoom, pan)
        if min(x0, y0) < 0.012 or max(x1, y1) > 0.988:        # cut off: step back first
            zoom *= 0.75
            continue
        s = min(fill / (x1 - x0), fill / (y1 - y0))
        cx, cy = (x0 + x1) / 2 - 0.5, (y0 + y1) / 2 - 0.5
        err = abs(s - 1) + 2 * abs(cx) + 2 * abs(cy)
        if best is None or err < best[0]:
            best = (err, zoom, pan)
        if abs(s - 1) < 0.03 and abs(cx) < 0.012 and abs(cy) < 0.012:
            break
        pan = (pan[0] - 0.8 * cx / (PAN * zoom), pan[1] + 0.8 * cy / (PAN * 4 / 3 * zoom))
        zoom *= s ** 0.7                                      # damped: perspective is not linear
    return best[1], best[2]


def backdrop(path, shadow=True):
    """Put the transparent render on a plain light background."""
    from PIL import Image
    im = Image.open(path).convert('RGBA')
    w, h = im.size
    if not shadow:                      # keep the model, drop the soft shadow round it
        a = np.array(im)
        a[:, :, 3] = np.where(a[:, :, 3] >= 250, a[:, :, 3], 0)
        im = Image.fromarray(a, 'RGBA')
    ramp = np.linspace(0, 1, h)[:, None, None]
    bg = np.array(BACKDROP[0])[None, None, :] * (1 - ramp) + np.array(BACKDROP[1])[None, None, :] * ramp
    back = Image.fromarray(np.broadcast_to(bg, (h, w, 3)).astype(np.uint8), 'RGB').convert('RGBA')
    back.alpha_composite(im)
    back.convert('RGB').save(path)


def render(B, env, views, quality='high', size=(2400, 1800)):
    tmp = os.path.join(ROOT, '_view.kicad_pcb')
    for name, show, offsets, opacity, camera, fill in views:
        out = os.path.join(OUT, name)
        try:
            view_board(tmp, show, offsets, opacity)
            zoom, pan = frame(B, env, tmp, camera, fill)
            B.cli('pcb', 'render', '-o', out, '-w', str(size[0]), '-h', str(size[1]),
                  '--background', 'transparent', '--quality', quality, *camera, '--zoom', '%.4f' % zoom,
                  '--pan', '%.4f,%.4f,0' % pan, tmp, env=env)
        finally:
            for junk in ('_view.kicad_pcb', '_view.kicad_prl', '_view.kicad_pro', 'fp-info-cache'):
                if os.path.exists(os.path.join(ROOT, junk)):
                    os.remove(os.path.join(ROOT, junk))
        if not os.path.exists(out):
            raise SystemExit('PROBLEM: no render for %s' % name)
        backdrop(out, '--floor' in camera)
        print('rendered %s (zoom %.2f)' % (name, zoom))


def main():
    import build as B
    env = B.kicad_env()
    write_board_scad()
    tris = build_parts()
    print('enclosure parts: %s' % ', '.join(p for p, _ in PRINTED))
    print('outside size: %.1f x %.1f x %.1f mm' % write_parts_list(tris))
    ok = True
    if '--no-check' not in sys.argv:
        ok = clearance(tris, B, env)
    if '--no-render' not in sys.argv:
        only = [a for a in sys.argv[1:] if a.endswith('.png')]
        views = [v for v in VIEWS if not only or v[0] in only]
        draft = '--draft' in sys.argv
        render(B, env, views, 'basic' if draft else 'high', (1200, 900) if draft else (2400, 1800))
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
