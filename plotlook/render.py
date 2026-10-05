"""The model: a PDF page as a toner plotter prints it, seen from a normal distance.

1. device raster: pdftoppm at the device's dpi (--device-dpi, 600), grey, no anti-aliasing, -thinlinemode solid:
   every line under a pixel prints a pixel wide. Rendered in tiles of at most TILE px a side, WORKERS at a time, each
   with a margin of a few px for step 2. pdftoppm's memory grows with a tile's area and content (about 60 bytes a
   pixel on a dense 42 x 56 in sheet). At some resolutions and tiles poppler 26.04 prints "Bogus memory allocation
   size" and leaves a tiling pattern out (a black hatch at 600 dpi in a 12600 px wide tile). Such a tile is rendered
   again at a resolution nudged by NUDGE, its origin scaled to match, and failing those, in quarters.
2. toner spread: coverage c (0 to 1) becomes c + g (max3x3(c) - c), g = gain / pixel (33 um at 600 dpi: 0.78), in
   ceil(g) passes over 1. A flat grey keeps its grey, a line widens by about a gain an edge, a solid stays solid.
3. downsample in linear light: integer block means of coverage per tile, then one Lanczos resize to the output size.
   Reflectance is affine in coverage, so averaging coverage averages reflectance.
4. contrast: coverage ** G after the average (under 1 darkens mid tones). Reflectance R = paper - c (paper - toner):
   white paper 1 and toner 0; bond about 0.94 with a warm tint, toner 0.06, for a photographed look.
5. sRGB encode, then sharpen: an unsharp mask on darkness (1 - encoded value), sigma 1 output px, amount A, clipped
   to paper and toner. It darkens marks against their surroundings and leaves the tone of large textured areas nearly
   as it is.
6. colour (--colour): the page rendered once more in RGB, anti-aliased, at the output size (at most COLOUR_PX on its long
   side, then resized), and each output pixel given that render's chroma at the tone steps 1 to 5 gave it: the plotted
   tone times the render's linear RGB over its luminance. A grey keeps exactly its plotted tone; a colour fill under
   black marks keeps its hue at the marks' plotted tone. It shows a drawing's colour on screen; it is not a model of
   how a colour plotter prints it.
7. 8-bit PNG with its dpi (mode L on white, RGB on bond or with colour); optionally also a quality 92 JPEG.

The gain of 33 um and the defaults of sharpen 1.5 and contrast 0.85 were measured on a Canon ColorWave 3600 (600 dpi
toner): the gain from a printed calibration strip (a 0.03 pt hatch at 1 mm pitch printed like 11 percent grey, a
0.2 pt one like 15), sharpen and contrast against photographs of plots taken from 2 to 5 ft.
"""
import io, math, re, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GAIN_UM = 33.0
DEVICE_DPI = 600
TILE = 2400                       # px a side; 3000 px tiles of a dense 42 x 56 in sheet took pdftoppm to 530 MB
WORKERS = 3
NUDGE = (0, 0.05, 0.1, 0.2, -0.05, -0.2, 0.5)   # dpi added in turn when pdftoppm leaves out a tiling pattern; across a
                                                # 2400 px tile at 600 dpi that drifts 0.2 px at 0.05, 2 px at 0.5
STRIP = 1024                      # output rows encoded at a time
COLOUR_PX = 6000                  # the colour render's long side at most; colour is resized up past it
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # windows: no console window for each pdftoppm under a gui
PAPERS = {'white': dict(paper=(1.0,), toner=0.0),
          'bond': dict(paper=(0.955, 0.94, 0.905), toner=0.06)}   # linear reflectance, r g b
PRESETS = {'portfolio': 'fit into 11 x 17 in at 300 dpi', '4k': 'fit into 3840 x 2160 px',
           '1440p': 'fit into 2560 x 1440 px', 'plot': 'the page at its own size, 300 dpi'}
ALIASES = {'web': '4k'}
SCREENS = {'4k': (3840, 2160), '1440p': (2560, 1440)}   # px, landscape; turned to match the page
POPPLER_HINT = ('plot look needs poppler\'s pdftoppm and pdfinfo on the PATH. Install poppler:\n'
                '  macOS:          brew install poppler\n'
                '  Debian, Ubuntu: sudo apt install poppler-utils\n'
                '  Fedora:         sudo dnf install poppler-utils\n'
                '  Windows:        scoop install poppler, choco install poppler, or conda install -c conda-forge '
                'poppler,\n                  then check that pdftoppm runs in a new terminal')


class TileTooBig(Exception):
    pass


def stderr_log(msg):
    print(msg, file=sys.stderr, flush=True)


def write_file(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def require_poppler():
    missing = [t for t in ('pdftoppm', 'pdfinfo') if not shutil.which(t)]
    if missing:
        raise SystemExit(f'plotlook: {" and ".join(missing)} not found.\n{POPPLER_HINT}')


def expand(paths):
    """the files given, a folder standing for its PDFs (not those in its subfolders)"""
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted((f for f in p.iterdir() if f.suffix.lower() == '.pdf' and not f.name.startswith('._')),
                          key=lambda f: f.name.lower())
        else:
            out.append(p)
    return [str(p) for p in out]


# ---------------------------------------------------------------- pages
def pages(pdf):
    """each page's (width, height) in points as pdftoppm renders it: the media box, turned by its rotation"""
    def info(*a):
        r = subprocess.run(['pdfinfo', *a, str(pdf)], capture_output=True, encoding='utf-8', errors='replace',
                           creationflags=NO_WINDOW)
        if r.returncode:
            raise SystemExit(f'poppler cannot read {pdf} (an .ai must be saved with PDF compatibility): '
                             f'{r.stderr.strip()[-200:]}')
        return r.stdout
    n = int(re.search(r'^Pages:\s+(\d+)', info(), re.M).group(1))
    out = info('-box', '-f', '1', '-l', str(n))
    box = {int(p): [float(v) for v in b.split()] for p, b in re.findall(r'^Page\s+(\d+) MediaBox:\s+(.+)$', out, re.M)}
    rot = {int(p): int(r) for p, r in re.findall(r'^Page\s+(\d+) rot:\s+(-?\d+)', out, re.M)}
    sizes = []
    for p in range(1, n + 1):
        x0, y0, x1, y1 = box[p]
        w, h = abs(x1 - x0), abs(y1 - y0)
        sizes.append((h, w) if rot.get(p, 0) % 180 else (w, h))
    return sizes


def device_px(pt, dpi):
    """pdftoppm's page size in pixels: the size in points at the dpi, rounded up"""
    return math.ceil(round(pt * dpi / 72, 6))


def out_size(w_in, h_in, preset=None, long=None, dpi=None):
    """(width px, height px, dpi written) of the output for a page or crop w_in x h_in inches"""
    preset = ALIASES.get(preset, preset)
    if long:
        s = long / max(w_in, h_in)
    elif dpi or preset == 'plot':
        s = float(dpi or 300)
    elif preset in SCREENS:
        bw, bh = SCREENS[preset][::-1] if h_in >= w_in else SCREENS[preset]
        s = min(bw / w_in, bh / h_in)
    elif preset == 'portfolio':
        bw, bh = (11, 17) if h_in >= w_in else (17, 11)
        fit = min(bw / w_in, bh / h_in)
        return max(1, round(w_in * fit * 300)), max(1, round(h_in * fit * 300)), 300.0
    else:
        raise SystemExit(f'plotlook: no preset {preset}; one of {", ".join(PRESETS)}')
    return max(1, round(w_in * s)), max(1, round(h_in * s)), round(s, 2)


# ---------------------------------------------------------------- the model
def max3(c):
    """3 x 3 maximum, the edge pixels repeated outward"""
    import numpy as np
    p = np.pad(c, 1, mode='edge')
    m = np.maximum(np.maximum(p[:-2], p[1:-1]), p[2:])
    return np.maximum(np.maximum(m[:, :-2], m[:, 1:-1]), m[:, 2:])


def blur(d):
    """gaussian of sigma 1 px over a radius of 4, the edge pixels repeated outward"""
    import numpy as np
    g = np.exp(-0.5 * np.arange(-4, 5, dtype=np.float64) ** 2)
    g = (g / g.sum()).astype(d.dtype)
    h, w = d.shape
    p = np.pad(d, 4, mode='edge')
    r = sum(g[i] * p[i:i + h] for i in range(9))
    return sum(g[i] * r[:, i:i + w] for i in range(9))


def spread(c, gain_px):
    """toner spread: a soft grey dilation by gain_px pixels an edge, in ceil(gain_px) passes"""
    import numpy as np
    n = math.ceil(gain_px - 1e-9)
    for _ in range(n):
        c = c + gain_px / n * (max3(c) - c)
    return np.minimum(c, 1.0, out=c) if n else c


def block_sums(c, k):
    """sums of k x k blocks, the last row and column of blocks partial"""
    import numpy as np
    h, w = c.shape
    H, W = -(-h // k) * k, -(-w // k) * k
    if (H, W) != (h, w):
        c = np.pad(c, ((0, H - h), (0, W - w)))
    return c.reshape(H // k, k, W // k, k).sum(axis=(1, 3), dtype=np.float64).astype(np.float32)


def block_means(c, k):
    """linear-light means of k x k blocks, partial blocks over the pixels they hold"""
    import numpy as np
    h, w = c.shape
    cy = np.minimum(k, h - np.arange(0, h, k))
    cx = np.minimum(k, w - np.arange(0, w, k))
    return block_sums(c, k) / (cy[:, None] * cx[None, :]).astype(np.float32)


def srgb(x):
    import numpy as np
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(np.maximum(x, 0), 1 / 2.4) - 0.055)


def linear(e):
    """sRGB-encoded values, 0 to 1, to linear light"""
    import numpy as np
    return np.where(e <= 0.04045, e / 12.92, np.power((e + 0.055) / 1.055, 2.4))


def colour_layer(pdf, page, region_in, size, tmp):
    """the page's colours over region_in (x0, y0, w, h in inches) at size (w, h px): linear RGB, anti-aliased"""
    import numpy as np
    from PIL import Image
    x0, y0, w_in, h_in = region_in
    ow, oh = size
    s = min(1.0, COLOUR_PX / max(ow, oh))
    rw, rh = max(1, round(ow * s)), max(1, round(oh * s))
    dpi = rw / w_in
    stem = Path(tmp) / f'colour-{page}'
    args = ['pdftoppm', '-r', f'{dpi:.6f}', '-f', str(page), '-l', str(page), '-singlefile',
            '-x', str(round(x0 * dpi)), '-y', str(round(y0 * dpi)), '-W', str(rw), '-H', str(rh), str(pdf), str(stem)]
    r = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if r.returncode:
        raise SystemExit(f'pdftoppm could not render {pdf} in colour: {r.stderr.strip()[-300:]}')
    path = Path(f'{stem}.ppm')
    im = Image.open(path)
    im.load()
    path.unlink()
    if im.size != (ow, oh):
        im = im.resize((ow, oh), Image.LANCZOS)
    return linear(np.asarray(im.convert('RGB'), np.float32) / 255.0)


def tinted(img, rgb):
    """an 8-bit plotted image (grey, or RGB on bond) given the chroma of rgb (linear, the same size): 8-bit RGB"""
    import numpy as np
    t = linear(img.astype(np.float32) / 255.0)
    t = np.repeat(t[:, :, None], 3, axis=2) if t.ndim == 2 else t
    y = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    ratio = np.where(y[:, :, None] > 1e-3, rgb / np.maximum(y, 1e-3)[:, :, None], 1.0)
    return np.round(srgb(np.clip(t * ratio, 0, 1)) * 255).astype(np.uint8)


def render_tile(pdf, page, dpi, x, y, w, h, tmp):
    """a tile of the device raster as coverage, 0 to 1"""
    import numpy as np
    stem = Path(tmp) / f'p{page}-{x}-{y}'
    args = ['pdftoppm', '-r', str(dpi), '-f', str(page), '-l', str(page), '-singlefile', '-gray',
            '-aa', 'no', '-aaVector', 'no', '-thinlinemode', 'solid',
            '-x', str(x), '-y', str(y), '-W', str(w), '-H', str(h), str(pdf), str(stem)]
    r = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if 'Bogus memory allocation' in r.stderr:
        Path(f'{stem}.pgm').unlink(missing_ok=True)
        raise TileTooBig
    if r.returncode:
        raise SystemExit(f'pdftoppm could not render {pdf}: {r.stderr.strip()[-300:]}')
    path = Path(f'{stem}.pgm')
    data = path.read_bytes()
    path.unlink()
    m = re.match(rb'P5\s+(\d+)\s+(\d+)\s+(\d+)\s', data)
    tw, th = int(m.group(1)), int(m.group(2))
    a = np.frombuffer(data, np.uint8, tw * th, m.end()).reshape(th, tw)
    if (tw, th) != (w, h):                       # the page's last pixel row or column, where rounding differs
        a = np.pad(a[:h, :w], ((0, h - min(h, th)), (0, w - min(w, tw))), constant_values=255)
    return 1.0 - a.astype(np.float32) / 255.0


def device_reduce(pdf, page, dpi, region, k, gain_px, tile=TILE, workers=WORKERS, log=None):
    """the page's region (x0, y0, w, h in device px) rendered as it prints, spread, and averaged in k x k blocks"""
    import numpy as np
    x0, y0, W, H = region
    ov = max(2, math.ceil(gain_px - 1e-9) + 1)
    out = np.zeros((-(-H // k), -(-W // k)), np.float32)
    nx, ny = -(-W // tile), -(-H // tile)
    tw, th = -(-(-(-W // nx)) // k) * k, -(-(-(-H // ny)) // k) * k     # k-aligned tile sides
    cores = [(cx, cy, min(tw, W - cx), min(th, H - cy)) for cy in range(0, H, th) for cx in range(0, W, tw)]
    split, nudged = [], []

    def work(core, tmp):
        cx, cy, cw, ch = core
        rx0, ry0 = max(0, cx - ov), max(0, cy - ov)
        rx1, ry1 = min(W, cx + cw + ov), min(H, cy + ch + ov)
        for d in NUDGE:
            r = dpi + d
            try:
                c = render_tile(pdf, page, r, round((x0 + rx0) * r / dpi), round((y0 + ry0) * r / dpi),
                                rx1 - rx0, ry1 - ry0, tmp)
                break
            except TileTooBig:
                continue
        else:
            if cw <= 2 * k * 64 and ch <= 2 * k * 64:
                raise SystemExit(f'pdftoppm cannot render a {cw} x {ch} px tile of page {page} of {pdf} without '
                                 f'leaving out art ("Bogus memory allocation size") at any of {dpi} dpi + {NUDGE[1:]}')
            split.append(core)
            hw, hh = -(-(cw // 2) // k) * k, -(-(ch // 2) // k) * k
            for sx, sy, sw, sh in ((0, 0, hw, hh), (hw, 0, cw - hw, hh), (0, hh, hw, ch - hh), (hw, hh, cw - hw, ch - hh)):
                if sw > 0 and sh > 0:
                    work((cx + sx, cy + sy, sw, sh), tmp)
            return
        if d:
            nudged.append(d)
        c = spread(c, gain_px)[cy - ry0:cy - ry0 + ch, cx - rx0:cx - rx0 + cw]
        b = block_sums(c, k)
        out[cy // k:cy // k + b.shape[0], cx // k:cx // k + b.shape[1]] = b

    with tempfile.TemporaryDirectory(prefix='plotlook-') as tmp:
        with ThreadPoolExecutor(max(1, workers)) as ex:
            for f in [ex.submit(work, core, tmp) for core in cores]:
                f.result()
    if log and nudged:
        log(f'  {len(nudged)} tile(s) rendered at {", ".join(sorted({f"{dpi + d:g}" for d in nudged}))} dpi, where '
            f'{dpi} left out art')
    if log and split:
        log(f'  {len(split)} tile(s) rendered again in quarters, where no resolution near {dpi} rendered them whole')
    out /= np.minimum(k, H - np.arange(0, H, k)).astype(np.float32)[:, None]
    out /= np.minimum(k, W - np.arange(0, W, k)).astype(np.float32)[None, :]
    return out


def finish(cov, size, paper='white', sharpen=1.5, contrast=0.85):
    """coverage at the reduced size to 8-bit sRGB at the output size: resize, contrast, reflectance, encode, sharpen"""
    import numpy as np
    from PIL import Image
    ow, oh = size
    if cov.shape != (oh, ow):
        cov = np.ascontiguousarray(cov, np.float32)
        img = Image.frombuffer('F', (cov.shape[1], cov.shape[0]), cov, 'raw', 'F', 0, 1)
        cov = np.asarray(img.resize((ow, oh), Image.LANCZOS))
    P = PAPERS[paper]
    chans = P['paper']
    res = np.empty((oh, ow, len(chans)), np.uint8)
    pad = 8 if sharpen else 0
    for r0 in range(0, oh, STRIP):
        r1 = min(oh, r0 + STRIP)
        a0, a1 = max(0, r0 - pad), min(oh, r1 + pad)
        c = np.clip(cov[a0:a1], 0, 1)
        if contrast != 1:
            c = np.power(c, contrast)
        for i, pw in enumerate(chans):
            e = srgb(pw - c * (pw - P['toner']))
            if sharpen:
                d = 1 - e
                d = d + sharpen * (d - blur(d))
                e = np.clip(1 - d, srgb(np.float64(P['toner'])), srgb(np.float64(pw)))
            res[r0:r1, :, i] = np.round(e[r0 - a0:r1 - a0] * 255)
    return res[:, :, 0] if len(chans) == 1 else res


# ---------------------------------------------------------------- one file
def parse_pages(spec, n):
    if not spec:
        return list(range(1, n + 1))
    got = []
    for part in spec.split(','):
        a, _, b = part.partition('-')
        got += range(int(a), int(b or a) + 1)
    bad = [p for p in got if not 1 <= p <= n]
    if bad:
        raise SystemExit(f'plotlook: no page {bad[0]}; the document has {n}')
    return got


def size_label(opts):
    if opts.long:
        return f'{opts.long}px'
    if opts.dpi:
        return f'{opts.dpi:g}dpi'
    p = ALIASES.get(opts.preset, opts.preset)
    return {'portfolio': '11x17', 'plot': '300dpi'}.get(p, p)


def out_name(stem, page, npages, opts):
    crop = '-crop-' + '-'.join(f'{v:g}' for v in opts.crop) if opts.crop else ''
    name = getattr(opts, 'preset_name', None)
    return (f'{stem}{f"-p{page}" if npages > 1 else ""}-{size_label(opts)}{f"-{name}" if name else ""}'
            f'{"-bond" if opts.paper == "bond" else ""}{"-colour" if getattr(opts, "colour", False) else ""}{crop}.png')


def plotlook(src, opts, log=stderr_log, write=write_file, device_dpi=None):
    """render the file's pages; the PNGs (and JPEGs) written. device_dpi: a function of the file giving its device dpi
    when opts.device_dpi is not set"""
    from PIL import Image
    require_poppler()
    src = Path(src).absolute()
    dev_dpi = int(getattr(opts, 'device_dpi', None) or (device_dpi(src) if device_dpi else DEVICE_DPI))
    gain_px = opts.gain / (25400 / dev_dpi)
    sizes = pages(src)
    dest = Path(opts.out).absolute() if opts.out else src.parent
    written = []
    for p in parse_pages(opts.pages, len(sizes)):
        t0 = time.time()
        wpt, hpt = sizes[p - 1]
        Wd, Hd = device_px(wpt, dev_dpi), device_px(hpt, dev_dpi)
        if opts.crop:
            x0, y0, x1, y1 = opts.crop
            if not (0 <= x0 < x1 <= wpt / 72 + 1e-6 and 0 <= y0 < y1 <= hpt / 72 + 1e-6):
                raise SystemExit(f'plotlook: --crop {opts.crop} is not inside page {p}, {wpt / 72:g} x {hpt / 72:g} in')
            rx0, ry0 = round(x0 * dev_dpi), round(y0 * dev_dpi)
            region = (rx0, ry0, min(Wd, round(x1 * dev_dpi)) - rx0, min(Hd, round(y1 * dev_dpi)) - ry0)
            w_in, h_in = x1 - x0, y1 - y0
        else:
            region, w_in, h_in = (0, 0, Wd, Hd), wpt / 72, hpt / 72
        ow, oh, odpi = out_size(w_in, h_in, opts.preset, opts.long, opts.dpi)
        k = max(1, int(min(region[2] / ow, region[3] / oh) + 1e-9))
        cov = device_reduce(src, p, dev_dpi, region, k, gain_px, opts.tile, opts.workers, log)
        img = finish(cov, (ow, oh), opts.paper, opts.sharpen, opts.contrast)
        del cov
        if getattr(opts, 'colour', False):
            reg_in = (region[0] / dev_dpi, region[1] / dev_dpi, w_in, h_in)
            with tempfile.TemporaryDirectory(prefix='plotlook-') as tmp:
                img = tinted(img, colour_layer(src, p, reg_in, (ow, oh), tmp))
        png = dest / out_name(src.stem, p, len(sizes), opts)
        im = Image.fromarray(img)
        buf = io.BytesIO()
        im.save(buf, 'PNG', dpi=(odpi, odpi))
        written.append(write(buf.getvalue(), png))
        if opts.jpeg:
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=92, dpi=(odpi, odpi))
            written.append(write(buf.getvalue(), png.with_suffix('.jpg')))
        if log:
            log(f'{png}  {ow} x {oh} px at {odpi:g} dpi, device {region[2]} x {region[3]} px in blocks of {k}, '
                f'{time.time() - t0:.0f} s')
    return written


def run(src, opts):
    """plotlook() with the log, writer and device dpi the command line set up (opts.quiet, opts.host)"""
    host = getattr(opts, 'host', None)
    return plotlook(src, opts, log=None if getattr(opts, 'quiet', False) else stderr_log,
                    write=getattr(host, 'write', None) or write_file, device_dpi=getattr(host, 'device_dpi', None))
