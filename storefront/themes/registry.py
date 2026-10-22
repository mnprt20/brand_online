import json
from pathlib import Path
import re
from django.conf import settings
from django.template.loader import select_template
from stores.models import Plan

DEFAULT_THEME_KEY = 'classic'
THEME_KEY_REGEX = re.compile(r'^[a-z0-9_-]{2,30}$')
HEX_COLOR_REGEX = re.compile(r'^#[0-9A-Fa-f]{6}$')

PLAN_RANK = {
    Plan.SLUG_OFFLINE: 1,
    Plan.SLUG_FRANCHISE: 2,
    Plan.SLUG_ONLINE: 3,
}

THEMES_ROOT = Path(settings.BASE_DIR) / 'storefront' / 'themes'


def is_valid_hex_color(value: str) -> bool:
    return bool(HEX_COLOR_REGEX.match((value or '').strip()))


def sanitize_brand_color(value: str, fallback: str = '#4f46e5') -> str:
    cleaned = (value or '').strip()
    if is_valid_hex_color(cleaned):
        return cleaned
    if is_valid_hex_color(fallback):
        return fallback
    return '#4f46e5'


def load_theme_manifest(theme_dir: Path) -> dict | None:
    manifest_path = theme_dir / 'theme.json'
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    key = data.get('key', '')
    if key != theme_dir.name or not THEME_KEY_REGEX.match(str(key)):
        return None
    data.setdefault('name', key.replace('_', ' ').replace('-', ' ').title())
    data.setdefault('description', '')
    data.setdefault('version', 1)
    data.setdefault('tags', [])
    data.setdefault('min_plan', Plan.SLUG_OFFLINE)
    data.setdefault('palette', ['#4f46e5', '#1e293b', '#f8fafc'])
    data.setdefault('default_brand_color', '#4f46e5')
    return data


def list_themes() -> list[dict]:
    if not THEMES_ROOT.exists():
        return []
    themes = []
    for child in sorted(THEMES_ROOT.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith('_') or child.name.startswith('.'):
            continue
        manifest = load_theme_manifest(child)
        if manifest:
            themes.append(manifest)
    # Sort with classic, minimal, bold first for predictable ordering, then alphabetical
    priority = {'classic': 0, 'minimal': 1, 'bold': 2}
    themes.sort(key=lambda t: (priority.get(t['key'], 10), t['key']))
    return themes


def get_theme(theme_key: str) -> dict:
    cleaned_key = (theme_key or '').strip()
    if THEME_KEY_REGEX.match(cleaned_key):
        theme_dir = THEMES_ROOT / cleaned_key
        manifest = load_theme_manifest(theme_dir)
        if manifest:
            return manifest
    default_dir = THEMES_ROOT / DEFAULT_THEME_KEY
    default_manifest = load_theme_manifest(default_dir)
    if default_manifest:
        return default_manifest
    return {
        'key': DEFAULT_THEME_KEY,
        'name': 'Classic',
        'description': 'Warm serif heritage catalogue layout.',
        'version': 1,
        'tags': ['classic', 'serif', 'warm'],
        'min_plan': Plan.SLUG_OFFLINE,
        'palette': ['#92400e', '#fffbeb', '#0f172a'],
        'default_brand_color': '#92400e',
    }


def resolve_theme_key(theme_key: str) -> str:
    return get_theme(theme_key)['key']


def is_theme_allowed_for_plan(theme: dict | str, plan_or_slug) -> bool:
    if isinstance(theme, str):
        theme = get_theme(theme)
    min_plan = (theme.get('min_plan') or Plan.SLUG_OFFLINE).lower()
    if isinstance(plan_or_slug, str):
        store_plan_slug = plan_or_slug.lower()
    elif hasattr(plan_or_slug, 'slug'):
        store_plan_slug = (plan_or_slug.slug or Plan.SLUG_OFFLINE).lower()
    else:
        store_plan_slug = Plan.SLUG_OFFLINE
    required_rank = PLAN_RANK.get(min_plan, 1)
    store_rank = PLAN_RANK.get(store_plan_slug, 1)
    return store_rank >= required_rank


def theme_template(theme_key: str, page_name: str):
    """
    Resolve a template for `theme_key` and `page_name` (e.g., 'home.html', 'checkout.html').
    Tries:
      1. storefront/themes/<resolved_key>/<page_name>
      2. storefront/shared/<page_name>
      3. storefront/themes/classic/<page_name>
    Returns the resolved template name string.
    """
    resolved_key = resolve_theme_key(theme_key)
    candidates = [
        f"storefront/themes/{resolved_key}/{page_name}",
        f"storefront/shared/{page_name}",
        f"storefront/themes/{DEFAULT_THEME_KEY}/{page_name}",
    ]
    selected = select_template(candidates)
    return selected.template.name
