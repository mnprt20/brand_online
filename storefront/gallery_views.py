from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from storefront.context_processors import build_theme_context_for_store
from storefront.forms import CheckoutForm
from storefront.themes.registry import (
    THEME_KEY_REGEX,
    THEMES_ROOT,
    list_themes,
    load_theme_manifest,
    theme_template,
)
from storefront.themes.sample_data import build_sample_catalogue


def _get_registered_theme_or_404(theme_key: str) -> dict:
    cleaned = (theme_key or '').strip()
    if not THEME_KEY_REGEX.match(cleaned):
        raise Http404("Theme not found.")
    manifest = load_theme_manifest(THEMES_ROOT / cleaned)
    if not manifest:
        raise Http404("Theme not found.")
    return manifest


class PlatformHomeView(View):
    template_name = 'storefront/gallery/platform_home.html'

    def get(self, request):
        themes = list_themes()
        return render(
            request,
            self.template_name,
            {
                'themes': themes,
                'featured_themes': themes[:6],
            },
        )


class ThemeGalleryView(View):
    template_name = 'storefront/gallery/theme_gallery.html'

    def get(self, request):
        themes = list_themes()
        plan_filter = (request.GET.get('plan') or '').strip().lower()
        if plan_filter in ('offline', 'franchise', 'online'):
            themes = [t for t in themes if t.get('min_plan') == plan_filter]
        return render(
            request,
            self.template_name,
            {
                'themes': themes,
                'selected_plan': plan_filter,
            },
        )


class ThemePreviewShellView(View):
    template_name = 'storefront/gallery/theme_preview_shell.html'

    def get(self, request, theme_key):
        theme = _get_registered_theme_or_404(theme_key)
        viewport = (request.GET.get('viewport') or 'desktop').strip().lower()
        if viewport not in ('desktop', 'tablet', 'mobile'):
            viewport = 'desktop'
        return render(
            request,
            self.template_name,
            {
                'theme': theme,
                'viewport': viewport,
                'demo_url': reverse('theme_demo', kwargs={'theme_key': theme['key']}),
            },
        )


@method_decorator(xframe_options_sameorigin, name='dispatch')
class ThemeDemoView(View):
    def get(self, request, theme_key):
        theme = _get_registered_theme_or_404(theme_key)
        brand_color = theme.get('default_brand_color') or '#4f46e5'
        sample_ctx = build_sample_catalogue(
            theme_key=theme['key'],
            brand_color=brand_color,
            selected_category_pk=request.GET.get('category'),
        )
        sample_store = sample_ctx['store']
        sample_ctx['checkout_form'] = CheckoutForm()
        sample_ctx.update(
            build_theme_context_for_store(
                sample_store,
                theme_key_override=theme['key'],
                brand_color_override=brand_color,
            )
        )
        template_name = theme_template(theme['key'], 'home.html')
        return render(request, template_name, sample_ctx)


class UseThemeView(View):
    def get(self, request, theme_key):
        theme = _get_registered_theme_or_404(theme_key)
        if request.user.is_authenticated:
            return redirect(f"{reverse('dashboard:appearance')}?select={theme['key']}")
        return redirect(f"{reverse('accounts:signup')}?theme={theme['key']}")
