"""Write docs/demo.png: a synthetic 5 x 3 in drawing (hairlines 0.03 to 0.5 pt, fine hatches, a stipple field)
rendered as a plain export draws it (each line by its coverage) above plot look's render at the same size.

  python docs/make_demo.py [DPI]      (default 150; needs poppler, numpy and Pillow)
"""
import random, subprocess, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plotlook import render  # noqa: E402

W, H = 360, 216                                     # pt
WEIGHTS = (0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5)


def content():
    ops = ['0 G 0 g 1 J']
    for i, wt in enumerate(WEIGHTS):                # hairlines, a label each
        y = H - 24 - i * 22
        ops.append(f'{wt} w 18 {y} m 108 {y} l S')
        ops.append(f'BT /F1 6 Tf 18 {y + 4} Td ({wt:g} pt) Tj ET')
    ops.append('q 126 24 96 168 re W n')            # hatches: 45 degrees, 0.05 pt at 0.5 mm, 0.1 pt at 1 mm
    for x0, top, wt, pitch in ((126, 108, 0.05, 72 / 50.8), (126, 24, 0.1, 72 / 25.4)):
        k = 0
        while k * pitch < 96 + 84:
            x = x0 - 84 + k * pitch
            ops.append(f'{wt} w {x:.3f} {top} m {x + 84:.3f} {top + 84} l S')
            k += 1
    ops.append('Q')
    ops.append('BT /F1 6 Tf 126 196 Td (hatch 0.05 pt at 0.5 mm, 0.1 pt at 1 mm) Tj ET')
    rnd = random.Random(7)                          # stipple: 0.6 pt dots, denser to the right
    ops.append('0.6 w')
    for _ in range(2600):
        x = 240 + 102 * rnd.random() ** 0.6
        y = 24 + 168 * rnd.random()
        ops.append(f'{x:.2f} {y:.2f} m {x:.2f} {y:.2f} l S')
    ops.append('BT /F1 6 Tf 240 196 Td (stipple, 0.6 pt dots) Tj ET')
    return '\n'.join(ops).encode()


def write_pdf(path):
    body = content()
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 5 0 R >> >> '
            f'/Contents 4 0 R >>'.encode(),
            b'<< /Length %d >>\nstream\n' % len(body) + body + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offs = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    x = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offs)
    path.write_bytes(bytes(out + b'trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, x)))


def main(dpi=150):
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pdf = tmp / 'demo.pdf'
        write_pdf(pdf)
        # a plain export draws a line by its coverage: rendered at 8 x and averaged down, as an exporter supersamples
        subprocess.run(['pdftoppm', '-r', str(dpi * 8), '-gray', '-png', '-singlefile', str(pdf), str(tmp / 'plain')],
                       check=True)
        plain = Image.open(tmp / 'plain.png').convert('L').reduce(8)
        opts = SimpleNamespace(preset=None, long=None, dpi=dpi, pages=None, crop=None, gain=render.GAIN_UM,
                               paper='white', sharpen=1.5, contrast=0.85, jpeg=False, out=str(tmp), tile=render.TILE,
                               workers=render.WORKERS, preset_name=None, device_dpi=None)
        look = Image.open(render.plotlook(pdf, opts, log=None)[0]).convert('L')
    pad, cap = 12, 18
    sheet = Image.new('L', (plain.width + 2 * pad, 2 * (plain.height + cap) + 3 * pad), 255)
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default()
    for i, (im, text) in enumerate([(plain, f'a plain export, lines by their coverage, {dpi} dpi'), (look, f'plot look, {dpi} dpi')]):
        y = pad + i * (plain.height + cap + pad)
        draw.text((pad, y), text, fill=0, font=font)
        sheet.paste(im, (pad, y + cap))
        draw.rectangle([pad - 1, y + cap - 1, pad + im.width, y + cap + im.height], outline=170)
    out = ROOT / 'docs' / 'demo.png'
    sheet.save(out, optimize=True)
    print(f'wrote {out}, {sheet.width} x {sheet.height} px')


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
