"""Grid router for the controller board.

A maze router on a 0.1 mm grid over the two outer copper layers.  Supply nets
that have an inner-layer plane (GND, +3V3, +12V) only get a short track and a
via to the plane; everything else is routed pad to pad.  Obstacles are stored
per layer as "which net owns this cell" after inflating all copper by the
design clearance, so a path through free cells is clear by construction.
When a pin ends up boxed in, the tracks around it are ripped up and routed
again after it.  KiCad's own DRC is the final check.
"""
import heapq
import math
import time
from collections import deque

import numpy as np
import pcbnew

import pcb_layout as L

G = 0.1                                   # grid pitch, mm
W = int(round(L.BOARD_W / G)) + 1
H = int(round(L.BOARD_H / G)) + 1
N = W * H
BASE_HALF = 0.1                           # half width of the narrowest track
BASE_CLR = 0.2                            # clearance designed for on the grid
MARGIN = 0.03
INF = BASE_CLR + BASE_HALF + MARGIN       # inflation beyond a copper edge
NECK_R = 1.6                              # wide nets may run thin this close to a fine pad
VIA_COST = 160
PAD_PENALTY = 8                           # extra step cost close to any pad
STUB_PENALTY = 40                         # ... and right in front of an escape stub
POCKET_LIMIT = 6000
OX, OY = L.ORIGIN
mm = pcbnew.FromMM
tm = pcbnew.ToMM

MOVES = [(1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10),
         (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]
PLANE_NETS = ['GND', '+3V3', '+12V']
# pads that carry real current get two vias into their plane
HEAVY = {('C1', '1'), ('C1', '2'), ('C3', '2'), ('C4', '2'), ('C6', '1'), ('C6', '2'), ('C7', '1'),
         ('C7', '2'), ('D1', '1'), ('U1', '4'), ('C20', '1'), ('C20', '2'), ('Q1', '2'),
         ('Q4', '2'), ('L1', '2'), ('D8', '1'), ('D3', '2')}
# Escape stubs for fine-pitch parts: ref -> (short, long, {pad: length}, {pads ending in a via}).
# Alternating lengths give each pin its own lane and room for a via at the long ends.
STUBS = {
    'U3': (1.0, 2.0, {}, set()),
    'U6': (0.8, 1.6, {}, set()),
}


def dilate(mask, k):
    """Square dilation of a boolean (H, W) array by k cells."""
    if k <= 0:
        return mask
    out = mask.copy()
    for s in range(1, k + 1):
        out[:, s:] |= mask[:, :-s]
        out[:, :-s] |= mask[:, s:]
    tmp = out.copy()
    for s in range(1, k + 1):
        out[s:, :] |= tmp[:-s, :]
        out[:-s, :] |= tmp[s:, :]
    return out


class Unit:
    """A rippable piece of routing: one signal net, or one pad's plane via."""

    def __init__(self, key, net):
        self.key, self.net = key, net
        self.tracks, self.vias, self.nodes = [], [], set()
        self.dep = None                 # key of the unit whose copper this one ends on

    def clear(self):
        self.tracks, self.vias, self.nodes = [], [], set()
        self.dep = None

    def bbox_hits(self, box):
        x0, y0, x1, y1 = box
        for _l, a, b, w in self.tracks:
            if min(a[0], b[0]) - w <= x1 and max(a[0], b[0]) + w >= x0 and \
               min(a[1], b[1]) - w <= y1 and max(a[1], b[1]) + w >= y0:
                return True
        for x, y, d, _dr in self.vias:
            if x0 - d <= x <= x1 + d and y0 - d <= y <= y1 + d:
                return True
        return False


class Router:
    def __init__(self, board, fps, nets, netinfo):
        self.board, self.fps, self.nets, self.netinfo = board, fps, nets, netinfo
        self.occ = np.zeros((2, H, W), np.int32)
        self.smd = np.zeros((H, W), bool)          # raw SMD pad copper on the top layer
        self.holes = np.zeros((H, W), bool)        # where a via drill would crowd another hole
        self.net_id = {name: i + 1 for i, name in enumerate(sorted(nets))}
        self.pads = []
        self.boxes = []                             # (box, net id) of every copper pad
        self.by_net = {}
        self.units = {}
        self.fixed = []                             # (net, layer, a, b, width) never ripped
        self.fixed_vias = []
        self.failed = []
        self.prerouted = set()                      # nets finished by fixed copper
        self.fine_pts = {}
        self._zone_masks = {}
        self.rips = 0
        self.order = {}
        self._collect()
        near = np.stack([dilate(self.occ[0] != 0, 4), dilate(self.occ[1] != 0, 4)])
        pen = near.astype(np.uint8) * PAD_PENALTY
        self.stub_ends = []
        self.usb_escape()
        for ref in STUBS:
            self.stubs(ref)
        for x, y in self.stub_ends:                 # leave room in front of every escape stub
            ix, iy, k = int(round(x / G)), int(round(y / G)), 7
            pen[0, max(iy - k, 0):iy + k + 1, max(ix - k, 0):ix + k + 1] = STUB_PENALTY
        self.pen = (pen[0].tobytes(), pen[1].tobytes())
        self.occ0 = self.occ.copy()
        self.plane_base = {}

    # ---- geometry helpers ------------------------------------------------
    @staticmethod
    def node(x, y, layer=0):
        return layer * N + int(round(y / G)) * W + int(round(x / G))

    def stamp_rect(self, layer, x0, y0, x1, y1, net, infl):
        ix0 = max(0, int(math.floor((x0 - infl) / G)))
        ix1 = min(W - 1, int(math.ceil((x1 + infl) / G)))
        iy0 = max(0, int(math.floor((y0 - infl) / G)))
        iy1 = min(H - 1, int(math.ceil((y1 + infl) / G)))
        if ix1 < ix0 or iy1 < iy0:
            return
        xs = np.arange(ix0, ix1 + 1) * G
        ys = np.arange(iy0, iy1 + 1) * G
        dx = np.maximum(np.maximum(x0 - xs, xs - x1), 0)[None, :]
        dy = np.maximum(np.maximum(y0 - ys, ys - y1), 0)[:, None]
        m = dx * dx + dy * dy <= infl * infl + 1e-9
        self._apply(layer, iy0, iy1, ix0, ix1, m, net)

    def stamp_seg(self, layer, ax, ay, bx, by, half, net, infl):
        rad = half + infl
        ix0 = max(0, int(math.floor((min(ax, bx) - rad) / G)))
        ix1 = min(W - 1, int(math.ceil((max(ax, bx) + rad) / G)))
        iy0 = max(0, int(math.floor((min(ay, by) - rad) / G)))
        iy1 = min(H - 1, int(math.ceil((max(ay, by) + rad) / G)))
        xs = (np.arange(ix0, ix1 + 1) * G)[None, :]
        ys = (np.arange(iy0, iy1 + 1) * G)[:, None]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        if L2 < 1e-12:
            t = np.zeros((ys.shape[0], xs.shape[1]))
        else:
            t = np.clip(((xs - ax) * vx + (ys - ay) * vy) / L2, 0, 1)
        d2 = (xs - (ax + t * vx)) ** 2 + (ys - (ay + t * vy)) ** 2
        self._apply(layer, iy0, iy1, ix0, ix1, d2 <= rad * rad + 1e-9, net)

    def _apply(self, layer, iy0, iy1, ix0, ix1, m, net):
        sub = self.occ[layer, iy0:iy1 + 1, ix0:ix1 + 1]
        if net < 0:
            sub[m] = -1
            return
        conflict = m & (sub != 0) & (sub != net)
        sub[m & (sub == 0)] = net
        sub[conflict] = -1

    # ---- board scan ------------------------------------------------------
    def _collect(self):
        F, B = pcbnew.F_Cu, pcbnew.B_Cu
        for ref, fp in self.fps.items():
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                x0, y0 = tm(bb.GetLeft()) - OX, tm(bb.GetTop()) - OY
                x1, y1 = tm(bb.GetRight()) - OX, tm(bb.GetBottom()) - OY
                cx, cy = tm(pad.GetPosition().x) - OX, tm(pad.GetPosition().y) - OY
                attr = pad.GetAttribute()
                drill = tm(pad.GetDrillSizeX())
                if drill > 0:
                    rr = max(drill, tm(pad.GetDrillSizeY())) / 2 + 0.25 + 0.25 + 0.05
                    k = int(math.ceil(rr / G))
                    ix, iy = int(round(cx / G)), int(round(cy / G))
                    yy, xx = np.ogrid[-k:k + 1, -k:k + 1]
                    disk = xx * xx + yy * yy <= (rr / G) ** 2
                    ya, yb, xa, xb = max(iy - k, 0), min(iy + k, H - 1), max(ix - k, 0), min(ix + k, W - 1)
                    self.holes[ya:yb + 1, xa:xb + 1] |= disk[ya - iy + k:yb - iy + k + 1, xa - ix + k:xb - ix + k + 1]
                name = pad.GetNetname()
                layers = [l for l, kl in ((0, F), (1, B)) if pad.IsOnLayer(kl)]
                if attr == pcbnew.PAD_ATTRIB_NPTH:
                    rad = max(drill, tm(pad.GetDrillSizeY())) / 2
                    if ref.startswith('H'):
                        rad = 3.0                    # room for the screw head
                    for l in (0, 1):
                        self.stamp_rect(l, cx, cy, cx, cy, -1, rad + 0.25 + BASE_HALF + MARGIN)
                    continue
                if not layers:
                    continue
                nid = self.net_id.get(name, -1)
                round_pad = abs((x1 - x0) - (y1 - y0)) < 0.02 and drill > 0
                for l in layers:
                    if round_pad:
                        self.stamp_rect(l, cx, cy, cx, cy, nid, (x1 - x0) / 2 + INF)
                    else:
                        self.stamp_rect(l, x0, y0, x1, y1, nid, INF)
                self.boxes.append(((x0, y0, x1, y1), nid if nid > 0 else -len(self.boxes) - 2, ref))
                smd = attr in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)
                if smd:
                    ix0, ix1 = int(math.floor(x0 / G)), int(math.ceil(x1 / G))
                    iy0, iy1 = int(math.floor(y0 / G)), int(math.ceil(y1 / G))
                    self.smd[max(iy0, 0):iy1 + 1, max(ix0, 0):ix1 + 1] = True
                if nid < 0:
                    continue
                p = dict(ref=ref, num=pad.GetNumber(), net=name, x=cx, y=cy, box=(x0, y0, x1, y1),
                         layers=layers, smd=smd, fine=min(x1 - x0, y1 - y0) <= 0.65 and smd,
                         nodes=None, pad=pad, idx=len(self.pads))
                self.pads.append(p)
                self.by_net.setdefault(name, []).append(p)
                if p['fine']:
                    self.fine_pts.setdefault(name, []).append((cx, cy))
            for z in fp.Zones():
                if z.GetIsRuleArea():
                    bb = z.GetBoundingBox()
                    for l in (0, 1):
                        self.stamp_rect(l, tm(bb.GetLeft()) - OX, tm(bb.GetTop()) - OY,
                                        tm(bb.GetRight()) - OX, tm(bb.GetBottom()) - OY,
                                        -1, BASE_HALF + MARGIN)
        for x0, y0, x1, y1, layers in getattr(L, 'KEEP_OUT', []):
            for l in layers:
                self.stamp_rect(l, x0, y0, x1, y1, -1, 0.0)
        e = int(math.ceil((0.5 + BASE_HALF + MARGIN) / G))
        self.occ[:, :e + 1, :] = -1
        self.occ[:, H - e - 1:, :] = -1
        self.occ[:, :, :e + 1] = -1
        self.occ[:, :, W - e - 1:] = -1
        rad = 2.0
        ys, xs = np.mgrid[0:H, 0:W]
        xs = xs * G
        ys = ys * G
        for cx, cy, sx, sy in ((rad, rad, -1, -1), (L.BOARD_W - rad, rad, 1, -1),
                               (rad, L.BOARD_H - rad, -1, 1), (L.BOARD_W - rad, L.BOARD_H - rad, 1, 1)):
            corner = ((xs - cx) * sx > 0) & ((ys - cy) * sy > 0) & \
                     (np.hypot(xs - cx, ys - cy) > rad - 0.5 - BASE_HALF - MARGIN)
            self.occ[:, corner] = -1

    def fix_track(self, net, layer, pts, width):
        for a, b in zip(pts, pts[1:]):
            self.fixed.append((net, layer, a, b, width))
            self.stamp_seg(layer, a[0], a[1], b[0], b[1], width / 2, self.net_id[net], INF)

    def fix_via(self, net, x, y, dia=0.6, drill=0.3):
        self.fixed_vias.append((net, x, y, dia, drill))
        for l in (0, 1):
            self.stamp_rect(l, x, y, x, y, self.net_id[net], dia / 2 + INF)
        k = int(math.ceil((drill / 2 + 0.55) / G))
        ix, iy = int(round(x / G)), int(round(y / G))
        self.holes[max(iy - k, 0):iy + k + 1, max(ix - k, 0):ix + k + 1] = True

    def usb_escape(self):
        """Hand-placed escape for the USB-C receptacle J3.

        The connector's D+ and D- pads interleave (B6 D+, A7 D-, A6 D+, B7 D-),
        so the pair cannot be joined on one layer.  The inner two pads run
        straight to the ESD array U4; the outer two fan away, pass above and
        below U4 and drop through vias to join on the far side.  CC pins go
        straight to their resistors, VBUS pads to vias, and the ground pads to
        the shield pads next to them."""
        def pad(ref, num):
            return [p for p in self.pads if p['ref'] == ref and p['num'] == num]
        def xy(ref, num):
            p = pad(ref, num)[0]
            return p['x'], p['y']
        if not pad('J3', 'A6'):
            return
        px = xy('J3', 'A6')[0]                      # x of the pad row
        y = {n: xy('J3', n)[1] for n in ('A5', 'B5', 'A6', 'B6', 'A7', 'B7', 'A4', 'A9', 'A1', 'B1')}
        dn, dp = pad('J3', 'A7')[0]['net'], pad('J3', 'A6')[0]['net']
        cc1, cc2 = pad('J3', 'A5')[0]['net'], pad('J3', 'B5')[0]['net']
        vbus, gnd = pad('J3', 'A4')[0]['net'], pad('J3', 'A1')[0]['net']
        u6x, u6y = xy('U4', '6')                    # U4 right column, D- row
        u4x, u4y = xy('U4', '4')                    # U4 right column, D+ row
        u1x = xy('U4', '1')[0]                      # U4 left column
        r11x, r12x = xy('R11', '1')[0], xy('R12', '1')[0]
        xs, xj = px - 1.37, px - 2.77               # end of straight stubs, start of inner fan
        # inner pair straight to U4, then under the body to its far pins and on to R11 / R12
        d = y['A7'] - u6y
        self.fix_track(dn, 0, [(px, y['A7']), (xj, y['A7']), (xj - d, u6y), (r11x, u6y)], 0.2)
        d = u4y - y['A6']
        self.fix_track(dp, 0, [(px, y['A6']), (xj, y['A6']), (xj - d, u4y), (r12x, u4y)], 0.2)
        # outer pair: fan out, run past U4, change layer, come back to the inner tracks
        top, bot = u6y - 0.95, u4y + 0.95
        xb = px - 1.92
        v1x, v3x = u1x - 2.46, u1x - 3.26
        d = y['B6'] - top
        self.fix_track(dp, 0, [(px, y['B6']), (xb, y['B6']), (xb - d, top), (v1x, top)], 0.2)
        self.fix_track(dp, 1, [(v1x, top), (v1x, u4y)], 0.2)
        self.fix_via(dp, v1x, top); self.fix_via(dp, v1x, u4y)
        d = bot - y['B7']
        self.fix_track(dn, 0, [(px, y['B7']), (xb, y['B7']), (xb - d, bot), (v3x, bot)], 0.2)
        self.fix_track(dn, 1, [(v3x, bot), (v3x, u6y)], 0.2)
        self.fix_via(dn, v3x, bot); self.fix_via(dn, v3x, u6y)
        # configuration channel pins straight into their pull-down resistors
        for net, yy, ref in ((cc2, y['B5'], 'R14'), (cc1, y['A5'], 'R13')):
            rx, ry = xy(ref, '1')
            sgn = -1 if ry < yy else 1
            dd = xs - rx
            self.fix_track(net, 0, [(px, yy), (xs, yy), (rx, yy + sgn * dd), (rx, ry)], 0.2)
        # VBUS pads to a via each; the ESD array reference pin gets its own via under the body
        for yy, sgn in ((y['A9'], -1), (y['A4'], 1)):
            vx, vy = round(px - 1.32, 1), round(yy + sgn * 0.5, 1)
            xk = vx + abs(vy - yy)
            self.fix_track(vbus, 0, [(px, yy), (xk, yy), (vx, vy)], 0.3)
            self.fix_via(vbus, vx, vy)
            for p in self.pads:
                if p['ref'] == 'J3' and p['net'] == vbus and abs(p['y'] - yy) < 0.01:
                    p['nodes'] = [self.node(vx, vy, 0), self.node(vx, vy, 1)]
        u5 = pad('U4', '5')[0]
        vx, vy = round(u5['x'] - 1.04, 1), round(u5['y'], 1)
        self.fix_track(vbus, 0, [(u5['x'], u5['y']), (vx, vy)], 0.25)
        self.fix_via(vbus, vx, vy)
        u5['nodes'] = [self.node(vx, vy, 0), self.node(vx, vy, 1)]
        # ground pads to the neighbouring shield pads (through-hole, on the ground plane)
        for yy, sgn in ((y['B1'], -1), (y['A1'], 1)):
            self.fix_track(gnd, 0, [(px, yy), (px, yy + sgn * 0.9)], 0.3)
            for p in self.pads:
                if p['ref'] == 'J3' and p['net'] == gnd and p['smd'] and abs(p['y'] - yy) < 0.01:
                    p['done'] = True
        self.prerouted.update((dn, dp, cc1, cc2))

    def stubs(self, ref):
        """Straight escapes for a fine-pitch part.  Each stub stays exactly on
        the pad centre line, then steps onto the grid in the same direction as
        its neighbours, so the spacing between stubs is preserved."""
        short, long_, special, via_pads = STUBS[ref]
        fp = self.fps[ref]
        fx, fy = tm(fp.GetPosition().x) - OX, tm(fp.GetPosition().y) - OY
        sides = {}
        for p in self.pads:
            if p['ref'] != ref or not p['smd'] or p['net'] in PLANE_NETS:
                continue
            if len(self.by_net[p['net']]) < 2:
                continue
            x0, y0, x1, y1 = p['box']
            if x1 - x0 >= y1 - y0:
                key = ('x', 1 if p['x'] > fx else -1)
            else:
                key = ('y', 1 if p['y'] > fy else -1)
            sides.setdefault(key, []).append(p)
        for (axis, sign), pads in sides.items():
            pads.sort(key=lambda p: p['y'] if axis == 'x' else p['x'])
            for i, p in enumerate(pads):
                x0, y0, x1, y1 = p['box']
                length = special.get(p['num'], long_ if i % 2 else short)
                nid = self.net_id[p['net']]
                while length >= 0.3:
                    if axis == 'x':
                        edge = x1 if sign > 0 else x0
                        e = (math.floor((edge + length) / G) if sign > 0 else math.ceil((edge - length) / G)) * G
                        perp = math.floor(p['y'] / G + 1e-6) * G
                        a, b, c = (p['x'], p['y']), (e, p['y']), (e + sign * G, perp)
                    else:
                        edge = y1 if sign > 0 else y0
                        e = (math.floor((edge + length) / G) if sign > 0 else math.ceil((edge - length) / G)) * G
                        perp = math.floor(p['x'] / G + 1e-6) * G
                        a, b, c = (p['x'], p['y']), (p['x'], e), (perp, e + sign * G)
                    if self._clear(a, b, nid, ref) and self._clear(b, c, nid, ref):
                        break
                    length -= 0.2
                else:
                    continue
                for s, t in ((a, b), (b, c)):
                    self.fixed.append((p['net'], 0, s, t, 0.2))
                    self.stamp_seg(0, s[0], s[1], t[0], t[1], 0.1, nid, INF)
                p['nodes'] = [self.node(c[0], c[1], 0)]
                self.stub_ends.append(c)
                self.fine_pts.setdefault(p['net'], []).append(c)   # wide nets start thin here
                if p['num'] in via_pads:
                    _w, clr, via, drill = self.klass(p['net'])
                    self.fixed_vias.append((p['net'], c[0], c[1], via, drill))
                    for l in (0, 1):
                        self.stamp_rect(l, c[0], c[1], c[0], c[1], nid, via / 2 + INF)
                    p['nodes'] = [self.node(c[0], c[1], 0), self.node(c[0], c[1], 1)]

    def _clear(self, a, b, nid, ref):
        """True if a thin track from a to b keeps its clearance to every pad of
        another net (exact geometry).  Pads of other parts get one grid cell of
        extra margin so the stub end stays usable on the grid."""
        tight = BASE_CLR + BASE_HALF - 1e-6
        loose = INF + G
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05) + 1)
        lo_x, hi_x = min(a[0], b[0]) - 1, max(a[0], b[0]) + 1
        lo_y, hi_y = min(a[1], b[1]) - 1, max(a[1], b[1]) + 1
        near = [(bx, tight if r == ref else loose) for bx, other, r in self.boxes
                if other != nid and bx[2] >= lo_x and bx[0] <= hi_x and bx[3] >= lo_y and bx[1] <= hi_y]
        for i in range(n + 1):
            x = a[0] + (b[0] - a[0]) * i / n
            y = a[1] + (b[1] - a[1]) * i / n
            for (x0, y0, x1, y1), need in near:
                dx = max(x0 - x, 0, x - x1)
                dy = max(y0 - y, 0, y - y1)
                if dx * dx + dy * dy < need * need:
                    return False
        return True

    def pad_nodes(self, p):
        """Grid nodes that lie on the pad copper (tested on the real pad shape,
        with a small margin, so a track ending on one always touches the pad)."""
        if p['nodes'] is None:
            x0, y0, x1, y1 = p['box']
            pad = p['pad']
            m = 0.06
            out = []
            for iy in range(int(math.ceil(y0 / G)), int(math.floor(y1 / G)) + 1):
                for ix in range(int(math.ceil(x0 / G)), int(math.floor(x1 / G)) + 1):
                    x, y = ix * G + OX, iy * G + OY
                    if all(pad.HitTest(pcbnew.VECTOR2I(mm(x + dx), mm(y + dy)))
                           for dx, dy in ((0, 0), (m, 0), (-m, 0), (0, m), (0, -m))):
                        out += [l * N + iy * W + ix for l in p['layers']]
            if not out:
                out = [self.node(p['x'], p['y'], l) for l in p['layers']]
            p['nodes'] = out
        return p['nodes']

    # ---- masks -----------------------------------------------------------
    def klass(self, net):
        return L.CLASSES[L.NET_CLASS.get(net, 'Default')]

    def masks(self, net):
        nid = self.net_id[net]
        width, clr, via, _drill = self.klass(net)
        thin = (self.occ == 0) | (self.occ == nid)
        extra = (width / 2 - BASE_HALF) + max(0.0, clr - BASE_CLR)
        k = int(math.ceil(extra / G - 1e-9))
        if k > 0:
            fat = np.stack([~dilate(~thin[0], k), ~dilate(~thin[1], k)])
            neck = np.zeros((H, W), bool)
            for (x, y) in self.fine_pts.get(net, []):
                ix, iy, rr = int(round(x / G)), int(round(y / G)), int(NECK_R / G)
                neck[max(iy - rr, 0):iy + rr + 1, max(ix - rr, 0):ix + rr + 1] = True
            passable = fat | (thin & neck[None, :, :])
        else:
            neck = None
            passable = thin
        kv = int(math.ceil((via / 2 - BASE_HALF + max(0.0, clr - BASE_CLR)) / G - 1e-9))
        ks = int(math.ceil((via / 2 + 0.1) / G))
        own = np.zeros((H, W), bool)                 # keep new vias off this net's existing ones
        for u in self.units.values():
            if u.net == net:
                for x, y, _d, _dr in u.vias:
                    own[int(round(y / G)), int(round(x / G))] = True
        for n, x, y, _d, _dr in self.fixed_vias:
            if n == net:
                own[int(round(y / G)), int(round(x / G))] = True
        via_ok = ~dilate(~thin[0], kv) & ~dilate(~thin[1], kv) & ~dilate(self.smd, ks) & \
            ~dilate(own, int(math.ceil((via + 0.3) / G))) & ~self.holes
        return passable, via_ok, neck

    def zone_mask(self, net):
        if net not in self._zone_masks:
            ys, xs = np.mgrid[0:H, 0:W]
            xs = xs * G
            ys = ys * G
            inset = 1.0
            if net == 'GND':
                m = np.ones((H, W), bool)
            elif net == '+12V':
                m = (xs <= L.SPLIT_X - inset) & (ys >= L.SPLIT_Y + inset)
            else:
                m = (xs >= L.SPLIT_X + inset) | (ys <= L.SPLIT_Y - inset)
            self._zone_masks[net] = m
        return self._zone_masks[net]

    # ---- search ----------------------------------------------------------
    def flood(self, passable, via_ok, starts):
        """Region reachable from `starts`, up to POCKET_LIMIT nodes.
        Returns (nodes, closed) where closed means the whole region was found."""
        pf, pb = passable[0].tobytes(), passable[1].tobytes()
        vok = via_ok.tobytes()
        seen = set(s for s in starts if (pf if s < N else pb)[s % N])
        dq = deque(seen)
        while dq and len(seen) < POCKET_LIMIT:
            n = dq.popleft()
            l, rem = divmod(n, N)
            p = pf if l == 0 else pb
            for d in (1, -1, W, -W):
                m = rem + d
                if 0 <= m < N and p[m]:
                    nn = l * N + m
                    if nn not in seen:
                        seen.add(nn)
                        dq.append(nn)
            if vok[rem]:
                nn = (1 - l) * N + rem
                if (pb if l == 0 else pf)[rem] and nn not in seen:
                    seen.add(nn)
                    dq.append(nn)
        return seen, not dq

    def search(self, passable, via_ok, starts, targets, goal_via=None, hint=None, window=None,
               via_cost=VIA_COST, weight=1.15):
        """A* from a set of start nodes to any node in `targets` (a set), or, when
        `goal_via` (bytes mask) is given, to any top-layer node where a plane via
        may be dropped.  Returns the node path or None."""
        pf, pb = passable[0].tobytes(), passable[1].tobytes()
        vok = via_ok.tobytes()
        qf, qb = self.pen
        if window:
            wx0, wy0, wx1, wy1 = window
        else:
            wx0, wy0, wx1, wy1 = 0, 0, W - 1, H - 1
        if hint is not None:
            tx, ty = int(round(hint[0] / G)), int(round(hint[1] / G))
        heap, best, parent = [], {}, {}
        for s in starts:
            l, rem = divmod(s, N)
            if not (pf if l == 0 else pb)[rem]:
                continue
            best[s] = 0
            heap.append((0, 0, s))
        heapq.heapify(heap)
        pop, push = heapq.heappop, heapq.heappush
        found = None
        while heap:
            _f, g, n = pop(heap)
            if g > best.get(n, 1 << 60):
                continue
            l, rem = divmod(n, N)
            if targets is not None and n in targets:
                found = n
                break
            if goal_via is not None and l == 0 and goal_via[rem]:
                found = n
                break
            iy, ix = divmod(rem, W)
            p = pf if l == 0 else pb
            q = qf if l == 0 else qb
            base = l * N
            for dx, dy, cost in MOVES:
                mx, my = ix + dx, iy + dy
                if mx < wx0 or mx > wx1 or my < wy0 or my > wy1:
                    continue
                m = my * W + mx
                if not p[m]:
                    continue
                if dx and dy and not (p[iy * W + mx] and p[my * W + ix]):
                    continue
                ng = g + cost + q[m]
                nn = base + m
                if ng < best.get(nn, 1 << 60):
                    best[nn] = ng
                    parent[nn] = n
                    if hint is not None:
                        ax, ay = abs(mx - tx), abs(my - ty)
                        h = (10 * max(ax, ay) + 4 * min(ax, ay)) * weight
                    else:
                        h = 0
                    push(heap, (ng + h, ng, nn))
            if vok[rem]:
                nn = (1 - l) * N + rem
                if (pb if l == 0 else pf)[rem]:
                    ng = g + via_cost
                    if ng < best.get(nn, 1 << 60):
                        best[nn] = ng
                        parent[nn] = n
                        if hint is not None:
                            ax, ay = abs(ix - tx), abs(iy - ty)
                            h = (10 * max(ax, ay) + 4 * min(ax, ay)) * weight
                        else:
                            h = 0
                        push(heap, (ng + h, ng, nn))
        if found is None:
            return None
        path = [found]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        path.reverse()
        return path

    # ---- committing copper ------------------------------------------------
    def add_track(self, unit, layer, a, b, width):
        if a == b:
            return
        unit.tracks.append((layer, a, b, width))
        self.stamp_seg(layer, a[0], a[1], b[0], b[1], width / 2, self.net_id[unit.net], INF)

    def add_via(self, unit, x, y):
        _w, clr, via, drill = self.klass(unit.net)
        here = [(vx, vy) for u in self.units.values() if u.net == unit.net for vx, vy, _d, _r in u.vias]
        here += [(vx, vy) for n, vx, vy, _d, _r in self.fixed_vias if n == unit.net]
        if any(abs(vx - x) < 1e-6 and abs(vy - y) < 1e-6 for vx, vy in here):
            return
        unit.vias.append((x, y, via, drill))
        for l in (0, 1):
            self.stamp_rect(l, x, y, x, y, self.net_id[unit.net],
                            via / 2 + INF + max(0.0, clr - BASE_CLR))

    def commit(self, unit, path, neck):
        """Turn a node path into tracks and vias on `unit`."""
        width = self.klass(unit.net)[0]
        nkb = neck.tobytes() if neck is not None else None
        pts = []
        for n in path:
            l, rem = divmod(n, N)
            iy, ix = divmod(rem, W)
            pts.append((l, ix, iy, bool(nkb[rem]) if nkb is not None else False))
        i = 0
        while i < len(pts) - 1:
            l, ix, iy, thin = pts[i]
            l2, ix2, iy2, thin2 = pts[i + 1]
            if l2 != l:
                self.add_via(unit, ix * G, iy * G)
                i += 1
                continue
            d = (ix2 - ix, iy2 - iy)
            w = BASE_HALF * 2 if (thin and thin2) else width
            j = i + 1
            while j < len(pts) - 1:
                a, b = pts[j], pts[j + 1]
                if b[0] != l or (b[1] - a[1], b[2] - a[2]) != d:
                    break
                if (BASE_HALF * 2 if (a[3] and b[3]) else width) != w:
                    break
                j += 1
            self.add_track(unit, l, (ix * G, iy * G), (pts[j][1] * G, pts[j][2] * G), w)
            i = j
        unit.nodes.update(path)

    def rebuild(self):
        self.occ = self.occ0.copy()
        for u in self.units.values():
            nid = self.net_id[u.net]
            clr = self.klass(u.net)[1]
            for layer, a, b, width in u.tracks:
                self.stamp_seg(layer, a[0], a[1], b[0], b[1], width / 2, nid, INF)
            for x, y, via, _drill in u.vias:
                for l in (0, 1):
                    self.stamp_rect(l, x, y, x, y, nid, via / 2 + INF + max(0.0, clr - BASE_CLR))

    # ---- jobs --------------------------------------------------------------
    def window(self, a, b, margin):
        return (max(0, int(min(a[0], b[0]) / G) - margin), max(0, int(min(a[1], b[1]) / G) - margin),
                min(W - 1, int(max(a[0], b[0]) / G) + margin), min(H - 1, int(max(a[1], b[1]) / G) + margin))

    def connect(self, net):
        """Route a signal net as a tree, nearest pad first.  Returns None when
        the net is complete, otherwise the nodes of the pocket that blocked it."""
        pads = self.by_net.get(net, [])
        unit = self.units.setdefault(('net', net), Unit(('net', net), net))
        tree = unit.nodes
        if not tree:
            tree.update(self.pad_nodes(min(pads, key=lambda p: p['x'] + p['y'])))
        while True:
            done = [p for p in pads if tree & set(self.pad_nodes(p))]
            rest = [p for p in pads if p not in done]
            if not rest:
                return None
            p = min(rest, key=lambda q: min(abs(q['x'] - d['x']) + abs(q['y'] - d['y']) for d in done))
            near = min(done, key=lambda d: abs(p['x'] - d['x']) + abs(p['y'] - d['y']))
            passable, via_ok, neck = self.masks(net)
            starts = self.pad_nodes(p)
            region, closed = self.flood(passable, via_ok, starts)
            if closed and not (region & tree):
                return region
            back, closed = self.flood(passable, via_ok, tree)
            if closed and not (back & set(starts)):
                return back
            path = None
            for margin in (60, 250, 1300):
                win = self.window((p['x'], p['y']), (near['x'], near['y']), margin)
                path = self.search(passable, via_ok, starts, tree, hint=(near['x'], near['y']), window=win)
                if path:
                    break
            if not path:
                return region
            self.commit(unit, path, neck)
            tree.update(starts)

    def plane_tree(self, net):
        if net not in self.plane_base:
            zone = self.zone_mask(net)
            base = set()
            for p in self.by_net.get(net, []):
                if not p['smd'] and zone[int(round(p['y'] / G)), int(round(p['x'] / G))]:
                    base.update(self.pad_nodes(p))
            self.plane_base[net] = base
        tree = set(self.plane_base[net])
        for u in self.units.values():
            if u.net == net:
                tree |= u.nodes
        return tree

    def fan(self, net, p):
        """Connect one pad of a plane net to its plane.  Returns None or the pocket."""
        key = ('fan', net, p['idx'])
        unit = self.units.setdefault(key, Unit(key, net))
        unit.clear()
        zone = self.zone_mask(net)
        starts = self.pad_nodes(p)
        tree = self.plane_tree(net)
        if p.get('done') or tree & set(starts):
            return None
        inzone = zone[int(round(p['y'] / G)), int(round(p['x'] / G))]
        count = 2 if (p['ref'], p['num']) in HEAVY else 1
        for i in range(count):
            passable, via_ok, neck = self.masks(net)
            goal = (via_ok & zone).tobytes()
            path = None
            for margin in ((40, 120, 400) if inzone else (400, 1300)):
                win = self.window((p['x'], p['y']), (p['x'], p['y']), margin)
                path = self.search(passable, via_ok, starts, tree if i == 0 else None, goal_via=goal,
                                   window=win, via_cost=10 ** 9)
                if path:
                    break
            if not path:
                if i:
                    break                        # the second via is a bonus
                region, _closed = self.flood(passable, via_ok, starts)
                return region
            end = path[-1]
            self.commit(unit, path, neck)
            if end in tree and end not in self.plane_base[net]:
                owner = next((u for u in self.units.values()
                              if u is not unit and u.net == net and end in u.nodes), None)
                if owner is not None:
                    unit.dep = owner.key
            if end not in tree:
                l, rem = divmod(end, N)
                iy, ix = divmod(rem, W)
                self.add_via(unit, ix * G, iy * G)
                unit.nodes.update((rem, N + rem))
            unit.nodes.update(starts)
        return None

    def do(self, job):
        return self.connect(job[1]) if job[0] == 'net' else self.fan(job[1], self.pads[job[2]])

    def victims(self, region, job):
        """Rippable units with copper next to a blocked pocket, plus every plane
        connection that leans on one of them."""
        xs = [(n % N) % W * G for n in region]
        ys = [(n % N) // W * G for n in region]
        box = (min(xs) - 0.7, min(ys) - 0.7, max(xs) + 0.7, max(ys) + 0.7)
        hit = {k for k, u in self.units.items()
               if k != job and (u.tracks or u.vias) and u.bbox_hits(box)}
        grew = True
        while grew:
            grew = False
            for k, u in self.units.items():
                if k not in hit and k != job and u.dep in hit:
                    hit.add(k)
                    grew = True
        return hit

    def run(self, jobs):
        """Work through the jobs; when one is boxed in, rip up its neighbours,
        route it, and put the neighbours back in their original order."""
        for j in jobs:
            self.order.setdefault(j, len(self.order))
        queue = deque(jobs)
        tries = {}
        while queue:
            job = queue.popleft()
            region = self.do(job)
            if region is None:
                continue
            tries[job] = tries.get(job, 0) + 1
            hit = self.victims(region, job) if region else set()
            if tries[job] > 6 or self.rips > 400 or not hit:
                name = job[1] if job[0] == 'net' else '%s %s.%s' % (
                    job[1], self.pads[job[2]]['ref'], self.pads[job[2]]['num'])
                self.failed.append((name, 'boxed in' if region else 'no path',
                                    'neighbours: ' + ', '.join(sorted({self.units[k].net for k in hit}))[:80]))
                continue
            for k in hit:
                self.units[k].clear()
            if job in self.units:
                self.units[job].clear()
            self.rips += 1
            self.rebuild()
            queue.appendleft(job)
            for k in sorted((k for k in hit if k not in queue), key=lambda k: self.order.get(k, 0),
                            reverse=True):
                queue.insert(1, k)

    def length(self, net):
        pads = self.by_net.get(net, [])
        xs = [p['x'] for p in pads]
        ys = [p['y'] for p in pads]
        return (max(xs) - min(xs)) + (max(ys) - min(ys)) if pads else 0

    # ---- output ------------------------------------------------------------
    def emit(self):
        F, B = pcbnew.F_Cu, pcbnew.B_Cu
        tracks = list(self.fixed)
        vias = list(self.fixed_vias)
        for u in self.units.values():
            tracks += [(u.net, l, a, b, w) for l, a, b, w in u.tracks]
            vias += [(u.net, x, y, d, dr) for x, y, d, dr in u.vias]
        for net, layer, a, b, width in tracks:
            t = pcbnew.PCB_TRACK(self.board)
            t.SetStart(pcbnew.VECTOR2I(mm(a[0] + OX), mm(a[1] + OY)))
            t.SetEnd(pcbnew.VECTOR2I(mm(b[0] + OX), mm(b[1] + OY)))
            t.SetWidth(mm(width))
            t.SetLayer(F if layer == 0 else B)
            t.SetNet(self.netinfo[net])
            self.board.Add(t)
        for net, x, y, dia, drill in vias:
            v = pcbnew.PCB_VIA(self.board)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetPosition(pcbnew.VECTOR2I(mm(x + OX), mm(y + OY)))
            v.SetLayerPair(F, B)
            try:
                v.SetWidth(F, mm(dia))
            except TypeError:
                v.SetWidth(mm(dia))
            v.SetDrill(mm(drill))
            v.SetNet(self.netinfo[net])
            self.board.Add(v)
        return len(tracks), len(vias)


def route(board, fps, nets, netinfo, fixed_only=False):
    t0 = time.time()
    r = Router(board, fps, nets, netinfo)
    if fixed_only:                                # for checking the hand-placed copper alone
        r.emit()
        return r
    signal = [n for n in nets if n not in PLANE_NETS and n not in r.prerouted
              and len(r.by_net.get(n, [])) >= 2]
    refs = {n: {p['ref'] for p in r.by_net[n]} for n in signal}
    wide = {'Supply': 0, 'Relay': 1}

    def rank(n):
        cls = L.NET_CLASS.get(n, 'Default')
        if 'J3' in refs[n] and cls == 'Default':
            return (0, r.length(n))               # USB data and CC first
        if cls in wide:
            return (1, wide[cls])
        if 'U3' in refs[n]:
            return (2, r.length(n))               # module pins before they get boxed in
        if 'U6' in refs[n] or 'U1' in refs[n]:
            return (3, r.length(n))
        return (4, r.length(n))

    jobs = [('net', n) for n in sorted(signal, key=rank)]
    r.run(jobs)
    print('  signal nets: %d, rip-ups %d, failures %d (%.0f s)' % (
        len(jobs), r.rips, len(r.failed), time.time() - t0))
    fans = []
    for net in PLANE_NETS:
        zone = r.zone_mask(net)
        for p in r.by_net.get(net, []):
            if p['smd'] or not zone[int(round(p['y'] / G)), int(round(p['x'] / G))]:
                fans.append(('fan', net, p['idx']))
    r.run(fans)
    nt, nv = r.emit()
    print('  routed: %d tracks, %d vias, %d rip-ups, %d failures (%.0f s)' % (
        nt, nv, r.rips, len(r.failed), time.time() - t0))
    for f in r.failed:
        print('  FAILED', f)
    return r
