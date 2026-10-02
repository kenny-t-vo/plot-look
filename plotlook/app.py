"""--make-app: Plot Look.app (macOS), an AppleScript droplet compiled with osacompile that runs `COMMAND --ui` with
the files dropped on it, or with none on a double-click. COMMAND is baked in: by default this Python with
-m plotlook. The app sets a PATH holding Homebrew's and ~/.local/bin, where poppler and uv usually are, and logs to
~/Library/Logs/plot-look.log.
"""
import os, shlex, shutil, subprocess, sys
from pathlib import Path

APP_NAME = 'Plot Look.app'
APP_PATH = '/opt/homebrew/bin:/usr/local/bin:{home}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin'


def q(s):
    """an AppleScript string literal"""
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


def app_script(command, home):
    """the droplet's AppleScript; command, a list of arguments, runs with --ui and the files"""
    log = f'{home}/Library/Logs/plot-look.log'
    return '\n'.join([
        f'property cmd : {q(shlex.join(str(c) for c in command))}',
        f'property envpath : {q(APP_PATH.format(home=home))}',
        f'property logpath : {q(log)}',
        '',
        'on run',
        '\tgo("")',
        'end run',
        '',
        'on open theFiles',
        '\tset args to ""',
        '\trepeat with f in theFiles',
        '\t\tset args to args & " " & quoted form of POSIX path of f',
        '\tend repeat',
        '\tgo(args)',
        'end open',
        '',
        'on go(args)',
        '\tdo shell script "export PATH=" & quoted form of envpath & "; " & cmd & " --ui" & args & " >> " '
        '& quoted form of logpath & " 2>&1 &"',
        'end go'])


def make_app(folder=None, command=None):
    """write Plot Look.app into folder (default /Applications, else ~/Applications); its path"""
    if sys.platform != 'darwin':
        raise SystemExit('plotlook: --make-app is macOS only')
    if folder:
        folder = Path(folder).expanduser().absolute()
    else:
        folder = Path('/Applications') if os.access('/Applications', os.W_OK) else Path.home() / 'Applications'
    folder.mkdir(parents=True, exist_ok=True)
    app = folder / APP_NAME
    src = app_script(command or [sys.executable, '-m', 'plotlook'], str(Path.home()))
    if app.exists():
        shutil.rmtree(app)
    r = subprocess.run(['osacompile', '-o', str(app), '-e', src], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'osacompile: {r.stderr.strip()}')
    print(f'wrote {app}: double-click to choose drawings, or drop PDFs and .ai files on it')
    return app
