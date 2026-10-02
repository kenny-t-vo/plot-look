"""Saved presets and the settings they hold.

A setting is a dict: one of size (a key of PRESETS), long (px) or dpi set, the others None; sharpen, contrast, paper,
gain; out, a folder or None for beside each drawing. Saved presets live in presets.json in
~/Library/Application Support/Plot Look, or in $PLOTLOOK_HOME, as
{NAME: {"size": KEY | "long": PX | "dpi": N, "sharpen", "contrast", "paper", "gain", "out"?}}.
"""
import json, os, re
from pathlib import Path

from .render import ALIASES, GAIN_UM, PAPERS, PRESETS

DEFAULTS = {'sharpen': 1.5, 'contrast': 0.85, 'paper': 'white', 'gain': GAIN_UM}
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,31}$')


def home():
    return Path(os.environ.get('PLOTLOOK_HOME') or Path.home() / 'Library' / 'Application Support' / 'Plot Look')


def read_json(name):
    path = home() / name
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise SystemExit(f'plotlook: {path} is not JSON: {e}')
    if not isinstance(data, dict):
        raise SystemExit(f'plotlook: {path} does not hold an object')
    return data


def write_json(name, data):
    home().mkdir(parents=True, exist_ok=True)
    (home() / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')


def load_presets():
    return read_json('presets.json')


def base_settings(size='portfolio', out=None):
    return dict(size=size, long=None, dpi=None, out=out, **DEFAULTS)


def from_saved(d):
    s = base_settings(out=d.get('out'))
    if d.get('long'):
        s.update(size=None, long=int(d['long']))
    elif d.get('dpi'):
        s.update(size=None, dpi=float(d['dpi']))
    else:
        s['size'] = ALIASES.get(d.get('size', 'portfolio'), d.get('size', 'portfolio'))
    s.update({k: d[k] for k in DEFAULTS if k in d})
    return s


def to_saved(s):
    d = {'size': s['size']} if s['size'] else {'long': s['long']} if s['long'] else {'dpi': s['dpi']}
    d.update({k: s[k] for k in DEFAULTS})
    if s['out']:
        d['out'] = s['out']
    return d


def check(s):
    """refuse settings out of range, from the command line or presets.json"""
    if s['size'] and s['size'] not in PRESETS:
        raise SystemExit(f'plotlook: no preset {s["size"]}; one of {", ".join(PRESETS)}')
    if not 0 <= s['sharpen'] <= 2:
        raise SystemExit('plotlook: --sharpen goes from 0 to 2')
    if s['contrast'] <= 0:
        raise SystemExit('plotlook: --contrast is over 0')
    if s['paper'] not in PAPERS:
        raise SystemExit(f'plotlook: no paper {s["paper"]}; one of {", ".join(PAPERS)}')
    return s


def name_error(name):
    if not NAME.match(name):
        return 'A preset\'s name is 1 to 32 letters, digits and hyphens, starting with a letter or digit.'
    if name.lower() in set(PRESETS) | set(ALIASES):
        return f'{name} is a built-in preset\'s name.'


def save_preset(name, s):
    err = name_error(name)
    if err:
        raise SystemExit(f'plotlook: {err}')
    saved = load_presets()
    saved[name] = to_saved(s)
    write_json('presets.json', saved)


def remove_presets(names):
    saved = load_presets()
    missing = [n for n in names if n not in saved]
    if missing:
        raise SystemExit(f'plotlook: no saved preset {missing[0]}')
    write_json('presets.json', {k: v for k, v in saved.items() if k not in names})


def describe(s):
    size = s['size'] or (f'{s["long"]} px long' if s['long'] else f'{s["dpi"]:g} dpi')
    return (f'{size}, sharpen {s["sharpen"]:g}, contrast {s["contrast"]:g}, {s["paper"]} paper, '
            f'toner spread {s["gain"]:g} um' + (f', into {s["out"]}' if s['out'] else ''))


def override(s, opts):
    """the settings given on the command line over s"""
    for k in (*DEFAULTS, 'out'):
        if getattr(opts, k, None) is not None:
            s[k] = getattr(opts, k)
    if s['out']:
        s['out'] = str(Path(s['out']).expanduser().absolute())
    return s


def resolve(opts):
    """(settings, saved preset name or None) from --preset, --long, --dpi and the other options"""
    s, name = base_settings(), None
    if opts.preset:
        key = ALIASES.get(opts.preset, opts.preset)
        if key in PRESETS:
            s['size'] = key
        else:
            saved = load_presets()
            if opts.preset not in saved:
                raise SystemExit(f'plotlook: no preset {opts.preset}; one of {", ".join([*PRESETS, *saved])}')
            s, name = from_saved(saved[opts.preset]), opts.preset
    if opts.long or opts.dpi:
        s.update(size=None, long=opts.long, dpi=opts.dpi)
    return check(override(s, opts)), name


def apply(opts, s, name):
    opts.preset, opts.long, opts.dpi = s['size'], s['long'], s['dpi']
    for k in (*DEFAULTS, 'out'):
        setattr(opts, k, s[k])
    opts.preset_name = name
    return opts
