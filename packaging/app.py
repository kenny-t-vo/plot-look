"""The downloadable apps' entry point (PyInstaller): poppler from the bundle on the PATH, then the dialogs over the
files given or dropped on the app, or the command line when the first argument is an option."""
import os, sys
from pathlib import Path

HERE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def main():
    poppler = HERE / 'poppler'
    os.environ['PATH'] = os.pathsep.join([str(poppler / 'bin'), os.environ.get('PATH', '')])
    fonts = poppler / 'etc' / 'fonts'
    if fonts.is_dir():                  # macOS: the bundled fontconfig's own path to its settings is the build's
        os.environ['FONTCONFIG_FILE'] = str(fonts / 'fonts.conf')
        os.environ['FONTCONFIG_PATH'] = str(fonts)
    from plotlook import cli, tkdialogs
    args = [a for a in sys.argv[1:] if not a.startswith('-psn_')]     # older macOS passes a process number
    if args and args[0].startswith('-'):
        return cli.main(args)
    tkdialogs.app(args, HERE / 'icon.ico')
    return 0


sys.exit(main())
