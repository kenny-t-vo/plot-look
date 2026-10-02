import contextlib, io, json, subprocess, sys
from pathlib import Path

from PIL import Image

from plotlook import app, cli, presets, ui
from pdfs import dialogs, mix_pdf, needs, page_pdf


def session(answers, files, *argv):
    with dialogs(answers) as (said, shown), contextlib.redirect_stderr(io.StringIO()):
        pngs = ui.run_ui([str(f) for f in files], cli.parser().parse_args([str(a) for a in argv]))
    return pngs, said, shown


@needs('pdftoppm')
def test_choose_files(tmp_path):
    """--ui chooses files and a preset, renders, and shows the first PNG in Finder"""
    mix, one = mix_pdf(tmp_path / 'mix.pdf'), page_pdf(tmp_path / 'one.pdf', b'0.75 g 0 0 72 72 re f')
    pngs, said, shown = session([f'{mix}\n{one}\n', 'Web 4K', 'Show in Finder'], [], '--out', tmp_path / 'ui')
    assert len(pngs) == 3 and 'choose file' in said[0] and 'choose from list' in said[1] and 'Rendered 3 PNGs' in said[2]
    assert 'OK button name "Render"' in said[1] and 'default items {"Portfolio · 11 × 17 in, 300 dpi"}' in said[1]
    assert 'Custom…' in said[1] and 'Remove a preset' not in said[1]
    assert shown == [pngs[0]] and all(p.name.endswith('-4k.png') for p in pngs)


@needs('pdftoppm')
def test_custom_preset_session(tmp_path):
    """Custom… changes the size, sharpen (a bad number asked again), paper and folder, saves them as a preset (a
    built-in's name refused) and renders under its name; a second run offers the preset, selects it as the last
    choice and overwrites the first run's file; Remove a preset… removes it after one confirmation"""
    mix, folder = mix_pdf(tmp_path / 'mix.pdf'), tmp_path / 'renders'
    folder.mkdir()
    pngs, said, _ = session(['Custom…', 'Size — Portfolio · 11 × 17 in, 300 dpi', 'Web 1440p', 'Sharpen — 1.5', 'abc',
                             '1.8', 'Paper — White', 'Bond', 'Save to — Beside each drawing', 'Choose folder…',
                             f'{folder}/', 'Save as preset…', 'web', 'crisp', 'Render', 'OK'], [mix])
    menu = [s for s in said if 'with prompt "Settings"' in s]
    home = presets.home()
    assert sorted(p.name for p in pngs) == ['mix-p1-1440p-crisp-bond.png', 'mix-p2-1440p-crisp-bond.png']
    assert all(p.parent == folder for p in pngs) and Image.open(pngs[0]).size == (2160, 1440)
    assert 'Sharpen, an unsharp mask on darkness, 0 to 2' in said[4] and 'abc is not a number from 0 to 2' in said[5]
    assert 'built-in' in said[13] and 'Rendered 2 PNGs' in said[-1]
    shown_folder = str(folder).replace(str(Path.home()), '~', 1)
    for row in ('Size — Web 1440p', 'Sharpen — 1.8', 'Paper — Bond', 'Toner spread — 33 µm', f'Save to — {shown_folder}'):
        assert row in menu[-1], row
    assert 'OK button name "Choose" cancel button name "Back"' in menu[0]
    assert json.loads((home / 'presets.json').read_text()) == {'crisp': {
        'size': '1440p', 'sharpen': 1.8, 'contrast': 0.85, 'paper': 'bond', 'gain': 33.0, 'out': str(folder)}}
    assert json.loads((home / 'ui.json').read_text()) == {'save_to': str(folder), 'last': 'crisp'}

    pngs[0].write_bytes(b'old')
    again, said, shown = session(['crisp', 'Show in Finder'], [mix], '--pages', '1')
    assert [p.name for p in again] == ['mix-p1-1440p-crisp-bond.png'] and again[0].parent == folder
    assert Image.open(again[0]).size == (2160, 1440) and 'default items {"crisp"}' in said[0]
    assert '"Remove a preset…"' in said[0] and shown == again

    none, said, _ = session(['Remove a preset…', 'crisp', 'Remove', ''], [mix])
    assert none == [] and 'with multiple selections allowed' in said[1] and 'Remove the preset crisp?' in said[2]
    assert len(said) == 4 and '"crisp"' not in said[3] and 'Remove a preset' not in said[3]
    assert presets.load_presets() == {} and 'default items {"Portfolio' in said[3]


@needs('osacompile', 'osadecompile')
def test_applescript_and_app(tmp_path):
    """the dialogs' AppleScript compiles, and Plot Look.app is a droplet running this Python with -m plotlook and a
    PATH for Homebrew and ~/.local/bin"""
    scripts = [ui.script_choose_files(), ui.script_list(['Web 4K', 'Toner spread — 33 µm'], 'Size', 'Web 4K', ok='Render'),
               ui.script_list(['a', 'b'], 'Remove', ok='Remove', multiple=True), ui.script_ask('Sharpen, 0 to 2:', '1.5'),
               ui.script_confirm('Remove a?', 'Remove'), ui.script_choose_folder(),
               ui.script_done(2, ['x.pdf: "quoted" error']), ui.script_done(0, [])]
    codes = [subprocess.run(['osacompile', '-o', str(tmp_path / f's{i}.scpt'), '-e', s], capture_output=True).returncode
             for i, s in enumerate(scripts)]
    assert codes == [0] * len(scripts)
    with contextlib.redirect_stdout(io.StringIO()):
        made = app.make_app(tmp_path)
    plist = (made / 'Contents' / 'Info.plist').read_text()
    src = subprocess.run(['osadecompile', str(made / 'Contents' / 'Resources' / 'Scripts' / 'main.scpt')],
                         capture_output=True, text=True).stdout
    assert made.name == 'Plot Look.app' and 'CFBundleDocumentTypes' in plist and 'on open' in src
    assert sys.executable in src and '-m plotlook' in src and '--ui' in src
    assert '/opt/homebrew/bin' in src and '/.local/bin' in src
