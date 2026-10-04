"""Write packaging/icon.png, the apps' icon at 1024 px: a sheet of 45 degree lines from hairline to heavy, on paper.

  python packaging/icon.py      (needs Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

N, S = 1024, 4                              # px, and the supersampling
BODY = (100, 100, 924, 924)                 # the rounded square, macOS's icon grid
RADIUS = 185
PITCH = 60                                  # px between lines
WIDTHS = (3, 20)                            # px, the thinnest and heaviest line
PAPER, INK = (246, 243, 236, 255), (26, 26, 26, 255)


def icon():
    big = N * S
    body = [v * S for v in BODY]
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(body, RADIUS * S, fill=255)
    lines = Image.new('L', (big, big), 0)
    d = ImageDraw.Draw(lines)
    x0, x1 = body[0] - (body[3] - body[1]), body[2]
    n = (x1 - x0) // (PITCH * S)
    for i in range(n + 1):
        x = x0 + i * PITCH * S
        w = WIDTHS[0] + (WIDTHS[1] - WIDTHS[0]) * i / n
        d.line([(x, body[1]), (x + body[3] - body[1], body[3])], fill=255, width=round(w * S))
    sheet = Image.composite(Image.new('RGBA', (big, big), INK), Image.new('RGBA', (big, big), PAPER), lines)
    shadow = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    shadow.putalpha(mask.point(lambda v: v * 70 // 255).filter(ImageFilter.GaussianBlur(14 * S)))
    out = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    out.alpha_composite(shadow, (0, 10 * S))
    out.paste(sheet, (0, 0), mask)
    return out.resize((N, N), Image.LANCZOS)


if __name__ == '__main__':
    path = Path(__file__).resolve().parent / 'icon.png'
    icon().save(path, optimize=True)
    print(path)
