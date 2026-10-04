"""helpers for the tests: small PDFs written by hand, tools a test needs, and the dialogs stubbed"""
import contextlib, os, shutil, sys
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None


def needs(*tools):
    """skip a test when a tool is not on the PATH (f.needs lets a runner without pytest skip it too)"""
    def mark(f):
        f.needs = (*getattr(f, 'needs', ()), *tools)
        if pytest:
            missing = [t for t in tools if not shutil.which(t)]
            f = pytest.mark.skipif(bool(missing), reason=f'no {", ".join(missing)}')(f)
        return f
    return mark


def needs_window(f):
    """skip a test that opens Tk windows where tkinter or a display is missing, named in f.needs as a missing tool"""
    try:
        import tkinter  # noqa: F401
        ok = sys.platform in ('darwin', 'win32') or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    except ImportError:
        ok = False
    return f if ok else needs('Tk windows')(f)


def mini_pdf(path, objs):
    out, offs = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    x = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offs)
    Path(path).write_bytes(bytes(out + b'trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
                                 % (len(objs) + 1, x)))
    return Path(path)


def page_pdf(path, content, w=72, h=72, pages=1):
    """a PDF of identical pages w x h pt drawing content, with stroke adjustment on (/G0) and Helvetica as /F1"""
    kids = ' '.join(f'{3 + i} 0 R' for i in range(pages))
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', f'<< /Type /Pages /Kids [{kids}] /Count {pages} >>'.encode()]
    objs += [f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /ExtGState << /G0 << /SA true >> >> '
             f'/Font << /F1 {4 + pages} 0 R >> >> /Contents {3 + pages} 0 R >>'.encode()] * pages
    objs.append(b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream')
    objs.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    return mini_pdf(path, objs)


def hatch(wt, w=72, h=72):
    """vertical lines wt pt wide at 1 mm pitch"""
    pitch = 72 / 25.4
    xs = [1.3 + i * pitch for i in range(int((w - 2) / pitch))]
    return (f'/G0 gs 0 G {wt} w ' + ' '.join(f'{x:.3f} 0 m {x:.3f} {h} l S' for x in xs)).encode()


def mix_pdf(path):
    """two 3 x 2 in pages: a hatch, a grey box, a diagonal and a hairline"""
    return page_pdf(path, hatch(0.05, 216, 144) + b' 0.6 g 20 20 80 50 re f 0 G 0.4 w 0 0 m 216 144 l S 0.02 w '
                    b'10 140 m 200 5 l S', 216, 144, pages=2)


@contextlib.contextmanager
def env(**values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update({k: str(v) for k, v in values.items()})
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def dialogs(answers):
    """osascript stubbed: each dialog's script goes into said and gets the next answer; Show in Finder into shown"""
    from plotlook import ui
    said, shown, it = [], [], iter(answers)
    osa0, reveal0 = ui.osa, ui.reveal
    ui.osa = lambda s: (said.append(s), next(it))[1]
    ui.reveal = shown.append
    try:
        yield said, shown
    finally:
        ui.osa, ui.reveal = osa0, reveal0
