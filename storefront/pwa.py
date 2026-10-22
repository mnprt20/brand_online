import io
import json
from PIL import Image, ImageDraw, ImageFont
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from storefront.auth import OnlineStoreMixin


def _parse_hex_color(hex_str, default=(79, 70, 229)):
    cleaned = (hex_str or '').strip().lstrip('#')
    if len(cleaned) == 6:
        try:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16),
            )
        except ValueError:
            return default
    if len(cleaned) == 3:
        try:
            return (
                int(cleaned[0] * 2, 16),
                int(cleaned[1] * 2, 16),
                int(cleaned[2] * 2, 16),
            )
        except ValueError:
            return default
    return default


def generate_pwa_icon_png(store, size: int) -> bytes:
    """
    Generate a square PNG icon of `(size, size)` for the given store.
    If `store.logo` is uploaded and readable, resize it with Pillow.
    Otherwise, generate a clean fallback icon using `store.theme_color`
    and the first letter of `store.name`.
    """
    img = None
    if store.logo:
        try:
            with Image.open(store.logo) as uploaded:
                converted = uploaded.convert('RGBA')
                img = converted.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            img = None

    if img is None:
        bg_rgb = _parse_hex_color(getattr(store, 'theme_color', '#4f46e5'))
        img = Image.new('RGBA', (size, size), color=(*bg_rgb, 255))
        draw = ImageDraw.Draw(img)
        letter = ((store.name or 'S').strip()[:1] or 'S').upper()
        try:
            font = ImageFont.load_default(size=max(24, int(size * 0.5)))
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), letter, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (size - text_w) / 2 - bbox[0]
        y = (size - text_h) / 2 - bbox[1]
        draw.text((x, y), letter, fill=(255, 255, 255, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


class StoreManifestView(OnlineStoreMixin, View):
    def get(self, request, store_slug):
        store_scope = reverse('storefront:detail', kwargs={'store_slug': self.store.slug})
        theme_color = self.store.theme_color or '#4f46e5'
        manifest = {
            'name': self.store.name,
            'short_name': self.store.name[:30],
            'description': self.store.description or f"Order online from {self.store.name}",
            'start_url': store_scope,
            'scope': store_scope,
            'display': 'standalone',
            'theme_color': theme_color,
            'background_color': '#ffffff',
            'icons': [
                {
                    'src': reverse('storefront:pwa_icon_192', kwargs={'store_slug': self.store.slug}),
                    'sizes': '192x192',
                    'type': 'image/png',
                    'purpose': 'any maskable',
                },
                {
                    'src': reverse('storefront:pwa_icon_512', kwargs={'store_slug': self.store.slug}),
                    'sizes': '512x512',
                    'type': 'image/png',
                    'purpose': 'any maskable',
                },
            ],
        }
        return HttpResponse(
            json.dumps(manifest, indent=2),
            content_type='application/manifest+json',
        )


class StoreIcon192View(OnlineStoreMixin, View):
    def get(self, request, store_slug):
        png_bytes = generate_pwa_icon_png(self.store, 192)
        return HttpResponse(png_bytes, content_type='image/png')


class StoreIcon512View(OnlineStoreMixin, View):
    def get(self, request, store_slug):
        png_bytes = generate_pwa_icon_png(self.store, 512)
        return HttpResponse(png_bytes, content_type='image/png')


class StoreServiceWorkerView(OnlineStoreMixin, View):
    def get(self, request, store_slug):
        from storefront.themes.registry import get_theme, sanitize_brand_color

        scope_path = reverse('storefront:detail', kwargs={'store_slug': self.store.slug})
        offline_url = reverse('storefront:pwa_offline', kwargs={'store_slug': self.store.slug})
        manifest_url = reverse('storefront:pwa_manifest', kwargs={'store_slug': self.store.slug})
        icon_192_url = reverse('storefront:pwa_icon_192', kwargs={'store_slug': self.store.slug})
        icon_512_url = reverse('storefront:pwa_icon_512', kwargs={'store_slug': self.store.slug})

        theme = get_theme(self.store.template_key)
        theme_key = theme['key']
        theme_version = theme.get('version', 1)
        brand_color = sanitize_brand_color(
            self.store.theme_color,
            fallback=theme.get('default_brand_color') or '#4f46e5',
        ).lstrip('#').lower()
        cache_name = f"store-pwa-{self.store.slug}-{theme_key}-v{theme_version}-{brand_color}"

        sw_script = f"""const CACHE_NAME = {json.dumps(cache_name)};
const OFFLINE_URL = {json.dumps(offline_url)};
const PRECACHE_URLS = [
  OFFLINE_URL,
  {json.dumps(manifest_url)},
  {json.dumps(icon_192_url)},
  {json.dumps(icon_512_url)}
];

const NEVER_CACHE_SEGMENTS = [
  '/account/',
  '/cart/',
  '/checkout/',
  '/online-checkout/',
  '/order/',
  '/dashboard/'
];

function shouldBypassCache(request) {{
  if (request.method !== 'GET') {{
    return true;
  }}
  const url = new URL(request.url);
  for (let i = 0; i < NEVER_CACHE_SEGMENTS.length; i++) {{
    if (url.pathname.indexOf(NEVER_CACHE_SEGMENTS[i]) !== -1) {{
      return true;
    }}
  }}
  return false;
}}

self.addEventListener('install', (event) => {{
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
}});

self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => {{
          if (key !== CACHE_NAME) {{
            return caches.delete(key);
          }}
          return null;
        }})
      )
    )
  );
  self.clients.claim();
}});

self.addEventListener('fetch', (event) => {{
  if (shouldBypassCache(event.request)) {{
    return;
  }}
  event.respondWith(
    fetch(event.request).catch(() => caches.match(OFFLINE_URL))
  );
}});
"""
        response = HttpResponse(sw_script, content_type='application/javascript')
        response['Service-Worker-Allowed'] = scope_path
        return response


class StoreOfflineView(OnlineStoreMixin, View):
    template_name = 'storefront/offline.html'

    def get(self, request, store_slug):
        return render(
            request,
            self.template_name,
            self.get_base_context(),
        )
