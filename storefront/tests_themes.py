from decimal import Decimal
import json
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.urls import reverse
from catalog.models import Category, Product
from orders.models import Order
from storefront.management.commands.check_themes import REQUIRED_MARKERS, validate_all_themes
from storefront.themes.registry import (
    DEFAULT_THEME_KEY,
    THEMES_ROOT,
    get_theme,
    list_themes,
    theme_template,
)
from stores.models import Customer, Membership, PaymentQR, Plan, Store

User = get_user_model()


class ThemeRegistryAndResolverTests(TestCase):
    def test_registry_discovers_all_migrated_and_converted_themes(self):
        themes = list_themes()
        keys = {t['key'] for t in themes}
        self.assertTrue(
            {'classic', 'minimal', 'bold', 'artisan_bistro', 'verdant_market', 'noir_velvet'}.issubset(keys)
        )
        self.assertGreaterEqual(len(themes), 6)

    def test_designs_dir_every_design_has_corresponding_registered_theme(self):
        designs_dir = Path(settings.DESIGNS_DIR)
        self.assertTrue(designs_dir.exists())
        design_folders = [
            d.name for d in designs_dir.iterdir()
            if d.is_dir() and not d.name.startswith('.')
        ]
        self.assertGreaterEqual(len(design_folders), 1)
        registered_keys = {t['key'] for t in list_themes()}
        for design_name in design_folders:
            self.assertIn(
                design_name,
                registered_keys,
                f"Design '{design_name}' in DESIGNS_DIR is missing a registered theme.",
            )

    def test_unknown_or_corrupt_theme_key_falls_back_to_classic(self):
        fallback = get_theme('nonexistent_theme_999')
        self.assertEqual(fallback['key'], DEFAULT_THEME_KEY)

        bad_key = get_theme('../../etc/passwd')
        self.assertEqual(bad_key['key'], DEFAULT_THEME_KEY)

        resolved_home = theme_template('nonexistent_theme_999', 'home.html')
        self.assertEqual(resolved_home, 'storefront/themes/classic/home.html')

        resolved_checkout = theme_template('artisan_bistro', 'checkout.html')
        self.assertEqual(resolved_checkout, 'storefront/shared/checkout.html')

    def test_check_themes_command_passes_with_zero_errors(self):
        errors = validate_all_themes()
        self.assertEqual(errors, [])
        call_command('check_themes')


class EveryThemeStorefrontAndCheckoutTests(TestCase):
    def setUp(self):
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

        self.owner_offline = User.objects.create_user(
            username='theme_owner_offline',
            password='ComplexPassword123!',
        )
        self.store_offline = Store.objects.create(
            name='Offline Heritage Tea',
            slug='offline-heritage-tea',
            owner=self.owner_offline,
            plan=self.plan_offline,
            template_key='classic',
            theme_color='#92400e',
        )
        Membership.objects.get_or_create(
            user=self.owner_offline,
            store=self.store_offline,
            defaults={'role': Membership.ROLE_OWNER},
        )
        self.cat_offline = Category.objects.create(
            store=self.store_offline,
            name='Loose Leaf',
            sort_order=1,
        )
        self.prod_offline = Product.objects.create(
            store=self.store_offline,
            category=self.cat_offline,
            name='Assam Golden Tips',
            description='First-flush malty black tea.',
            price=Decimal('320.00'),
            is_available=True,
            created_by=self.owner_offline,
        )

        self.owner_online = User.objects.create_user(
            username='theme_owner_online',
            password='ComplexPassword123!',
        )
        self.store_online = Store.objects.create(
            name='Online Roastery Collective',
            slug='online-roastery-collective',
            owner=self.owner_online,
            plan=self.plan_online,
            template_key='classic',
            theme_color='#4f46e5',
            online_ordering_open=True,
            delivery_enabled=True,
            pickup_enabled=True,
            delivery_fee=Decimal('30.00'),
            accept_cod=True,
            accept_upi_qr=True,
        )
        Membership.objects.get_or_create(
            user=self.owner_online,
            store=self.store_online,
            defaults={'role': Membership.ROLE_OWNER},
        )
        PaymentQR.objects.create(store=self.store_online, upi_id='roastery@upi')
        self.cat_online = Category.objects.create(
            store=self.store_online,
            name='Single Origin',
            sort_order=1,
        )
        self.prod_online = Product.objects.create(
            store=self.store_online,
            category=self.cat_online,
            name='Ethiopian Yirgacheffe',
            description='Floral jasmine and bergamot filter roast.',
            price=Decimal('450.00'),
            is_available=True,
            created_by=self.owner_online,
        )
        self.customer = Customer.objects.create(
            store=self.store_online,
            name='Aarav Mehta',
            phone='9876500011',
            password='CustomerPass123!',
        )

    def test_every_registered_theme_renders_on_plan1_and_plan3_with_all_markers(self):
        client = Client()
        themes = list_themes()

        for theme in themes:
            t_key = theme['key']

            # 1. Plan 1 (Offline store) rendering
            self.store_offline.template_key = t_key
            self.store_offline.save(update_fields=['template_key'])
            r_off = client.get(reverse('storefront:detail', kwargs={'store_slug': self.store_offline.slug}))
            self.assertEqual(r_off.status_code, 200, f"Plan 1 failed for theme {t_key}")
            body_off = r_off.content.decode('utf-8')
            self.assertIn(f'data-theme="{t_key}"', body_off)
            self.assertIn('Assam Golden Tips', body_off)
            self.assertIn('320.00', body_off)
            self.assertIn('Loose Leaf', body_off)
            self.assertIn('data-sf="cart-link"', body_off)
            self.assertIn('data-sf="category-filter"', body_off)
            self.assertIn('data-sf="add-to-cart"', body_off)
            # Plan 1 store must NOT show Online account links
            self.assertNotIn('data-sf="account-links"', body_off)

            # 2. Plan 3 (Online store, ordering open)
            self.store_online.template_key = t_key
            self.store_online.online_ordering_open = True
            self.store_online.save(update_fields=['template_key', 'online_ordering_open'])
            r_on = client.get(reverse('storefront:detail', kwargs={'store_slug': self.store_online.slug}))
            self.assertEqual(r_on.status_code, 200, f"Plan 3 failed for theme {t_key}")
            body_on = r_on.content.decode('utf-8')
            self.assertIn(f'data-theme="{t_key}"', body_on)
            self.assertIn('Ethiopian Yirgacheffe', body_on)
            self.assertIn('450.00', body_on)
            self.assertIn('Single Origin', body_on)
            self.assertIn('data-sf="cart-link"', body_on)
            self.assertIn('data-sf="account-links"', body_on)
            self.assertIn('data-sf="category-filter"', body_on)
            self.assertIn('data-sf="add-to-cart"', body_on)
            self.assertNotIn('data-sf="closed-banner"', body_on)

            # 3. Plan 3 (Online store, ordering closed -> closed-banner marker present)
            self.store_online.online_ordering_open = False
            self.store_online.save(update_fields=['online_ordering_open'])
            r_closed = client.get(reverse('storefront:detail', kwargs={'store_slug': self.store_online.slug}))
            self.assertEqual(r_closed.status_code, 200)
            body_closed = r_closed.content.decode('utf-8')
            for marker in REQUIRED_MARKERS:
                self.assertIn(marker, body_closed, f"Missing marker {marker} on closed Online store for {t_key}")

            # 4. Shared functional pages (checkout, login, register) render with active theme shell
            for page_url in [
                reverse('storefront:checkout', kwargs={'store_slug': self.store_online.slug}),
                reverse('storefront:customer_login', kwargs={'store_slug': self.store_online.slug}),
                reverse('storefront:customer_register', kwargs={'store_slug': self.store_online.slug}),
            ]:
                p_resp = client.get(page_url)
                self.assertEqual(p_resp.status_code, 200)
                self.assertIn(f'data-theme="{t_key}"', p_resp.content.decode('utf-8'))

    def test_qr_checkout_and_online_checkout_work_on_converted_theme(self):
        # Switch store_online to a converted GPT-5 theme (`noir_velvet`)
        self.store_online.template_key = 'noir_velvet'
        self.store_online.theme_color = '#ca8a04'
        self.store_online.online_ordering_open = True
        self.store_online.save()

        client = Client()
        # 1. Offline QR checkout flow
        client.post(
            reverse('storefront:cart_add', kwargs={'store_slug': self.store_online.slug}),
            {'product_id': self.prod_online.pk, 'quantity': 1},
        )
        qr_resp = client.post(
            reverse('storefront:checkout', kwargs={'store_slug': self.store_online.slug}),
            {
                'customer_name': 'Karan QR',
                'customer_phone': '9111222333',
                'note': 'Noir theme QR test',
            },
        )
        self.assertEqual(qr_resp.status_code, 302)
        qr_order = Order.objects.filter(store=self.store_online, customer_name='Karan QR').first()
        self.assertIsNotNone(qr_order)
        conf_resp = client.get(qr_resp['Location'])
        self.assertEqual(conf_resp.status_code, 200)
        self.assertIn('data-theme="noir_velvet"', conf_resp.content.decode('utf-8'))

        # 2. Online pickup checkout flow
        client.post(
            reverse('storefront:customer_login', kwargs={'store_slug': self.store_online.slug}),
            {'phone': '9876500011', 'password': 'CustomerPass123!'},
        )
        client.post(
            reverse('storefront:cart_add', kwargs={'store_slug': self.store_online.slug}),
            {'product_id': self.prod_online.pk, 'quantity': 2},
        )
        online_resp = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store_online.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
                'customer_note': 'Noir velvet online order',
            },
        )
        self.assertEqual(online_resp.status_code, 302)
        online_order = Order.objects.filter(store=self.store_online, customer=self.customer).first()
        self.assertIsNotNone(online_order)
        self.assertEqual(online_order.total, Decimal('900.00'))

        # Verify customer order tracking page also renders inside `noir_velvet` theme
        track_resp = client.get(
            reverse(
                'storefront:customer_order_detail',
                kwargs={'store_slug': self.store_online.slug, 'order_number': online_order.order_number},
            )
        )
        self.assertEqual(track_resp.status_code, 200)
        self.assertIn('data-theme="noir_velvet"', track_resp.content.decode('utf-8'))


class PublicGalleryAndDemoTests(TestCase):
    def setUp(self):
        self.plan_offline, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_OFFLINE,
            defaults={'name': 'Offline Catalogue', 'max_users': 1},
        )

    def test_public_home_gallery_preview_and_zero_db_write_demo(self):
        client = Client()

        # 1. Platform home page /
        home_resp = client.get(reverse('root'))
        self.assertEqual(home_resp.status_code, 200)
        for theme in list_themes():
            self.assertContains(home_resp, theme['name'])

        # 2. Gallery directory /themes/
        gal_resp = client.get(reverse('theme_gallery'))
        self.assertEqual(gal_resp.status_code, 200)
        for theme in list_themes():
            self.assertContains(gal_resp, theme['name'])
            self.assertContains(gal_resp, reverse('theme_preview', kwargs={'theme_key': theme['key']}))

        # 3. Preview shell /themes/<key>/
        prev_resp = client.get(reverse('theme_preview', kwargs={'theme_key': 'artisan_bistro'}))
        self.assertEqual(prev_resp.status_code, 200)
        self.assertContains(prev_resp, 'Artisan Bistro')
        self.assertContains(prev_resp, 'data-sf="viewport-switcher"')
        self.assertContains(prev_resp, reverse('theme_demo', kwargs={'theme_key': 'artisan_bistro'}))

        # 4. Demo /themes/<key>/demo/ renders sample store with ZERO DB writes and SAMEORIGIN header
        stores_before = Store.objects.count()
        products_before = Product.objects.count()
        orders_before = Order.objects.count()

        for theme in list_themes():
            demo_resp = client.get(reverse('theme_demo', kwargs={'theme_key': theme['key']}))
            self.assertEqual(demo_resp.status_code, 200)
            self.assertEqual(demo_resp.headers.get('X-Frame-Options'), 'SAMEORIGIN')
            demo_html = demo_resp.content.decode('utf-8')
            self.assertIn('data-sf="demo-ribbon"', demo_html)
            self.assertIn('Demo preview', demo_html)
            self.assertIn('Sourdough Country Loaf', demo_html)

        self.assertEqual(Store.objects.count(), stores_before)
        self.assertEqual(Product.objects.count(), products_before)
        self.assertEqual(Order.objects.count(), orders_before)

        # 5. Unknown theme key returns 404 on /themes/<bad>/ and /themes/<bad>/demo/
        self.assertEqual(client.get('/themes/unknown_theme_xyz/').status_code, 404)
        self.assertEqual(client.get('/themes/unknown_theme_xyz/demo/').status_code, 404)


class OwnerAppearanceAndPWACacheTests(TestCase):
    def setUp(self):
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

        # Store A (Offline plan)
        self.owner_a = User.objects.create_user(username='owner_app_a', password='ComplexPassword123!')
        self.store_a = Store.objects.create(
            name='Store Alpha Offline',
            slug='store-alpha-offline',
            owner=self.owner_a,
            plan=self.plan_offline,
            template_key='classic',
            theme_color='#92400e',
        )
        Membership.objects.get_or_create(
            user=self.owner_a,
            store=self.store_a,
            defaults={'role': Membership.ROLE_OWNER},
        )
        Product.objects.create(
            store=self.store_a,
            name='Alpha Secret Muffin',
            price=Decimal('99.00'),
            is_available=True,
            created_by=self.owner_a,
        )

        # Store B (Online plan, with staff)
        self.owner_b = User.objects.create_user(username='owner_app_b', password='ComplexPassword123!')
        self.store_b = Store.objects.create(
            name='Store Beta Online',
            slug='store-beta-online',
            owner=self.owner_b,
            plan=self.plan_online,
            template_key='classic',
            theme_color='#4f46e5',
        )
        Membership.objects.get_or_create(
            user=self.owner_b,
            store=self.store_b,
            defaults={'role': Membership.ROLE_OWNER},
        )
        self.staff_b = User.objects.create_user(username='staff_app_b', password='ComplexPassword123!')
        Membership.objects.create(
            user=self.staff_b,
            store=self.store_b,
            role=Membership.ROLE_STAFF,
            display_name='Staff Beta',
            is_active=True,
        )
        Product.objects.create(
            store=self.store_b,
            name='Beta Signature Espresso',
            price=Decimal('180.00'),
            is_available=True,
            created_by=self.owner_b,
        )

    def test_staff_blocked_with_403_on_appearance_and_preview(self):
        client = Client()
        client.login(username='staff_app_b', password='ComplexPassword123!')
        r1 = client.get(reverse('dashboard:appearance'))
        self.assertEqual(r1.status_code, 403)
        r2 = client.post(
            reverse('dashboard:appearance'),
            {'template_key': 'minimal', 'theme_color': '#112233'},
        )
        self.assertEqual(r2.status_code, 403)
        r3 = client.get(reverse('dashboard:appearance_preview', kwargs={'theme_key': 'minimal'}))
        self.assertEqual(r3.status_code, 403)

    def test_owner_can_change_theme_and_brand_color_and_tenant_isolation_holds(self):
        client_a = Client()
        client_a.login(username='owner_app_a', password='ComplexPassword123!')

        # Change Store A to artisan_bistro and #b91c1c
        post_resp = client_a.post(
            reverse('dashboard:appearance'),
            {'template_key': 'artisan_bistro', 'theme_color': '#b91c1c'},
        )
        self.assertEqual(post_resp.status_code, 302)
        self.store_a.refresh_from_db()
        self.store_a_theme = self.store_a.template_key
        self.assertEqual(self.store_a.template_key, 'artisan_bistro')
        self.assertEqual(self.store_a.theme_color, '#b91c1c')

        # Store B must remain untouched
        self.store_b.refresh_from_db()
        self.assertEqual(self.store_b.template_key, 'classic')
        self.assertEqual(self.store_b.theme_color, '#4f46e5')

        # Store A storefront reflects new theme and brand color
        sf_a = client_a.get(reverse('storefront:detail', kwargs={'store_slug': self.store_a.slug}))
        self.assertEqual(sf_a.status_code, 200)
        html_a = sf_a.content.decode('utf-8')
        self.assertIn('data-theme="artisan_bistro"', html_a)
        self.assertIn('--brand-color: #b91c1c', html_a)

    def test_plan_gate_blocks_higher_min_plan_theme_selection(self):
        client_a = Client()
        client_a.login(username='owner_app_a', password='ComplexPassword123!')

        # Store A is on Offline plan; verdant_market requires franchise, noir_velvet requires online
        for restricted_key in ('verdant_market', 'noir_velvet'):
            resp = client_a.post(
                reverse('dashboard:appearance'),
                {'template_key': restricted_key, 'theme_color': '#047857'},
            )
            self.assertEqual(resp.status_code, 400)
            self.store_a.refresh_from_db()
            self.assertEqual(self.store_a.template_key, 'classic')

        # Store B is on Online plan and CAN select both verdant_market and noir_velvet
        client_b = Client()
        client_b.login(username='owner_app_b', password='ComplexPassword123!')
        for allowed_key in ('verdant_market', 'noir_velvet'):
            resp_b = client_b.post(
                reverse('dashboard:appearance'),
                {'template_key': allowed_key, 'theme_color': '#ca8a04'},
            )
            self.assertEqual(resp_b.status_code, 302)
            self.store_b.refresh_from_db()
            self.assertEqual(self.store_b.template_key, allowed_key)

    def test_invalid_or_css_injection_brand_color_is_rejected(self):
        client_b = Client()
        client_b.login(username='owner_app_b', password='ComplexPassword123!')

        malicious_inputs = [
            'red; background:url(javascript:alert(1))',
            '#12345',
            '#1234567',
            '#GGGGGG',
            '</style><script>alert(1)</script>',
        ]
        for bad_color in malicious_inputs:
            resp = client_b.post(
                reverse('dashboard:appearance'),
                {'template_key': 'classic', 'theme_color': bad_color},
            )
            self.assertEqual(resp.status_code, 400, f"Expected 400 for invalid color: {bad_color}")
            self.store_b.refresh_from_db()
            self.assertEqual(self.store_b.theme_color, '#4f46e5')

    def test_owner_preview_shows_only_own_products_without_saving_and_has_noindex(self):
        client_a = Client()
        client_a.login(username='owner_app_a', password='ComplexPassword123!')

        # Owner A previews 'noir_velvet' (even before upgrading, preview with own products works without saving)
        prev_resp = client_a.get(
            reverse('dashboard:appearance_preview', kwargs={'theme_key': 'noir_velvet'})
        )
        self.assertEqual(prev_resp.status_code, 200)
        html = prev_resp.content.decode('utf-8')
        self.assertIn('data-theme="noir_velvet"', html)
        self.assertIn('Alpha Secret Muffin', html)
        self.assertNotIn('Beta Signature Espresso', html)
        self.assertIn('<meta name="robots" content="noindex, nofollow">', html)

        # Store A's saved template_key in DB is still 'classic'
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.template_key, 'classic')

    def test_pwa_manifest_sw_cache_key_and_self_contained_offline_page(self):
        client = Client()

        # Initial SW and Manifest on Store B (classic, #4f46e5)
        sw_url = reverse('storefront:pwa_sw', kwargs={'store_slug': self.store_b.slug})
        manifest_url = reverse('storefront:pwa_manifest', kwargs={'store_slug': self.store_b.slug})
        offline_url = reverse('storefront:pwa_offline', kwargs={'store_slug': self.store_b.slug})

        sw_1 = client.get(sw_url).content.decode('utf-8')
        self.assertIn('store-pwa-store-beta-online-classic-v1-4f46e5', sw_1)

        # Change Store B theme to noir_velvet and brand color to #e11d48
        self.store_b.template_key = 'noir_velvet'
        self.store_b.theme_color = '#e11d48'
        self.store_b.save()

        sw_2 = client.get(sw_url).content.decode('utf-8')
        self.assertIn('store-pwa-store-beta-online-noir_velvet-v1-e11d48', sw_2)
        self.assertNotEqual(sw_1, sw_2)

        manifest_data = json.loads(client.get(manifest_url).content.decode('utf-8'))
        self.assertEqual(manifest_data['theme_color'], '#e11d48')

        # Offline page must be 100% self-contained (no external URLs, no theme CSS link)
        offline_resp = client.get(offline_url)
        self.assertEqual(offline_resp.status_code, 200)
        offline_html = offline_resp.content.decode('utf-8')
        self.assertIn('Store Beta Online', offline_html)
        self.assertIn('#e11d48', offline_html)
        self.assertNotIn('http://', offline_html)
        self.assertNotIn('https://', offline_html)
        self.assertNotIn('<link rel="stylesheet"', offline_html)
