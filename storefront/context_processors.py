from storefront.themes.registry import (
    DEFAULT_THEME_KEY,
    get_theme,
    resolve_theme_key,
    sanitize_brand_color,
)


def build_theme_context_for_store(store, theme_key_override=None, brand_color_override=None):
    raw_key = theme_key_override or getattr(store, 'template_key', None) or DEFAULT_THEME_KEY
    theme = get_theme(raw_key)
    resolved_key = theme['key']
    default_color = theme.get('default_brand_color') or '#4f46e5'
    raw_color = (
        brand_color_override
        or getattr(store, 'theme_color', None)
        or default_color
    )
    brand_color = sanitize_brand_color(raw_color, fallback=default_color)
    return {
        'active_theme': theme,
        'active_theme_key': resolved_key,
        'active_theme_base': f"storefront/themes/{resolved_key}/base.html",
        'active_theme_card': f"storefront/themes/{resolved_key}/product_card.html",
        'active_theme_css': f"themes/{resolved_key}/style.css",
        'brand_color': brand_color,
    }


def storefront_theme_context(request):
    """
    Provides default theme variables so any template extending `active_theme_base`
    or `storefront/base_shell.html` always has safe defaults even if rendered directly.
    """
    theme = get_theme(DEFAULT_THEME_KEY)
    return {
        'active_theme': theme,
        'active_theme_key': DEFAULT_THEME_KEY,
        'active_theme_base': f"storefront/themes/{DEFAULT_THEME_KEY}/base.html",
        'active_theme_card': f"storefront/themes/{DEFAULT_THEME_KEY}/product_card.html",
        'active_theme_css': f"themes/{DEFAULT_THEME_KEY}/style.css",
        'brand_color': sanitize_brand_color('#4f46e5'),
    }
