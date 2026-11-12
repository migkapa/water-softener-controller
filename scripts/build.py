#!/usr/bin/env python3
"""Generate the KiCad project, then run ERC and export netlist, BOM and PDF.

    python3 scripts/build.py              # schematic: generate, check, export
    python3 scripts/build.py --no-export  # only write the schematic files
    python3 scripts/build.py --pcb        # schematic, then place, route and check the board
    python3 scripts/build.py --product    # schematic, then the enclosure and product renders
                                          # (uses the existing board; add --pcb to rebuild it)
    python3 scripts/build.py --video      # schematic, then the presentation film (needs --product once)
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import design  # noqa: E402
from kisch import KICAD_SHARE  # noqa: E402
from sexp import find, find_all, parse  # noqa: E402

KICAD_CLI = os.environ.get('KICAD_CLI') or os.path.join(os.path.dirname(KICAD_SHARE), 'MacOS', 'kicad-cli')
if not os.path.exists(KICAD_CLI):                 # not the macOS app layout: take it from the PATH
    KICAD_CLI = shutil.which('kicad-cli') or KICAD_CLI
NAME = design.NAME
DATE = '2026-11-10'
REV = 'A'
OUT = os.path.join(ROOT, 'output')


def cli(*args, env=None):
    res = subprocess.run([KICAD_CLI, *args], capture_output=True, text=True, env=env, cwd=ROOT)
    text = '\n'.join(l for l in (res.stdout + res.stderr).splitlines() if 'Fontconfig' not in l)
    return res.returncode, text


def write_project_files():
    pro = {
        'board': {'design_settings': {'defaults': {}, 'diff_pair_dimensions': [], 'drc_exclusions': [],
                                      'rules': {}, 'track_widths': [], 'via_dimensions': []}},
        'boards': [], 'libraries': {'pinned_footprint_libs': [], 'pinned_symbol_libs': []},
        'meta': {'filename': NAME + '.kicad_pro', 'version': 1},
        'net_settings': {'classes': [], 'meta': {'version': 0}},
        'pcbnew': {'page_layout_descr_file': ''}, 'sheets': [], 'text_variables': {},
    }
    path = os.path.join(ROOT, NAME + '.kicad_pro')
    if not os.path.exists(path):
        with open(path, 'w') as fh:
            json.dump(pro, fh, indent=2)
            fh.write('\n')
    with open(os.path.join(ROOT, 'sym-lib-table'), 'w') as fh:
        fh.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "%s") (type "KiCad") '
                 '(uri "${KIPRJMOD}/%s.kicad_sym") (options "") '
                 '(descr "Project symbols"))\n)\n' % (NAME, NAME))


def check_footprints(prj):
    missing = []
    for sh in prj.sheets:
        for p in sh.parts:
            if p.info.is_power or not p.footprint:
                if not p.info.is_power:
                    missing.append('%s has no footprint' % p.ref)
                continue
            lib, name = p.footprint.split(':', 1)
            path = os.path.join(KICAD_SHARE, 'footprints', lib + '.pretty', name + '.kicad_mod')
            if not os.path.exists(path):
                missing.append('%s: footprint %s not found' % (p.ref, p.footprint))
    return missing


_ENV = None


def kicad_env():
    """Environment for kicad-cli and KiCad's Python.

    They get a throw-away settings folder holding the stock library tables, so
    a build neither depends on nor changes the user's own KiCad settings."""
    global _ENV
    if _ENV is None:
        _ENV = dict(os.environ)
        if not _ENV.get('KICAD_CONFIG_HOME'):
            cfg = tempfile.mkdtemp(prefix='kicad-cli-config-')
            ver = os.path.join(cfg, '10.0')
            os.makedirs(ver)
            for t in ('sym-lib-table', 'fp-lib-table'):
                shutil.copy(os.path.join(KICAD_SHARE, 'template', t), os.path.join(ver, t))
            _ENV['KICAD_CONFIG_HOME'] = cfg
    return _ENV


def run_erc(env):
    path = os.path.join(OUT, 'erc.json')
    code, text = cli('sch', 'erc', '--severity-all', '--format', 'json', '-o', path,
                     NAME + '.kicad_sch', env=env)
    data = json.load(open(path))
    rows = []
    for sh in data.get('sheets', []):
        for v in sh.get('violations', []):
            rows.append((v['severity'], v['type'], sh.get('path', ''), v['description'],
                         '; '.join(i['description'] for i in v.get('items', []))))
    return rows


def read_netlist(env):
    path = os.path.join(OUT, NAME + '.net')
    cli('sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', path, NAME + '.kicad_sch', env=env)
    text = open(path, encoding='utf-8').read()
    if ROOT + os.sep in text:                     # keep this machine's folder names out of the file
        text = text.replace(ROOT + os.sep, '')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
    tree = parse(text)
    nets = {}
    for net in find_all(find(tree, 'nets'), 'net'):
        name = find(net, 'name')[1]
        nodes = []
        for node in find_all(net, 'node'):
            nodes.append('%s.%s' % (find(node, 'ref')[1], find(node, 'pin')[1]))
        nets[name] = sorted(nodes)
    return nets


def clean_pdf_metadata(path, title):
    """Keep only the title and dates in the document info; drop producer and
    creator strings, XMP and the unused viewer script KiCad embeds."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(path)
    created = reader.metadata.get('/CreationDate') if reader.metadata else None
    if created and created.count(':') > 1:        # D:2026:11:10:21:37:03 -> D:20261110213703
        created = 'D:' + created[2:].replace(':', '')
    writer = PdfWriter(clone_from=reader)
    writer._info.get_object().clear()
    meta = {'/Title': title}
    if created:
        meta.update({'/CreationDate': created, '/ModDate': created})
    writer.add_metadata(meta)
    root = writer._root_object
    if '/Metadata' in root:
        del root['/Metadata']
    names = root.get('/Names')
    if names is not None:
        names = names.get_object()
        if '/JavaScript' in names:
            del names['/JavaScript']
        if not names:
            del root['/Names']
    with open(path, 'wb') as fh:
        writer.write(fh)
    subprocess.run(['xattr', '-c', path], check=False)


def verify_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    print('PDF info:', dict(reader.metadata or {}), 'pages:', len(reader.pages))
    raw = subprocess.run(['strings', path], capture_output=True, text=True).stdout
    text = raw + '\n'.join(pg.extract_text() or '' for pg in reader.pages)
    import re
    hits = sorted(set(m.group(0).lower() for m in re.finditer(
        r'reportlab|pypdf|python|claude|anthropic|openai|generated|javascript', text, re.I)))
    print('PDF forbidden strings:', hits or 'none')
    return not hits


def export_images(pdf):
    """One PNG per sheet, for quick viewing and sharing (needs poppler's pdftoppm)."""
    if not shutil.which('pdftoppm'):
        return
    d = os.path.join(OUT, 'sheets')
    os.makedirs(d, exist_ok=True)
    for i, name in enumerate(('1-overview', '2-power', '3-mcu', '4-valve-drive', '5-sensors'), 1):
        subprocess.run(['pdftoppm', '-r', '150', '-f', str(i), '-l', str(i), '-singlefile', '-png',
                        pdf, os.path.join(d, name)], check=False)


def export_bom(env):
    path = os.path.join(OUT, NAME + '_bom.csv')
    code, text = cli('sch', 'export', 'bom',
                     '--fields', 'Reference,Value,Rating,Footprint,Manufacturer,MPN,${QUANTITY}',
                     '--labels', 'Refs,Value,Rating,Footprint,Manufacturer,MPN,Qty',
                     '--group-by', 'Value,Rating,Footprint,Manufacturer,MPN',
                     '--ref-range-delimiter', '', '-o', path, NAME + '.kicad_sch', env=env)
    rows = list(csv.reader(open(path, newline='')))
    qty = sum(int(r_[-1]) for r_ in rows[1:])
    print('BOM: %d lines, %d parts' % (len(rows) - 1, qty))


def upgrade(prj, env):
    """Re-save every sheet in the native format of the installed KiCad."""
    for sh in prj.sheets:
        code, text = cli('sch', 'upgrade', sh.filename, env=env)
        if 'Successfully' not in text:
            print('PROBLEM upgrade', sh.filename, text.strip())


def kicad_script(name, what):
    """Run one of the scripts that need the Python bundled with KiCad."""
    import glob
    pys = sorted(glob.glob(os.path.join(os.path.dirname(KICAD_SHARE), 'Frameworks',
                                        'Python.framework', 'Versions', '*', 'bin', 'python3')))
    if not pys:                                   # elsewhere pcbnew is installed into a normal Python
        for exe in (os.environ.get('KICAD_PYTHON'), sys.executable, shutil.which('python3')):
            if exe and subprocess.run([exe, '-c', 'import pcbnew'], capture_output=True).returncode == 0:
                pys = [exe]
                break
    if not pys:
        print('PROBLEM: no Python with pcbnew found (set KICAD_PYTHON), %s not built' % what)
        sys.exit(1)
    res = subprocess.run([pys[-1], os.path.join(HERE, name)], capture_output=True, text=True,
                         cwd=ROOT, env=kicad_env())
    for line in (res.stdout + res.stderr).splitlines():
        if 'Fontconfig' not in line and 'wxApp' not in line and 'Debug: ' not in line:
            print(line)
    if res.returncode:
        sys.exit(res.returncode)


def build_pcb():
    """Place, route and check the board."""
    kicad_script('pcb.py', 'board')


def build_product():
    """Enclosure parts, clearance check against the board, product renders."""
    if not shutil.which('openscad'):
        print('PROBLEM: OpenSCAD not found, enclosure not built')
        sys.exit(1)
    if not os.path.exists(os.path.join(ROOT, NAME + '.kicad_pcb')):
        print('PROBLEM: no board yet, run with --pcb first')
        sys.exit(1)
    kicad_script('enclosure.py', 'enclosure')


def build_video():
    """Presentation film made from the board and enclosure models."""
    if not shutil.which('ffmpeg'):
        print('PROBLEM: ffmpeg not found, film not made')
        sys.exit(1)
    kicad_script('video.py', 'film')


def main():
    os.makedirs(OUT, exist_ok=True)
    prj = design.build(ROOT)
    problems = prj.write(DATE, REV)
    write_project_files()
    problems += check_footprints(prj)
    refs = [p.ref for sh in prj.sheets for p in sh.parts]
    dup = sorted({x for x in refs if refs.count(x) > 1})
    if dup:
        problems.append('duplicate references: %s' % dup)
    print('parts: %d  (power symbols %d)' % (
        sum(1 for x in refs if not x.startswith('#')), sum(1 for x in refs if x.startswith('#'))))
    for p in problems:
        print('PROBLEM', p)
    if '--no-export' in sys.argv:
        return
    env = kicad_env()
    upgrade(prj, env)
    rows = run_erc(env)
    print('ERC violations: %d' % len(rows))
    for row in rows:
        print('  ', ' | '.join(row))
    nets = read_netlist(env)
    with open(os.path.join(OUT, 'nets.txt'), 'w') as fh:
        for name in sorted(nets):
            fh.write('%-22s %s\n' % (name, ' '.join(nets[name])))
    print('nets: %d' % len(nets))
    export_bom(env)
    pdf = os.path.join(OUT, NAME + '_schematic.pdf')
    code, text = cli('sch', 'export', 'pdf', '--exclude-pdf-property-popups',
                     '--exclude-pdf-metadata', '-o', pdf, NAME + '.kicad_sch', env=env)
    clean_pdf_metadata(pdf, design.TITLE + ' - schematic rev ' + REV)
    ok = verify_pdf(pdf)
    export_images(pdf)
    prl = os.path.join(ROOT, NAME + '.kicad_prl')   # per-user UI state written by kicad-cli
    if os.path.exists(prl):
        os.remove(prl)
    if rows or problems or not ok:
        sys.exit(1)
    if '--pcb' in sys.argv:
        build_pcb()
    if '--product' in sys.argv:
        build_product()
    if '--video' in sys.argv:
        build_video()


if __name__ == '__main__':
    main()
