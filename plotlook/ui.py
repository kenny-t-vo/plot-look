"""--ui: one Tk window, the same on macOS, Windows and Linux and in the downloadable apps (app() below).

Drawings lists the files given, those added with Add… and, on macOS, those dropped on the app while it runs; a folder
stands for its PDFs. Size, Colour, Look and Save to hold the settings, each changed with one click or by typing a
number. Preset lists the saved presets (presets.json): choosing one sets every field, and the choice goes blank once a
field no longer matches it. Render is the only control that starts a render, and the fields are checked when it is
pressed. The render runs in a thread that reports each tile through a queue the window polls; Stop ends it after the
tiles in progress. The window stays open for another render. ui.json beside presets.json keeps the last fields for the
next open; an older ui.json ({"last": ..., "save_to": ...}) still reads.
"""
import copy, os, queue, subprocess, sys, threading, time
from pathlib import Path

from . import render
from .presets import (DEFAULTS, apply, base_settings, check, from_saved, load_presets, name_error, override,
                      read_json, remove_presets, save_preset, to_saved, write_json)
from .render import ALIASES, PAPERS, PRESETS

MAC, WIN = sys.platform == 'darwin', sys.platform == 'win32'
SIZE_ITEMS = {'portfolio': 'Portfolio · 11 × 17 in, 300 dpi', '4k': 'Web 4K · fits 3840 × 2160',
              '1440p': 'Web 1440p · fits 2560 × 1440', 'plot': 'Plot size · 300 dpi'}
NUMBERS = {'sharpen': ('Sharpen', 0, 2, False), 'contrast': ('Contrast', 0.1, 3, False),
           'gain': ('Toner spread', 0, 100, False), 'long': ('Long edge', 100, 30000, True),
           'dpi': ('Resolution', 10, 1200, False)}
STEPS = {'sharpen': 0.1, 'contrast': 0.05, 'gain': 1}
COLOUR = 'Keep the drawing\'s colours (for screens)'
SHOW = 'Show in Finder' if MAC else 'Show in Explorer' if WIN else 'Show folder'
DRAWINGS = ('.pdf', '.ai')
STATE = 'ui.json'
ROWS = 6                        # the list's rows before it scrolls
WRAP = 520                      # px (on Windows at 96 dpi), the width of the status and error lines
POLL = 100                      # ms between looks at the render's queue


def reveal(path):
    """the file selected in Finder or Explorer, elsewhere its folder opened"""
    if MAC:
        subprocess.run(['open', '-R', str(path)])
    elif WIN:
        subprocess.run(f'explorer /select,"{path}"')
    else:
        subprocess.run(['xdg-open', str(Path(path).parent)])


def shown_path(p):
    """a path as the window shows it: ~ for the home folder, except on Windows"""
    p, home = str(p), str(Path.home())
    if not WIN and (p == home or p.startswith(home + os.sep)):
        return '~' + p[len(home):]
    return p


def duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f'{m} min {s} s' if m else f'{s} s'


def number(text, k):
    """text as setting k's number, in NUMBERS[k]'s range; ValueError naming the setting otherwise"""
    what, lo, hi, whole = NUMBERS[k]
    try:
        v = float(text.strip().replace(',', '.'))
        ok = lo <= v <= hi and (not whole or v == int(v))
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f'{what}: {text.strip() or "nothing"} is not {"a whole number" if whole else "a number"} '
                         f'from {lo:g} to {hi:g}')
    return int(v) if whole else v


def read_state(saved):
    """(settings, saved preset name or None, folder or None) from ui.json, or a fresh window's: colour on"""
    try:
        st = read_json(STATE)
    except SystemExit:
        st = {}
    s, name = base_settings(colour=True), None
    last = st.get('last')
    try:
        if isinstance(st.get('settings'), dict):
            s, name = check(from_saved(st['settings'])), st.get('preset')
        elif last in saved:                              # an older ui.json: the last choice in its list
            s, name = check(from_saved(saved[last])), last
        elif ALIASES.get(last, last) in PRESETS:
            s['size'] = ALIASES.get(last, last)
    except (SystemExit, ValueError, TypeError, KeyError):
        s, name = base_settings(colour=True), None
    return s, name, st.get('folder') or st.get('save_to')


class Dialog:
    """a small modal window over w: text, a field holding answer unless that is None, and buttons, the first one
    cancelling and the last one answering (on Windows shown the other way round)"""

    def __init__(self, w, text, buttons, answer=None):
        ttk, px = w.ttk, w.px
        self.text = text
        self.top = t = w.tk.Toplevel(w.top)
        t.withdraw()
        t.title('Plot Look')
        t.resizable(False, False)
        t.transient(w.top)
        f = ttk.Frame(t, padding=(px(16), px(12)))
        f.pack(fill='both', expand=True)
        ttk.Label(f, text=text, wraplength=px(360), justify='left').pack(anchor='w')
        self.entry = None
        if answer is not None:
            self.entry = ttk.Entry(f, width=32)
            self.entry.insert(0, answer)
            self.entry.select_range(0, 'end')
            self.entry.pack(fill='x', pady=(px(10), 0))
        row = ttk.Frame(f)
        row.pack(anchor='e', pady=(px(14), 0))
        for b in (buttons[::-1] if WIN else buttons):
            ttk.Button(row, text=b, command=lambda b=b: self.press(b)).pack(side='left', padx=(px(8), 0))
        self.cancel, self.ok, self.answer = buttons[0], buttons[-1], None
        t.bind('<Return>', lambda e: self.press(self.ok))
        t.bind('<KP_Enter>', lambda e: self.press(self.ok))
        t.bind('<Escape>', lambda e: self.press(self.cancel))
        t.protocol('WM_DELETE_WINDOW', lambda: self.press(self.cancel))

    def press(self, button):
        if button == self.ok:
            self.answer = self.entry.get() if self.entry else True
        self.top.destroy()

    def run(self, w):
        """the field's text (True without a field) for the last button, None otherwise"""
        t = self.top
        t.update_idletasks()
        x = w.top.winfo_rootx() + (w.top.winfo_width() - t.winfo_reqwidth()) // 2
        y = w.top.winfo_rooty() + w.px(60)
        t.geometry(f'+{max(0, x)}+{max(0, y)}')
        t.deiconify()
        try:
            t.grab_set()
        except w.tk.TclError:
            pass
        (self.entry or t).focus_force()
        w.modal = self
        try:
            w.top.wait_window(t)
        finally:
            w.modal = None
        return self.answer


class Window:
    """the window over files; opts, the command line's, fill the fields they give and pass the rest (pages, crop,
    jpeg, device dpi, the host) to the render. master: a Tk to open in as a Toplevel (the tests share one), else the
    window is its own Tk. icon: a .ico for the title bar on Windows"""

    def __init__(self, files=(), opts=None, icon=None, master=None):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            raise SystemExit('plotlook: --ui needs tkinter (on Debian or Ubuntu, sudo apt install python3-tk)')
        if WIN and master is None:
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)     # sharp text on a scaled display
            except (AttributeError, OSError):
                pass
        if opts is None:
            from .cli import parser
            opts = parser().parse_args([])
        self.tk, self.ttk, self.opts = tk, ttk, opts
        try:
            self.top = tk.Toplevel(master) if master is not None else tk.Tk()
        except tk.TclError as e:
            raise SystemExit(f'plotlook: --ui cannot open a window: {e}')
        self.top.withdraw()
        self.top.title('Plot Look')
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        if icon and WIN:
            self.top.iconbitmap(default=str(icon))
        self.scale = self.top.winfo_fpixels('1i') / 96 if WIN else 1     # windows: px at the display's dpi
        self.files, self.errors, self.rendered, self.pngs = [], [], [], []
        self.modal = self.thread = self.poll_id = None
        self.rendering = self.loading = self.closed = False
        self.stop, self.messages = threading.Event(), queue.Queue()
        self.saved, self.folder = {}, None
        self.build()
        self.load_saved()
        s, name, self.folder = read_state(self.saved)
        s, name = self.command_line(s, name)
        self.set_fields(s)
        self.preset.set(name if name and self.matches(name) else '')
        self.add(files)
        if MAC and master is None:
            self.top.createcommand('::tk::mac::OpenDocument', lambda *paths: self.add(paths))
            self.top.createcommand('::tk::mac::Quit', self.close)
        self.show()

    def px(self, n):
        return round(n * self.scale)

    # ------------------------------------------------------------ the window
    def build(self):
        tk, ttk, px = self.tk, self.ttk, self.px
        style = ttk.Style(self.top)
        style.configure('Muted.TLabel', foreground='gray50')
        style.configure('Error.TLabel', foreground='#c62828')
        f = ttk.Frame(self.top, padding=(px(16), px(12)))
        f.pack(fill='both', expand=True)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)
        gap = px(4)

        def row(r, text, top=False):
            ttk.Label(f, text=text).grid(row=r, column=0, sticky='ne' if top else 'e', padx=(0, px(10)),
                                         pady=(px(6) if top else gap, gap))
            cell = ttk.Frame(f)
            cell.grid(row=r, column=1, sticky='nsew', pady=gap)
            return cell

        def changes(*vs):
            for v in vs:
                v.trace_add('write', self.changed)
            return vs[0] if len(vs) == 1 else vs

        # drawings
        c = row(0, 'Drawings', top=True)
        c.columnconfigure(0, weight=1)
        c.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(c, height=ROWS, width=60, selectmode='extended', activestyle='none',
                                  exportselection=False)
        self.listbox.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = ttk.Scrollbar(c, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.scrollbar.set)
        b = ttk.Frame(c)
        b.grid(row=1, column=0, columnspan=2, sticky='w', pady=(gap, 0))
        self.add_button = ttk.Button(b, text='Add…', command=self.choose_files)
        self.add_button.pack(side='left')
        self.remove_button = ttk.Button(b, text='Remove', command=self.remove_files)
        self.remove_button.pack(side='left', padx=(px(6), 0))

        # size
        c = row(1, 'Size')
        self.size = changes(tk.StringVar(self.top, 'portfolio'))
        self.long, self.dpi = changes(tk.StringVar(self.top, '3840'), tk.StringVar(self.top, '300'))
        for i, (k, text) in enumerate(SIZE_ITEMS.items()):
            ttk.Radiobutton(c, text=text, value=k, variable=self.size).grid(row=i // 2, column=i % 2 * 3,
                                                                            columnspan=3, sticky='w', padx=(0, px(16)))
        for col, (k, text, unit) in enumerate((('long', 'Long edge', 'px'), ('dpi', 'Resolution', 'dpi'))):
            r = ttk.Frame(c)
            r.grid(row=2, column=col * 3, columnspan=3, sticky='w', padx=(0, px(16)))
            ttk.Radiobutton(r, text=text, value=k, variable=self.size).pack(side='left')
            e = ttk.Entry(r, textvariable=self.long if k == 'long' else self.dpi, width=7)
            e.pack(side='left', padx=(px(4), px(4)))
            e.bind('<FocusIn>', lambda ev, k=k: self.size.set(k))
            ttk.Label(r, text=unit).pack(side='left')

        # colour
        c = row(2, 'Colour')
        self.colour = changes(tk.BooleanVar(self.top, True))
        ttk.Checkbutton(c, text=COLOUR, variable=self.colour).pack(side='left')

        # look
        c = row(3, 'Look')
        self.vals = {}
        for i, (k, unit) in enumerate((('sharpen', ''), ('contrast', ''), ('gain', 'µm'))):
            what, lo, hi, _ = NUMBERS[k]
            ttk.Label(c, text=what).grid(row=0, column=i * 3, sticky='w', padx=(px(14) if i else 0, px(4)))
            self.vals[k] = changes(tk.StringVar(self.top))
            ttk.Spinbox(c, textvariable=self.vals[k], from_=lo, to=hi, increment=STEPS[k], width=5).grid(
                row=0, column=i * 3 + 1, sticky='w')
            ttk.Label(c, text=unit).grid(row=0, column=i * 3 + 2, sticky='w', padx=(px(3) if unit else 0, 0))
        p = ttk.Frame(c)
        p.grid(row=1, column=0, columnspan=9, sticky='w', pady=(gap, 0))
        self.paper = changes(tk.StringVar(self.top, 'white'))
        ttk.Label(p, text='Paper').pack(side='left', padx=(0, px(6)))
        for k in PAPERS:
            ttk.Radiobutton(p, text=k.capitalize(), value=k, variable=self.paper).pack(side='left', padx=(0, px(10)))
        ttk.Button(p, text='Defaults', command=self.defaults).pack(side='left', padx=(px(8), 0))

        # save to
        c = row(4, 'Save to')
        self.save_to = changes(tk.StringVar(self.top, 'beside'))
        self.folder_text = changes(tk.StringVar(self.top, ''))
        ttk.Radiobutton(c, text='Beside each drawing', value='beside', variable=self.save_to).pack(side='left')
        ttk.Radiobutton(c, text='Folder', value='folder', variable=self.save_to,
                        command=self.folder_chosen).pack(side='left', padx=(px(12), px(6)))
        ttk.Button(c, text='Choose…', command=self.choose_folder).pack(side='right', padx=(px(8), 0))
        ttk.Label(c, textvariable=self.folder_text, style='Muted.TLabel').pack(side='left', fill='x', expand=True)

        # preset
        c = row(5, 'Preset')
        self.preset = tk.StringVar(self.top, '')
        self.combo = ttk.Combobox(c, textvariable=self.preset, state='readonly', width=24)
        self.combo.pack(side='left')
        self.combo.bind('<<ComboboxSelected>>', lambda e: self.choose_preset())
        ttk.Button(c, text='Save as…', command=self.save_as).pack(side='left', padx=(px(8), 0))
        ttk.Button(c, text='Remove', command=self.remove_preset).pack(side='left', padx=(px(6), 0))

        ttk.Separator(f).grid(row=6, column=0, columnspan=2, sticky='ew', pady=(px(10), px(8)))

        # render and status
        r = ttk.Frame(f)
        r.grid(row=7, column=0, columnspan=2, sticky='ew')
        r.columnconfigure(0, weight=1)
        self.bar = ttk.Progressbar(r, mode='determinate', maximum=1.0)
        self.bar.grid(row=0, column=0, sticky='ew', padx=(0, px(10)))
        self.stop_button = ttk.Button(r, text='Stop', command=self.stop_render, state='disabled', takefocus=False)
        self.stop_button.grid(row=0, column=1, padx=(0, px(6)))
        self.render_button = ttk.Button(r, text='Render', command=self.render, takefocus=False)
        self.render_button.grid(row=0, column=2)
        self.status = tk.StringVar(self.top, 'Add drawings, choose the settings, then Render.')
        self.status_label = ttk.Label(r, textvariable=self.status, wraplength=px(WRAP), justify='left')
        self.status_label.grid(row=1, column=0, sticky='w', pady=(px(6), 0))
        self.show_button = ttk.Button(r, text=SHOW, command=lambda: self.pngs and reveal(self.pngs[0]),
                                      takefocus=False)
        self.show_button.grid(row=1, column=1, columnspan=2, sticky='e', pady=(px(6), 0))
        self.show_button.grid_remove()
        self.error_text = tk.StringVar(self.top, '')
        self.error_label = ttk.Label(r, textvariable=self.error_text, style='Error.TLabel', wraplength=px(WRAP),
                                     justify='left')
        self.error_label.grid(row=2, column=0, columnspan=3, sticky='w', pady=(px(4), 0))

    def show(self):
        """the window centred and brought to the front"""
        t = self.top
        t.update_idletasks()
        t.minsize(t.winfo_reqwidth(), t.winfo_reqheight())
        x = (t.winfo_screenwidth() - t.winfo_reqwidth()) // 2
        y = (t.winfo_screenheight() - t.winfo_reqheight()) // 3
        t.geometry(f'+{max(0, x)}+{max(0, y)}')
        t.deiconify()
        t.attributes('-topmost', True)
        t.after(300, lambda: self.closed or t.attributes('-topmost', False))
        t.lift()
        t.focus_force()

    def run(self):
        """until the window is closed; the PNGs rendered"""
        self.top.wait_window()
        return self.rendered

    def close(self):
        """the window closed, its fields kept when they check out; a render in progress stops after its tiles"""
        if self.closed:
            return
        self.stop.set()
        try:
            self.remember(self.fields(), self.preset.get() or None)
        except ValueError:
            pass
        self.closed = True
        if self.poll_id:
            self.top.after_cancel(self.poll_id)
        self.top.destroy()

    def say(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(style='Error.TLabel' if error else 'TLabel')
        if error:
            render.stderr_log(f'plotlook: {text}')

    # ------------------------------------------------------------ drawings
    def add(self, paths):
        """the files (a folder: its PDFs) added to the list, unless listed already"""
        have = {os.path.normcase(f) for f in self.files}
        for f in render.expand(paths):
            f = os.path.abspath(f)
            if os.path.normcase(f) not in have:
                have.add(os.path.normcase(f))
                self.files.append(f)
                self.listbox.insert('end', f'{Path(f).name}   ·   {shown_path(Path(f).parent)}')
        if len(self.files) > ROWS:
            self.scrollbar.grid(row=0, column=1, sticky='ns')
        else:
            self.scrollbar.grid_remove()

    def choose_files(self):
        from tkinter import filedialog
        got = filedialog.askopenfilenames(parent=self.top, title='Drawings to render as plotted',
                                          filetypes=[('PDF, or .ai saved with PDF compatibility', ('.pdf', '.ai'))])
        self.add(got or ())

    def remove_files(self):
        for i in sorted(self.listbox.curselection(), reverse=True):
            self.listbox.delete(i)
            del self.files[i]
        self.add(())

    # ------------------------------------------------------------ fields
    def set_fields(self, s):
        self.loading = True
        try:
            if s['size']:
                self.size.set(s['size'])
            else:
                k = 'long' if s['long'] else 'dpi'
                (self.long if k == 'long' else self.dpi).set(f'{s[k]:g}')
                self.size.set(k)
            self.colour.set(bool(s.get('colour')))
            for k in self.vals:
                self.vals[k].set(f'{s[k]:g}')
            self.paper.set(s['paper'])
            if s['out']:
                self.folder = s['out']
            self.save_to.set('folder' if s['out'] else 'beside')
            self.folder_text.set(shown_path(self.folder) if self.folder else 'none chosen')
        finally:
            self.loading = False

    def fields(self):
        """the settings in the fields; ValueError naming the first that does not check out"""
        s = base_settings(out=self.folder if self.save_to.get() == 'folder' else None, colour=self.colour.get())
        k = self.size.get()
        if k in ('long', 'dpi'):
            s.update(size=None, **{k: number((self.long if k == 'long' else self.dpi).get(), k)})
        else:
            s['size'] = k
        for k in self.vals:
            s[k] = number(self.vals[k].get(), k)
        s['paper'] = self.paper.get()
        try:
            return check(s)
        except SystemExit as e:
            raise ValueError(str(e).removeprefix('plotlook: '))

    def command_line(self, s, name):
        """(settings, preset name) with the options given on the command line over s"""
        o = self.opts
        if getattr(o, 'preset', None):
            key = ALIASES.get(o.preset, o.preset)
            if key in PRESETS:
                s.update(size=key, long=None, dpi=None)
            elif o.preset in self.saved:
                s, name = check(from_saved(self.saved[o.preset])), o.preset
            else:
                raise SystemExit(f'plotlook: no preset {o.preset}; one of {", ".join([*PRESETS, *self.saved])}')
        if getattr(o, 'long', None) or getattr(o, 'dpi', None):
            s.update(size=None, long=o.long, dpi=o.dpi)
        s = check(override(s, o))
        if s['out']:
            self.folder = s['out']
        return s, name

    def defaults(self):
        for k in self.vals:
            self.vals[k].set(f'{DEFAULTS[k]:g}')
        self.paper.set(DEFAULTS['paper'])

    def folder_chosen(self):
        if not self.folder and not self.choose_folder():
            self.save_to.set('beside')

    def choose_folder(self):
        """a folder from the system's dialog, Save to set to it; False on cancel"""
        from tkinter import filedialog
        got = filedialog.askdirectory(parent=self.top, title='Folder for the PNGs', mustexist=True,
                                      initialdir=self.folder or str(Path.home()))
        if not got:
            return False
        self.folder = str(Path(got))
        self.folder_text.set(shown_path(self.folder))
        self.save_to.set('folder')
        return True

    def changed(self, *_):
        """the preset's choice blanked once the fields no longer match it"""
        if not self.loading and self.preset.get() and not self.matches(self.preset.get()):
            self.preset.set('')

    # ------------------------------------------------------------ presets
    def load_saved(self):
        try:
            self.saved = load_presets()
        except SystemExit as e:
            self.saved = {}
            self.say(str(e).removeprefix('plotlook: '), error=True)
        self.combo['values'] = sorted(self.saved)

    def matches(self, name):
        try:
            return name in self.saved and to_saved(self.fields()) == to_saved(check(from_saved(self.saved[name])))
        except (ValueError, SystemExit, TypeError, KeyError):
            return False

    def choose_preset(self):
        name = self.preset.get()
        try:
            s = check(from_saved(self.saved[name]))
        except (SystemExit, ValueError, TypeError, KeyError) as e:
            self.preset.set('')
            return self.say(f'The preset {name} does not read: {e}', error=True)
        self.set_fields(s)
        self.preset.set(name)

    def dialog(self, text, buttons, answer=None):
        return Dialog(self, text, buttons, answer).run(self)

    def save_as(self):
        try:
            s = self.fields()
        except ValueError as e:
            return self.say(str(e), error=True)
        text, answer = 'Name for the preset (letters, digits and hyphens):', self.preset.get()
        while True:
            got = self.dialog(text, ['Cancel', 'Save'], answer)
            if got is None:
                return
            got = answer = got.strip()
            err = name_error(got)
            if err:
                text = f'{err} Name for the preset:'
                continue
            if got in self.saved and not self.dialog(f'Replace the preset {got}?', ['Cancel', 'Replace']):
                continue
            break
        save_preset(got, s)
        self.load_saved()
        self.preset.set(got)
        self.say(f'Saved the preset {got}.')

    def remove_preset(self):
        name = self.preset.get()
        if not name:
            return self.say('Choose a saved preset to remove.', error=True)
        if self.dialog(f'Remove the preset {name}?', ['Cancel', 'Remove']):
            remove_presets([name])
            self.load_saved()
            self.preset.set('')
            self.say(f'Removed the preset {name}.')

    def remember(self, s, name):
        write_json(STATE, {'settings': to_saved(s), 'preset': name, 'folder': self.folder})

    # ------------------------------------------------------------ render
    def render(self):
        """the files rendered with the fields' settings, in a thread; nothing if a field does not check out"""
        if self.rendering:
            return
        if not self.files:
            return self.say('Add the drawings to render.', error=True)
        try:
            s = self.fields()
        except ValueError as e:
            return self.say(str(e), error=True)
        name = self.preset.get() or None
        self.remember(s, name)
        opts = apply(copy.copy(self.opts), s, name)
        self.stop.clear()
        self.rendering = True
        self.errors, self.pngs = [], []
        self.error_text.set('')
        self.show_button.grid_remove()
        self.render_button.state(['disabled'])
        self.stop_button.state(['!disabled'])
        self.bar['value'] = 0
        self.t0 = time.time()
        self.at = dict(i=0, n=len(self.files), name='', pages=1, page=1, done=0, total=0)
        self.say('Starting…')
        self.thread = threading.Thread(target=self.work, args=(list(self.files), opts), daemon=True)
        self.thread.start()
        self.poll_id = self.top.after(POLL, self.poll)

    def stop_render(self):
        if self.rendering:
            self.stop.set()
            self.stop_button.state(['disabled'])

    def work(self, files, opts):
        """the render's thread: messages to the window through the queue"""
        put = self.messages.put
        pngs, stopped = [], False
        try:
            render.require_poppler()
        except SystemExit as e:
            put(('error', str(e)))
            files = []
        for i, f in enumerate(files):
            if self.stop.is_set():
                stopped = True
                break
            name = Path(f).name
            try:
                if Path(f).suffix.lower() not in DRAWINGS:
                    raise ValueError('not a PDF or .ai')
                if not Path(f).is_file():
                    raise ValueError('no such file')
                put(('file', i, len(files), name, len(render.parse_pages(opts.pages, len(render.pages(f))))))
                pngs += [w for w in render.run(f, opts, lambda d, t: put(('tiles', d, t)), self.stop)
                         if w.suffix == '.png']
            except render.Stopped:
                stopped = True
                break
            except (SystemExit, Exception) as e:
                render.stderr_log(f'plotlook: {name}: {e}')
                put(('error', f'{name}: {e}'))
        put(('end', pngs, stopped))

    def poll(self):
        """the render's messages shown: what it is on, the bar, errors, and at the end the count"""
        self.poll_id = None
        at = self.at
        while True:
            try:
                m = self.messages.get_nowait()
            except queue.Empty:
                break
            if m[0] == 'file':
                at.update(i=m[1], n=m[2], name=m[3], pages=max(1, m[4]), page=1, done=0, total=0)
            elif m[0] == 'tiles':
                if at['total'] and at['done'] == at['total']:      # the last page's tiles were all done
                    at['page'] += 1
                at.update(done=m[1], total=m[2])
            elif m[0] == 'error':
                self.errors.append(m[1])
                self.error_text.set('\n'.join(self.errors[-6:]))
            elif m[0] == 'end':
                return self.finished(m[1], m[2])
        page = at['page'] - 1 + (at['done'] / at['total'] if at['total'] else 0)
        self.bar['value'] = (at['i'] + min(page / at['pages'], 1)) / at['n']
        if at['name']:
            tiles = f'tiles {at["done"]} of {at["total"]}' if at['total'] else 'starting'
            self.say(f'{at["name"]}, file {at["i"] + 1} of {at["n"]} · page {min(at["page"], at["pages"])} of '
                     f'{at["pages"]} · {tiles} · {duration(time.time() - self.t0)}'
                     + (' · stopping after the tiles in progress' if self.stop.is_set() else ''))
        self.poll_id = self.top.after(POLL, self.poll)

    def finished(self, pngs, stopped):
        self.rendering = False
        self.pngs = pngs
        self.rendered += pngs
        self.render_button.state(['!disabled'])
        self.stop_button.state(['disabled'])
        n = len(pngs)
        took = duration(time.time() - self.t0)
        if stopped:
            self.say(f'Stopped after {n} PNG{"" if n == 1 else "s"}, in {took}.')
        else:
            self.bar['value'] = 1.0
            self.say(f'Rendered {n} PNG{"" if n == 1 else "s"} in {took}.', error=not n and bool(self.errors))
        if pngs:
            self.show_button.grid()


def run_ui(files, opts):
    """--ui: the window over the files given until it is closed; the PNGs rendered"""
    return Window(files, opts).run()


def app(files, icon=None):
    """the downloadable apps: the window over the files given; on macOS those dropped on the app join the list"""
    Window(files, None, icon).run()
