"""--ui: the dialogs, standard AppleScript ones through osascript on macOS (AppleScript below), Tk ones in a window
elsewhere and in the downloadable apps (tkdialogs.Tk). Both take the same calls.

The files when none are given; then a list of the built-in presets, the saved presets, Custom… and, when there are
saved presets, Remove a preset…, with Render as its button and the last choice selected. Custom… lists the settings
with their values, each changed in one small dialog, then Render and Save as preset…; it starts from the defaults and
the last Save to. Standard dialogs take no right-click, so removing goes through Remove a preset…. ui.json beside
presets.json keeps the last choice and the last Save to. After rendering, a count with Show in Finder.
"""
import subprocess, sys
from pathlib import Path

from . import render
from .app import q
from .presets import (apply, base_settings, check, from_saved, load_presets, name_error, override,
                      read_json, remove_presets, save_preset, write_json)
from .render import PAPERS

SIZE_ITEMS = {'portfolio': 'Portfolio · 11 × 17 in, 300 dpi', '4k': 'Web 4K', '1440p': 'Web 1440p',
              'plot': 'Plot size · 300 dpi'}
CUSTOM, REMOVE, RENDER, SAVE_AS = 'Custom…', 'Remove a preset…', 'Render', 'Save as preset…'
LONG_ITEM, DPI_ITEM = 'Long edge in px…', 'Resolution in dpi…'
BESIDE, CHOOSE_FOLDER = 'Beside each drawing', 'Choose folder…'
SETTING_NAMES = {'size': 'Size', 'sharpen': 'Sharpen', 'contrast': 'Contrast', 'paper': 'Paper',
                 'gain': 'Toner spread', 'out': 'Save to'}
NUMBERS = {'sharpen': ('Sharpen, an unsharp mask on darkness', 0, 2, False),
           'contrast': ('Contrast, a gamma on coverage; under 1 darkens mid tones', 0.1, 3, False),
           'gain': ('Toner spread in µm an edge', 0, 100, False),
           'long': ('Long edge in px', 100, 30000, True),
           'dpi': ('Resolution in dpi', 10, 1200, False)}
STATE = 'ui.json'


def script_choose_files():
    return '\n'.join([
        'activate',
        'set fs to choose file with prompt "Drawings to render as plotted (PDF, or .ai saved with PDF compatibility)" '
        'of type {"com.adobe.pdf", "com.adobe.illustrator.ai-image", "pdf", "ai"} with multiple selections allowed',
        'set out to ""',
        'repeat with f in fs',
        '\tset out to out & POSIX path of f & linefeed',
        'end repeat',
        'return out'])


def script_list(items, prompt, default=None, ok='OK', cancel='Cancel', multiple=False):
    """choose from list; the items chosen a line each, or "" on cancel"""
    return '\n'.join([
        'activate',
        'set r to choose from list {' + ', '.join(q(i) for i in items) + '} with title "Plot Look" '
        f'with prompt {q(prompt)}' + (f' default items {{{q(default)}}}' if default else '')
        + f' OK button name {q(ok)} cancel button name {q(cancel)}'
        + (' with multiple selections allowed' if multiple else ''),
        'if r is false then return ""',
        'set out to ""',
        'repeat with i in r',
        '\tset out to out & i & linefeed',
        'end repeat',
        'return out'])


def script_ask(prompt, answer=''):
    """a text field; the text, or None on cancel"""
    return '\n'.join([
        'activate',
        f'set r to display dialog {q(prompt)} with title "Plot Look" default answer {q(answer)} '
        'buttons {"Cancel", "OK"} default button "OK" cancel button "Cancel"',
        'return text returned of r'])


def script_confirm(text, button):
    return '\n'.join([
        'activate',
        f'set r to display dialog {q(text)} with title "Plot Look" buttons {{"Cancel", {q(button)}}} '
        f'default button {q(button)} cancel button "Cancel"',
        'return button returned of r'])


def script_choose_folder():
    return '\n'.join([
        'activate',
        'return POSIX path of (choose folder with prompt "Folder for the PNGs")'])


def done_text(n, errors):
    return f'Rendered {n} PNG{"" if n == 1 else "s"}.' + ('\n\n' + '\n'.join(errors) if errors else '')


def script_done(n, errors):
    buttons = '{"OK", "Show in Finder"}' if n else '{"OK"}'
    default = '"Show in Finder"' if n else '"OK"'
    return '\n'.join([
        'activate',
        f'set r to display dialog {q(done_text(n, errors))} with title "Plot Look" buttons {buttons} '
        f'default button {default}',
        'return button returned of r'])


def osa(script):
    """run AppleScript; its result, or None when the person cancels"""
    r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, encoding='utf-8')
    if r.returncode:
        if '-128' in r.stderr:
            return None
        raise SystemExit(f'osascript: {r.stderr.strip()}')
    return r.stdout.strip()


class AppleScript:
    """the dialogs as standard AppleScript ones through osascript"""

    def choose_files(self):
        """the files chosen, [] on cancel"""
        return [l for l in (osa(script_choose_files()) or '').splitlines() if l.strip()]

    def choose(self, items, prompt, default=None, ok='OK', cancel='Cancel'):
        """the item chosen, or None on cancel"""
        return osa(script_list(items, prompt, default, ok, cancel)) or None

    def choose_many(self, items, prompt, ok='OK'):
        """the items chosen, [] on cancel"""
        return [l for l in (osa(script_list(items, prompt, ok=ok, multiple=True)) or '').splitlines() if l]

    def ask(self, prompt, answer=''):
        """the text, or None on cancel"""
        return osa(script_ask(prompt, answer))

    def confirm(self, text, button):
        return osa(script_confirm(text, button)) is not None

    def choose_folder(self):
        """the folder's path, or None on cancel"""
        return osa(script_choose_folder())

    def done(self, n, errors):
        """the count and any errors; True for Show in Finder"""
        return osa(script_done(n, errors)) == 'Show in Finder'

    def progress(self, text):
        pass

    def work(self, fn):
        return fn()


def reveal(path):
    """the file selected in Finder or Explorer, elsewhere its folder opened"""
    if sys.platform == 'darwin':
        subprocess.run(['open', '-R', str(path)])
    elif sys.platform == 'win32':
        subprocess.run(f'explorer /select,"{path}"')
    else:
        subprocess.run(['xdg-open', str(Path(path).parent)])


def size_item(s):
    if s['size']:
        return SIZE_ITEMS[s['size']]
    return f'Long edge {s["long"]} px' if s['long'] else f'{s["dpi"]:g} dpi'


def setting_value(s, k):
    if k == 'size':
        return size_item(s)
    if k == 'paper':
        return s['paper'].capitalize()
    if k == 'gain':
        return f'{s["gain"]:g} µm'
    if k == 'out':
        if not s['out']:
            return BESIDE
        return s['out'] if sys.platform == 'win32' else s['out'].replace(str(Path.home()), '~', 1)
    return f'{s[k]:g}'


def ask_number(d, k, current):
    """a number in NUMBERS[k]'s range from a text field, or None on cancel"""
    what, lo, hi, whole = NUMBERS[k]
    prompt = f'{what}, {lo:g} to {hi:g}:'
    answer = f'{current:g}'
    while True:
        got = d.ask(prompt, answer)
        if got is None:
            return None
        try:
            v = float(got.replace(',', '.'))
            if lo <= v <= hi and (not whole or v == int(v)):
                return int(v) if whole else v
        except ValueError:
            pass
        prompt, answer = f'{got} is not {"a whole number" if whole else "a number"} from {lo:g} to {hi:g}. {what}:', got


def edit_setting(d, k, s, state):
    """one dialog to change setting k in s; True if it changed"""
    if k in ('sharpen', 'contrast', 'gain'):
        v = ask_number(d, k, s[k])
        if v is None:
            return False
        s[k] = v
        return True
    if k == 'paper':
        got = d.choose([p.capitalize() for p in PAPERS], 'Paper', s['paper'].capitalize())
        if not got:
            return False
        s['paper'] = got.lower()
        return True
    if k == 'out':
        got = d.choose([BESIDE, CHOOSE_FOLDER], 'Save the PNGs', CHOOSE_FOLDER if s['out'] else BESIDE)
        if not got:
            return False
        out = None
        if got == CHOOSE_FOLDER:
            out = d.choose_folder()
            if not out:
                return False
            out = out.rstrip('/') or '/'
        s['out'] = state['save_to'] = out
        write_json(STATE, state)
        return True
    items = [*SIZE_ITEMS.values(), LONG_ITEM, DPI_ITEM]
    cur = size_item(s) if s['size'] else LONG_ITEM if s['long'] else DPI_ITEM
    got = d.choose(items, 'Size of the PNGs', cur)
    if not got:
        return False
    if got in (LONG_ITEM, DPI_ITEM):
        k2 = 'long' if got == LONG_ITEM else 'dpi'
        v = ask_number(d, k2, s[k2] or (3840 if k2 == 'long' else 300))
        if v is None:
            return False
        s.update(size=None, long=None, dpi=None)
        s[k2] = v
    else:
        s.update(size={v: k for k, v in SIZE_ITEMS.items()}[got], long=None, dpi=None)
    return True


def ask_preset_name(d):
    """a new or replaced preset's name, or None on cancel"""
    prompt, answer = 'Name for the preset (letters, digits and hyphens):', ''
    while True:
        got = d.ask(prompt, answer)
        if got is None:
            return None
        got = got.strip()
        err = name_error(got)
        if err:
            prompt, answer = f'{err} Name for the preset:', got
            continue
        if got in load_presets() and not d.confirm(f'Replace the preset {got}?', 'Replace'):
            continue
        return got


def custom_menu(d, state):
    """the Custom… settings; (settings, saved preset name or None), or None to go back"""
    s, name = base_settings(out=state.get('save_to')), None
    while True:
        rows = {f'{SETTING_NAMES[k]} — {setting_value(s, k)}': k for k in SETTING_NAMES}
        got = d.choose([*rows, RENDER, SAVE_AS], 'Settings', RENDER, ok='Choose', cancel='Back')
        if not got:
            return None
        if got == RENDER:
            return s, name
        if got == SAVE_AS:
            n = ask_preset_name(d)
            if n:
                save_preset(n, s)
                name = n
        elif edit_setting(d, rows[got], s, state):
            name = None


def remove_menu(d, saved):
    names = d.choose_many(sorted(saved), 'Presets to remove', ok='Remove')
    if not names:
        return
    text = f'Remove the preset{"s" if len(names) > 1 else ""} {", ".join(names)}?'
    if d.confirm(text, 'Remove'):
        remove_presets(names)


def main_menu(d):
    """the list of presets, with Custom… and Remove a preset…; (settings, saved preset name or None), or None"""
    state = read_json(STATE)
    keys = {v: k for k, v in SIZE_ITEMS.items()}
    while True:
        saved = load_presets()
        items = [*SIZE_ITEMS.values(), *sorted(saved), CUSTOM] + ([REMOVE] if saved else [])
        last = {'custom': CUSTOM}.get(state.get('last'), SIZE_ITEMS.get(state.get('last'), state.get('last')))
        got = d.choose(items, 'Size of the PNGs', last if last in items else items[0], ok='Render')
        if not got:
            return None
        if got == REMOVE:
            remove_menu(d, saved)
            continue
        if got == CUSTOM:
            picked = custom_menu(d, state)
            if not picked:
                continue
            s, name = picked
            last = name or 'custom'
        elif got in saved:
            s, name, last = check(from_saved(saved[got])), got, got
        else:
            s, name, last = base_settings(keys[got]), None, keys[got]
        state['last'] = last
        write_json(STATE, state)
        return s, name


def run_ui(files, opts, d=None):
    """the dialogs d (AppleScript's on macOS, else Tk's): files (if none given), the settings, render, a count with
    Show in Finder; the PNGs written"""
    if d is None:
        if sys.platform == 'darwin':
            d = AppleScript()
        else:
            from .tkdialogs import Tk
            d = Tk()
    if not files:
        files = d.choose_files()
        if not files:
            return []
    picked = main_menu(d)
    if not picked:
        return []
    s, name = picked
    apply(opts, check(override(s, opts)), name)

    def render_all():
        pngs, errors = [], []
        for i, f in enumerate(files):
            if Path(f).suffix.lower() not in ('.pdf', '.ai'):
                errors.append(f'{Path(f).name}: not a PDF or .ai')
                continue
            d.progress(Path(f).name + (f', {i + 1} of {len(files)}' if len(files) > 1 else ''))
            try:
                pngs += [w for w in render.run(f, opts) if w.suffix == '.png']
            except (SystemExit, Exception) as e:
                errors.append(f'{Path(f).name}: {e}')
        return pngs, errors

    pngs, errors = d.work(render_all)
    if d.done(len(pngs), errors) and pngs:
        reveal(pngs[0])
    return pngs
