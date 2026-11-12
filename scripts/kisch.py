"""Small KiCad schematic writer.

Places library symbols at explicit coordinates, resolves pin positions from the
real KiCad symbol libraries, and writes .kicad_sch files.  Wires are split at
T-points and junctions are added automatically, so connectivity in the file is
always endpoint-to-endpoint.
"""
import copy
import math
import os
import uuid

from sexp import Sym, dump, find, find_all, parse

def find_kicad_share():
    """KiCad's shared data folder: the one that holds symbols/, footprints/ and template/."""
    places = [os.environ.get('KICAD_SHARE'),
              os.path.expanduser('~/Applications/KiCad/KiCad.app/Contents/SharedSupport'),
              '/Applications/KiCad/KiCad.app/Contents/SharedSupport',
              '/usr/share/kicad', '/usr/local/share/kicad']
    for place in places:
        if place and os.path.isdir(os.path.join(place, 'symbols')):
            return place
    raise SystemExit('KiCad not found. Set KICAD_SHARE to the folder that holds symbols/ and footprints/.')


KICAD_SHARE = find_kicad_share()
NS = uuid.UUID('6f1d1f0a-5c0e-4b7e-9a57-0d2c6f1b7a11')
U = 2.54            # one schematic grid unit, mm
CHAR_W = 1.05       # rough advance of one character at 1.27 mm text


def uid(*parts):
    return str(uuid.uuid5(NS, '|'.join(str(p) for p in parts)))


def S(x):
    return Sym(x)


def r(v):
    return round(float(v) + 0.0, 4)


# --------------------------------------------------------------------------
# symbol libraries
# --------------------------------------------------------------------------
class Library:
    paths = {}      # library nickname -> file (project libraries)
    _libs = {}
    _flat = {}
    _info = {}

    @classmethod
    def lib(cls, name):
        if name not in cls._libs:
            path = cls.paths.get(name) or f'{KICAD_SHARE}/symbols/{name}.kicad_sym'
            tree = parse(open(path, encoding='utf-8').read())
            cls._libs[name] = {s[1]: s for s in find_all(tree, 'symbol')}
        return cls._libs[name]

    @classmethod
    def flat(cls, lib_id):
        if lib_id not in cls._flat:
            libname, name = lib_id.split(':', 1)
            node = cls._flatten(libname, name)
            node[1] = lib_id
            cls._flat[lib_id] = node
        return cls._flat[lib_id]

    @classmethod
    def _flatten(cls, libname, name):
        sym = cls.lib(libname)[name]
        ext = find(sym, 'extends')
        if ext is None:
            return copy.deepcopy(sym)
        basename = ext[1]
        base = cls._flatten(libname, basename)
        dprops = find_all(sym, 'property')
        dnames = {p[1] for p in dprops}
        header, props, units, tail = [], [], [], []
        for c in base[2:]:
            if not isinstance(c, list):
                continue
            if c[0] == 'property':
                if c[1] not in dnames:
                    props.append(c)
            elif c[0] == 'symbol':
                c = copy.deepcopy(c)
                c[1] = name + c[1][len(basename):]
                units.append(c)
            elif c[0] == 'embedded_fonts':
                tail.append(c)
            else:
                header.append(c)
        return ([S('symbol'), name] + header + [copy.deepcopy(p) for p in dprops]
                + props + units + tail)

    @classmethod
    def info(cls, lib_id):
        if lib_id not in cls._info:
            cls._info[lib_id] = SymInfo(lib_id)
        return cls._info[lib_id]


def _is_hidden(node):
    for c in node[1:]:
        if c == 'hide':
            return True
        if isinstance(c, list) and c and c[0] == 'hide' and (len(c) == 1 or c[1] == 'yes'):
            return True
    eff = find(node, 'effects')
    if eff is not None:
        return _is_hidden(eff)
    return False


class SymInfo:
    """Pins, default field placement and body extent of a library symbol."""

    def __init__(self, lib_id):
        self.lib_id = lib_id
        self.node = Library.flat(lib_id)
        self.name = lib_id.split(':', 1)[1]
        self.is_power = find(self.node, 'power') is not None
        self.props = {}
        for p in find_all(self.node, 'property'):
            at = find(p, 'at')
            eff = find(p, 'effects')
            just = find(eff, 'justify') if eff is not None else None
            self.props[p[1]] = dict(
                value=p[2], x=float(at[1]), y=float(at[2]),
                angle=float(at[3]) if len(at) > 3 else 0.0,
                justify=[str(j) for j in just[1:]] if just else [],
                hidden=_is_hidden(p))
        self.pins = []
        bx, by = [], []
        for unit in find_all(self.node, 'symbol'):
            unit_no = int(unit[1][len(self.name) + 1:].split('_')[0])
            for g in unit[2:]:
                if not isinstance(g, list):
                    continue
                kind = g[0]
                if kind == 'pin':
                    at = find(g, 'at')
                    self.pins.append(dict(
                        unit=unit_no, etype=str(g[1]),
                        x=float(at[1]), y=float(at[2]), angle=float(at[3]),
                        length=float(find(g, 'length')[1]),
                        name=find(g, 'name')[1], number=find(g, 'number')[1],
                        hidden=_is_hidden(g)))
                elif kind == 'rectangle':
                    for k in ('start', 'end'):
                        c = find(g, k)
                        bx.append(float(c[1])); by.append(float(c[2]))
                elif kind in ('polyline', 'bezier'):
                    for c in find(g, 'pts')[1:]:
                        bx.append(float(c[1])); by.append(float(c[2]))
                elif kind == 'circle':
                    c = find(g, 'center'); rad = float(find(g, 'radius')[1])
                    bx += [float(c[1]) - rad, float(c[1]) + rad]
                    by += [float(c[2]) - rad, float(c[2]) + rad]
                elif kind == 'arc':
                    for k in ('start', 'mid', 'end'):
                        c = find(g, k)
                        bx.append(float(c[1])); by.append(float(c[2]))
        self.body = (min(bx), min(by), max(bx), max(by)) if bx else (-1, -1, 1, 1)


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def matrix(rot, mirror):
    m = {0: (1, 0, 0, -1), 90: (0, -1, -1, 0),
         180: (-1, 0, 0, 1), 270: (0, 1, 1, 0)}[rot]
    x1, y1, x2, y2 = m
    if mirror == 'y':
        x1, y1 = -x1, -y1
    elif mirror == 'x':
        x2, y2 = -x2, -y2
    return x1, y1, x2, y2


def xf(m, px, py):
    return m[0] * px + m[1] * py, m[2] * px + m[3] * py


class Pin:
    def __init__(self, part, d, x, y, dx, dy):
        self.part, self.d = part, d
        self.x, self.y, self.dx, self.dy = x, y, dx, dy
        self.number, self.name, self.etype = d['number'], d['name'], d['etype']

    @property
    def xy(self):
        return (self.x, self.y)

    def out(self, n=1.0):
        """Point n grid units away from the body along the pin direction."""
        return (r(self.x + self.dx * n * U), r(self.y + self.dy * n * U))


def pt(p):
    if isinstance(p, Pin):
        return (p.x, p.y)
    return (r(p[0]), r(p[1]))


# --------------------------------------------------------------------------
# placed symbol
# --------------------------------------------------------------------------
class Part:
    def __init__(self, sheet, lib_id, ref, x, y, rot=0, mirror=None, value=None,
                 footprint=None, fields=None, fpos=None, dnp=False, unit=1,
                 in_bom=True, on_board=True, show_value=True, datasheet=None):
        self.sheet, self.lib_id, self.ref = sheet, lib_id, ref
        self.x, self.y, self.rot, self.mirror = r(x), r(y), rot, mirror
        self.info = Library.info(lib_id)
        self.m = matrix(rot, mirror)
        self.value = value if value is not None else self.info.props['Value']['value']
        fp = self.info.props.get('Footprint', {}).get('value', '')
        self.footprint = footprint if footprint is not None else fp
        self.datasheet = datasheet or self.info.props.get('Datasheet', {}).get('value', '~') or '~'
        self.fields = dict(fields or {})
        self.fpos = dict(fpos or {})
        self.dnp, self.unit = dnp, unit
        self.in_bom, self.on_board, self.show_value = in_bom, on_board, show_value
        self.pins = []
        for d in self.info.pins:
            if d['unit'] not in (0, unit):
                continue
            ox, oy = xf(self.m, d['x'], d['y'])
            a = math.radians(d['angle'])
            # direction pointing away from the body, in symbol coordinates
            vx, vy = -round(math.cos(a)), -round(math.sin(a))
            dx, dy = xf(self.m, vx, vy)
            self.pins.append(Pin(self, d, r(self.x + ox), r(self.y + oy), dx, dy))

    def pin(self, key):
        key = str(key)
        for p in self.pins:
            if p.number == key:
                return p
        named = [p for p in self.pins if p.name == key]
        if not named:
            raise KeyError(f'{self.ref} ({self.lib_id}) has no pin {key!r}')
        vis = [p for p in named if not p.d['hidden']]
        return (vis or named)[0]

    __getitem__ = pin

    # ---- field placement -------------------------------------------------
    def _stored_text(self, want_just):
        """Return (angle, justify) to store so text shows horizontal with the
        wanted on-screen justification under this symbol's transform."""
        vertical = self.rot in (90, 270)
        angle = 90 if vertical else 0
        vx, vy = (0, 1) if vertical else (1, 0)
        flipped = (self.m[0] * vx + self.m[1] * vy) < 0
        just = want_just
        if flipped and want_just in ('left', 'right'):
            just = 'right' if want_just == 'left' else 'left'
        return angle, just

    def _two_terminal(self):
        vis = [p for p in self.pins]
        return len(vis) == 2 and not self.info.is_power

    def field_positions(self):
        """name -> (x, y, angle, justify) for Reference and Value."""
        out = {}
        if self.fpos:
            for name, spec in self.fpos.items():
                dx, dy = spec[0], spec[1]
                want = spec[2] if len(spec) > 2 else None
                angle, just = self._stored_text(want)
                out[name] = (r(self.x + dx), r(self.y + dy), angle, just)
        if self._two_terminal() and 'Reference' not in out:
            a, b = self.pins
            bx0, by0, bx1, by1 = self.info.body
            if abs(a.x - b.x) < 0.01:      # vertical part: text to the right
                half = max(abs(xf(self.m, bx0, by0)[0]), abs(xf(self.m, bx1, by1)[0]))
                angle, just = self._stored_text('left')
                x = r(self.x + half + 0.9)
                out.setdefault('Reference', (x, r(self.y - 1.27), angle, just))
                out.setdefault('Value', (x, r(self.y + 1.27), angle, just))
            else:                          # horizontal part: text above / below
                half = max(abs(xf(self.m, bx0, by0)[1]), abs(xf(self.m, bx1, by1)[1]))
                angle, just = self._stored_text(None)
                out.setdefault('Reference', (self.x, r(self.y - half - 1.5), angle, just))
                out.setdefault('Value', (self.x, r(self.y + half + 1.5), angle, just))
        if self.info.is_power and 'Value' not in out and (self.rot or self.mirror):
            p = self.info.props['Value']
            ox, oy = xf(self.m, 0, 1 if p['y'] > 0 else -1)
            if ox:
                angle, just = self._stored_text('left' if ox > 0 else 'right')
                out['Value'] = (r(self.x + ox * 3.3), self.y, angle, just)
            else:
                angle, just = self._stored_text(None)
                out['Value'] = (self.x, r(self.y + oy * 4.2), angle, just)
        for name in ('Reference', 'Value'):
            if name in out:
                continue
            p = self.info.props[name]
            ox, oy = xf(self.m, p['x'], p['y'])
            if self.rot == 0 and self.mirror is None:
                just = None
                if 'left' in p['justify']:
                    just = 'left'
                elif 'right' in p['justify']:
                    just = 'right'
                out[name] = (r(self.x + ox), r(self.y + oy), p['angle'], just)
            else:
                angle, just = self._stored_text(None)
                out[name] = (r(self.x + ox), r(self.y + oy), angle, just)
        return out

    # ---- serialisation ---------------------------------------------------
    def _prop(self, name, value, x, y, angle=0, justify=None, hide=False):
        eff = [S('effects'), [S('font'), [S('size'), 1.27, 1.27]]]
        if justify:
            eff.append([S('justify'), S(justify)])
        if hide:
            eff.append([S('hide'), S('yes')])
        return [S('property'), name, value, [S('at'), x, y, angle], eff]

    def node(self, project, path):
        n = [S('symbol'), [S('lib_id'), self.lib_id],
             [S('at'), self.x, self.y, self.rot]]
        if self.mirror:
            n.append([S('mirror'), S(self.mirror)])
        n += [[S('unit'), self.unit],
              [S('exclude_from_sim'), S('no')],
              [S('in_bom'), S('yes' if self.in_bom else 'no')],
              [S('on_board'), S('yes' if self.on_board else 'no')],
              [S('dnp'), S('yes' if self.dnp else 'no')],
              [S('fields_autoplaced'), S('yes')],
              [S('uuid'), uid(path, 'sym', self.ref)]]
        fp = self.field_positions()
        rx, ry, ra, rj = fp['Reference']
        vx, vy, va, vj = fp['Value']
        power = self.info.is_power
        n.append(self._prop('Reference', self.ref, rx, ry, ra, rj, hide=power))
        n.append(self._prop('Value', self.value, vx, vy, va, vj, hide=not self.show_value))
        n.append(self._prop('Footprint', self.footprint, self.x, self.y, hide=True))
        n.append(self._prop('Datasheet', self.datasheet, self.x, self.y, hide=True))
        desc = self.fields.pop('Description', None)
        if desc is None:
            desc = self.info.props.get('Description', {}).get('value', '')
        n.append(self._prop('Description', desc, self.x, self.y, hide=True))
        for k, v in self.fields.items():
            n.append(self._prop(k, v, self.x, self.y, hide=True))
        for p in self.pins:
            n.append([S('pin'), p.number, [S('uuid'), uid(path, 'pin', self.ref, p.number, p.name)]])
        n.append([S('instances'), [S('project'), project,
                 [S('path'), path, [S('reference'), self.ref], [S('unit'), self.unit]]]])
        return n


# --------------------------------------------------------------------------
# sheet
# --------------------------------------------------------------------------
class Sheet:
    def __init__(self, name, filename, title, paper='A3', page='1'):
        self.name, self.filename, self.title = name, filename, title
        self.paper, self.page = paper, page
        self.uuid = uid('sheetfile', filename)
        self.parts, self.wires = [], []
        self.labels, self.glabels, self.ncs = [], [], []
        self.texts, self.rects, self.subsheets = [], [], []
        self.project = None
        self.path = None          # instance path, set by Project

    # ---- placement -------------------------------------------------------
    def part(self, lib_id, ref, x, y, **kw):
        p = Part(self, lib_id, ref, x, y, **kw)
        self.parts.append(p)
        return p

    pwr_count = 0

    def power(self, name, at, rot=0):
        """Place a power symbol whose pin sits at `at`."""
        x, y = pt(at)
        Sheet.pwr_count += 1
        prefix = '#FLG' if name == 'PWR_FLAG' else '#PWR'
        return self.part('power:' + name, '%s%03d' % (prefix, Sheet.pwr_count), x, y, rot=rot)

    def gnd(self, at, rot=0):
        return self.power('GND', at, rot)

    def wire(self, *points):
        pts = [pt(p) for p in points]
        for a, b in zip(pts, pts[1:]):
            if a != b:
                if abs(a[0] - b[0]) > 0.001 and abs(a[1] - b[1]) > 0.001:
                    raise ValueError(f'diagonal wire {a} -> {b} on {self.name}')
                self.wires.append((a, b))
        return pts[-1]

    def label(self, text, at, rot=0):
        self.labels.append((text, pt(at), rot))

    def glabel(self, text, at, side='right', shape='bidirectional'):
        """Global label; `side` is the direction the text extends from `at`."""
        self.glabels.append((text, pt(at), side, shape))

    def nc(self, at):
        self.ncs.append(pt(at))

    def text(self, s, at, size=1.27, bold=False, justify='left'):
        self.texts.append((s, pt(at), size, bold, justify))

    def rect(self, a, b, dash=True):
        self.rects.append((pt(a), pt(b), dash))

    def block(self, a, b, title):
        """Dashed frame with a heading, used to group a functional block."""
        a, b = pt(a), pt(b)
        self.rect(a, b)
        self.text(title, (a[0] + 1.5, a[1] + 3.9), size=1.8, bold=True)

    # ---- convenience -----------------------------------------------------
    def tag(self, pin, name, n=2.0, shape='bidirectional'):
        """Stub wire from a pin plus a global label at its end."""
        end = pin.out(n)
        self.wire(pin, end)
        side = {(1, 0): 'right', (-1, 0): 'left', (0, -1): 'up', (0, 1): 'down'}[(pin.dx, pin.dy)]
        self.glabel(name, end, side, shape)
        return end

    # ---- connectivity clean-up ------------------------------------------
    def _all_pins(self):
        return [p for part in self.parts for p in part.pins]

    def finalize(self):
        """Split wires at T-points and compute junctions."""
        points = set()
        for a, b in self.wires:
            points.add(a); points.add(b)
        pin_pts = {}
        for p in self._all_pins():
            pin_pts.setdefault(p.xy, []).append(p)
        points |= set(pin_pts)
        points |= {l[1] for l in self.labels} | {g[1] for g in self.glabels}

        def inside(p, a, b):
            if a[0] == b[0] == p[0]:
                return min(a[1], b[1]) + 0.001 < p[1] < max(a[1], b[1]) - 0.001
            if a[1] == b[1] == p[1]:
                return min(a[0], b[0]) + 0.001 < p[0] < max(a[0], b[0]) - 0.001
            return False

        segs = []
        for a, b in self.wires:
            cuts = sorted((p for p in points if inside(p, a, b)),
                          key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
            chain = [a] + cuts + [b]
            segs += list(zip(chain, chain[1:]))
        # drop exact duplicates
        seen, uniq = set(), []
        for a, b in segs:
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key); uniq.append((a, b))
        self.segs = uniq
        count = {}
        for a, b in uniq:
            count[a] = count.get(a, 0) + 1
            count[b] = count.get(b, 0) + 1
        self.junctions = sorted(
            p for p, c in count.items()
            if c >= 3 or (c >= 2 and p in pin_pts))
        # dangling wire ends are almost always a drawing mistake
        self.dangling = []
        occupied = set(pin_pts) | {l[1] for l in self.labels} | {g[1] for g in self.glabels} | set(self.ncs)
        for p, c in count.items():
            if c == 1 and p not in occupied:
                self.dangling.append(p)

    # ---- serialisation ---------------------------------------------------
    def tree(self, project, date, rev, company=''):
        self.finalize()
        path = self.path
        n = [S('kicad_sch'), [S('version'), 20250114], [S('generator'), 'eeschema'],
             [S('generator_version'), '9.0'], [S('uuid'), self.uuid],
             [S('paper'), self.paper],
             [S('title_block'), [S('title'), self.title], [S('date'), date],
              [S('rev'), rev], [S('company'), company],
              [S('comment'), 1, project.description]]]
        libs = [S('lib_symbols')]
        for lib_id in sorted({p.lib_id for p in self.parts}):
            libs.append(copy.deepcopy(Library.flat(lib_id)))
        n.append(libs)
        for p in self.junctions:
            n.append([S('junction'), [S('at'), p[0], p[1]], [S('diameter'), 0],
                      [S('color'), 0, 0, 0, 0], [S('uuid'), uid(path, 'j', p)]])
        for p in self.ncs:
            n.append([S('no_connect'), [S('at'), p[0], p[1]], [S('uuid'), uid(path, 'nc', p)]])
        for a, b in self.segs:
            n.append([S('wire'), [S('pts'), [S('xy'), a[0], a[1]], [S('xy'), b[0], b[1]]],
                      [S('stroke'), [S('width'), 0], [S('type'), S('default')]],
                      [S('uuid'), uid(path, 'w', a, b)]])
        for (a, b, dash) in self.rects:
            n.append([S('rectangle'), [S('start'), a[0], a[1]], [S('end'), b[0], b[1]],
                      [S('stroke'), [S('width'), 0.15], [S('type'), S('dash' if dash else 'solid')]],
                      [S('fill'), [S('type'), S('none')]], [S('uuid'), uid(path, 'r', a, b)]])
        for i, (s, p, size, bold, just) in enumerate(self.texts):
            font = [S('font'), [S('size'), size, size]]
            if bold:
                font.append([S('bold'), S('yes')])
            eff = [S('effects'), font]
            eff.append([S('justify'), S(just), S('bottom')] if just != 'center'
                       else [S('justify'), S('bottom')])
            n.append([S('text'), s, [S('exclude_from_sim'), S('no')], [S('at'), p[0], p[1], 0],
                      eff, [S('uuid'), uid(path, 't', i, s)]])
        for i, (text, p, rot) in enumerate(self.labels):
            n.append([S('label'), text, [S('at'), p[0], p[1], rot],
                      [S('effects'), [S('font'), [S('size'), 1.27, 1.27]],
                       [S('justify'), S('left'), S('bottom')]],
                      [S('uuid'), uid(path, 'l', i, text, p)]])
        for i, (text, p, side, shape) in enumerate(self.glabels):
            angle = {'right': 0, 'up': 90, 'left': 180, 'down': 270}[side]
            just = 'left' if side in ('right', 'up') else 'right'
            n.append([S('global_label'), text, [S('shape'), S(shape)],
                      [S('at'), p[0], p[1], angle], [S('fields_autoplaced'), S('yes')],
                      [S('effects'), [S('font'), [S('size'), 1.27, 1.27]], [S('justify'), S(just)]],
                      [S('uuid'), uid(path, 'g', i, text, p)],
                      [S('property'), 'Intersheetrefs', '${INTERSHEET_REFS}',
                       [S('at'), p[0], p[1], 0],
                       [S('effects'), [S('font'), [S('size'), 1.27, 1.27]],
                        [S('justify'), S(just)], [S('hide'), S('yes')]]]])
        for part in self.parts:
            n.append(part.node(project.name, path))
        for sub in self.subsheets:
            child, (x, y), (w, h) = sub
            n.append([S('sheet'), [S('at'), x, y], [S('size'), w, h],
                      [S('exclude_from_sim'), S('no')], [S('in_bom'), S('yes')],
                      [S('on_board'), S('yes')], [S('dnp'), S('no')],
                      [S('fields_autoplaced'), S('yes')],
                      [S('stroke'), [S('width'), 0.1524], [S('type'), S('solid')]],
                      [S('fill'), [S('color'), 0, 0, 0, 0.0]],
                      [S('uuid'), child.sheet_uuid],
                      [S('property'), 'Sheetname', child.name, [S('at'), x, r(y - 0.7), 0],
                       [S('effects'), [S('font'), [S('size'), 1.6, 1.6], [S('bold'), S('yes')]],
                        [S('justify'), S('left'), S('bottom')]]],
                      [S('property'), 'Sheetfile', child.filename, [S('at'), x, r(y + h + 0.6), 0],
                       [S('effects'), [S('font'), [S('size'), 1.27, 1.27]],
                        [S('justify'), S('left'), S('top')]]],
                      [S('instances'), [S('project'), project.name,
                       [S('path'), self.path, [S('page'), child.page]]]]])
        if self is project.root:
            n.append([S('sheet_instances'), [S('path'), '/', [S('page'), self.page]]])
        n.append([S('embedded_fonts'), S('no')])
        return n


class Project:
    def __init__(self, name, directory, description=''):
        self.name, self.dir, self.description = name, directory, description
        self.root = None
        self.sheets = []

    def set_root(self, sheet):
        self.root = sheet
        sheet.path = '/' + sheet.uuid
        self.sheets.append(sheet)

    def add_child(self, sheet, at, size):
        sheet.sheet_uuid = uid('sheetsym', sheet.filename)
        sheet.path = self.root.path + '/' + sheet.sheet_uuid
        self.root.subsheets.append((sheet, (r(at[0]), r(at[1])), (r(size[0]), r(size[1]))))
        self.sheets.append(sheet)

    def write(self, date, rev, company=''):
        problems = []
        for sh in self.sheets:
            tree = sh.tree(self, date, rev, company)
            with open(os.path.join(self.dir, sh.filename), 'w', encoding='utf-8') as fh:
                fh.write(dump(tree) + '\n')
            for p in sh.dangling:
                problems.append(f'{sh.name}: dangling wire end at {p}')
        return problems
