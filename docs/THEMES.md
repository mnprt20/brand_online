# Storefront Theme System (`docs/THEMES.md`)

## 1. Overview
Each storefront theme is a self-contained folder under `storefront/themes/<key>/`. Adding a new theme requires **zero code changes** to views, models, or URLs—only dropping a valid theme folder into `storefront/themes/<key>/` and running `python manage.py check_themes`.

---

## 2. Folder Layout
```text
storefront/themes/<key>/
├── theme.json
├── base.html
├── home.html
├── product_card.html
└── static/
    └── themes/
        └── <key>/
            ├── style.css
            └── script.js (optional)
```

### `theme.json` Schema
- `key` (`string`): Must match the folder name and regex `^[a-z0-9_-]{2,30}$`.
- `name` (`string`): Display name shown in the public gallery and owner dashboard.
- `description` (`string`): Short summary of the theme's visual style.
- `version` (`integer`): Theme version number (used for PWA Service Worker cache busting).
- `tags` (`list[string]`): Descriptive tags (e.g., `["bistro", "warm", "serif"]`).
- `min_plan` (`string`): `"offline"`, `"franchise"`, or `"online"` (default `"offline"`).
- `palette` (`list[string]`): 3 to 4 `#RRGGBB` hex colors displayed as swatches in the gallery and dashboard.
- `default_brand_color` (`string`): Default `#RRGGBB` hex accent color.
- `original_font` (`string`, optional): Records any external font stack replaced during conversion.

---

## 3. Shared Layer & Required Partials
Every theme's `base.html` extends `storefront/base_shell.html`, which sets `<body data-theme="<key>">`, injects `--brand-color: #RRGGBB`, loads `static/storefront/shared.css` and `static/themes/<key>/style.css`, and includes the Online-plan top bar and closed banner.

Themes **must** include or render the 5 required functional `data-sf` markers:
1. `data-sf="cart-link"` — via `{% include "storefront/partials/_cart_link.html" %}`
2. `data-sf="account-links"` — automatically included by `storefront/base_shell.html` via `storefront/partials/_account_links.html`
3. `data-sf="closed-banner"` — automatically included by `storefront/base_shell.html` via `storefront/partials/_closed_banner.html`
4. `data-sf="category-filter"` — via `{% include "storefront/partials/_category_filter.html" %}`
5. `data-sf="add-to-cart"` — via `{% include "storefront/partials/_add_to_cart_form.html" %}` inside `product_card.html`

---

## 4. Security & Conversion Rules
- **No external dependencies:** No Google Fonts, external stylesheets, external scripts, or external image URLs (only Tailwind CDN in `base_shell.html` is permitted).
- **No unsafe template tags:** Never use `|safe` or `{% autoescape off %}`.
- **No inline JS:** Never use inline `<script>` tags or `on*=` attributes inside theme HTML files.
- **Accessibility:** Every `<img>` tag must include an `alt` attribute.
- **Stylesheet size:** `style.css` must be under 150 KB.

---

## 5. Verification
Run the management command to validate all themes:
```bash
python manage.py check_themes
```
