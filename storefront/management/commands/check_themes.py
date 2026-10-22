import json
from pathlib import Path
import re
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.test import RequestFactory
from storefront.context_processors import build_theme_context_for_store
from storefront.forms import CheckoutForm
from storefront.themes.registry import (
    HEX_COLOR_REGEX,
    THEMES_ROOT,
    THEME_KEY_REGEX,
    theme_template,
)
from storefront.themes.sample_data import SampleStore, build_sample_catalogue

REQUIRED_MARKERS = [
    'data-sf="cart-link"',
    'data-sf="account-links"',
    'data-sf="closed-banner"',
    'data-sf="category-filter"',
    'data-sf="add-to-cart"',
]

FORBIDDEN_TEMPLATE_PATTERNS = [
    (re.compile(r'\|\s*safe\b'), 'Forbidden |safe filter found'),
    (re.compile(r'\{%\s*autoescape\s+off\s*%\}'), 'Forbidden {% autoescape off %} found'),
    (re.compile(r'\bon[a-z]+\s*=', re.IGNORECASE), 'Forbidden inline on*= event handler found'),
]

EXTERNAL_URL_REGEX = re.compile(r'https?://[^\s"\'<>)]+', re.IGNORECASE)
ALLOWED_EXTERNAL_PREFIXES = (
    'https://cdn.tailwindcss.com',
)


def validate_all_themes() -> list[str]:
    errors = []
    if not THEMES_ROOT.exists():
        errors.append(f"Themes directory does not exist: {THEMES_ROOT}")
        return errors

    theme_dirs = [
        d for d in sorted(THEMES_ROOT.iterdir(), key=lambda p: p.name)
        if d.is_dir() and not d.name.startswith('_') and not d.name.startswith('.')
    ]
    if not theme_dirs:
        errors.append("No themes found in storefront/themes/.")
        return errors

    rf = RequestFactory()

    for theme_dir in theme_dirs:
        folder_key = theme_dir.name
        if not THEME_KEY_REGEX.match(folder_key):
            errors.append(f"[{folder_key}] Folder name does not match ^[a-z0-9_-]{{2,30}}$.")

        manifest_file = theme_dir / 'theme.json'
        if not manifest_file.is_file():
            errors.append(f"[{folder_key}] Missing theme.json.")
            continue

        try:
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        except Exception as exc:
            errors.append(f"[{folder_key}] Invalid JSON in theme.json: {exc}")
            continue

        required_fields = (
            'key',
            'name',
            'description',
            'version',
            'tags',
            'min_plan',
            'palette',
            'default_brand_color',
        )
        for field in required_fields:
            if field not in manifest:
                errors.append(f"[{folder_key}] Missing required field '{field}' in theme.json.")

        if manifest.get('key') != folder_key:
            errors.append(
                f"[{folder_key}] theme.json key '{manifest.get('key')}' does not match folder name '{folder_key}'."
            )

        if not isinstance(manifest.get('version'), int):
            errors.append(f"[{folder_key}] theme.json 'version' must be an integer.")

        if manifest.get('min_plan') not in ('offline', 'franchise', 'online'):
            errors.append(f"[{folder_key}] theme.json 'min_plan' must be offline, franchise, or online.")

        palette = manifest.get('palette')
        if not isinstance(palette, list) or not (3 <= len(palette) <= 4):
            errors.append(f"[{folder_key}] theme.json 'palette' must be a list of 3 to 4 hex colors.")
        else:
            for c in palette:
                if not HEX_COLOR_REGEX.match(str(c)):
                    errors.append(f"[{folder_key}] Invalid palette hex color '{c}'.")

        default_bc = str(manifest.get('default_brand_color', ''))
        if not HEX_COLOR_REGEX.match(default_bc):
            errors.append(f"[{folder_key}] Invalid default_brand_color '{default_bc}'.")

        # Required files
        base_html = theme_dir / 'base.html'
        home_html = theme_dir / 'home.html'
        card_html = theme_dir / 'product_card.html'
        style_css = theme_dir / 'static' / 'themes' / folder_key / 'style.css'

        for req_path, label in [
            (base_html, 'base.html'),
            (home_html, 'home.html'),
            (card_html, 'product_card.html'),
            (style_css, f"static/themes/{folder_key}/style.css"),
        ]:
            if not req_path.is_file():
                errors.append(f"[{folder_key}] Missing required file {label}.")

        if style_css.is_file():
            size_bytes = style_css.stat().st_size
            if size_bytes > 150 * 1024:
                errors.append(f"[{folder_key}] style.css exceeds 150 KB ({size_bytes} bytes).")

        # Inspect all HTML and CSS files in the theme folder for security & conversion rules
        for file_path in theme_dir.rglob('*'):
            if not file_path.is_file() or file_path.suffix.lower() not in ('.html', '.css', '.js'):
                continue
            content = file_path.read_text(encoding='utf-8', errors='replace')
            rel_name = file_path.relative_to(theme_dir)

            for regex, msg in FORBIDDEN_TEMPLATE_PATTERNS:
                if regex.search(content):
                    errors.append(f"[{folder_key}/{rel_name}] {msg}")

            if file_path.suffix.lower() == '.html':
                # Check for inline <script> inside theme HTML files
                if re.search(r'<script\b', content, re.IGNORECASE):
                    errors.append(f"[{folder_key}/{rel_name}] Inline <script> tag is not allowed in theme HTML.")

                # Check that every <img ...> tag has an alt= attribute
                for img_match in re.finditer(r'<img\b[^>]*>', content, re.IGNORECASE):
                    img_tag = img_match.group(0)
                    if not re.search(r'\balt\s*=', img_tag, re.IGNORECASE):
                        errors.append(f"[{folder_key}/{rel_name}] <img> tag missing alt attribute: {img_tag}")

            for url_match in EXTERNAL_URL_REGEX.finditer(content):
                ext_url = url_match.group(0)
                if not any(ext_url.startswith(prefix) for prefix in ALLOWED_EXTERNAL_PREFIXES):
                    errors.append(f"[{folder_key}/{rel_name}] Disallowed external URL: {ext_url}")

        # Smoke render home.html with sample Online store (online_ordering_open=False so closed-banner also renders)
        if base_html.is_file() and home_html.is_file() and card_html.is_file():
            try:
                sample_ctx = build_sample_catalogue(
                    theme_key=folder_key,
                    brand_color=default_bc or '#4f46e5',
                )
                # Use an active real-mode simulation with online_ordering_open=False so all 5 markers appear
                test_store = SampleStore(
                    name='Validation Store',
                    slug='validation-store',
                    template_key=folder_key,
                    theme_color=default_bc or '#4f46e5',
                    online_ordering_open=False,
                    has_online=True,
                )
                sample_ctx['store'] = test_store
                sample_ctx['is_demo'] = True
                sample_ctx['checkout_form'] = CheckoutForm()
                sample_ctx.update(build_theme_context_for_store(test_store, theme_key_override=folder_key))

                request = rf.get(f'/themes/{folder_key}/demo/')
                tpl_name = theme_template(folder_key, 'home.html')
                rendered = render_to_string(tpl_name, sample_ctx, request=request)

                for marker in REQUIRED_MARKERS:
                    if marker not in rendered:
                        errors.append(
                            f"[{folder_key}] Rendered home.html is missing required marker: {marker}"
                        )
            except Exception as exc:
                errors.append(f"[{folder_key}] Failed to render home.html: {exc}")

    return errors


class Command(BaseCommand):
    help = 'Validates all storefront themes in storefront/themes/ against manifest, security, and marker rules.'

    def handle(self, *args, **options):
        errors = validate_all_themes()
        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(f"ERROR: {err}"))
            raise CommandError(f"Theme validation failed with {len(errors)} error(s).")
        self.stdout.write(self.style.SUCCESS("All themes validated successfully (0 errors)."))
