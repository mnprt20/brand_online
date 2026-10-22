from decimal import Decimal
import io
import shutil
import tempfile
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from catalog.models import Category, Product
from orders.models import Order, OrderItem
from stores.models import Plan, Store, Membership, PaymentQR

User = get_user_model()


def make_test_image_bytes():
    buf = io.BytesIO()
    img = Image.new('RGB', (32, 32), color=(73, 109, 137))
    img.save(buf, format='PNG')
    return buf.getvalue()


class StoresModelTests(TestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(username='owner_a', password='password123')
        self.owner_b = User.objects.create_user(username='owner_b', password='password123')
        self.plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.plan_online = Plan.objects.get(slug=Plan.SLUG_ONLINE)

    def test_plans_seeded_correctly(self):
        self.assertEqual(Plan.objects.count(), 3)
        self.assertEqual(self.plan_offline.max_users, 1)
        self.assertEqual(self.plan_offline.price, Decimal('0.00'))
        self.assertGreater(self.plan_franchise.max_users, 1)
        self.assertGreater(self.plan_online.max_users, 1)

    def test_seed_plans_command_is_idempotent(self):
        call_command('seed_plans')
        self.assertEqual(Plan.objects.count(), 3)

    def test_plan_1_limit_enforced_on_second_membership(self):
        store = Store.objects.create(
            owner=self.owner_a,
            name='Alpha Store',
            slug='alpha-store',
            plan=self.plan_offline,
        )
        Membership.objects.create(
            user=self.owner_a,
            store=store,
            role=Membership.ROLE_OWNER,
        )
        with self.assertRaises(ValidationError):
            Membership.objects.create(
                user=self.owner_b,
                store=store,
                role=Membership.ROLE_STAFF,
            )

    def test_store_scoped_manager_isolates_records(self):
        store_a = Store.objects.create(
            owner=self.owner_a,
            name='Alpha Store',
            slug='alpha-store',
            plan=self.plan_offline,
        )
        Membership.objects.create(user=self.owner_a, store=store_a, role=Membership.ROLE_OWNER)
        qr_a = PaymentQR.objects.create(store=store_a, upi_id='alpha@upi')

        store_b = Store.objects.create(
            owner=self.owner_b,
            name='Beta Store',
            slug='beta-store',
            plan=self.plan_offline,
        )
        Membership.objects.create(user=self.owner_b, store=store_b, role=Membership.ROLE_OWNER)
        qr_b = PaymentQR.objects.create(store=store_b, upi_id='beta@upi')

        self.assertQuerySetEqual(PaymentQR.objects.for_user(self.owner_a), [qr_a])
        self.assertQuerySetEqual(PaymentQR.objects.for_user(self.owner_b), [qr_b])


class DashboardSecurityAndCRUDTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.temp_media)
        self.override.enable()

        self.plan = Plan.objects.get(slug=Plan.SLUG_OFFLINE)

        # Owner A setup
        self.owner_a = User.objects.create_user(username='owner_a', password='password123')
        self.store_a = Store.objects.create(
            owner=self.owner_a,
            name='Store A',
            slug='store-a',
            plan=self.plan,
        )
        Membership.objects.create(user=self.owner_a, store=self.store_a, role=Membership.ROLE_OWNER)
        self.cat_a = Category.objects.create(store=self.store_a, name='Cat A', sort_order=1)
        self.prod_a = Product.objects.create(
            store=self.store_a,
            category=self.cat_a,
            name='Prod A',
            price=Decimal('100.00'),
            created_by=self.owner_a,
        )
        self.order_a = Order.objects.create(
            store=self.store_a,
            customer_name='Cust A',
            customer_phone='1111111111',
        )
        OrderItem.objects.create(
            order=self.order_a,
            product=self.prod_a,
            product_name_snapshot='Prod A',
            unit_price_snapshot=Decimal('100.00'),
            quantity=1,
        )
        self.qr_a = PaymentQR.objects.create(store=self.store_a, upi_id='a@upi')

        # Owner B setup
        self.owner_b = User.objects.create_user(username='owner_b', password='password123')
        self.store_b = Store.objects.create(
            owner=self.owner_b,
            name='Store B',
            slug='store-b',
            plan=self.plan,
        )
        Membership.objects.create(user=self.owner_b, store=self.store_b, role=Membership.ROLE_OWNER)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_anonymous_users_redirected_to_login_on_every_dashboard_url(self):
        dashboard_urls = [
            reverse('dashboard:home'),
            reverse('dashboard:store_qr'),
            reverse('dashboard:category_list'),
            reverse('dashboard:category_add'),
            reverse('dashboard:category_detail', args=[self.cat_a.pk]),
            reverse('dashboard:category_edit', args=[self.cat_a.pk]),
            reverse('dashboard:category_delete', args=[self.cat_a.pk]),
            reverse('dashboard:product_list'),
            reverse('dashboard:product_add'),
            reverse('dashboard:product_detail', args=[self.prod_a.pk]),
            reverse('dashboard:product_edit', args=[self.prod_a.pk]),
            reverse('dashboard:product_delete', args=[self.prod_a.pk]),
            reverse('dashboard:settings'),
            reverse('dashboard:settings_by_id', args=[self.store_a.pk]),
            reverse('dashboard:settings_edit', args=[self.store_a.pk]),
            reverse('dashboard:settings_delete', args=[self.store_a.pk]),
            reverse('dashboard:payment_qr'),
            reverse('dashboard:payment_qr_by_id', args=[self.qr_a.pk]),
            reverse('dashboard:order_list'),
            reverse('dashboard:order_detail', args=[self.order_a.pk]),
            reverse('dashboard:order_edit', args=[self.order_a.pk]),
            reverse('dashboard:order_status', args=[self.order_a.pk]),
            reverse('dashboard:order_delete', args=[self.order_a.pk]),
        ]
        for url in dashboard_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, f"Expected redirect for anonymous GET {url}")
            self.assertIn('/accounts/login/', resp['Location'])

    def test_tenant_isolation_owner_b_gets_404_or_403_for_owner_a_resources(self):
        self.client.login(username='owner_b', password='password123')

        # Category view, edit, delete
        self.assertIn(
            self.client.get(reverse('dashboard:category_detail', args=[self.cat_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.get(reverse('dashboard:category_edit', args=[self.cat_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(
                reverse('dashboard:category_edit', args=[self.cat_a.pk]),
                {'name': 'Hacked', 'sort_order': 9},
            ).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(reverse('dashboard:category_delete', args=[self.cat_a.pk])).status_code,
            (403, 404),
        )
        self.assertTrue(Category.objects.filter(pk=self.cat_a.pk, name='Cat A').exists())

        # Product view, edit, delete
        self.assertIn(
            self.client.get(reverse('dashboard:product_detail', args=[self.prod_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.get(reverse('dashboard:product_edit', args=[self.prod_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(
                reverse('dashboard:product_edit', args=[self.prod_a.pk]),
                {'name': 'Hacked Prod', 'price': '1.00', 'is_available': True},
            ).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(reverse('dashboard:product_delete', args=[self.prod_a.pk])).status_code,
            (403, 404),
        )
        self.assertTrue(Product.objects.filter(pk=self.prod_a.pk, name='Prod A').exists())

        # Order view, edit/status, delete
        self.assertIn(
            self.client.get(reverse('dashboard:order_detail', args=[self.order_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.get(reverse('dashboard:order_edit', args=[self.order_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(
                reverse('dashboard:order_status', args=[self.order_a.pk]),
                {'status': Order.STATUS_CANCELLED, 'payment_status': Order.PAYMENT_UNPAID},
            ).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(reverse('dashboard:order_delete', args=[self.order_a.pk])).status_code,
            (403, 404),
        )
        self.assertTrue(Order.objects.filter(pk=self.order_a.pk, status=Order.STATUS_NEW).exists())

        # Settings & PaymentQR by ID (view, edit, delete)
        self.assertIn(
            self.client.get(reverse('dashboard:settings_by_id', args=[self.store_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(
                reverse('dashboard:settings_edit', args=[self.store_a.pk]),
                {'name': 'Hacked Store', 'slug': 'hacked', 'template_key': 'bold'},
            ).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.delete(reverse('dashboard:settings_delete', args=[self.store_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.get(reverse('dashboard:payment_qr_by_id', args=[self.qr_a.pk])).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.post(
                reverse('dashboard:payment_qr_by_id', args=[self.qr_a.pk]),
                {'upi_id': 'hacked@upi'},
            ).status_code,
            (403, 404),
        )

    def test_product_image_upload_saves_and_renders(self):
        self.client.login(username='owner_a', password='password123')
        image_file = SimpleUploadedFile(
            'latte.png',
            make_test_image_bytes(),
            content_type='image/png',
        )
        resp = self.client.post(
            reverse('dashboard:product_add'),
            {
                'category': self.cat_a.pk,
                'name': 'Caramel Latte',
                'description': 'Rich espresso with caramel',
                'price': '175.00',
                'image': image_file,
                'is_available': True,
            },
        )
        self.assertEqual(resp.status_code, 302)
        product = Product.objects.get(store=self.store_a, name='Caramel Latte')
        self.assertTrue(bool(product.image))
        self.assertEqual(product.created_by, self.owner_a)

        list_resp = self.client.get(reverse('dashboard:product_list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, product.image.url)

    def test_store_qr_endpoints_return_valid_png(self):
        png_magic = b'\x89PNG\r\n\x1a\n'
        self.client.login(username='owner_a', password='password123')

        dash_qr_resp = self.client.get(reverse('dashboard:store_qr'))
        self.assertEqual(dash_qr_resp.status_code, 200)
        self.assertEqual(dash_qr_resp['Content-Type'], 'image/png')
        self.assertTrue(dash_qr_resp.content.startswith(png_magic))

        pub_qr_resp = self.client.get(reverse('storefront:store_qr', args=[self.store_a.slug]))
        self.assertEqual(pub_qr_resp.status_code, 200)
        self.assertEqual(pub_qr_resp['Content-Type'], 'image/png')
        self.assertTrue(pub_qr_resp.content.startswith(png_magic))

    def test_all_models_registered_in_admin(self):
        from django.contrib import admin
        from orders.models import OrderItem
        expected_models = [Plan, Store, Membership, PaymentQR, Category, Product, Order, OrderItem]
        for model in expected_models:
            self.assertIn(model, admin.site._registry, f"{model.__name__} not registered in Django admin")


class Plan2Stage1ModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='fran_owner', password='password123')
        self.staff1 = User.objects.create_user(username='fran_staff1', password='password123')
        self.staff2 = User.objects.create_user(username='fran_staff2', password='password123')
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.store = Store.objects.create(
            owner=self.owner,
            name='Franchise Store',
            slug='franchise-store',
            plan=self.plan_franchise,
            extra_seats=0,
        )
        self.owner_membership = Membership.objects.create(
            user=self.owner,
            store=self.store,
            role=Membership.ROLE_OWNER,
            display_name='Store Owner',
        )

    def test_franchise_plan_seed_values(self):
        self.assertEqual(self.plan_franchise.max_users, 2)
        self.assertTrue(self.plan_franchise.features.get('staff'))
        self.assertTrue(self.plan_franchise.features.get('sales_report'))
        plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.assertEqual(plan_offline.max_users, 1)

    def test_seat_limit_with_extra_seats_and_deactivation(self):
        # Franchise plan has max_users=2, extra_seats=0 -> 2 active seats total (owner + 1 staff)
        m_staff1 = Membership.objects.create(
            user=self.staff1,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff One',
        )
        self.assertTrue(bool(m_staff1.referral_code))

        # Creating a third active user fails
        with self.assertRaises(ValidationError):
            Membership.objects.create(
                user=self.staff2,
                store=self.store,
                role=Membership.ROLE_STAFF,
                display_name='Staff Two',
            )

        # Deactivating staff1 frees a seat
        m_staff1.is_active = False
        m_staff1.save()
        m_staff2 = Membership.objects.create(
            user=self.staff2,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff Two',
        )
        self.assertTrue(m_staff2.is_active)

        # Reactivating staff1 without extra_seats fails
        m_staff1.is_active = True
        with self.assertRaises(ValidationError):
            m_staff1.save()

        # Increasing extra_seats=1 allows reactivating staff1
        self.store.extra_seats = 1
        self.store.save()
        m_staff1.is_active = True
        m_staff1.save()
        self.assertEqual(self.store.active_seat_count, 3)

    def test_data_migration_backfills_unique_non_empty_referral_codes(self):
        from importlib import import_module
        from django.apps import apps
        from stores.services import backfill_membership_referral_codes

        m_staff1 = Membership.objects.create(
            user=self.staff1,
            store=self.store,
            role=Membership.ROLE_STAFF,
        )
        # Clear one referral code and run the migration 0004 backfill function
        Membership.objects.filter(pk=self.owner_membership.pk).update(referral_code='')
        mig_0004 = import_module('stores.migrations.0004_backfill_referral_codes_and_franchise_plan')
        mig_0004.backfill_and_update_plans(apps, None)
        self.owner_membership.refresh_from_db()
        self.assertTrue(len(self.owner_membership.referral_code) >= 8)

        # Clear the second membership's referral code and run service backfill
        Membership.objects.filter(pk=m_staff1.pk).update(referral_code='')
        backfill_membership_referral_codes(Membership)
        m_staff1.refresh_from_db()
        self.assertTrue(len(m_staff1.referral_code) >= 8)
        self.assertNotEqual(self.owner_membership.referral_code, m_staff1.referral_code)


class Plan2Stage2PermissionTests(TestCase):
    def setUp(self):
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.owner = User.objects.create_user(username='p2_owner', password='password123')
        self.store = Store.objects.create(
            owner=self.owner,
            name='P2 Store',
            slug='p2-store',
            plan=self.plan_franchise,
            extra_seats=2,
        )
        Membership.objects.create(
            user=self.owner,
            store=self.store,
            role=Membership.ROLE_OWNER,
            display_name='P2 Owner',
        )
        self.staff_a = User.objects.create_user(username='p2_staff_a', password='password123')
        self.m_staff_a = Membership.objects.create(
            user=self.staff_a,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff A',
        )
        self.staff_b = User.objects.create_user(username='p2_staff_b', password='password123')
        self.m_staff_b = Membership.objects.create(
            user=self.staff_b,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff B',
        )

        self.cat = Category.objects.create(store=self.store, name='Drinks')
        self.prod = Product.objects.create(
            store=self.store,
            category=self.cat,
            name='Tea',
            price=Decimal('50.00'),
            created_by=self.owner,
        )
        self.qr = PaymentQR.objects.create(store=self.store, upi_id='p2@upi')

        self.order_staff_a = Order.objects.create(
            store=self.store,
            customer_name='Cust A',
            customer_phone='9000000001',
            placed_by=self.staff_a,
        )
        self.order_staff_b = Order.objects.create(
            store=self.store,
            customer_name='Cust B',
            customer_phone='9000000002',
            placed_by=self.staff_b,
        )
        self.order_direct = Order.objects.create(
            store=self.store,
            customer_name='Cust Direct',
            customer_phone='9000000003',
            placed_by=None,
        )

    def test_staff_cannot_reach_owner_only_urls(self):
        self.client.login(username='p2_staff_a', password='password123')
        owner_only_urls = [
            reverse('dashboard:category_list'),
            reverse('dashboard:category_add'),
            reverse('dashboard:category_detail', args=[self.cat.pk]),
            reverse('dashboard:category_edit', args=[self.cat.pk]),
            reverse('dashboard:category_delete', args=[self.cat.pk]),
            reverse('dashboard:product_list'),
            reverse('dashboard:product_add'),
            reverse('dashboard:product_detail', args=[self.prod.pk]),
            reverse('dashboard:product_edit', args=[self.prod.pk]),
            reverse('dashboard:product_delete', args=[self.prod.pk]),
            reverse('dashboard:settings'),
            reverse('dashboard:payment_qr'),
            reverse('dashboard:order_delete', args=[self.order_staff_a.pk]),
            reverse('dashboard:store_qr'),
        ]
        for url in owner_only_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for staff GET {url}")

    def test_staff_isolation_cannot_view_or_update_other_staff_or_unattributed_orders(self):
        self.client.login(username='p2_staff_a', password='password123')

        # Staff A can view and update own order
        self.assertEqual(
            self.client.get(reverse('dashboard:order_detail', args=[self.order_staff_a.pk])).status_code,
            200,
        )

        # Staff A cannot view or update Staff B's order or direct/unattributed order
        for forbidden_order in (self.order_staff_b, self.order_direct):
            self.assertIn(
                self.client.get(reverse('dashboard:order_detail', args=[forbidden_order.pk])).status_code,
                (403, 404),
            )
            self.assertIn(
                self.client.post(
                    reverse('dashboard:order_status', args=[forbidden_order.pk]),
                    {'status': Order.STATUS_PAID, 'payment_status': Order.PAYMENT_PAID},
                ).status_code,
                (403, 404),
            )

    def test_deactivated_staff_cannot_login_and_existing_session_is_rejected(self):
        # Log in while active
        self.assertTrue(self.client.login(username='p2_staff_a', password='password123'))
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 200)

        # Deactivate staff member
        self.m_staff_a.is_active = False
        self.m_staff_a.save()

        # Next request with existing session is rejected (403) and session is cleared
        next_resp = self.client.get(reverse('dashboard:home'))
        self.assertEqual(next_resp.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

        # Attempting to log in via login view fails
        login_resp = self.client.post(
            reverse('accounts:login'),
            {'username': 'p2_staff_a', 'password': 'password123'},
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)


class Plan2Stage3StaffManagementTests(TestCase):
    def setUp(self):
        self.plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)

        self.owner_p1 = User.objects.create_user(username='p1_owner', password='password123')
        self.store_p1 = Store.objects.create(
            owner=self.owner_p1,
            name='P1 Store',
            slug='p1-store',
            plan=self.plan_offline,
        )
        Membership.objects.create(user=self.owner_p1, store=self.store_p1, role=Membership.ROLE_OWNER)

        self.owner_fran = User.objects.create_user(username='fran_owner3', password='password123')
        self.store_fran = Store.objects.create(
            owner=self.owner_fran,
            name='Fran Store 3',
            slug='fran-store-3',
            plan=self.plan_franchise,
            extra_seats=0,
        )
        Membership.objects.create(user=self.owner_fran, store=self.store_fran, role=Membership.ROLE_OWNER)

    def test_plan_1_store_blocked_from_staff_management_urls(self):
        self.client.login(username='p1_owner', password='password123')
        for url in [reverse('dashboard:staff_list'), reverse('dashboard:staff_add')]:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, (403, 404))

    def test_staff_add_hashes_password_enforces_seat_limit_and_resets_password(self):
        self.client.login(username='fran_owner3', password='password123')
        raw_pw = 'SafeStaffPass99!'

        # Create 1st staff (uses 2/2 seats)
        resp = self.client.post(
            reverse('dashboard:staff_add'),
            {
                'username': 'seller_one',
                'display_name': 'Seller One',
                'password': raw_pw,
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, raw_pw)

        staff_user = User.objects.get(username='seller_one')
        self.assertNotEqual(staff_user.password, raw_pw)
        self.assertTrue(staff_user.check_password(raw_pw))
        staff_membership = Membership.objects.get(user=staff_user, store=self.store_fran)
        self.assertEqual(staff_membership.display_name, 'Seller One')
        self.assertTrue(staff_membership.is_active)

        # Creating 2nd staff fails because seat limit is 2 (owner + 1 staff)
        resp_limit = self.client.post(
            reverse('dashboard:staff_add'),
            {
                'username': 'seller_two',
                'display_name': 'Seller Two',
                'password': raw_pw,
            },
        )
        self.assertEqual(resp_limit.status_code, 400)
        self.assertContains(resp_limit, 'Seat limit reached', status_code=400)
        self.assertFalse(User.objects.filter(username='seller_two').exists())

        # Deactivating seller_one frees a seat so seller_two can be added
        self.client.post(
            reverse('dashboard:staff_toggle', args=[staff_membership.pk]),
            {'action': 'deactivate'},
        )
        staff_membership.refresh_from_db()
        self.assertFalse(staff_membership.is_active)

        resp_second = self.client.post(
            reverse('dashboard:staff_add'),
            {
                'username': 'seller_two',
                'display_name': 'Seller Two',
                'password': raw_pw,
            },
        )
        self.assertEqual(resp_second.status_code, 302)
        self.assertTrue(User.objects.filter(username='seller_two').exists())

        # Reset password for seller_one
        new_pw = 'UpdatedStaffPass88!'
        reset_resp = self.client.post(
            reverse('dashboard:staff_reset_password', args=[staff_membership.pk]),
            {'new_password': new_pw},
            follow=True,
        )
        self.assertEqual(reset_resp.status_code, 200)
        self.assertNotContains(reset_resp, new_pw)
        staff_user.refresh_from_db()
        self.assertTrue(staff_user.check_password(new_pw))


class Plan2Stage4CounterOrderQRReferralTests(TestCase):
    def setUp(self):
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)

        self.owner = User.objects.create_user(username='s4_owner', password='Password123!')
        self.store = Store.objects.create(
            owner=self.owner,
            name='Stage 4 Franchise',
            slug='s4-franchise',
            plan=self.plan_franchise,
            extra_seats=2,
        )
        self.owner_membership = Membership.objects.create(
            user=self.owner,
            store=self.store,
            role=Membership.ROLE_OWNER,
            display_name='S4 Owner',
        )

        self.staff1 = User.objects.create_user(username='s4_staff1', password='Password123!')
        self.m_staff1 = Membership.objects.create(
            user=self.staff1,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Anita Seller',
        )

        self.staff_inactive = User.objects.create_user(username='s4_inactive', password='Password123!')
        self.m_inactive = Membership.objects.create(
            user=self.staff_inactive,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Inactive Seller',
            is_active=False,
        )

        # Other store with its own staff
        self.other_owner = User.objects.create_user(username='s4_other_owner', password='Password123!')
        self.other_store = Store.objects.create(
            owner=self.other_owner,
            name='Other Franchise',
            slug='s4-other-franchise',
            plan=self.plan_franchise,
        )
        Membership.objects.create(
            user=self.other_owner,
            store=self.other_store,
            role=Membership.ROLE_OWNER,
            display_name='Other Owner',
        )
        self.other_staff = User.objects.create_user(username='s4_other_staff', password='Password123!')
        self.m_other_staff = Membership.objects.create(
            user=self.other_staff,
            store=self.other_store,
            role=Membership.ROLE_STAFF,
            display_name='Other Store Staff',
        )

        # Products
        self.cat = Category.objects.create(store=self.store, name='Beverages', sort_order=1)
        self.p1 = Product.objects.create(
            store=self.store,
            category=self.cat,
            name='Cold Brew',
            price=Decimal('145.50'),
            is_available=True,
            created_by=self.owner,
        )
        self.p2 = Product.objects.create(
            store=self.store,
            category=self.cat,
            name='Croissant',
            price=Decimal('89.25'),
            is_available=True,
            created_by=self.owner,
        )
        self.other_product = Product.objects.create(
            store=self.other_store,
            name='Secret Item',
            price=Decimal('500.00'),
            is_available=True,
            created_by=self.other_owner,
        )

    def test_staff_read_only_catalog_and_counter_order_creation(self):
        self.client.login(username='s4_staff1', password='Password123!')

        # Read-only catalog shows store products and not other store's products
        cat_resp = self.client.get(reverse('dashboard:staff_catalog'))
        self.assertEqual(cat_resp.status_code, 200)
        self.assertContains(cat_resp, 'Cold Brew')
        self.assertContains(cat_resp, 'Croissant')
        self.assertNotContains(cat_resp, 'Secret Item')

        # Staff creates a counter order via the dashboard form
        get_resp = self.client.get(reverse('dashboard:counter_order_add'))
        self.assertEqual(get_resp.status_code, 200)

        post_resp = self.client.post(
            reverse('dashboard:counter_order_add'),
            {
                'customer_name': 'Meera Kapoor',
                'customer_phone': '9876543210',
                'note': 'Counter pickup',
                f'quantity_{self.p1.pk}': '2',
                f'quantity_{self.p2.pk}': '3',
            },
        )
        self.assertEqual(post_resp.status_code, 302)

        order = Order.objects.get(store=self.store, customer_name='Meera Kapoor')
        self.assertEqual(order.placed_by, self.staff1)
        expected_total = (Decimal('145.50') * 2) + (Decimal('89.25') * 3)
        self.assertEqual(order.total, expected_total)

        items = list(order.items.order_by('id'))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].product_name_snapshot, 'Cold Brew')
        self.assertEqual(items[0].unit_price_snapshot, Decimal('145.50'))
        self.assertEqual(items[0].quantity, 2)
        self.assertEqual(items[1].product_name_snapshot, 'Croissant')
        self.assertEqual(items[1].unit_price_snapshot, Decimal('89.25'))
        self.assertEqual(items[1].quantity, 3)

        # Attempting to order another store's product is rejected
        bad_resp = self.client.post(
            reverse('dashboard:counter_order_add'),
            {
                'customer_name': 'Bad Order',
                'customer_phone': '1112223333',
                f'quantity_{self.other_product.pk}': '1',
            },
        )
        self.assertEqual(bad_resp.status_code, 400)
        self.assertFalse(Order.objects.filter(customer_name='Bad Order').exists())

    def test_personal_qr_returns_png_encoding_staff_referral_url(self):
        from stores.views import generate_qr_png_response_for_url

        self.client.login(username='s4_staff1', password='Password123!')

        page_resp = self.client.get(reverse('dashboard:my_qr'))
        self.assertEqual(page_resp.status_code, 200)
        expected_rel_url = f"/s/{self.store.slug}/?ref={self.m_staff1.referral_code}"
        self.assertContains(page_resp, expected_rel_url)

        qr_resp = self.client.get(reverse('dashboard:my_qr_download'))
        self.assertEqual(qr_resp.status_code, 200)
        self.assertEqual(qr_resp['Content-Type'], 'image/png')
        self.assertTrue(qr_resp.content.startswith(b'\x89PNG\r\n\x1a\n'))

        expected_abs_url = f"http://testserver/s/{self.store.slug}/?ref={self.m_staff1.referral_code}"
        self.assertEqual(qr_resp['X-QR-Target-URL'], expected_abs_url)
        expected_png = generate_qr_png_response_for_url(expected_abs_url, 'test.png').content
        self.assertEqual(qr_resp.content, expected_png)

        # Owner can also download this staff member's QR and gets identical PNG bytes
        self.client.login(username='s4_owner', password='Password123!')
        owner_qr_resp = self.client.get(reverse('dashboard:staff_qr', args=[self.m_staff1.pk]))
        self.assertEqual(owner_qr_resp.status_code, 200)
        self.assertEqual(owner_qr_resp['Content-Type'], 'image/png')
        self.assertEqual(owner_qr_resp['X-QR-Target-URL'], expected_abs_url)
        self.assertEqual(owner_qr_resp.content, expected_png)

        # Plan 1 store requesting personal QR endpoints gets 403
        u_p1 = User.objects.create_user(username='p1_qr_owner', password='Password123!')
        s_p1 = Store.objects.create(owner=u_p1, name='P1 QR', slug='p1-qr', plan=self.plan_offline)
        Membership.objects.create(user=u_p1, store=s_p1, role=Membership.ROLE_OWNER)
        self.client.login(username='p1_qr_owner', password='Password123!')
        self.assertIn(self.client.get(reverse('dashboard:my_qr')).status_code, (403, 404))
        self.assertIn(self.client.get(reverse('dashboard:my_qr_download')).status_code, (403, 404))

    def _place_storefront_order_with_ref(self, ref_query, customer_name):
        from django.test import Client
        c = Client()
        sf_url = reverse('storefront:detail', args=[self.store.slug])
        if ref_query is not None:
            sf_url = f"{sf_url}?ref={ref_query}"
        r_visit = c.get(sf_url)
        self.assertEqual(r_visit.status_code, 200)

        c.post(
            reverse('storefront:cart_add', args=[self.store.slug]),
            {'product_id': self.p1.pk, 'quantity': 1},
        )
        r_chk = c.post(
            reverse('storefront:checkout', args=[self.store.slug]),
            {
                'customer_name': customer_name,
                'customer_phone': '9000011111',
                'note': '',
            },
        )
        self.assertEqual(r_chk.status_code, 302)
        return Order.objects.get(store=self.store, customer_name=customer_name)

    def test_referral_attribution_valid_invalid_other_store_deactivated_and_direct(self):
        # 1. Valid staff referral code -> order.placed_by == staff_user
        order_valid = self._place_storefront_order_with_ref(
            self.m_staff1.referral_code,
            'Customer Valid Ref',
        )
        self.assertEqual(order_valid.placed_by, self.staff1)

        # 2. Invalid referral code -> checkout succeeds, order.placed_by is None
        order_invalid = self._place_storefront_order_with_ref(
            'INVALID_CODE_999',
            'Customer Invalid Ref',
        )
        self.assertIsNone(order_invalid.placed_by)

        # 3. Referral code belonging to staff of ANOTHER store -> order.placed_by is None
        order_other_store = self._place_storefront_order_with_ref(
            self.m_other_staff.referral_code,
            'Customer Other Store Ref',
        )
        self.assertIsNone(order_other_store.placed_by)

        # 4. Referral code of a DEACTIVATED staff member -> order.placed_by is None
        order_deactivated = self._place_storefront_order_with_ref(
            self.m_inactive.referral_code,
            'Customer Deactivated Staff Ref',
        )
        self.assertIsNone(order_deactivated.placed_by)

        # 5. Normal store visit with no ref -> order.placed_by is None
        order_direct = self._place_storefront_order_with_ref(
            None,
            'Customer Direct No Ref',
        )
        self.assertIsNone(order_direct.placed_by)


class Plan2Stage5SoldByAndSalesReportTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone

        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)

        self.owner = User.objects.create_user(username='s5_owner', password='Password123!')
        self.store = Store.objects.create(
            owner=self.owner,
            name='Stage 5 Franchise',
            slug='s5-franchise',
            plan=self.plan_franchise,
            extra_seats=2,
        )
        Membership.objects.create(
            user=self.owner,
            store=self.store,
            role=Membership.ROLE_OWNER,
            display_name='S5 Owner',
        )

        self.staff1 = User.objects.create_user(username='s5_staff1', password='Password123!')
        self.m_staff1 = Membership.objects.create(
            user=self.staff1,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Rohan Seller',
        )

        self.staff2 = User.objects.create_user(username='s5_staff2', password='Password123!')
        self.m_staff2 = Membership.objects.create(
            user=self.staff2,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Sneha Seller',
        )

        self.cat = Category.objects.create(store=self.store, name='Bakery', sort_order=1)
        self.prod_bread = Product.objects.create(
            store=self.store,
            category=self.cat,
            name='Sourdough Bread',
            price=Decimal('150.00'),
            is_available=True,
            created_by=self.owner,
        )
        self.prod_cake = Product.objects.create(
            store=self.store,
            category=self.cat,
            name='Chocolate Tart',
            price=Decimal('225.50'),
            is_available=True,
            created_by=self.owner,
        )
        self.today = timezone.now().date()
        self.old_dt = timezone.now() - timedelta(days=60)

    def _create_order(self, placed_by, status, items_spec, customer_name='Customer', created_at_override=None):
        order = Order.objects.create(
            store=self.store,
            customer_name=customer_name,
            customer_phone='9876500000',
            status=status,
            placed_by=placed_by,
        )
        for product, qty in items_spec:
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name_snapshot=product.name,
                unit_price_snapshot=product.price,
                quantity=qty,
            )
        order.recalculate_total(save=True)
        if created_at_override is not None:
            Order.objects.filter(pk=order.pk).update(created_at=created_at_override)
            order.refresh_from_db()
        return order

    def test_owner_orders_list_sold_by_column_and_staff_filter(self):
        o_staff1 = self._create_order(
            self.staff1,
            Order.STATUS_PAID,
            [(self.prod_bread, 1)],
            customer_name='Buyer From Rohan',
        )
        o_staff2 = self._create_order(
            self.staff2,
            Order.STATUS_NEW,
            [(self.prod_cake, 1)],
            customer_name='Buyer From Sneha',
        )
        o_direct = self._create_order(
            None,
            Order.STATUS_COMPLETED,
            [(self.prod_bread, 2)],
            customer_name='Buyer Direct',
        )

        self.client.login(username='s5_owner', password='Password123!')

        # Full list shows all 3 and Sold by labels
        resp_all = self.client.get(reverse('dashboard:order_list'))
        self.assertEqual(resp_all.status_code, 200)
        self.assertContains(resp_all, 'Rohan Seller')
        self.assertContains(resp_all, 'Sneha Seller')
        self.assertContains(resp_all, 'Owner/Direct')

        # Filter by staff1
        resp_s1 = self.client.get(f"{reverse('dashboard:order_list')}?staff={self.staff1.pk}")
        self.assertEqual(resp_s1.status_code, 200)
        self.assertContains(resp_s1, o_staff1.order_number)
        self.assertNotContains(resp_s1, o_staff2.order_number)
        self.assertNotContains(resp_s1, o_direct.order_number)

        # Filter by direct
        resp_dir = self.client.get(f"{reverse('dashboard:order_list')}?staff=direct")
        self.assertEqual(resp_dir.status_code, 200)
        self.assertContains(resp_dir, o_direct.order_number)
        self.assertNotContains(resp_dir, o_staff1.order_number)
        self.assertNotContains(resp_dir, o_staff2.order_number)

    def test_sales_report_accuracy_date_range_permissions_and_query_ceiling(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Staff 1 orders:
        # 1. PAID: 2 x Bread (300.00) + 1 x Cake (225.50) = 525.50 (3 units)
        self._create_order(
            self.staff1,
            Order.STATUS_PAID,
            [(self.prod_bread, 2), (self.prod_cake, 1)],
        )
        # 2. COMPLETED: 1 x Cake (225.50) = 225.50 (1 unit)
        self._create_order(
            self.staff1,
            Order.STATUS_COMPLETED,
            [(self.prod_cake, 1)],
        )
        # 3. NEW (pending): 3 x Bread (450.00) -> counted in orders & pending & units, NOT revenue
        self._create_order(
            self.staff1,
            Order.STATUS_NEW,
            [(self.prod_bread, 3)],
        )
        # 4. CANCELLED: 5 x Bread (750.00) -> excluded from counts, units, and revenue
        self._create_order(
            self.staff1,
            Order.STATUS_CANCELLED,
            [(self.prod_bread, 5)],
        )

        # Staff 2 orders:
        # 1. PAID: 4 x Bread (600.00) (4 units)
        self._create_order(
            self.staff2,
            Order.STATUS_PAID,
            [(self.prod_bread, 4)],
        )
        # 2. CONFIRMED (pending): 2 x Cake (451.00) -> pending, NOT revenue
        self._create_order(
            self.staff2,
            Order.STATUS_CONFIRMED,
            [(self.prod_cake, 2)],
        )

        # Unattributed (Direct) orders:
        # 1. COMPLETED: 1 x Bread (150.00) + 2 x Cake (451.00) = 601.00 (3 units)
        self._create_order(
            None,
            Order.STATUS_COMPLETED,
            [(self.prod_bread, 1), (self.prod_cake, 2)],
        )
        # 2. NEW (pending): 1 x Bread (150.00) (1 unit, 0 revenue)
        self._create_order(
            None,
            Order.STATUS_NEW,
            [(self.prod_bread, 1)],
        )
        # 3. CANCELLED: 2 x Cake -> excluded
        self._create_order(
            None,
            Order.STATUS_CANCELLED,
            [(self.prod_cake, 2)],
        )

        # Out-of-range order (60 days ago, PAID, 10 x Bread = 1500.00)
        self._create_order(
            self.staff1,
            Order.STATUS_PAID,
            [(self.prod_bread, 10)],
            created_at_override=self.old_dt,
        )

        # Permission checks on sales report:
        report_url = reverse('dashboard:sales_report')
        self.assertEqual(self.client.get(report_url).status_code, 302)

        self.client.login(username='s5_staff1', password='Password123!')
        self.assertEqual(self.client.get(report_url).status_code, 403)

        u_p1 = User.objects.create_user(username='s5_p1_owner', password='Password123!')
        s_p1 = Store.objects.create(owner=u_p1, name='S5 P1', slug='s5-p1', plan=self.plan_offline)
        Membership.objects.create(user=u_p1, store=s_p1, role=Membership.ROLE_OWNER)
        self.client.login(username='s5_p1_owner', password='Password123!')
        self.assertIn(self.client.get(report_url).status_code, (403, 404))

        # Owner logs in and requests default 30-day sales report
        self.client.login(username='s5_owner', password='Password123!')
        with CaptureQueriesContext(connection) as queries_initial:
            resp = self.client.get(report_url)
        self.assertEqual(resp.status_code, 200)
        initial_query_count = len(queries_initial)
        self.assertLessEqual(initial_query_count, 10)

        rows_by_name = {r['seller_name']: r for r in resp.context['report_rows']}

        # Assert Staff 1 (Rohan Seller) exact numbers (out-of-range 60d order and cancelled order excluded)
        r_s1 = rows_by_name['Rohan Seller']
        self.assertEqual(r_s1['orders_count'], 3)          # 1 paid + 1 completed + 1 new
        self.assertEqual(r_s1['pending_count'], 1)         # 1 new
        self.assertEqual(r_s1['paid_completed_count'], 2)  # 1 paid + 1 completed
        self.assertEqual(r_s1['units_sold'], 7)            # (2+1) + 1 + 3
        self.assertEqual(r_s1['revenue'], Decimal('751.00'))  # 525.50 + 225.50
        s1_prods = {p['product_name']: p for p in r_s1['products']}
        self.assertEqual(s1_prods['Sourdough Bread']['units_sold'], 5)  # 2 paid + 3 new
        self.assertEqual(s1_prods['Sourdough Bread']['revenue'], Decimal('300.00'))  # only 2 paid
        self.assertEqual(s1_prods['Chocolate Tart']['units_sold'], 2)   # 1 paid + 1 completed
        self.assertEqual(s1_prods['Chocolate Tart']['revenue'], Decimal('451.00'))

        # Assert Staff 2 (Sneha Seller) exact numbers
        r_s2 = rows_by_name['Sneha Seller']
        self.assertEqual(r_s2['orders_count'], 2)          # 1 paid + 1 confirmed
        self.assertEqual(r_s2['pending_count'], 1)         # 1 confirmed
        self.assertEqual(r_s2['paid_completed_count'], 1)  # 1 paid
        self.assertEqual(r_s2['units_sold'], 6)            # 4 + 2
        self.assertEqual(r_s2['revenue'], Decimal('600.00'))
        s2_prods = {p['product_name']: p for p in r_s2['products']}
        self.assertEqual(s2_prods['Sourdough Bread']['units_sold'], 4)
        self.assertEqual(s2_prods['Sourdough Bread']['revenue'], Decimal('600.00'))
        self.assertEqual(s2_prods['Chocolate Tart']['units_sold'], 2)
        self.assertEqual(s2_prods['Chocolate Tart']['revenue'], Decimal('0.00'))  # confirmed is pending

        # Assert Direct / unattributed exact numbers
        r_dir = rows_by_name['Direct / unattributed']
        self.assertEqual(r_dir['orders_count'], 2)         # 1 completed + 1 new
        self.assertEqual(r_dir['pending_count'], 1)        # 1 new
        self.assertEqual(r_dir['paid_completed_count'], 1) # 1 completed
        self.assertEqual(r_dir['units_sold'], 4)           # (1+2) + 1
        self.assertEqual(r_dir['revenue'], Decimal('601.00'))
        dir_prods = {p['product_name']: p for p in r_dir['products']}
        self.assertEqual(dir_prods['Sourdough Bread']['units_sold'], 2)  # 1 completed + 1 new
        self.assertEqual(dir_prods['Sourdough Bread']['revenue'], Decimal('150.00'))
        self.assertEqual(dir_prods['Chocolate Tart']['units_sold'], 2)
        self.assertEqual(dir_prods['Chocolate Tart']['revenue'], Decimal('451.00'))

        # Assert Grand Totals
        gt = resp.context['grand_totals']
        self.assertEqual(gt['orders_count'], 7)            # 3 + 2 + 2
        self.assertEqual(gt['pending_count'], 3)           # 1 + 1 + 1
        self.assertEqual(gt['paid_completed_count'], 4)    # 2 + 1 + 1
        self.assertEqual(gt['units_sold'], 17)             # 7 + 6 + 4
        self.assertEqual(gt['revenue'], Decimal('1952.00'))  # 751.00 + 600.00 + 601.00

        # Date range filter including 60 days ago includes the 1500.00 order
        wide_start = (self.old_dt.date()).isoformat()
        wide_end = self.today.isoformat()
        resp_wide = self.client.get(f"{report_url}?start_date={wide_start}&end_date={wide_end}")
        self.assertEqual(resp_wide.status_code, 200)
        self.assertEqual(resp_wide.context['grand_totals']['revenue'], Decimal('3452.00'))

        # Add 10 more orders and verify query count does NOT grow with order count
        for i in range(10):
            self._create_order(
                self.staff1 if i % 2 == 0 else self.staff2,
                Order.STATUS_PAID,
                [(self.prod_bread, 1), (self.prod_cake, 2)],
                customer_name=f'Bulk Buyer {i}',
            )
        with CaptureQueriesContext(connection) as queries_after_bulk:
            resp_bulk = self.client.get(report_url)
        self.assertEqual(resp_bulk.status_code, 200)
        self.assertEqual(len(queries_after_bulk), initial_query_count)


class Plan3Stage1ModelAndMigrationTests(TestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(username='p3_owner_a', password='Password123!')
        self.owner_b = User.objects.create_user(username='p3_owner_b', password='Password123!')
        self.plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.plan_online = Plan.objects.get(slug=Plan.SLUG_ONLINE)

        self.store_a = Store.objects.create(
            owner=self.owner_a,
            name='Online Store A',
            slug='online-store-a',
            plan=self.plan_online,
        )
        Membership.objects.create(
            user=self.owner_a,
            store=self.store_a,
            role=Membership.ROLE_OWNER,
        )

        self.store_b = Store.objects.create(
            owner=self.owner_b,
            name='Online Store B',
            slug='online-store-b',
            plan=self.plan_online,
        )
        Membership.objects.create(
            user=self.owner_b,
            store=self.store_b,
            role=Membership.ROLE_OWNER,
        )

    def test_online_plan_seed_and_store_defaults(self):
        self.assertEqual(self.plan_offline.max_users, 1)
        self.assertEqual(self.plan_franchise.max_users, 2)
        self.assertEqual(self.plan_online.max_users, 5)
        self.assertTrue(self.plan_online.features.get('staff'))
        self.assertTrue(self.plan_online.features.get('sales_report'))
        self.assertTrue(self.plan_online.features.get('online_app'))
        self.assertTrue(self.store_a.has_online_features())
        self.assertTrue(self.store_a.has_franchise_features())

        # Verify Store defaults from <model_changes>
        self.assertFalse(self.store_a.online_ordering_open)
        self.assertTrue(self.store_a.pickup_enabled)
        self.assertFalse(self.store_a.delivery_enabled)
        self.assertEqual(self.store_a.delivery_fee, Decimal('0.00'))
        self.assertIsNone(self.store_a.free_delivery_above)
        self.assertEqual(self.store_a.minimum_order_amount, Decimal('0.00'))
        self.assertTrue(self.store_a.accept_upi_qr)
        self.assertTrue(self.store_a.accept_cod)

    def test_customer_model_per_store_phone_uniqueness_and_password_hashing(self):
        from django.db import IntegrityError
        from stores.models import Customer, CustomerAddress

        raw_pw = 'CustSecret99!'
        c_a = Customer.objects.create(
            store=self.store_a,
            name='Asha Verma',
            phone='9876543210',
            password=raw_pw,
        )
        self.assertNotEqual(c_a.password, raw_pw)
        self.assertTrue(c_a.check_password(raw_pw))

        # Same phone can register at Store B independently
        c_b = Customer.objects.create(
            store=self.store_b,
            name='Asha Verma B',
            phone='9876543210',
            password=raw_pw,
        )
        self.assertEqual(c_b.phone, c_a.phone)

        # Duplicate phone at the same store fails
        from django.db import transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Customer.objects.create(
                    store=self.store_a,
                    name='Duplicate',
                    phone='9876543210',
                    password=raw_pw,
                )

        # Address book default switching
        addr1 = CustomerAddress.objects.create(
            customer=c_a,
            label='Home',
            address_line='12 MG Road',
            landmark='Near Metro',
            pincode='560001',
        )
        self.assertTrue(addr1.is_default)
        addr2 = CustomerAddress.objects.create(
            customer=c_a,
            label='Office',
            address_line='45 Brigade Road',
            pincode='560025',
            is_default=True,
        )
        addr1.refresh_from_db()
        self.assertFalse(addr1.is_default)
        self.assertTrue(addr2.is_default)

    def test_order_status_event_data_migration_backfills_exactly_one_per_order(self):
        from importlib import import_module
        from django.apps import apps
        from orders.models import OrderStatusEvent

        o1 = Order.objects.create(
            store=self.store_a,
            customer_name='Legacy Buyer 1',
            customer_phone='9111111111',
            status=Order.STATUS_NEW,
        )
        o2 = Order.objects.create(
            store=self.store_a,
            customer_name='Legacy Buyer 2',
            customer_phone='9222222222',
            status=Order.STATUS_COMPLETED,
            placed_by=self.owner_a,
        )

        # Simulate pre-existing orders prior to migration 0003 by deleting their events
        OrderStatusEvent.objects.filter(order__in=[o1, o2]).delete()
        self.assertEqual(OrderStatusEvent.objects.filter(order__in=[o1, o2]).count(), 0)

        mig_0003 = import_module('orders.migrations.0003_backfill_order_status_events')
        mig_0003.backfill_order_status_events(apps, None)

        self.assertEqual(OrderStatusEvent.objects.filter(order=o1).count(), 1)
        self.assertEqual(OrderStatusEvent.objects.filter(order=o2).count(), 1)
        self.assertEqual(OrderStatusEvent.objects.get(order=o1).status, Order.STATUS_NEW)
        self.assertEqual(OrderStatusEvent.objects.get(order=o2).status, Order.STATUS_COMPLETED)
        self.assertEqual(OrderStatusEvent.objects.get(order=o2).changed_by, self.owner_a)

        # Running backfill a second time is idempotent (still 1 event per order)
        mig_0003.backfill_order_status_events(apps, None)
        self.assertEqual(OrderStatusEvent.objects.filter(order=o1).count(), 1)
        self.assertEqual(OrderStatusEvent.objects.filter(order=o2).count(), 1)

    def test_new_plan_3_models_registered_in_admin(self):
        from django.contrib import admin
        from orders.models import OrderStatusEvent
        from stores.models import Customer, CustomerAddress

        for model in (Customer, CustomerAddress, OrderStatusEvent):
            self.assertIn(model, admin.site._registry, f"{model.__name__} not registered in admin")


class Plan3Stage2CustomerAuthAndAddressesTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

        self.plan_offline = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.plan_franchise = Plan.objects.get(slug=Plan.SLUG_FRANCHISE)
        self.plan_online = Plan.objects.get(slug=Plan.SLUG_ONLINE)

        self.owner_x = User.objects.create_user(username='s2_owner_x', password='Password123!')
        self.store_x = Store.objects.create(
            owner=self.owner_x,
            name='Store X Online',
            slug='store-x-online',
            plan=self.plan_online,
            online_ordering_open=False,
        )
        Membership.objects.create(user=self.owner_x, store=self.store_x, role=Membership.ROLE_OWNER)

        self.owner_y = User.objects.create_user(username='s2_owner_y', password='Password123!')
        self.store_y = Store.objects.create(
            owner=self.owner_y,
            name='Store Y Online',
            slug='store-y-online',
            plan=self.plan_online,
            online_ordering_open=True,
        )
        Membership.objects.create(user=self.owner_y, store=self.store_y, role=Membership.ROLE_OWNER)

        self.owner_p1 = User.objects.create_user(username='s2_owner_p1', password='Password123!')
        self.store_p1 = Store.objects.create(
            owner=self.owner_p1,
            name='Store P1 Offline',
            slug='store-p1-offline',
            plan=self.plan_offline,
        )
        Membership.objects.create(user=self.owner_p1, store=self.store_p1, role=Membership.ROLE_OWNER)

        self.owner_p2 = User.objects.create_user(username='s2_owner_p2', password='Password123!')
        self.store_p2 = Store.objects.create(
            owner=self.owner_p2,
            name='Store P2 Franchise',
            slug='store-p2-franchise',
            plan=self.plan_franchise,
        )
        Membership.objects.create(user=self.owner_p2, store=self.store_p2, role=Membership.ROLE_OWNER)

    def test_feature_gate_plan1_and_plan2_return_404_on_customer_urls(self):
        for non_online_store in (self.store_p1, self.store_p2):
            for url_name in ('customer_register', 'customer_login', 'customer_account', 'address_add'):
                url = reverse(f'storefront:{url_name}', args=[non_online_store.slug])
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 404, f"Expected 404 for {url}")

            # Offline QR checkout still works on Plan 1 and Plan 2
            chk_resp = self.client.get(reverse('storefront:checkout', args=[non_online_store.slug]))
            self.assertEqual(chk_resp.status_code, 200)

    def test_customer_registration_hashing_duplicate_phone_lockout_and_session_scoping(self):
        from django.core.cache import cache
        from stores.models import Customer

        raw_pw = 'CustStrongPass77!'
        reg_url_x = reverse('storefront:customer_register', args=[self.store_x.slug])

        # 1. Register customer at Store X
        reg_resp = self.client.post(
            reg_url_x,
            {'name': 'Vikram Rao', 'phone': '9811122233', 'password': raw_pw},
            follow=True,
        )
        self.assertEqual(reg_resp.status_code, 200)
        self.assertNotContains(reg_resp, raw_pw)

        cust_x = Customer.objects.get(store=self.store_x, phone='9811122233')
        self.assertNotEqual(cust_x.password, raw_pw)
        self.assertTrue(cust_x.check_password(raw_pw))

        # 2. Customer session from Store X is NOT valid at Store Y
        acct_y_resp = self.client.get(reverse('storefront:customer_account', args=[self.store_y.slug]))
        self.assertEqual(acct_y_resp.status_code, 302)
        self.assertIn(reverse('storefront:customer_login', args=[self.store_y.slug]), acct_y_resp['Location'])

        # 3. Customer cannot reach any /dashboard/ URL
        for dash_url in (
            reverse('dashboard:home'),
            reverse('dashboard:product_list'),
            reverse('dashboard:order_list'),
            reverse('dashboard:settings'),
        ):
            r_dash = self.client.get(dash_url)
            self.assertIn(r_dash.status_code, (302, 403))

        # 4. Duplicate phone at the same store fails
        self.client.post(reverse('storefront:customer_logout', args=[self.store_x.slug]))
        dup_resp = self.client.post(
            reg_url_x,
            {'name': 'Vikram Dup', 'phone': '9811122233', 'password': raw_pw},
        )
        self.assertEqual(dup_resp.status_code, 400)
        self.assertContains(dup_resp, 'already exists', status_code=400)

        # 5. Same phone CAN register at Store Y independently
        reg_url_y = reverse('storefront:customer_register', args=[self.store_y.slug])
        reg_y_resp = self.client.post(
            reg_url_y,
            {'name': 'Vikram Store Y', 'phone': '9811122233', 'password': 'OtherPassword88!'},
        )
        self.assertEqual(reg_y_resp.status_code, 302)
        self.assertTrue(Customer.objects.filter(store=self.store_y, phone='9811122233').exists())

        # 6. Login throttling: 5 failed attempts trigger 10-minute lockout
        login_url_x = reverse('storefront:customer_login', args=[self.store_x.slug])
        for attempt in range(1, 6):
            fail_resp = self.client.post(
                login_url_x,
                {'phone': '9811122233', 'password': 'WrongPassword000!'},
            )
            self.assertEqual(fail_resp.status_code, 400)

        # 6th attempt even with the CORRECT password fails while locked out
        locked_resp = self.client.post(
            login_url_x,
            {'phone': '9811122233', 'password': raw_pw},
        )
        self.assertEqual(locked_resp.status_code, 400)
        self.assertContains(locked_resp, 'locked', status_code=400)

        # Simulate lockout window expiring (clear cache) -> login with valid password succeeds
        cache.clear()
        ok_resp = self.client.post(
            login_url_x,
            {'phone': '9811122233', 'password': raw_pw},
        )
        self.assertEqual(ok_resp.status_code, 302)

    def test_customer_address_book_crud_and_isolation_and_online_banner(self):
        from stores.models import Customer, CustomerAddress

        cust_a = Customer.objects.create(
            store=self.store_x,
            name='Customer A',
            phone='9700000001',
            password='Password123!',
        )
        cust_b = Customer.objects.create(
            store=self.store_x,
            name='Customer B',
            phone='9700000002',
            password='Password123!',
        )
        addr_b = CustomerAddress.objects.create(
            customer=cust_b,
            label='B Home',
            address_line='99 Secret Lane',
            pincode='400001',
        )

        # Log in as Customer A
        self.client.post(
            reverse('storefront:customer_login', args=[self.store_x.slug]),
            {'phone': '9700000001', 'password': 'Password123!'},
        )

        # Add address for Customer A
        add_resp = self.client.post(
            reverse('storefront:address_add', args=[self.store_x.slug]),
            {
                'label': 'Home',
                'address_line': '10 Park Street',
                'landmark': 'Opposite Bakery',
                'pincode': '700016',
                'is_default': 'on',
            },
        )
        self.assertEqual(add_resp.status_code, 302)
        addr_a = CustomerAddress.objects.get(customer=cust_a)
        self.assertEqual(addr_a.pincode, '700016')

        # Customer A cannot edit, delete, or set default on Customer B's address (404)
        self.assertEqual(
            self.client.get(reverse('storefront:address_edit', args=[self.store_x.slug, addr_b.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse('storefront:address_edit', args=[self.store_x.slug, addr_b.pk]),
                {'label': 'Hacked', 'address_line': 'Hacked', 'pincode': '000000'},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse('storefront:address_delete', args=[self.store_x.slug, addr_b.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse('storefront:address_set_default', args=[self.store_x.slug, addr_b.pk])).status_code,
            404,
        )
        self.assertTrue(CustomerAddress.objects.filter(pk=addr_b.pk, label='B Home').exists())

        # Store X is closed -> shows ordering closed banner across all 3 templates
        for tpl in (Store.TEMPLATE_CLASSIC, Store.TEMPLATE_MINIMAL, Store.TEMPLATE_BOLD):
            self.store_x.template_key = tpl
            self.store_x.save()
            sf_resp = self.client.get(reverse('storefront:detail', args=[self.store_x.slug]))
            self.assertEqual(sf_resp.status_code, 200)
            self.assertContains(sf_resp, 'Online ordering is currently closed')
            self.assertContains(sf_resp, 'Customer A')









