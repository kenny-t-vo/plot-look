import contextlib, io, json, subprocess, sys

from PIL import Image

from plotlook import app, cli, presets, ui
from pdfs import needs, needs_window, page_pdf


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        cli.main([str(a) for a in argv])
    return out.getvalue()


def test_numbers():
    """a field's number reads with a comma or a point, in its range, a whole one where it must be; anything else is
    refused with the setting's name and range"""
    got = [ui.number('1,5', 'sharpen'), ui.number(' 2000 ', 'long'), ui.number('72', 'dpi'), ui.number('100', 'gain')]
    assert got == [1.5, 2000, 72.0, 100.0] and isinstance(got[1], int)
    errors = []
    for text, k in (('abc', 'sharpen'), ('2.5', 'sharpen'), ('0', 'contrast'), ('120.5', 'long'), ('', 'gain'),
                    ('nan', 'dpi')):
        try:
            ui.number(text, k)
        except ValueError as e:
            errors.append(str(e))
    assert errors == ['Sharpen: abc is not a number from 0 to 2', 'Sharpen: 2.5 is not a number from 0 to 2',
                      'Contrast: 0 is not a number from 0.1 to 3',
                      'Long edge: 120.5 is not a whole number from 100 to 30000',
                      'Toner spread: nothing is not a number from 0 to 100',
                      'Resolution: nan is not a number from 10 to 1200'], errors


@needs('pdftoppm')
def test_colour_setting(tmp_path):
    """--colour is saved in a preset as "colour": true (left out when off, so older presets read as before); the
    preset renders in colour, --no-colour over it in grey, and the command line's default stays grey"""
    pdf, o = page_pdf(tmp_path / 'x.pdf', b'0 0.85 0.95 0.1 k 0 0 72 72 re f'), tmp_path / 'o'
    run('--save-preset', 'tinted', '--long', '100', '--colour')
    run('--save-preset', 'plain', '--long', '100')
    assert json.loads((presets.home() / 'presets.json').read_text()) == {
        'tinted': {'long': 100, 'sharpen': 1.5, 'contrast': 0.85, 'paper': 'white', 'gain': 33.0, 'colour': True},
        'plain': {'long': 100, 'sharpen': 1.5, 'contrast': 0.85, 'paper': 'white', 'gain': 33.0}}
    assert run('--presets').splitlines() == ['plain  100 px long, sharpen 1.5, contrast 0.85, white paper, toner spread 33 um',
                                             'tinted  100 px long, sharpen 1.5, contrast 0.85, white paper, toner spread 33 um, '
                                             'colour']
    run(pdf, '--preset', 'tinted', '--out', o, '-q')
    run(pdf, '--preset', 'tinted', '--no-colour', '--out', o, '-q')
    run(pdf, '--preset', 'plain', '--color', '--dpi', '50', '--out', o, '-q')
    run(pdf, '--long', '120', '--out', o, '-q')
    assert sorted(p.name for p in o.iterdir()) == ['x-100px-tinted-colour.png', 'x-100px-tinted.png', 'x-120px.png',
                                                    'x-50dpi-plain-colour.png']
    modes = {p.name: Image.open(p).mode for p in o.iterdir()}
    assert modes == {'x-100px-tinted-colour.png': 'RGB', 'x-100px-tinted.png': 'L', 'x-120px.png': 'L',
                     'x-50dpi-plain-colour.png': 'RGB'}


@needs('osacompile', 'osadecompile')
@needs_window
def test_app(tmp_path):
    """Plot Look.app is a droplet running this Python with -m plotlook --ui and the files dropped, with a PATH for
    Homebrew and ~/.local/bin; a Python without tkinter is refused, since the app opens the window"""
    with contextlib.redirect_stdout(io.StringIO()):
        made = app.make_app(tmp_path)
    plist = (made / 'Contents' / 'Info.plist').read_text()
    src = subprocess.run(['osadecompile', str(made / 'Contents' / 'Resources' / 'Scripts' / 'main.scpt')],
                         capture_output=True, text=True).stdout
    assert made.name == 'Plot Look.app' and 'CFBundleDocumentTypes' in plist and 'on open' in src
    assert sys.executable in src and '-m plotlook' in src and '--ui' in src
    assert '/opt/homebrew/bin' in src and '/.local/bin' in src
    tk0 = sys.modules.get('tkinter')
    sys.modules['tkinter'] = None                   # import tkinter raises ImportError
    try:
        app.make_app(tmp_path / 'no-tk')
        raise AssertionError('not refused')
    except SystemExit as e:
        assert 'tkinter' in str(e) and not (tmp_path / 'no-tk' / 'Plot Look.app').exists()
    finally:
        if tk0 is None:
            sys.modules.pop('tkinter', None)
        else:
            sys.modules['tkinter'] = tk0
