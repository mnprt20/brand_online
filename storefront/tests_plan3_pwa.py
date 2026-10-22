import io
import json
import shutil
import tempfile
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from stores.models import Membership, Plan, Store

User = get_user_model()


class Plan3PWATests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.temp_media)
        self.override.enable()

        self.plan_offline, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_OFFLINE,
            defaults={'name': 'Offline Catalogue', 'max_users': 1},
        )
        self.plan_franchise, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_FRANCHISE,
            defaults={'name': 'Franchise', 'max_users': 2},
        )
        self.plan_online, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_ONLINE,
            defaults={'name': 'Online App', 'max_users': 5},
        )

        self.owner_online = User.objects.create_user(
            username='pwa_owner_online',
            password='ComplexPassword123!',
        )
        self.owner_offline = User.objects.create_user(
            username='pwa_owner_offline',
            password='ComplexPassword123!',
        )
        self.owner_franchise = User.objects.create_user(
            username='pwa_owner_franchise',
            password='ComplexPassword123!',
        )

        self.online_store = Store.objects.create(
            name='Sunrise Bakery App',
            slug='sunrise-bakery',
            owner=self.owner_online,
            plan=self.plan_online,
            theme_color='#e11d48',
        )
        Membership.objects.get_or_create(
            user=self.owner_online,
            store=self.online_store,
            defaults={'role': Membership.ROLE_OWNER},
        )

        self.offline_store = Store.objects.create(
            name='Corner Offline Shop',
            slug='corner-offline',
            owner=self.owner_offline,
            plan=self.plan_offline,
        )
        Membership.objects.get_or_create(
            user=self.owner_offline,
            store=self.offline_store,
            defaults={'role': Membership.ROLE_OWNER},
        )

        self.franchise_store = Store.objects.create(
            name='City Franchise Hub',
            slug='city-franchise',
            owner=self.owner_franchise,
            plan=self.plan_franchise,
        )
        Membership.objects.get_or_create(
            user=self.owner_franchise,
            store=self.franchise_store,
            defaults={'role': Membership.ROLE_OWNER},
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_pwa_endpoints_return_404_on_plan1_and_plan2_stores(self):
        client = Client()
        for store in (self.offline_store, self.franchise_store):
            urls = [
                reverse('storefront:pwa_manifest', kwargs={'store_slug': store.slug}),
                reverse('storefront:pwa_icon_192', kwargs={'store_slug': store.slug}),
                reverse('storefront:pwa_icon_512', kwargs={'store_slug': store.slug}),
                reverse('storefront:pwa_sw', kwargs={'store_slug': store.slug}),
                reverse('storefront:pwa_offline', kwargs={'store_slug': store.slug}),
            ]
            for url in urls:
                resp = client.get(url)
                self.assertEqual(resp.status_code, 404, f"Expected 404 for {url}")

            sf_resp = client.get(reverse('storefront:detail', kwargs={'store_slug': store.slug}))
            self.assertEqual(sf_resp.status_code, 200)
            self.assertNotContains(sf_resp, 'manifest.webmanifest')
            self.assertNotContains(sf_resp, 'serviceWorker.register')

    def test_manifest_sw_offline_and_storefront_head_on_online_store(self):
        client = Client()
        # 1. Manifest JSON
        manifest_resp = client.get(
            reverse('storefront:pwa_manifest', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(manifest_resp.status_code, 200)
        self.assertEqual(manifest_resp['Content-Type'], 'application/manifest+json')
        data = json.loads(manifest_resp.content.decode('utf-8'))
        self.assertEqual(data['name'], 'Sunrise Bakery App')
        self.assertEqual(data['start_url'], '/s/sunrise-bakery/')
        self.assertEqual(data['scope'], '/s/sunrise-bakery/')
        self.assertEqual(data['display'], 'standalone')
        self.assertEqual(data['theme_color'], '#e11d48')
        self.assertEqual(len(data['icons']), 2)
        sizes = {icon['sizes'] for icon in data['icons']}
        self.assertEqual(sizes, {'192x192', '512x512'})

        # 2. Service worker headers and script
        sw_resp = client.get(
            reverse('storefront:pwa_sw', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(sw_resp.status_code, 200)
        self.assertEqual(sw_resp['Content-Type'], 'application/javascript')
        self.assertEqual(sw_resp['Service-Worker-Allowed'], '/s/sunrise-bakery/')
        sw_body = sw_resp.content.decode('utf-8')
        self.assertIn('/s/sunrise-bakery/offline/', sw_body)
        self.assertIn("'/account/'", sw_body)
        self.assertIn("'/online-checkout/'", sw_body)

        # 3. Offline page
        offline_resp = client.get(
            reverse('storefront:pwa_offline', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(offline_resp.status_code, 200)
        self.assertContains(offline_resp, 'Sunrise Bakery App')
        self.assertContains(offline_resp, 'Offline')

        # 4. Storefront HTML includes manifest link, theme-color meta, and SW registration
        sf_resp = client.get(
            reverse('storefront:detail', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(sf_resp.status_code, 200)
        self.assertContains(sf_resp, '/s/sunrise-bakery/manifest.webmanifest')
        self.assertContains(sf_resp, '#e11d48')
        self.assertContains(sf_resp, 'serviceWorker.register')

    def test_pwa_icons_192_and_512_fallback_and_uploaded_logo(self):
        client = Client()

        # 1. Without logo (fallback generated icon)
        r192 = client.get(
            reverse('storefront:pwa_icon_192', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(r192.status_code, 200)
        self.assertEqual(r192['Content-Type'], 'image/png')
        with Image.open(io.BytesIO(r192.content)) as img192:
            self.assertEqual(img192.format, 'PNG')
            self.assertEqual(img192.size, (192, 192))

        r512 = client.get(
            reverse('storefront:pwa_icon_512', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(r512.status_code, 200)
        self.assertEqual(r512['Content-Type'], 'image/png')
        with Image.open(io.BytesIO(r512.content)) as img512:
            self.assertEqual(img512.format, 'PNG')
            self.assertEqual(img512.size, (512, 512))

        # 2. With uploaded logo (resized with Pillow)
        buf = io.BytesIO()
        Image.new('RGB', (300, 300), color=(20, 140, 80)).save(buf, format='PNG')
        self.online_store.logo = SimpleUploadedFile(
            'bakery_logo.png',
            buf.getvalue(),
            content_type='image/png',
        )
        self.online_store.save()

        r192_logo = client.get(
            reverse('storefront:pwa_icon_192', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(r192_logo.status_code, 200)
        with Image.open(io.BytesIO(r192_logo.content)) as img192_logo:
            self.assertEqual(img192_logo.size, (192, 192))

        r512_logo = client.get(
            reverse('storefront:pwa_icon_512', kwargs={'store_slug': self.online_store.slug})
        )
        self.assertEqual(r512_logo.status_code, 200)
        with Image.open(io.BytesIO(r512_logo.content)) as img512_logo:
            self.assertEqual(img512_logo.size, (512, 512))
