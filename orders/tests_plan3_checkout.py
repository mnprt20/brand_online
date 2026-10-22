from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from catalog.models import Category, Product
from orders.models import Order, OrderStatusEvent
from stores.models import Customer, CustomerAddress, Membership, PaymentQR, Plan, Store

User = get_user_model()


class Plan3OnlineCheckoutTests(TestCase):
    def setUp(self):
        self.plan_offline, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_OFFLINE,
            defaults={'name': 'Offline Catalogue', 'max_users': 1},
        )
        self.plan_online, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_ONLINE,
            defaults={'name': 'Online App', 'max_users': 5},
        )

        self.owner = User.objects.create_user(
            username='checkout_owner',
            password='ComplexPassword123!',
        )
        self.staff = User.objects.create_user(
            username='checkout_staff',
            password='ComplexPassword123!',
        )

        self.store = Store.objects.create(
            name='Fresh Basket Online',
            slug='fresh-basket',
            owner=self.owner,
            plan=self.plan_online,
            online_ordering_open=True,
            delivery_enabled=True,
            pickup_enabled=True,
            delivery_fee=Decimal('40.00'),
            free_delivery_above=Decimal('500.00'),
            minimum_order_amount=Decimal('100.00'),
            accept_upi_qr=True,
            accept_cod=True,
        )
        Membership.objects.get_or_create(
            user=self.owner,
            store=self.store,
            defaults={'role': Membership.ROLE_OWNER},
        )
        self.staff_membership = Membership.objects.create(
            user=self.staff,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff Priya',
            is_active=True,
        )
        PaymentQR.objects.create(
            store=self.store,
            upi_id='freshbasket@upi',
        )

        self.category = Category.objects.create(store=self.store, name='Staples')
        self.product_finite = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Organic Honey',
            price=Decimal('200.00'),
            stock=5,
            is_available=True,
            created_by=self.owner,
        )
        self.product_unlimited = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Fresh Bread',
            price=Decimal('60.00'),
            stock=None,
            is_available=True,
            created_by=self.owner,
        )

        self.customer = Customer(
            store=self.store,
            name='Riya Customer',
            phone='9811122233',
        )
        self.customer.set_password('ComplexPassword123!')
        self.customer.save()

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            label='Home',
            address_line='42 Park Avenue, Sector 9',
            landmark='Near Metro Station',
            pincode='110001',
            is_default=True,
        )

    def _login_customer(self, client):
        client.post(
            reverse('storefront:customer_login', kwargs={'store_slug': self.store.slug}),
            {'phone': self.customer.phone, 'password': 'ComplexPassword123!'},
        )

    def _add_to_cart(self, client, product, quantity=1):
        client.post(
            reverse('storefront:cart_add', kwargs={'store_slug': self.store.slug}),
            {'product_id': product.pk, 'quantity': quantity},
        )

    def test_guest_rejected_on_online_checkout_while_qr_checkout_works(self):
        anon = Client()
        self._add_to_cart(anon, self.product_finite, 1)

        # Online checkout requires customer login
        online_resp = anon.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(online_resp.status_code, 302)
        self.assertIn('/account/login/', online_resp['Location'])
        self.assertEqual(Order.objects.count(), 0)

        # Offline QR checkout still works without login
        qr_resp = anon.post(
            reverse('storefront:checkout', kwargs={'store_slug': self.store.slug}),
            {
                'customer_name': 'Walkin Guest',
                'customer_phone': '9000011111',
                'note': 'Table 2',
            },
        )
        self.assertEqual(qr_resp.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        qr_order = Order.objects.first()
        self.assertEqual(qr_order.source, Order.SOURCE_QR)
        self.assertIsNone(qr_order.customer)

    def test_fulfilment_rules_closed_store_disabled_methods_minimum_order(self):
        client = Client()
        self._login_customer(client)

        # 1. Below minimum order amount (60 < 100)
        self._add_to_cart(client, self.product_unlimited, 1)
        resp_min = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_min.status_code, 400)
        self.assertContains(resp_min, 'Minimum order amount', status_code=400)
        self.assertEqual(Order.objects.count(), 0)

        # Add more so subtotal = 260 >= 100
        self._add_to_cart(client, self.product_finite, 1)

        # 2. Store closed
        self.store.online_ordering_open = False
        self.store.save()
        resp_closed = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_closed.status_code, 400)
        self.assertContains(resp_closed, 'Online ordering is currently closed', status_code=400)
        self.assertEqual(Order.objects.count(), 0)
        self.store.online_ordering_open = True
        self.store.save()

        # 3. Disabled pickup
        self.store.pickup_enabled = False
        self.store.save()
        resp_no_pickup = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_no_pickup.status_code, 400)
        self.assertContains(resp_no_pickup, 'Pickup is currently disabled', status_code=400)
        self.store.pickup_enabled = True
        self.store.save()

        # 4. Disabled delivery
        self.store.delivery_enabled = False
        self.store.save()
        resp_no_delivery = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'delivery',
                'address_id': str(self.address.pk),
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_no_delivery.status_code, 400)
        self.assertContains(resp_no_delivery, 'Delivery is currently disabled', status_code=400)
        self.assertEqual(Order.objects.count(), 0)

    def test_delivery_fee_and_free_delivery_threshold_and_address_snapshot(self):
        client = Client()
        self._login_customer(client)

        # Case A: Subtotal = 200.00 (< 500.00 threshold) -> delivery_fee = 40.00, total = 240.00
        self._add_to_cart(client, self.product_finite, 1)
        resp_a = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'delivery',
                'address_id': str(self.address.pk),
                'payment_method': 'upi_qr',
                'payment_reference': 'UTR999888777',
                'customer_note': 'Ring doorbell once',
            },
        )
        self.assertEqual(resp_a.status_code, 302)
        order_a = Order.objects.for_store(self.store).first()
        self.assertEqual(order_a.subtotal, Decimal('200.00'))
        self.assertEqual(order_a.delivery_fee, Decimal('40.00'))
        self.assertEqual(order_a.total, Decimal('240.00'))
        self.assertEqual(order_a.payment_method, Order.PAYMENT_METHOD_UPI_QR)
        self.assertEqual(order_a.payment_reference, 'UTR999888777')
        self.assertEqual(order_a.payment_status, Order.PAYMENT_UNPAID)
        self.assertEqual(order_a.customer_note, 'Ring doorbell once')
        self.assertIn('42 Park Avenue, Sector 9', order_a.delivery_address_text)

        # Edit and delete the CustomerAddress; historical order snapshot must NOT change
        original_snapshot = order_a.delivery_address_text
        self.address.address_line = '999 Changed Street'
        self.address.save()
        order_a.refresh_from_db()
        self.assertEqual(order_a.delivery_address_text, original_snapshot)
        self.address.delete()
        order_a.refresh_from_db()
        self.assertEqual(order_a.delivery_address_text, original_snapshot)

        # Case B: Subtotal = 600.00 (>= 500.00 threshold) -> delivery_fee = 0.00, total = 600.00
        self._add_to_cart(client, self.product_finite, 3)
        resp_b = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'delivery',
                'address_id': 'new',
                'new_address_label': 'Office',
                'new_address_line': 'Tower B, Cyber City',
                'new_address_pincode': '122002',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_b.status_code, 302)
        order_b = Order.objects.for_store(self.store).exclude(pk=order_a.pk).first()
        self.assertEqual(order_b.subtotal, Decimal('600.00'))
        self.assertEqual(order_b.delivery_fee, Decimal('0.00'))
        self.assertEqual(order_b.total, Decimal('600.00'))
        self.assertEqual(order_b.payment_method, Order.PAYMENT_METHOD_COD)
        self.assertIn('Tower B, Cyber City', order_b.delivery_address_text)

    def test_disabled_payment_method_rejected(self):
        self.store.accept_cod = False
        self.store.save()

        client = Client()
        self._login_customer(client)
        self._add_to_cart(client, self.product_finite, 1)

        resp = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'not enabled for this store', status_code=400)
        self.assertEqual(Order.objects.count(), 0)

    def test_stock_decrement_rejection_and_single_restore_on_cancel(self):
        client = Client()
        self._login_customer(client)

        # 1. Try to order 6 when stock is 5 -> rejected, stock stays 5, no Order created
        self._add_to_cart(client, self.product_finite, 6)
        resp_over = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_over.status_code, 400)
        self.assertContains(resp_over, 'Insufficient stock', status_code=400)
        self.product_finite.refresh_from_db()
        self.assertEqual(self.product_finite.stock, 5)
        self.assertEqual(Order.objects.count(), 0)

        # 2. Update cart to 2 -> succeeds, stock becomes 3, unlimited product stays None
        client.post(
            reverse('storefront:cart_update', kwargs={'store_slug': self.store.slug}),
            {'product_id': self.product_finite.pk, 'quantity': 2},
        )
        self._add_to_cart(client, self.product_unlimited, 3)

        resp_ok = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp_ok.status_code, 302)
        self.product_finite.refresh_from_db()
        self.product_unlimited.refresh_from_db()
        self.assertEqual(self.product_finite.stock, 3)
        self.assertIsNone(self.product_unlimited.stock)

        order = Order.objects.for_store(self.store).first()
        self.assertIsNotNone(order)
        self.assertEqual(
             list(OrderStatusEvent.objects.filter(order=order).values_list('status', flat=True)),
            [Order.STATUS_NEW],
        )

        # 3. Cancel order -> stock restores to 5 once, and second restore call is a no-op
        order.transition_status(Order.STATUS_CANCELLED, by_customer=True)
        self.product_finite.refresh_from_db()
        self.assertEqual(self.product_finite.stock, 5)
        self.assertFalse(order.restore_stock_if_needed())
        self.product_finite.refresh_from_db()
        self.assertEqual(self.product_finite.stock, 5)

    def test_referral_attribution_applies_to_online_orders(self):
        client = Client()
        # Visit storefront with staff referral link
        client.get(
            reverse('storefront:detail', kwargs={'store_slug': self.store.slug})
            + f"?ref={self.staff_membership.referral_code}"
        )
        self._login_customer(client)
        self._add_to_cart(client, self.product_finite, 1)

        resp = client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.for_store(self.store).first()
        self.assertEqual(order.placed_by, self.staff)
        self.assertEqual(order.source, Order.SOURCE_ONLINE)
        self.assertEqual(order.customer, self.customer)
