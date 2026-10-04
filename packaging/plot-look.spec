# PyInstaller spec for the downloadable apps, run by build.py, which adds poppler afterwards: Plot Look.app on macOS, a
# Plot Look folder on Windows
import os, sys

ROOT = os.path.dirname(SPECPATH)
sys.path.insert(0, ROOT)
from plotlook import __version__  # noqa: E402

ICON = os.path.join(SPECPATH, 'icon.png')
datas = []
if sys.platform == 'win32':         # the exe's icon and Tk's title bar icon, at the sizes windows shows
    from PIL import Image
    ico = os.path.join(ROOT, 'build', 'app', 'icon.ico')
    Image.open(ICON).save(ico, sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    ICON, datas = ico, [(ico, '.')]

a = Analysis([os.path.join(SPECPATH, 'app.py')], pathex=[ROOT], datas=datas)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Plot Look', console=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, name='Plot Look')

if sys.platform == 'darwin':
    app = BUNDLE(coll, name='Plot Look.app', icon=ICON, bundle_identifier='io.github.kenny-t-vo.plot-look',
                 version=__version__, info_plist={
                     'CFBundleDisplayName': 'Plot Look',
                     'LSMinimumSystemVersion': '11.0',      # conda-forge's poppler, on Intel too; build.py checks
                     'NSHighResolutionCapable': True,
                     'CFBundleDocumentTypes': [{
                         'CFBundleTypeName': 'Drawing', 'CFBundleTypeRole': 'Viewer', 'LSHandlerRank': 'Alternate',
                         'LSItemContentTypes': ['com.adobe.pdf', 'com.adobe.illustrator.ai-image', 'public.folder']}]})
