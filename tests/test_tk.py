import contextlib, io, json, os, queue, time

from PIL import Image

from plotlook import cli, presets, ui
from pdfs import mix_pdf, needs, needs_window, page_pdf, tk_root


def window(files=(), *argv):
    """a window over files, in the tests' one Tk, with the command line's options argv"""
    return ui.Window([str(f) for f in files], cli.parser().parse_args(['--ui', *map(str, argv)]), master=tk_root())


def drive(w, *acts, limit=120):
    """the window run while acts are called in turn, 20 ms apart (an act returning False is called again until it
    returns something else), then closed; an act's error raised here, and an error after limit seconds"""
    acts, t0, failed = list(acts), time.time(), []

    def tick():
        if w.closed:
            return
        if time.time() - t0 > limit:
            failed.append(f'still running after {limit} s, at {acts[:1]}')
            return w.close()
        act = acts.pop(0) if acts else w.close
        tk_root().after(20, tick)           # first, so that an act opening a modal dialog is followed by the next
        try:
            if act() is False:
                acts.insert(0, act)
        except BaseException as e:
            failed.append(e)
            w.close()
    tk_root().after(20, tick)
    out = w.run()
    if failed:
        raise failed[0] if isinstance(failed[0], BaseException) else AssertionError(failed[0])
    return out


def answer(w, button, text=None, seen=None):
    """an act: once a modal dialog is open, its text put in seen, its field set to text, and button pressed"""
    def act():
        if w.modal is None:
            return False
        if seen is not None:
            seen.append(w.modal.text)
        if text is not None:
            w.modal.entry.delete(0, 'end')
            w.modal.entry.insert(0, text)
        w.modal.press(button)
    return act


def until(test):
    """an act that waits until test() is true"""
    return lambda: bool(test()) or False


class Recorded(queue.Queue):
    """the render's messages, kept in said as well"""

    def __init__(self):
        super().__init__()
        self.said = []

    def put(self, m, *a, **k):
        self.said.append(m)
        super().put(m, *a, **k)


@needs_window
def test_files(tmp_path):
    """the files given are listed with their folders; a folder adds its PDFs and a file listed already is not added
    again; Remove removes the selected; a double-click in the list or Return starts nothing"""
    a = page_pdf(tmp_path / 'a.pdf', b'')
    (tmp_path / 'sheets').mkdir()
    b, c = page_pdf(tmp_path / 'sheets' / 'b.pdf', b''), page_pdf(tmp_path / 'sheets' / 'c.pdf', b'')
    w, seen = window([a]), {}

    def act():
        w.add([tmp_path / 'sheets', os.path.join(tmp_path, 'sheets', '..', 'a.pdf')])
        seen.update(files=list(w.files), rows=w.listbox.get(0, 'end'))
        w.listbox.selection_set(0)
        w.listbox.selection_set(2)
        w.remove_files()
        w.listbox.selection_set(0)
        for e in ('<ButtonPress-1>', '<ButtonRelease-1>') * 2:      # a double-click
            w.listbox.event_generate(e, x=10, y=5)
        w.top.event_generate('<Return>')
        seen['rendering'] = w.rendering
    drive(w, act)
    assert seen['files'] == [str(a), str(b), str(c)] and w.files == [str(b)] and not seen['rendering']
    assert seen['rows'][0] == f'a.pdf   ·   {ui.shown_path(tmp_path)}' and seen['rows'][2].startswith('c.pdf')


@needs('pdftoppm')
@needs_window
def test_render(tmp_path):
    """a fresh window starts with Colour ticked; Web 1440p chosen and Render pressed renders each page, its tiles
    reported in order, into PNGs named and sized for it, in RGB with colour; the status counts them and Show in
    Finder (Explorer) is offered; unticked, the PNGs are grey"""
    mix, o = mix_pdf(tmp_path / 'mix.pdf'), tmp_path / 'o'
    w, seen = window([mix], '--out', o, '--tile', '400', '-q'), {}
    w.messages = Recorded()
    seen['fresh'] = (w.colour.get(), w.size.get(), w.save_to.get())
    drive(w, lambda: (w.size.set('1440p'), w.render_button.invoke(), seen.update(stop=w.stop_button.instate(['!disabled']))),
          until(lambda: not w.rendering),
          lambda: seen.update(status=w.status.get(), shown=bool(w.show_button.grid_info()), bar=w.bar['value'],
                              render=w.render_button.instate(['!disabled']), stop_after=w.stop_button.instate(['disabled'])),
          lambda: (w.colour.set(False), w.render_button.invoke()),
          until(lambda: not w.rendering))
    tiles = [m[1:] for m in w.messages.said if m[0] == 'tiles']
    per_page = [(d, 15) for d in range(1, 16)]               # 1800 x 1200 device px in 400 px tiles
    assert seen['fresh'] == (True, 'portfolio', 'folder') and seen['stop'] and seen['stop_after'] and seen['render']
    assert tiles == per_page * 4, tiles
    assert seen['status'].startswith('Rendered 2 PNGs in ') and seen['shown'] and seen['bar'] == 1.0
    assert sorted(p.name for p in o.iterdir()) == ['mix-p1-1440p-colour.png', 'mix-p1-1440p.png',
                                                    'mix-p2-1440p-colour.png', 'mix-p2-1440p.png']
    c, g = Image.open(o / 'mix-p1-1440p-colour.png'), Image.open(o / 'mix-p2-1440p.png')
    assert c.size == g.size == (2160, 1440) and c.mode == 'RGB' and g.mode == 'L'


@needs('pdftoppm')
@needs_window
def test_stop(tmp_path):
    """Stop ends a render after the tiles in progress, saying so, with no PNG written for the page it was on"""
    mix, o = mix_pdf(tmp_path / 'mix.pdf'), tmp_path / 'o'
    w, seen = window([mix], '--out', o, '--preset', 'plot', '--tile', '100', '-q'), {}
    drive(w, lambda: w.render_button.invoke(), until(lambda: w.at['done'] >= 1),
          lambda: (w.stop_button.invoke(), seen.update(t=time.time())), until(lambda: not w.rendering),
          lambda: seen.update(status=w.status.get(), took=time.time() - seen['t'], done=w.at['done'],
                              total=w.at['total']))
    assert seen['status'].startswith('Stopped after 0 PNGs') and seen['done'] < seen['total'] and seen['took'] < 10
    assert not o.exists() or not list(o.iterdir())


@needs('pdftoppm')
@needs_window
def test_errors_and_bad_numbers(tmp_path):
    """a bad number, or no drawings, is named in the status line and nothing renders; a file that is not a PDF or .ai
    and one poppler cannot read are named in the window and on stderr, and the others render"""
    one, o = page_pdf(tmp_path / 'one.pdf', b'0.5 g 0 0 72 72 re f'), tmp_path / 'o'
    (tmp_path / 'notes.txt').write_text('x')
    (tmp_path / 'bad.pdf').write_bytes(b'not a pdf')
    w, said, err = window([tmp_path / 'notes.txt', tmp_path / 'bad.pdf', one], '--out', o, '-q'), [], io.StringIO()

    def press():
        w.render_button.invoke()
        said.append((w.status.get(), w.rendering))
    with contextlib.redirect_stderr(err):
        drive(w, lambda: (w.vals['sharpen'].set('abc'), press()),
              lambda: (w.vals['sharpen'].set('1,2'), w.size.set('long'), w.long.set('50'), press()),
              lambda: (w.long.set('120.5'), press()),
              lambda: (w.long.set('100'), press()),
              until(lambda: not w.rendering),
              lambda: said.append((w.status.get(), w.error_text.get())))
    assert said[0] == ('Sharpen: abc is not a number from 0 to 2', False)
    assert said[1] == ('Long edge: 50 is not a whole number from 100 to 30000', False)
    assert said[2] == ('Long edge: 120.5 is not a whole number from 100 to 30000', False) and said[3][1]
    assert said[4][0].startswith('Rendered 1 PNG in ') and 'notes.txt: not a PDF or .ai' in said[4][1]
    assert 'bad.pdf: poppler cannot read' in said[4][1] and 'notes.txt: not a PDF' in err.getvalue()
    assert 'Sharpen: abc' in err.getvalue() and 'bad.pdf: poppler cannot read' in err.getvalue()
    assert [p.name for p in o.iterdir()] == ['one-100px-colour.png']
    w, said = window(), []
    drive(w, press)
    assert said == [('Add the drawings to render.', False)]


@needs_window
def test_presets(tmp_path):
    """Save as… refuses a built-in's name and saves the fields as a preset, colour included; a changed field blanks
    the choice and choosing the preset sets the fields back; saving over it asks first; Remove removes it after a
    confirmation"""
    w, seen, texts = window(), {}, []
    drive(w, lambda: (w.size.set('4k'), w.vals['sharpen'].set('1.8'), w.paper.set('bond')),
          w.save_as, answer(w, 'Save', 'web', texts), answer(w, 'Save', 'crisp', texts),
          lambda: seen.update(chosen=w.preset.get(), values=w.combo['values'],
                              saved=json.loads((presets.home() / 'presets.json').read_text())),
          lambda: (w.vals['contrast'].set('1'), seen.update(blank=w.preset.get())),
          lambda: (w.preset.set('crisp'), w.combo.event_generate('<<ComboboxSelected>>'),
                   seen.update(back=(w.vals['contrast'].get(), w.preset.get()))),
          w.save_as, answer(w, 'Save', 'crisp', texts), answer(w, 'Replace', seen=texts),
          w.remove_preset, answer(w, 'Remove', seen=texts),
          lambda: seen.update(after=(w.preset.get(), w.combo['values'], presets.load_presets())))
    assert 'built-in' in texts[1] and texts[3] == 'Replace the preset crisp?' and texts[4] == 'Remove the preset crisp?'
    assert seen['chosen'] == 'crisp' and list(seen['values']) == ['crisp'] and seen['saved'] == {'crisp': {
        'size': '4k', 'sharpen': 1.8, 'contrast': 0.85, 'paper': 'bond', 'gain': 33.0, 'colour': True}}
    assert seen['blank'] == '' and seen['back'] == ('0.85', 'crisp') and seen['after'][0] == ''
    assert not seen['after'][1] and seen['after'][2] == {}


@needs_window
def test_remembered(tmp_path):
    """the fields, the folder and the preset come back at the next open from ui.json; an older ui.json
    ({"last", "save_to"}) still reads; options on the command line fill their fields"""
    folder = tmp_path / 'renders'
    w = window()
    drive(w, lambda: (w.size.set('long'), w.long.set('2000'), w.colour.set(False), w.vals['contrast'].set('1.2'),
                      w.paper.set('bond')),
          lambda: (setattr(w, 'folder', str(folder)), w.save_to.set('folder')))
    w = window()
    got, text = w.fields(), w.folder_text.get()
    w.close()
    assert got == dict(size=None, long=2000, dpi=None, out=str(folder), colour=False, sharpen=1.5, contrast=1.2,
                       paper='bond', gain=33.0) and text == ui.shown_path(folder)

    presets.save_preset('crisp', presets.from_saved({'size': '1440p', 'sharpen': 2}))
    presets.write_json('ui.json', {'last': 'crisp', 'save_to': str(folder)})
    w = window()
    old = (w.preset.get(), w.size.get(), w.vals['sharpen'].get(), w.colour.get(), w.save_to.get(), w.folder)
    w.close()
    presets.write_json('ui.json', {'last': '4k'})
    w = window([], '--sharpen', '0.5', '--colour')
    given = (w.size.get(), w.vals['sharpen'].get(), w.colour.get(), w.preset.get())
    w.close()
    assert old == ('crisp', '1440p', '2', False, 'beside', str(folder)) and given == ('4k', '0.5', True, '')
