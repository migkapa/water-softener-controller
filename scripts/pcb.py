#!/usr/bin/env python3
"""Build water_softener.kicad_pcb from the schematic netlist.

Run with the Python that ships inside KiCad (it provides `pcbnew`):

    <KiCad.app>/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 scripts/pcb.py

Steps: load the netlist, place every footprint from pcb_layout.P, draw the
outline, route (pcb_route.py), add the copper planes and pours, fill, save.
"""
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import pcbnew  # noqa: E402

import pcb_layout as L  # noqa: E402
from sexp import find, find_all, parse  # noqa: E402

NAME = 'water_softener'
PCB = os.path.join(ROOT, NAME + '.kicad_pcb')
NETLIST = os.path.join(ROOT, 'output', NAME + '.net')
SHARE = os.environ.get('KICAD_SHARE') or os.path.normpath(
    os.path.join(os.path.dirname(pcbnew.__file__), *(['..'] * 6), 'SharedSupport'))
if not os.path.isdir(os.path.join(SHARE, 'footprints')):
    from kisch import KICAD_SHARE as SHARE  # noqa: E402
OX, OY = L.ORIGIN
mm = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(mm(x + OX), mm(y + OY))


def load_netlist(path):
    tree = parse(open(path, encoding='utf-8').read())
    comps = {}
    for c in find_all(find(tree, 'components'), 'comp'):
        fields = {}
        for f in find_all(find(c, 'fields') or ['fields'], 'field'):
            fields[find(f, 'name')[1]] = f[2] if len(f) > 2 and not isinstance(f[2], list) else ''
        props = {}
        for p in find_all(c, 'property'):
            v = find(p, 'value')
            props[find(p, 'name')[1]] = v[1] if v is not None and len(v) > 1 else ''
        sp = find(c, 'sheetpath')
        d = find(c, 'description')
        comps[find(c, 'ref')[1]] = dict(
            value=find(c, 'value')[1], footprint=find(c, 'footprint')[1], fields=fields,
            props=props, sheet=find(sp, 'names')[1], sheet_ts=find(sp, 'tstamps')[1],
            ts=find(c, 'tstamps')[1], desc=d[1] if d is not None and len(d) > 1 else '')
    nets = {}
    for n in find_all(find(tree, 'nets'), 'net'):
        nets[find(n, 'name')[1]] = [(find(x, 'ref')[1], find(x, 'pin')[1])
                                    for x in find_all(n, 'node')]
    return comps, nets


def setup_rules(board, nets):
    ds = board.GetDesignSettings()
    ns = ds.m_NetSettings
    for name, (width, clr, via, drill) in L.CLASSES.items():
        nc = ns.GetDefaultNetclass() if name == 'Default' else pcbnew.NETCLASS(name)
        nc.SetTrackWidth(mm(width)); nc.SetClearance(mm(clr))
        nc.SetViaDiameter(mm(via)); nc.SetViaDrill(mm(drill))
        if name != 'Default':
            ns.SetNetclass(name, nc)
    for net, cls in L.NET_CLASS.items():
        if net not in nets:
            raise SystemExit('net class table names an unknown net: %s' % net)
        ns.SetNetclassPatternAssignment(net, cls)


def add_footprints(board, comps, nets):
    missing = sorted(set(comps) - set(L.P))
    extra = sorted(set(L.P) - set(comps))
    if missing or extra:
        raise SystemExit('placement table mismatch: missing %s, unknown %s' % (missing, extra))
    netinfo = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pad_net = {(ref, pin): name for name, nodes in nets.items() for ref, pin in nodes}
    fps = {}
    for ref in sorted(comps, key=lambda r: (r.rstrip('0123456789'), int(''.join(ch for ch in r if ch.isdigit()) or 0))):
        c = comps[ref]
        lib, fpname = c['footprint'].split(':', 1)
        fp = pcbnew.FootprintLoad(os.path.join(SHARE, 'footprints', lib + '.pretty'), fpname)
        if fp is None:
            raise SystemExit('footprint not found: %s' % c['footprint'])
        fp.SetFPIDAsString(c['footprint'])
        fp.SetReference(ref)
        fp.SetValue(c['value'])
        fp.SetPath(pcbnew.KIID_PATH(c['sheet_ts'] + c['ts']))
        fp.SetSheetname(c['sheet'])
        fp.SetSheetfile(c['props'].get('Sheetfile', ''))
        fp.SetField('Description', c['desc'])
        fp.SetField('Datasheet', c['fields'].get('Datasheet', ''))
        for key in ('Description', 'Datasheet'):
            fp.GetField(key).SetVisible(False)
        for key in ('Rating', 'Manufacturer', 'MPN'):
            if c['fields'].get(key):
                fp.SetField(key, c['fields'][key])
                fld = fp.GetField(key) if fp.HasField(key) else None
                if fld is not None:
                    fld.SetVisible(False)
        if ref.startswith(('TP', 'H')):
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM)
        # silkscreen: keep designators for parts a person has to find, drop them
        # for small passives, holes and terminals (those get a function legend)
        rt = fp.Reference()
        if ref[0] in 'RCH' or ref in TERMINALS or ref in CROWDED:
            rt.SetVisible(False)
        else:
            rt.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
            rt.SetTextThickness(mm(0.12))
        add_body(fp, ref)
        board.Add(fp)
        x, y, rot = L.P[ref]
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            net = pad_net.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(netinfo[net])
        fps[ref] = fp
    return fps, netinfo


TERMINALS = ('J2', 'J6', 'J7', 'J8', 'J9', 'J10', 'J11', 'J12')
CROWDED = ('Q2', 'Q5', 'Q6', 'Q7', 'Q8', 'D8')     # no room for a designator next to these


def wrl_box(path, size, colour, extra=''):
    """Write a one-box VRML model (KiCad reads VRML in units of 2.54 mm)."""
    sx, sy, sz = (v / 2.54 for v in size)
    with open(path, 'w') as fh:
        fh.write('#VRML V2.0 utf8\n')
        fh.write('Transform { translation 0 0 %.4f children [ Shape {\n' % (sz / 2))
        fh.write('  appearance Appearance { material Material { diffuseColor %.2f %.2f %.2f '
                 'specularColor 0.2 0.2 0.2 shininess 0.3 } }\n' % colour)
        fh.write('  geometry Box { size %.4f %.4f %.4f } } ] }\n' % (sx, sy, sz))
        fh.write(extra)


def module_model(path):
    """ESP32-C6-MINI-1: carrier board, shield can and antenna area."""
    def box(size, centre, colour):
        sx, sy, sz = (v / 2.54 for v in size)
        cx, cy, cz = (v / 2.54 for v in centre)
        return ('Transform { translation %.4f %.4f %.4f children [ Shape {\n'
                '  appearance Appearance { material Material { diffuseColor %.2f %.2f %.2f '
                'specularColor 0.4 0.4 0.4 shininess 0.5 } }\n'
                '  geometry Box { size %.4f %.4f %.4f } } ] }\n'
                % (cx, cy, cz, colour[0], colour[1], colour[2], sx, sy, sz))
    with open(path, 'w') as fh:
        fh.write('#VRML V2.0 utf8\n')
        fh.write(box((13.2, 16.6, 0.8), (0, 2.7, 0.4), (0.08, 0.10, 0.12)))      # carrier
        fh.write(box((11.8, 10.4, 1.6), (0, -0.2, 1.6), (0.78, 0.78, 0.80)))    # shield can
        fh.write(box((10.5, 0.5, 0.05), (0, 9.6, 0.83), (0.80, 0.65, 0.25)))    # antenna trace
        fh.write(box((0.5, 3.6, 0.05), (-5.0, 8.0, 0.83), (0.80, 0.65, 0.25)))
        fh.write(box((0.5, 3.6, 0.05), (2.0, 8.0, 0.83), (0.80, 0.65, 0.25)))


def add_body(fp, ref):
    d3 = os.path.join(ROOT, '3d')
    name = None
    if ref in L.BODIES:
        name, size, (cx, cy), colour = L.BODIES[ref]
        os.makedirs(d3, exist_ok=True)
        path = os.path.join(d3, name + '.wrl')
        wrl_box(path, size, colour)
        offset = (cx, -cy, 0.0)
    elif ref == 'U3':
        name = 'esp32_c6_mini_1'
        os.makedirs(d3, exist_ok=True)
        module_model(os.path.join(d3, name + '.wrl'))
        offset = (0.0, 0.0, 0.0)
    elif ref == 'U6':
        # the footprint names a model that the library does not ship
        fp.Models().clear()
        m = pcbnew.FP_3DMODEL()
        m.m_Filename = ('${KICAD10_3DMODEL_DIR}/Package_SO.3dshapes/'
                        'HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm.step')
        fp.Add3DModel(m)
        return
    if not name:
        return
    fp.Models().clear()
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = '${KIPRJMOD}/3d/%s.wrl' % name
    m.m_Offset = pcbnew.VECTOR3D(*offset)
    fp.Add3DModel(m)


def add_outline(board):
    w, h = L.BOARD_W, L.BOARD_H
    r = 2.0
    def seg(a, b):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(*a)); s.SetEnd(V(*b))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1))
        board.Add(s)
    def arc(c, start, mid, end):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(V(*start), V(*mid), V(*end))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1))
        board.Add(s)
    k = r * (1 - 0.70710678)
    seg((r, 0), (w - r, 0)); seg((w, r), (w, h - r)); seg((w - r, h), (r, h)); seg((0, h - r), (0, r))
    arc(None, (0, r), (k, k), (r, 0))
    arc(None, (w - r, 0), (w - k, k), (w, r))
    arc(None, (w, h - r), (w - k, h - k), (w - r, h))
    arc(None, (r, h), (k, h - k), (0, h - r))


def add_text(board, text, x, y, layer=pcbnew.F_SilkS, size=1.0, thick=0.15):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(V(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(thick))
    board.Add(t)
    return t


def add_zone(board, netinfo, net, layer, poly, priority=0, clearance=0.3, name=None):
    z = pcbnew.ZONE(board)
    z.SetLayer(board.GetLayerID(layer))
    z.SetNet(netinfo[net])
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(mm(clearance))
    z.SetMinThickness(mm(0.25))
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.5))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    if name:
        z.SetZoneName(name)
    outline = z.Outline()
    outline.NewOutline()
    for x, y in poly:
        outline.Append(mm(x + OX), mm(y + OY))
    z.SetIsFilled(False)
    board.Add(z)
    return z


def build(route=True):
    comps, nets = load_netlist(NETLIST)
    if os.path.exists(PCB):
        os.remove(PCB)
    board = pcbnew.NewBoard(PCB)
    board.SetCopperLayerCount(4)
    board.GetDesignSettings().SetBoardThickness(mm(1.6))
    setup_rules(board, nets)
    fps, netinfo = add_footprints(board, comps, nets)
    add_outline(board)
    for text, x, y in L.LEGENDS:
        add_text(board, text, x, y - 0.45, size=0.8, thick=0.13)
    add_text(board, 'WATER SOFTENER CONTROLLER', 88, 39.0, size=1.2, thick=0.18)
    add_text(board, 'REV A', 88, 41.2, size=1.0)
    stats = None
    if route:
        import pcb_route
        stats = pcb_route.route(board, fps, nets, netinfo, fixed_only='--fixed-only' in sys.argv)
    for net, layer, poly in L.PLANES:
        add_zone(board, netinfo, net, layer, poly, name=net + ' plane')
    board.BuildConnectivity()
    pcbnew.SaveBoard(PCB, board)
    pcbnew.GetSettingsManager().SaveProject()
    print('footprints: %d  nets: %d  tracks: %d' % (len(fps), len(nets), len(board.GetTracks())))
    return stats


def copper_plot(B, env, pdir, px=3000):
    """PNG of the two outer copper layers (uses macOS Quick Look to rasterise)."""
    import shutil
    import subprocess
    try:
        from PIL import Image
    except ImportError:
        return
    if not shutil.which('qlmanage'):
        return
    svg = os.path.join(pdir, 'copper.svg')
    B.cli('pcb', 'export', 'svg', '--layers', 'B.Cu,F.Cu,Edge.Cuts', '--mode-single',
          '--fit-page-to-board', '--exclude-drawing-sheet', '-o', svg, NAME + '.kicad_pcb', env=env)
    if not os.path.exists(svg):
        return
    subprocess.run(['qlmanage', '-t', '-s', str(px), '-o', pdir, svg], capture_output=True)
    thumb = svg + '.png'
    if os.path.exists(thumb):
        im = Image.open(thumb)
        im.crop((0, 0, px, int(px * L.BOARD_H / L.BOARD_W))).convert('RGB').save(
            os.path.join(pdir, 'copper_outer_layers.png'))
        os.remove(thumb)
    os.remove(svg)


def finish():
    """Fill the planes, run KiCad's DRC and render the board."""
    import json
    import shutil
    import subprocess
    import build as B
    env = B.kicad_env()
    out = os.path.join(ROOT, 'output')
    pdir = os.path.join(out, 'pcb')
    os.makedirs(pdir, exist_ok=True)
    report = os.path.join(out, NAME + '_drc.json')
    B.cli('pcb', 'drc', '--severity-all', '--refill-zones', '--save-board', '--schematic-parity',
          '--format', 'json', '-o', report, NAME + '.kicad_pcb', env=env)
    d = json.load(open(report))
    errors = [v for v in d.get('violations', []) if v['severity'] == 'error']
    warnings = [v for v in d.get('violations', []) if v['severity'] != 'error']
    loose, parity = d.get('unconnected_items', []), d.get('schematic_parity', [])
    kinds = {}
    for v in warnings:
        kinds[v['type']] = kinds.get(v['type'], 0) + 1
    print('DRC: %d errors, %d unconnected, %d schematic mismatches, %d warnings %s' % (
        len(errors), len(loose), len(parity), len(warnings), kinds))
    for v in errors[:20]:
        print('   ', v['type'], '|', v['description'][:90], '|',
              ' ; '.join(i['description'][:40] for i in v['items']))
    views = (('board_top.png', ['--side', 'top', '--quality', 'basic']),
             ('board_bottom.png', ['--side', 'bottom', '--quality', 'basic']),
             ('board_angle.png', ['--side', 'top', '--rotate', '-40,0,25', '--perspective',
                                  '--quality', 'high', '--floor']))
    for name, opts in views:
        B.cli('pcb', 'render', '-o', os.path.join(pdir, name), '-w', '2400', '-h', '1700',
              '--background', 'opaque', *opts, NAME + '.kicad_pcb', env=env)
    copper_plot(B, env, pdir)
    for junk in (NAME + '.kicad_prl', 'fp-info-cache'):
        if os.path.exists(os.path.join(ROOT, junk)):
            os.remove(os.path.join(ROOT, junk))
    return not errors and not loose and not parity


if __name__ == '__main__':
    stats = build(route='--no-route' not in sys.argv)
    if '--no-route' not in sys.argv and '--fixed-only' not in sys.argv:
        ok = finish()
        if not ok or (stats is not None and stats.failed):
            sys.exit(1)
