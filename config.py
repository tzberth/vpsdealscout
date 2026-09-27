# ::ILANG [TYPE:module][ROLE:read-site-config]
# ::RULE{.ilang/site.ilang is the single source for provider and site settings}
# ::BOUNDARY{never:duplicate provider lists in Python|scope:permanent}
from pathlib import Path
import re

CONFIG = Path(__file__).parent / '.ilang' / 'site.ilang'


def load_config():
    raw = CONFIG.read_text(encoding='utf-8')
    state = re.search(r'::STATE\{@SITE,\s*(.*?)\}', raw)
    if not state:
        raise ValueError('Missing @SITE in site.ilang')
    site = dict(re.findall(r'(brand|niche|domain|locale):([^,}]+)', state.group(1)))
    site = {key: value.strip() for key, value in site.items()}
    providers = []
    inside = False
    for line in raw.splitlines():
        if line.startswith('::MODULE{PROVIDERS'):
            inside = True
            continue
        if inside and line.startswith('::MODULE{'):
            break
        if inside and '|' in line:
            parts = [part.strip() for part in line.split('|')]
            if len(parts) >= 4 and parts[1].startswith('https://') and parts[2].startswith('https://'):
                kind = parts[4] if len(parts) > 4 else 'pricing'
                mode = parts[5] if len(parts) > 5 else 'dual'
                retention = parts[6] if len(parts) > 6 else ''
                if kind not in ('promotion', 'pricing'):
                    raise ValueError(f'Invalid source kind for {parts[0]}')
                if mode not in ('dual', 'single'):
                    raise ValueError(f'Invalid page mode for {parts[0]}')
                if retention not in ('', 'retain'):
                    raise ValueError(f'Invalid retention rule for {parts[0]}')
                providers.append(dict(name=parts[0], website=parts[1], source=parts[2], affiliate=parts[3], kind=kind, mode=mode, retain=retention == 'retain'))
    if not providers:
        raise ValueError('No providers in site.ilang')
    return site, providers
