import contextlib, io

from PIL import Image

from plotlook import cli, tkdialogs, ui
from pdfs import mix_pdf, needs, needs_window


def answer(d, *acts):
    """acts in turn, one each time the window waits on a step"""
    acts = list(acts)

    def tick():
        if d.waiting and acts:
            acts.pop(0)()
        if acts:
            d.root.after(20, tick)
    d.root.after(20, tick)


def pick(d, *items):
    """select items in the window's list"""
    d.list.selection_clear(0, 'end')
    for item in items:
        d.list.selection_set(d.list.get(0, 'end').index(item))


@needs('pdftoppm')
@needs_window
def test_tk(tmp_path):
    """the Tk window, one for the whole test (on Windows a second Tk in a process could not find init.tcl): --ui with
    a preset chosen from its list, the render with its progress, and the count; then a list starts on its default and
    gives the item chosen, or None on cancel; a text field starts on its answer; a confirmation, the count's Show
    button, a render's value and error, and a closed window ends the dialogs"""
    mix = mix_pdf(tmp_path / 'mix.pdf')
    d = tkdialogs.Tk()
    said = []
    progress0 = d.progress
    d.progress = lambda text: (said.append(text), progress0(text))
    try:
        answer(d, lambda: (pick(d, 'Web 1440p'), d.press('Render')), lambda: d.press('OK'))
        with contextlib.redirect_stderr(io.StringIO()):
            pngs = ui.run_ui([str(mix)], cli.parser().parse_args(['--out', str(tmp_path / 'o')]), d)
        assert sorted(p.name for p in pngs) == ['mix-p1-1440p.png', 'mix-p2-1440p.png'] and said == ['mix.pdf']
        assert Image.open(pngs[0]).size == (2160, 1440)

        answer(d, lambda: d.press('Render'))
        assert d.choose(['Web 4K', 'Web 1440p'], 'Size', 'Web 1440p', ok='Render') == 'Web 1440p'
        answer(d, lambda: (pick(d, 'a'), d.press('Choose')))
        assert d.choose(['a', 'b'], 'Settings', 'b', ok='Choose', cancel='Back') == 'a'
        answer(d, lambda: d.press('Back'))
        assert d.choose(['a', 'b'], 'Settings', ok='Choose', cancel='Back') is None
        answer(d, lambda: (pick(d, 'x', 'z'), d.press('Remove')))
        assert d.choose_many(['x', 'y', 'z'], 'Presets to remove', ok='Remove') == ['x', 'z']
        seen = []
        answer(d, lambda: (seen.append(d.entry.get()), d.entry.delete(0, 'end'), d.entry.insert(0, '2'), d.press('OK')))
        assert d.ask('Sharpen, 0 to 2:', '1.5') == '2' and seen == ['1.5']
        answer(d, lambda: d.press('Cancel'))
        assert d.ask('Name for the preset:') is None
        answer(d, lambda: d.press('Replace'))
        assert d.confirm('Replace the preset crisp?', 'Replace') is True
        show = 'Show in Finder' if tkdialogs.MAC else 'Show in Explorer' if tkdialogs.WIN else 'Show folder'
        answer(d, lambda: d.press(show))
        assert d.done(2, []) is True
        assert d.work(lambda: (d.progress('a.pdf, 1 of 2'), 42)[1]) == 42
        try:
            d.work(lambda: 1 / 0)
            raise AssertionError('no error')
        except ZeroDivisionError:
            pass
        answer(d, d.close)
        for _ in range(2):
            try:
                d.ask('Sharpen:')
                raise AssertionError('not closed')
            except tkdialogs.Closed:
                pass
    finally:
        d.root.destroy()
