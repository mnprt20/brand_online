from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


from storefront.gallery_views import (
    PlatformHomeView,
    ThemeDemoView,
    ThemeGalleryView,
    ThemePreviewShellView,
    UseThemeView,
)


urlpatterns = [
    path('', PlatformHomeView.as_view(), name='root'),
    path('themes/', ThemeGalleryView.as_view(), name='theme_gallery'),
    path('themes/<slug:theme_key>/', ThemePreviewShellView.as_view(), name='theme_preview'),
    path('themes/<slug:theme_key>/demo/', ThemeDemoView.as_view(), name='theme_demo'),
    path('themes/<slug:theme_key>/use/', UseThemeView.as_view(), name='theme_use'),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('dashboard/', include('stores.urls')),
    path('s/', include('storefront.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
