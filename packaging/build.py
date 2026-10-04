"""Build the downloadable app for this machine: Plot Look.app on macOS, a Plot Look folder on Windows, each holding
Python, plot look and poppler's pdftoppm and pdfinfo, so that it needs nothing installed.

  python packaging/build.py PREFIX [--name NAME]

PREFIX is a conda-forge environment holding poppler (micromamba create -p PREFIX -c conda-forge poppler). The build
copies pdftoppm and pdfinfo and the libraries they load from it into build/app/poppler, runs PyInstaller with
plot-look.spec, then puts that poppler into the app as it is, out of PyInstaller's reach, which would relink it to
copies of its libraries beside Python's own (on macOS the app is signed again, ad hoc). It renders a test page
through the built app's command line and zips the app as dist/Plot-Look-VERSION-NAME.zip, NAME by default
mac-apple-silicon, mac-intel or windows. It needs PyInstaller, numpy and Pillow in the Python that runs it, and
pefile on Windows (PyInstaller's own). The release workflow runs it on each platform.
"""
import argparse, os, platform, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, DIST = ROOT / 'build' / 'app', ROOT / 'dist'
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from plotlook import __version__  # noqa: E402
from pdfs import hatch, page_pdf  # noqa: E402

MAC, WIN = sys.platform == 'darwin', sys.platform == 'win32'
TOOLS = ('pdftoppm', 'pdfinfo')
MACHO = (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe')     # 64-bit and universal
FONT_CACHE = '~/Library/Caches/Plot Look/fontconfig'
WINDOW_WAIT = 15                    # s for the app to open its window on a build machine


def mac_deps(f):
    """the libraries a Mach-O file loads through @rpath, by name; refuses any other non-system one"""
    out = subprocess.run(['otool', '-L', str(f)], capture_output=True, text=True, check=True).stdout
    deps = [l.split()[0] for l in out.splitlines()[1:] if l.strip()]
    other = [d for d in deps if not d.startswith(('@rpath/', '/usr/lib/', '/System/'))]
    if other:
        raise SystemExit(f'{f} loads {other[0]}, outside its environment\'s lib and the system')
    return [d[len('@rpath/'):] for d in deps if d.startswith('@rpath/')]


def win_deps(f):
    """the DLLs a PE file imports, by name"""
    import pefile
    pe = pefile.PE(str(f), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                                           pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
    return [e.dll.decode() for k in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
            for e in getattr(pe, k, [])]


def closure(tools, deps, find):
    """the tools and every library they load that find(name) locates in the environment"""
    files, todo = {}, list(tools)
    while todo:
        f = todo.pop()
        if f.name in files:
            continue
        files[f.name] = f
        todo += [p for p in map(find, deps(f)) if p and p.name not in files]
    return files


def collect_poppler(prefix, dest):
    """pdftoppm, pdfinfo and the libraries they load from the environment prefix into dest: bin/ (with the DLLs on
    Windows; lib/ beside it on macOS, where the tools look in ../lib) and, on macOS, fontconfig's settings in
    etc/fonts with the font cache in the user's Caches; the bytes copied"""
    if dest.exists():
        shutil.rmtree(dest)
    (dest / 'bin').mkdir(parents=True)
    if MAC:
        lib = prefix / 'lib'
        files = closure([prefix / 'bin' / t for t in TOOLS], mac_deps, lambda n: lib / n if (lib / n).exists() else None)
        (dest / 'lib').mkdir()
        for name, f in files.items():
            shutil.copy2(f, dest / ('bin' if name in TOOLS else 'lib') / name)     # a symlink's target, under its name
        fonts = dest / 'etc' / 'fonts'
        shutil.copytree(prefix / 'etc' / 'fonts', fonts, symlinks=False)
        conf = (fonts / 'fonts.conf').read_text()
        conf = re.sub(r'[ \t]*<cachedir[^>]*>[^<]*</cachedir>\n', '', conf)
        conf = conf.replace('</fontconfig>', f'\t<cachedir>{FONT_CACHE}</cachedir>\n</fontconfig>')
        (fonts / 'fonts.conf').write_text(conf)
    else:
        found = {p.name.lower(): p for d in (prefix / 'Library' / 'bin', prefix) for p in d.glob('*.dll')}
        files = closure([prefix / 'Library' / 'bin' / f'{t}.exe' for t in TOOLS], win_deps,
                        lambda n: None if n.lower().startswith('api-ms-win-') else found.get(n.lower()))
        for f in files.values():
            shutil.copy2(f, dest / 'bin' / f.name)
    return sum(f.stat().st_size for f in dest.rglob('*') if f.is_file())


def min_macos(f):
    """the macOS a Mach-O file needs, as (major, minor)"""
    out = subprocess.run(['otool', '-l', str(f)], capture_output=True, text=True, check=True).stdout
    found = re.findall(r'cmd LC_(?:BUILD_VERSION|VERSION_MIN_MACOSX)\n(?:.*\n){1,2}?\s*(?:minos|version) (\d+)\.(\d+)', out)
    return max(((int(a), int(b)) for a, b in found), default=(0, 0))


def check_min_macos(app):
    """refuses a binary in the app that needs a newer macOS than its Info.plist's LSMinimumSystemVersion"""
    import plistlib
    need = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())['LSMinimumSystemVersion']
    need = tuple(int(v) for v in need.split('.')[:2])
    for f in sorted(app.rglob('*')):
        if f.is_file() and not f.is_symlink():
            with open(f, 'rb') as fh:
                if fh.read(4) in MACHO and min_macos(f) > need:
                    raise SystemExit(f'{f.relative_to(app)} needs macOS {".".join(map(str, min_macos(f)))}, '
                                     f'newer than the app\'s {".".join(map(str, need))}')


def app_executable():
    return DIST / 'Plot Look.app' / 'Contents' / 'MacOS' / 'Plot Look' if MAC else DIST / 'Plot Look' / 'Plot Look.exe'


def install_poppler(poppler):
    """the collected poppler into the built app, where packaging/app.py looks for it: on macOS the binaries in
    Contents/Frameworks/poppler, signed, its etc in Contents/Resources/poppler linked from there, and the app signed
    again; on Windows in _internal/poppler"""
    if not MAC:
        shutil.copytree(poppler, DIST / 'Plot Look' / '_internal' / 'poppler')
        return
    app = DIST / 'Plot Look.app'
    code, data = app / 'Contents' / 'Frameworks' / 'poppler', app / 'Contents' / 'Resources' / 'poppler'
    for d in ('bin', 'lib'):
        shutil.copytree(poppler / d, code / d)
    shutil.copytree(poppler / 'etc', data / 'etc')
    (code / 'etc').symlink_to(Path('..', '..', 'Resources', 'poppler', 'etc'))
    subprocess.run(['codesign', '--force', '--sign', '-', *map(str, sorted((code / 'lib').iterdir())),
                    *map(str, sorted((code / 'bin').iterdir()))], check=True, capture_output=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True, capture_output=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    check_min_macos(app)


def window_shown(title):
    """windows: a visible top-level window of that title"""
    import ctypes
    h = ctypes.windll.user32.FindWindowW(None, title)
    return bool(h and ctypes.windll.user32.IsWindowVisible(h))


def smoke():
    """a page with a hatch on its left and a word in Helvetica, which the PDF does not embed, on its right, rendered
    through the built app's command line; then the app opened on it, as a double-click on the page would, which must
    still be running WINDOW_WAIT later, at its list of sizes (on Windows in a visible window named Plot Look).
    Refuses a missing hatch or word, or an app that quit"""
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        env = {**os.environ, 'PLOTLOOK_HOME': str(tmp / 'home')}
        pdf = page_pdf(tmp / 'smoke.pdf', b'q 0 0 100 144 re W n ' + hatch(0.1, 216, 144)
                       + b' Q BT /F1 40 Tf 112 56 Td (Plot) Tj ET', 216, 144)
        r = subprocess.run([str(app_executable()), '--long', '432', '-q', '--out', str(tmp), str(pdf)],
                           capture_output=True, text=True, timeout=600, env=env)
        png = tmp / 'smoke-432px.png'
        if r.returncode or not png.exists():
            raise SystemExit(f'smoke test: the app exited with {r.returncode}: {r.stderr.strip()[-500:]}')
        a = np.asarray(Image.open(png).convert('L'), np.float32)
        app = subprocess.Popen([str(app_executable()), str(pdf)], env=env)
        try:
            time.sleep(WINDOW_WAIT)
            quit_code = app.poll()
            shown = quit_code is None and (not WIN or window_shown('Plot Look'))
        finally:
            app.kill()
            app.wait()
    hatch_mean, word_min = float(a[20:268, 10:190].mean()), float(a[:, 230:].min())
    print(f'smoke test: {a.shape[1]} x {a.shape[0]} px, hatch mean {hatch_mean:.0f}, word darkest {word_min:.0f}; '
          f'the window {"open" if shown else "missing"} after {WINDOW_WAIT} s')
    if not (150 < hatch_mean < 245 and word_min < 80):
        raise SystemExit('smoke test: the hatch or the word did not render')
    if not shown:
        raise SystemExit(f'smoke test: the app {f"quit with {quit_code}" if quit_code is not None else "showed no window"}'
                         f' when opened on a PDF')


def main():
    a = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    a.add_argument('prefix', type=Path, help='a conda-forge environment holding poppler')
    a.add_argument('--name', help='the platform in the zip\'s name (default from this machine)')
    opts = a.parse_args()
    name = opts.name or ('windows' if WIN else 'mac-apple-silicon' if platform.machine() == 'arm64' else 'mac-intel')
    poppler = BUILD / 'poppler'
    size = collect_poppler(opts.prefix.resolve(), poppler)
    print(f'poppler: {sum(1 for f in poppler.rglob("*") if f.is_file())} files, {size / 1e6:.0f} MB')
    for d in (DIST / 'Plot Look', DIST / 'Plot Look.app'):
        if d.exists():
            shutil.rmtree(d)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
                    '--distpath', str(DIST), '--workpath', str(BUILD / 'work'), str(ROOT / 'packaging' / 'plot-look.spec')],
                   check=True)
    install_poppler(poppler)
    smoke()
    zip_path = DIST / f'Plot-Look-{__version__}-{name}.zip'
    zip_path.unlink(missing_ok=True)
    if MAC:
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(DIST / 'Plot Look.app'),
                        str(zip_path)], check=True)
    else:
        shutil.make_archive(str(zip_path.with_suffix('')), 'zip', DIST, 'Plot Look')
    print(f'{zip_path}  {zip_path.stat().st_size / 1e6:.0f} MB')


if __name__ == '__main__':
    main()
