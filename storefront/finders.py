from pathlib import Path
from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder
from django.core.files.storage import FileSystemStorage


class ThemeStaticFilesFinder(BaseFinder):
    """
    Finds static files inside `storefront/themes/<key>/static/` so each theme
    folder is completely self-contained.
    """

    def _get_storages(self):
        themes_root = Path(settings.BASE_DIR) / 'storefront' / 'themes'
        if not themes_root.exists():
            return []
        storages = []
        for theme_dir in sorted(themes_root.iterdir(), key=lambda p: p.name):
            static_dir = theme_dir / 'static'
            if theme_dir.is_dir() and static_dir.is_dir():
                storage = FileSystemStorage(location=str(static_dir))
                storage.prefix = ''
                storages.append(storage)
        return storages

    def find(self, path, all=False, **kwargs):
        matches = []
        for storage in self._get_storages():
            if storage.exists(path):
                matched_path = storage.path(path)
                if not all:
                    return matched_path
                matches.append(matched_path)
        return matches

    def list(self, ignore_patterns):
        from django.contrib.staticfiles import utils

        for storage in self._get_storages():
            if storage.exists(''):
                for path in utils.get_files(storage, ignore_patterns):
                    yield path, storage
