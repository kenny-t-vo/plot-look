import numpy as np

from plotlook import render
from pdfs import hatch, mix_pdf, needs, page_pdf


def test_sizes():
    """portfolio fits 11 x 17 in at 300 dpi and 4k (web) and 1440p fit 3840 x 2160 and 2560 x 1440 px, turned to the
    page; plot is the page at 300 dpi, and --long and --dpi set a size"""
    o = render.out_size
    assert o(11, 17, 'portfolio') == (3300, 5100, 300.0) and o(36, 24, 'portfolio') == (4950, 3300, 300.0)
    assert o(36, 24, '4k')[:2] == (3240, 2160) == o(36, 24, 'web')[:2] and o(9, 16, '4k')[:2] == (2160, 3840)
    assert o(17, 11, '1440p')[:2] == (2225, 1440) and o(42, 56, '1440p')[:2] == (1440, 1920)
    assert o(40, 10, '1440p')[:2] == (2560, 640)
    assert o(36, 24, 'plot') == (10800, 7200, 300.0)
    assert o(36, 24, long=1000)[:2] == (1000, 667) and o(36, 24, dpi=150) == (5400, 3600, 150.0)


def test_linear_light():
    """one black device pixel in a 4 x 4 block averages to reflectance 0.9375, sRGB 248, lighter than the gamma-space
    mean's 239"""
    one = np.zeros((4, 4), np.float32)
    one[1, 2] = 1
    m = render.block_means(one, 4)
    v = render.finish(m, (1, 1), sharpen=0, contrast=1.0)
    assert abs(1 - float(m[0, 0]) - 0.9375) < 1e-6 and int(v[0, 0]) == 248 and round(255 * 15 / 16) == 239


def test_filters():
    """the 3 x 3 maximum and the sigma 1 blur repeat the edge pixels, and the blur keeps a flat field flat"""
    a = np.zeros((5, 6), np.float32)
    a[0, 0] = 1
    m = render.max3(a)
    assert m[:2, :2].all() and m.sum() == 4
    assert np.allclose(render.blur(np.full((7, 9), 0.3, np.float32)), 0.3, atol=1e-6)
    b = render.blur(np.pad(np.ones((1, 1), np.float32), 6))
    assert abs(float(b.sum()) - 1) < 1e-5 and abs(float(b[6, 6]) - 0.3989 ** 2 / 0.99993 ** 2) < 1e-3


@needs('pdftoppm')
def test_toner_spread(tmp_path):
    """after the toner spread a 0.03 pt hatch at 1 mm covers about 11 percent and a 0.2 pt one about 15 (poppler
    draws a 0.2 pt line 1 or 2 px wide, 13.4 percent), and a flat K25 stays 25"""
    gain = render.GAIN_UM / (25400 / 600)
    cov = {}
    for wt in (0.03, 0.2):
        f = page_pdf(tmp_path / f'h{wt}.pdf', hatch(wt))
        cov[wt] = float(render.spread(render.render_tile(f, 1, 600, 0, 0, 600, 600, tmp_path), gain)[50:550, 12:578].mean())
    k25 = page_pdf(tmp_path / 'k25.pdf', b'0.75 g 0 0 72 72 re f')
    c25 = float(render.spread(render.render_tile(k25, 1, 600, 0, 0, 600, 600, tmp_path), gain)[50:550, 50:550].mean())
    assert abs(cov[0.03] - 0.11) < 0.015 and abs(cov[0.2] - 0.15) < 0.02 and abs(c25 - 0.25) < 0.01, (cov, c25)


@needs('pdftoppm')
def test_tiles(tmp_path):
    """a page rendered in 97 px tiles, with their margins for the spread, matches it rendered whole"""
    mix = mix_pdf(tmp_path / 'mix.pdf')
    gain = render.GAIN_UM / (25400 / 600)
    W, H = render.device_px(216, 600), render.device_px(144, 600)
    whole = render.device_reduce(mix, 1, 600, (0, 0, W, H), 3, gain, tile=100000, workers=1)
    tiled = render.device_reduce(mix, 1, 600, (0, 0, W, H), 3, gain, tile=97, workers=4)
    assert whole.shape == tiled.shape == (H // 3, W // 3) and float(np.abs(whole - tiled).max()) < 1e-5
