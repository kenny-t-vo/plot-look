"""The command line. Sizes, names and presets:

portfolio fits the page (or the crop) into 11 x 17 in at 300 dpi, turned to match; 4k (alias web) fits it into
3840 x 2160 px and 1440p into 2560 x 1440 px, turned the same way; plot is the page at its own size at 300 dpi;
--long PX and --dpi N set a size, over a preset's. The dpi written is the pixels an inch of the size the image stands
for. --crop takes inches from the page's top left.

Output goes beside the input, or into --out, as STEM[-pN]-SIZE[-NAME][-bond][-crop-X0-Y0-X1-Y1].png: -pN when the
document has several pages; SIZE 11x17, 4k, 1440p, 300dpi (plot), NNNNpx (--long) or NNNdpi (--dpi); NAME a saved
preset's. A file of that name is overwritten.

--preset NAME takes a saved preset as well as the built-ins, and the options given override its values;
--save-preset NAME saves the options in effect (then renders if files were given, named as with --preset NAME).
A name is 1 to 32 letters, digits and hyphens, and not a built-in's.

main() takes a host for a program that wraps this one: prog (the name in the help), device_dpi (a function of the
file, when --device-dpi is not given), write (data, path) and app_command (what --make-app bakes in).
"""
import argparse, sys
from pathlib import Path

from . import __version__, render
from .presets import (check, describe, from_saved, home, load_presets, remove_presets, resolve, save_preset, apply)
from .render import PAPERS, TILE, WORKERS

EXAMPLES = '''examples:
  plotlook site-plan.pdf                        11 x 17 in at 300 dpi, beside the PDF
  plotlook sheets/ --preset 1440p --out web/    every PDF in sheets/, fit into 2560 x 1440
  plotlook big.pdf --crop 10,8,18,14 --dpi 300  a detail of a large sheet, inches from its top left
  plotlook a.pdf --preset 4k --paper bond --jpeg
  plotlook --save-preset crisp --preset portfolio --sharpen 2
  plotlook a.pdf --preset crisp                 writes a-11x17-crisp.png
  plotlook --ui                                 dialogs to choose drawings and a preset
  plotlook --make-app                           macOS: Plot Look.app, a droplet with dialogs
'''


def parser(prog='plotlook'):
    a = argparse.ArgumentParser(prog=prog, description='Render PDF drawings to PNG as they look plotted on a toner '
                                'plotter and seen from a normal distance.', epilog=EXAMPLES,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('files', nargs='*', help='PDFs (an .ai saved with PDF compatibility reads too), or folders of PDFs')
    a.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    g = a.add_argument_group('size')
    g.add_argument('--preset', metavar='NAME', help='portfolio (default), 4k (or web), 1440p, plot, or a saved preset')
    s = g.add_mutually_exclusive_group()
    s.add_argument('--long', type=int, metavar='PX', help='the long edge in px')
    s.add_argument('--dpi', type=float, metavar='N', help='the page at its own size at N dpi')
    g.add_argument('--pages', help='pages to render, as 1,3-4 (default all)')
    g.add_argument('--crop', type=lambda v: [float(x) for x in v.split(',')], metavar='X0,Y0,X1,Y1',
                   help='a region in inches from the page\'s top left')
    t = a.add_argument_group('look')
    t.add_argument('--sharpen', type=float, metavar='A', help='unsharp mask on darkness, 0 to 2 (1.5)')
    t.add_argument('--contrast', type=float, metavar='G', help='gamma on coverage, under 1 darkens mid tones (0.85)')
    t.add_argument('--paper', choices=list(PAPERS), help='white (default), or bond: warm, toner 0.06, in RGB')
    d = a.add_argument_group('device')
    d.add_argument('--gain', type=float, metavar='UM', help='toner spread in microns an edge (33)')
    d.add_argument('--device-dpi', type=int, metavar='N', help=f'the plotter\'s resolution ({render.DEVICE_DPI})')
    o = a.add_argument_group('output')
    o.add_argument('--out', metavar='DIR', help='folder for the PNGs (default beside each PDF)')
    o.add_argument('--jpeg', action='store_true', help='also a quality 92 JPEG')
    o.add_argument('-q', '--quiet', action='store_true', help='no progress lines')
    p = a.add_argument_group('presets')
    p.add_argument('--save-preset', metavar='NAME', help='save the options given as a preset')
    p.add_argument('--remove-preset', metavar='NAME')
    p.add_argument('--presets', action='store_true', help='list the saved presets')
    m = a.add_argument_group('dialogs')
    m.add_argument('--ui', action='store_true', help='choose files (if none given) and a preset in dialogs: '
                   'AppleScript ones on macOS, Tk ones elsewhere')
    m.add_argument('--make-app', nargs='?', const='', metavar='DIR',
                   help='macOS: write Plot Look.app (default /Applications), a droplet that runs --ui')
    a.add_argument('--tile', type=int, default=TILE, help=argparse.SUPPRESS)
    a.add_argument('--workers', type=int, default=WORKERS, help=argparse.SUPPRESS)
    return a


def main(argv=None, host=None):
    prog = getattr(host, 'prog', None) or 'plotlook'
    opts = parser(prog).parse_args(sys.argv[1:] if argv is None else argv)
    opts.host = host
    if opts.make_app is not None and sys.platform != 'darwin':
        raise SystemExit(f'{prog}: --make-app is macOS only; elsewhere run {prog} --ui, or {prog} FILE.pdf ...')
    if opts.make_app is not None:
        from .app import make_app
        make_app(opts.make_app or None, getattr(host, 'app_command', None))
        return 0
    if opts.presets:
        saved = load_presets()
        for n in sorted(saved):
            print(f'{n}  {describe(check(from_saved(saved[n])))}')
        if not saved:
            print(f'no saved presets in {home() / "presets.json"}')
        return 0
    if opts.remove_preset:
        remove_presets([opts.remove_preset])
        print(f'removed preset {opts.remove_preset}')
        return 0
    if opts.crop and len(opts.crop) != 4:
        raise SystemExit('plotlook: --crop takes X0,Y0,X1,Y1 in inches from the page\'s top left')
    files = render.expand(opts.files)
    if opts.files and not files:
        raise SystemExit(f'plotlook: no PDFs in {", ".join(opts.files)}')
    if opts.ui:
        from .ui import run_ui
        run_ui(files, opts)
        return 0
    s, name = resolve(opts)
    if opts.save_preset:
        save_preset(opts.save_preset, s)
        name = opts.save_preset
        print(f'saved preset {name}: {describe(s)}')
        if not files:
            return 0
    if not files:
        parser(prog).print_usage()
        return 2
    apply(opts, s, name)
    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        raise SystemExit(f'plotlook: no file {missing[0]}')
    for f in files:
        render.run(f, opts)
    return 0
