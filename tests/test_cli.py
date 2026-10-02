import contextlib, io, json, sys
from types import SimpleNamespace

from PIL import Image

from plotlook import __version__, cli, presets, render
from pdfs import env, mix_pdf, needs, page_pdf


def run(*argv):
    """cli.main's stdout and stderr"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        cli.main([str(a) for a in argv])
    return out.getvalue(), err.getvalue()


def refused(*argv):
    try:
        run(*argv)
    except SystemExit as e:
        return str(e) or None
    return None


def test_names():
    """outputs are named STEM[-pN]-SIZE[-PRESET][-bond][-crop-X0-Y0-X1-Y1].png"""
    def nm(stem, page, n, **o):
        return render.out_name(stem, page, n, SimpleNamespace(**{
            'preset': 'portfolio', 'long': None, 'dpi': None, 'paper': 'white', 'crop': None, 'preset_name': None, **o}))
    assert [nm('site-plan', 1, 1, preset='1440p'), nm('sections', 2, 3, preset='4k'),
            nm('detail', 1, 1, preset_name='crisp'), nm('a', 1, 1, preset='web'),
            nm('a', 1, 1, preset='plot', paper='bond'), nm('a', 1, 1, long=2000),
            nm('a', 1, 1, dpi=150.0, crop=[0.5, 0, 2, 1.25])] == [
        'site-plan-1440p.png', 'sections-p2-4k.png', 'detail-11x17-crisp.png', 'a-4k.png', 'a-300dpi-bond.png',
        'a-2000px.png', 'a-150dpi-crop-0.5-0-2-1.25.png']


def test_presets(tmp_path):
    """--save-preset writes presets.json and reads back, --presets lists them, built-in, unsafe and unknown names are
    refused, the options given override a saved preset's values, and --remove-preset removes one"""
    run('--save-preset', 'crisp', '--preset', '1440p', '--sharpen', '2', '--paper', 'bond')
    run('--save-preset', 'big', '--long', '5000', '--out', tmp_path / 'big')
    listed, _ = run('--presets')
    saved = json.loads((presets.home() / 'presets.json').read_text())
    assert saved == {'crisp': {'size': '1440p', 'sharpen': 2.0, 'contrast': 0.85, 'paper': 'bond', 'gain': 33.0},
                     'big': {'long': 5000, 'sharpen': 1.5, 'contrast': 0.85, 'paper': 'white', 'gain': 33.0,
                             'out': str(tmp_path / 'big')}}
    assert presets.to_saved(presets.from_saved(saved['big'])) == saved['big'] and 'crisp  1440p, sharpen 2' in listed
    for bad in (['--save-preset', 'Web'], ['--save-preset', 'a b'], ['--save-preset', '-x1'],
                ['--remove-preset', 'nope'], ['--preset', 'nope', 'x.pdf'], ['--preset', 'crisp', '--sharpen', '3', 'x.pdf']):
        assert refused(*bad), bad
    s, name = presets.resolve(cli.parser().parse_args(['--preset', 'crisp', '--paper', 'white', '--dpi', '100']))
    assert name == 'crisp' and s['dpi'] == 100 and s['size'] is None and s['paper'] == 'white' and s['sharpen'] == 2
    run('--remove-preset', 'big')
    run('--remove-preset', 'crisp')
    assert presets.load_presets() == {}


@needs('pdftoppm')
def test_render(tmp_path):
    """pages named -pN, web as 4k in 3840 x 2160 at the dpi of the page's size over a file of that name, bond in RGB
    with a JPEG, a crop by its inches, and a saved preset's name in the file's"""
    mix, o = mix_pdf(tmp_path / 'mix.pdf'), tmp_path / 'o'
    o.mkdir()
    (o / 'mix-p1-4k.png').write_bytes(b'not a png')
    run(mix, '--preset', 'web', '--out', o, '-q')
    run(mix, '--pages', '2', '--dpi', '100', '--paper', 'bond', '--jpeg', '--out', o, '-q')
    run(mix, '--pages', '1', '--dpi', '100', '--crop', '0.5,0.5,1.5,1', '--out', o, '-q')
    run(mix, '--pages', '1', '--save-preset', 'small', '--long', '300', '--out', o, '-q')
    got = sorted(p.name for p in o.iterdir())
    assert got == ['mix-p1-100dpi-crop-0.5-0.5-1.5-1.png', 'mix-p1-300px-small.png', 'mix-p1-4k.png',
                   'mix-p2-100dpi-bond.jpg', 'mix-p2-100dpi-bond.png', 'mix-p2-4k.png'], got
    w1, b2 = Image.open(o / 'mix-p1-4k.png'), Image.open(o / 'mix-p2-100dpi-bond.png')
    assert w1.size == (3240, 2160) and w1.mode == 'L' and abs(w1.info['dpi'][0] - 1080) < 0.5
    assert b2.size == (300, 200) and b2.mode == 'RGB' and Image.open(o / 'mix-p1-100dpi-crop-0.5-0.5-1.5-1.png').size == (100, 50)


@needs('pdftoppm')
def test_folders_and_progress(tmp_path):
    """a folder stands for its PDFs, not its subfolders'; a progress line a page goes to stderr, none with -q; a
    device dpi of 300 renders at 300"""
    d = tmp_path / 'sheets'
    (d / 'sub').mkdir(parents=True)
    for name in ('b.pdf', 'A.PDF', 'sub/c.pdf'):
        page_pdf(d / name, b'0 G 1 w 0 0 m 72 72 l S')
    (d / 'notes.txt').write_text('x')
    out, err = run(d, '--long', '100', '--out', tmp_path / 'o', '--device-dpi', '300')
    assert sorted(p.name for p in (tmp_path / 'o').iterdir()) == ['A-100px.png', 'b-100px.png']
    assert len(err.splitlines()) == 2 and 'A-100px.png  100 x 100 px' in err and 'device 300 x 300 px' in err and not out
    assert run(d, '--long', '100', '--out', tmp_path / 'o', '-q') == ('', '')
    assert refused(tmp_path / 'o') and 'no PDFs' in refused(tmp_path / 'o')


def test_missing_poppler(tmp_path):
    """without pdftoppm it says so, with how to install poppler"""
    f = page_pdf(tmp_path / 'a.pdf', b'')
    with env(PATH=str(tmp_path)):
        msg = refused(f)
    assert 'pdftoppm' in msg and 'brew install poppler' in msg and 'apt install poppler-utils' in msg and 'Windows' in msg


def test_version_help_and_platform():
    """--version prints the version, the help has examples, and --ui and --make-app say they are macOS only elsewhere"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            cli.main(['--version'])
        except SystemExit as e:
            assert e.code == 0
    assert out.getvalue().strip() == f'plotlook {__version__}'
    assert 'examples:' in cli.parser().format_help() and '--preset 1440p' in cli.parser().format_help()
    plat = sys.platform
    sys.platform = 'linux'
    try:
        assert 'macOS only' in refused('--ui') and 'macOS only' in refused('--make-app')
    finally:
        sys.platform = plat
