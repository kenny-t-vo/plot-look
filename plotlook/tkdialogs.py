"""Tk dialogs: --ui where there is no AppleScript (Windows, Linux), and the downloadable apps.

The steps of ui.py, shown in turn in one window: a list (a double-click or Return chooses, Escape cancels), a text
field, a confirmation, the count with Show in Finder or Explorer. Files and folders are chosen in the system's own
dialogs. Rendering runs in a thread while the window names the file it is on. Closing the window ends the dialogs;
during a render it ends the program.

app() runs the downloadable apps: the dialogs over the files given, or dropped on the app (macOS sends those as an
event just after launch, and again for a drop while it runs), and any error shown in the window.
"""
import os, queue, sys, threading, traceback

MAC, WIN = sys.platform == 'darwin', sys.platform == 'win32'
WRAP = 420                      # px (on Windows at 96 dpi), the width of a prompt and of the progress bar
ROWS = 14                       # a list's rows before it scrolls
LAUNCH_WAIT = 2000              # ms for the open event a launch from Finder sends


class Closed(Exception):
    """the window was closed"""


class Tk:
    """the dialogs as steps in one Tk window; icon, a .ico for its title bar on Windows"""

    def __init__(self, icon=None):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            raise SystemExit('plotlook: --ui needs tkinter (on Debian or Ubuntu, sudo apt install python3-tk)')
        if WIN:
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)     # sharp text on a scaled display
            except (AttributeError, OSError):
                pass
        self.tk, self.ttk = tk, ttk
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            raise SystemExit(f'plotlook: --ui cannot open a window: {e}')
        self.root.title('Plot Look')
        self.root.resizable(False, False)
        self.root.withdraw()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        if icon and WIN:
            self.root.iconbitmap(default=str(icon))
        self.scale = self.root.winfo_fpixels('1i') / 96 if WIN else 1     # windows: px at the display's dpi
        self.pressed = tk.StringVar(self.root)
        self.frame = self.list = self.entry = None
        self.shown = self.closed = self.working = self.waiting = False
        self.messages = queue.Queue()

    # ------------------------------------------------------------ the window
    def px(self, n):
        return round(n * self.scale)

    def show(self):
        if not self.shown:
            self.shown = True
            self.root.update_idletasks()
            x = (self.root.winfo_screenwidth() - self.root.winfo_reqwidth()) // 2
            y = (self.root.winfo_screenheight() - self.root.winfo_reqheight()) // 3
            self.root.geometry(f'+{x}+{y}')
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.after(300, lambda: self.root.attributes('-topmost', False))
        self.root.lift()
        self.root.focus_force()

    def page(self):
        """a fresh frame in the window"""
        if self.frame:
            self.frame.destroy()
        self.list = self.entry = None
        self.frame = self.ttk.Frame(self.root, padding=(self.px(20), self.px(16)))
        self.frame.pack(fill='both', expand=True)
        return self.frame

    def press(self, button):
        self.pressed.set(button)

    def close(self):
        if self.working:
            os._exit(1)
        self.closed = True
        self.press('')

    def step(self, prompt, buttons, default, cancel, body=None):
        """the prompt, what body draws, and the buttons (on macOS from left to right, on Windows the other way);
        (the button pressed, what body's reader reads then)"""
        if self.closed:
            raise Closed
        f = self.page()
        self.ttk.Label(f, text=prompt, wraplength=self.px(WRAP), justify='left').pack(anchor='w')
        read = body(f) if body else None
        row = self.ttk.Frame(f)
        row.pack(anchor='e', pady=(self.px(16), 0))
        for b in (buttons[::-1] if WIN else buttons):
            self.ttk.Button(row, text=b, default='active' if b == default else 'normal',
                            command=lambda b=b: self.press(b)).pack(side='left', padx=(self.px(8), 0))
        self.root.bind('<Return>', lambda e: self.press(default))
        self.root.bind('<KP_Enter>', lambda e: self.press(default))
        self.root.bind('<Escape>', lambda e: self.press(cancel))
        self.show()
        self.waiting = True
        self.root.wait_variable(self.pressed)
        self.waiting = False
        if self.closed:
            raise Closed
        return self.pressed.get(), read() if read else None

    def listbox(self, f, items, selected, mode, ok):
        box = self.ttk.Frame(f)
        box.pack(fill='both', expand=True, pady=(self.px(10), 0))
        rows = min(len(items), ROWS)
        lb = self.list = self.tk.Listbox(box, height=rows, width=max(32, max(map(len, items)) + 2), selectmode=mode,
                                         activestyle='none', exportselection=False)
        lb.insert('end', *items)
        lb.pack(side='left', fill='both', expand=True)
        if len(items) > rows:
            bar = self.ttk.Scrollbar(box, orient='vertical', command=lb.yview)
            lb.configure(yscrollcommand=bar.set)
            bar.pack(side='right', fill='y')
        for i, item in enumerate(items):
            if item in selected:
                lb.selection_set(i)
                lb.activate(i)
                lb.see(i)
        if mode == 'browse':
            if not lb.curselection():
                lb.selection_set(0)
            lb.bind('<Double-Button-1>', lambda e: self.press(ok))
        lb.focus_set()
        return lambda: [items[i] for i in lb.curselection()]

    # ------------------------------------------------------------ the calls ui.py makes
    def choose_files(self):
        """the files chosen, [] on cancel; the window shows first, so that the system's dialog opens on it rather
        than at a corner of the screen"""
        from tkinter import filedialog
        self.ttk.Label(self.page(), text='Drawings to render as plotted: PDFs, or .ai files saved with PDF '
                       'compatibility.', wraplength=self.px(WRAP), justify='left').pack(anchor='w')
        self.show()
        self.root.update()
        got = filedialog.askopenfilenames(parent=self.root, title='Drawings to render as plotted',
                                          filetypes=[('PDF, or .ai saved with PDF compatibility', ('.pdf', '.ai'))])
        return list(got or ())

    def choose(self, items, prompt, default=None, ok='OK', cancel='Cancel'):
        """the item chosen, or None on cancel"""
        b, got = self.step(prompt, [cancel, ok], ok, cancel, lambda f: self.listbox(f, items, [default], 'browse', ok))
        return got[0] if b == ok and got else None

    def choose_many(self, items, prompt, ok='OK'):
        """the items chosen, [] on cancel"""
        b, got = self.step(prompt, ['Cancel', ok], ok, 'Cancel', lambda f: self.listbox(f, items, [], 'multiple', ok))
        return got if b == ok else []

    def ask(self, prompt, answer=''):
        """the text, or None on cancel"""
        def body(f):
            e = self.entry = self.ttk.Entry(f, width=36)
            e.insert(0, answer)
            e.select_range(0, 'end')
            e.pack(fill='x', pady=(self.px(10), 0))
            e.focus_set()
            return e.get
        b, got = self.step(prompt, ['Cancel', 'OK'], 'OK', 'Cancel', body)
        return got if b == 'OK' else None

    def confirm(self, text, button):
        return self.step(text, ['Cancel', button], button, 'Cancel')[0] == button

    def choose_folder(self):
        """the folder's path, or None on cancel"""
        from pathlib import Path
        from tkinter import filedialog
        got = filedialog.askdirectory(parent=self.root, title='Folder for the PNGs', mustexist=True)
        return str(Path(got)) if got else None

    def done(self, n, errors):
        """the count and any errors; True for Show in Finder (Explorer)"""
        from .ui import done_text
        show = 'Show in Finder' if MAC else 'Show in Explorer' if WIN else 'Show folder'
        buttons = ['OK', show] if n else ['OK']
        return self.step(done_text(n, errors), buttons, buttons[-1], 'OK')[0] == show

    def error(self, text):
        """the text's last lines until OK, or nothing once the window is closed"""
        try:
            self.step('\n'.join(text.strip().splitlines()[-16:]), ['OK'], 'OK', 'OK')
        except Closed:
            pass

    def progress(self, text):
        """what the render is on; from its thread"""
        self.messages.put(text)

    def work(self, fn):
        """fn() in a thread while the window shows the progress it reports; its value, or its exception raised here"""
        f = self.page()
        self.ttk.Label(f, text='Rendering…').pack(anchor='w')
        status = self.ttk.Label(f, text='', wraplength=self.px(WRAP), justify='left')
        status.pack(anchor='w', pady=(self.px(6), self.px(12)))
        bar = self.ttk.Progressbar(f, mode='indeterminate', length=self.px(WRAP))
        bar.pack(fill='x')
        bar.start(15)
        for key in ('<Return>', '<KP_Enter>', '<Escape>'):
            self.root.unbind(key)
        self.show()
        out, finished = {}, self.tk.StringVar(self.root)

        def run():
            try:
                out['value'] = fn()
            except BaseException as e:
                out['error'] = e

        def poll():
            while not self.messages.empty():
                status['text'] = self.messages.get()
            if t.is_alive():
                self.root.after(100, poll)
            else:
                finished.set('done')

        t = threading.Thread(target=run, daemon=True)
        self.working = True
        t.start()
        self.root.after(100, poll)
        self.root.wait_variable(finished)
        self.working = False
        bar.stop()
        if 'error' in out:
            raise out['error']
        return out['value']


def app(files, icon=None):
    """the downloadable apps: the dialogs over files and those dropped on the app, until no more are dropped"""
    from . import cli, render
    from .ui import run_ui
    d = Tk(icon)
    dropped = []
    if MAC:
        opened = d.tk.BooleanVar(d.root)

        def open_documents(*paths):
            dropped.extend(paths)
            opened.set(True)
        d.root.createcommand('::tk::mac::OpenDocument', open_documents)
        d.root.createcommand('::tk::mac::OpenApplication', lambda: opened.set(True))
        d.root.createcommand('::tk::mac::Quit', d.close)
        if not files:
            d.root.after(LAUNCH_WAIT, lambda: opened.set(True))
            d.root.wait_variable(opened)
    try:
        while True:
            files, dropped[:] = [*files, *dropped], []
            run_ui(render.expand(files), cli.parser().parse_args([]), d)
            if not dropped:
                break
            files = []
    except Closed:
        pass
    except SystemExit as e:
        if e.code not in (None, 0):
            d.error(str(e.code))
    except Exception:
        d.error(traceback.format_exc())
    d.root.destroy()
