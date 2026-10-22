from decimal import Decimal
import io
import shutil
import tempfile
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from catalog.models import Category, Product
from orders.models import Order
from stores.models import Plan, Store, Membership, PaymentQR

User = get_user_model()


def make_test_png():
    buf = io.BytesIO()
    img = Image.new('RGB', (24, 24), color=(10, 120, 80))
    img.save(buf, format='PNG')
    return buf.getvalue()


class StorefrontAndCheckoutTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.temp_media)
        self.override.enable()

        self.owner = User.objects.create_user(username='merchant', password='password123')
        self.plan = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.store = Store.objects.create(
            owner=self.owner,
            name='Fresh Mart',
            slug='fresh-mart',
            plan=self.plan,
            template_key=Store.TEMPLATE_CLASSIC,
            is_active=True,
        )
        Membership.objects.create(user=self.owner, store=self.store, role=Membership.ROLE_OWNER)

        self.cat_fruits = Category.objects.create(store=self.store, name='Fruits', sort_order=1)
        self.cat_dairy = Category.objects.create(store=self.store, name='Dairy', sort_order=2)

        self.prod_apple = Product.objects.create(
            store=self.store,
            category=self.cat_fruits,
            name='Organic Apples',
            price=Decimal('120.50'),
            is_available=True,
            created_by=self.owner,
        )
        self.prod_milk = Product.objects.create(
            store=self.store,
            category=self.cat_dairy,
            name='Almond Milk',
            price=Decimal('210.00'),
            is_available=True,
            created_by=self.owner,
        )
        self.prod_hidden = Product.objects.create(
            store=self.store,
            category=self.cat_fruits,
            name='Out of Season Mango',
            price=Decimal('300.00'),
            is_available=False,
            created_by=self.owner,
        )

        qr_file = SimpleUploadedFile('upi_qr.png', make_test_png(), content_type='image/png')
        self.payment_qr = PaymentQR.objects.create(
            store=self.store,
            upi_id='freshmart@upi',
            qr_image=qr_file,
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_storefront_returns_200_for_all_three_templates(self):
        url = reverse('storefront:detail', args=[self.store.slug])
        for key, expected_template in [
            (Store.TEMPLATE_CLASSIC, 'storefront/classic.html'),
            (Store.TEMPLATE_MINIMAL, 'storefront/minimal.html'),
            (Store.TEMPLATE_BOLD, 'storefront/bold.html'),
        ]:
            self.store.template_key = key
            self.store.save()
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, expected_template)
            self.assertContains(resp, 'Organic Apples')
            self.assertNotContains(resp, 'Out of Season Mango')

    def test_inactive_store_returns_404(self):
        self.store.is_active = False
        self.store.save()
        url = reverse('storefront:detail', args=[self.store.slug])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_category_filter_on_storefront(self):
        url = reverse('storefront:detail', args=[self.store.slug])
        resp = self.client.get(f"{url}?category={self.cat_fruits.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Organic Apples')
        self.assertNotContains(resp, 'Almond Milk')

    def test_full_cart_to_order_checkout_flow(self):
        add_url = reverse('storefront:cart_add', args=[self.store.slug])
        self.client.post(add_url, {'product_id': self.prod_apple.pk, 'quantity': 2})
        self.client.post(add_url, {'product_id': self.prod_milk.pk, 'quantity': 1})

        checkout_url = reverse('storefront:checkout', args=[self.store.slug])
        resp = self.client.post(
            checkout_url,
            {
                'customer_name': 'Rahul Sharma',
                'customer_phone': '9988776655',
                'note': 'Leave at door',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.filter(store=self.store).count(), 1)

        order = Order.objects.get(store=self.store)
        expected_total = (Decimal('120.50') * 2) + Decimal('210.00')
        self.assertEqual(order.total, expected_total)
        self.assertEqual(order.customer_name, 'Rahul Sharma')
        self.assertEqual(order.items.count(), 2)

        confirm_resp = self.client.get(resp['Location'])
        self.assertEqual(confirm_resp.status_code, 200)
        self.assertContains(confirm_resp, order.order_number)
        self.assertContains(confirm_resp, str(expected_total))
        self.assertContains(confirm_resp, 'freshmart@upi')
        self.assertContains(confirm_resp, self.payment_qr.qr_image.url)

    def test_full_end_to_end_owner_and_customer_journey(self):
        # 1. Owner signs up
        signup_resp = self.client.post(
            reverse('accounts:signup'),
            {
                'username': 'e2e_owner',
                'email': 'e2e@example.com',
                'store_name': 'E2E Artisans',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )
        self.assertEqual(signup_resp.status_code, 302)
        store = Store.objects.get(slug='e2e-artisans')

        # 2. Add a product with an image in the dashboard
        img = SimpleUploadedFile('item.png', make_test_png(), content_type='image/png')
        prod_resp = self.client.post(
            reverse('dashboard:product_add'),
            {
                'name': 'Handmade Mug',
                'description': 'Ceramic mug',
                'price': '450.00',
                'image': img,
                'is_available': True,
            },
        )
        self.assertEqual(prod_resp.status_code, 302)
        product = Product.objects.get(store=store, name='Handmade Mug')

        # 3. Download store QR from dashboard
        qr_resp = self.client.get(reverse('dashboard:store_qr'))
        self.assertEqual(qr_resp.status_code, 200)
        self.assertEqual(qr_resp['Content-Type'], 'image/png')
        self.assertTrue(qr_resp.content.startswith(b'\x89PNG\r\n\x1a\n'))

        # 4. Customer opens /s/<slug>/, adds to cart, and places an order
        sf_resp = self.client.get(reverse('storefront:detail', args=[store.slug]))
        self.assertEqual(sf_resp.status_code, 200)
        self.assertContains(sf_resp, 'Handmade Mug')

        self.client.post(
            reverse('storefront:cart_add', args=[store.slug]),
            {'product_id': product.pk, 'quantity': 2},
        )
        chk_resp = self.client.post(
            reverse('storefront:checkout', args=[store.slug]),
            {
                'customer_name': 'Priya Nair',
                'customer_phone': '9123456780',
                'note': 'Gift wrap please',
            },
        )
        self.assertEqual(chk_resp.status_code, 302)

        # 5. Owner sees the order in the dashboard and updates its status
        order = Order.objects.get(store=store)
        self.assertEqual(order.total, Decimal('900.00'))
        orders_page = self.client.get(reverse('dashboard:order_list'))
        self.assertEqual(orders_page.status_code, 200)
        self.assertContains(orders_page, order.order_number)
        self.assertContains(orders_page, 'Priya Nair')

