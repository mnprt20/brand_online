from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from catalog.models import Category, Product
from orders.models import Order, OrderStatusEvent
from orders.services import place_online_order
from stores.models import Customer, CustomerAddress, Membership, Plan, Store

User = get_user_model()


class Plan3DashboardOrdersAndSettingsTests(TestCase):
    def setUp(self):
        self.plan_online, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_ONLINE,
            defaults={'name': 'Online App', 'max_users': 5},
        )
        self.owner = User.objects.create_user(
            username='dash3_owner',
            password='ComplexPassword123!',
        )
        self.staff1 = User.objects.create_user(
            username='dash3_staff1',
            password='ComplexPassword123!',
        )
        self.staff2 = User.objects.create_user(
            username='dash3_staff2',
            password='ComplexPassword123!',
        )
        self.other_owner = User.objects.create_user(
            username='dash3_other_owner',
            password='ComplexPassword123!',
        )

        self.store = Store.objects.create(
            name='Prime Grocers',
            slug='prime-grocers',
            owner=self.owner,
            plan=self.plan_online,
            online_ordering_open=True,
            delivery_enabled=True,
            pickup_enabled=True,
            delivery_fee=Decimal('25.00'),
            minimum_order_amount=Decimal('50.00'),
            accept_upi_qr=True,
            accept_cod=True,
        )
        Membership.objects.get_or_create(
            user=self.owner,
            store=self.store,
            defaults={'role': Membership.ROLE_OWNER},
        )
        self.m_staff1 = Membership.objects.create(
            user=self.staff1,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff One',
            is_active=True,
        )
        self.m_staff2 = Membership.objects.create(
            user=self.staff2,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name='Staff Two',
            is_active=True,
        )

        self.other_store = Store.objects.create(
            name='Other Grocers',
            slug='other-grocers',
            owner=self.other_owner,
            plan=self.plan_online,
        )
        Membership.objects.get_or_create(
            user=self.other_owner,
            store=self.other_store,
            defaults={'role': Membership.ROLE_OWNER},
        )

        self.category = Category.objects.create(store=self.store, name='Fruits')
        self.product = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Alphonso Mangoes',
            price=Decimal('300.00'),
            stock=20,
            is_available=True,
            created_by=self.owner,
        )

        self.customer = Customer(
            store=self.store,
            name='Vikram Customer',
            phone='9876500001',
        )
        self.customer.set_password('ComplexPassword123!')
        self.customer.save()
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            label='Flat',
            address_line='B-12 Green Park',
            pincode='110016',
            is_default=True,
        )

    def test_owner_can_update_plan3_store_settings_and_staff_cannot(self):
        owner_client = Client()
        owner_client.login(username='dash3_owner', password='ComplexPassword123!')

        resp = owner_client.post(
            reverse('dashboard:settings'),
            {
                'name': 'Prime Grocers Updated',
                'slug': 'prime-grocers',
                'template_key': Store.TEMPLATE_MINIMAL,
                'description': 'Fresh produce daily',
                'is_active': 'on',
                'online_ordering_open': '',  # unchecked -> False
                'delivery_enabled': 'on',
                'pickup_enabled': '',  # unchecked -> False
                'delivery_fee': '45.00',
                'free_delivery_above': '750.00',
                'minimum_order_amount': '150.00',
                'delivery_note': 'Delivered within 45 mins',
                'accept_upi_qr': 'on',
                'accept_cod': '',  # unchecked -> False
                'theme_color': '#10b981',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.name, 'Prime Grocers Updated')
        self.assertFalse(self.store.online_ordering_open)
        self.assertTrue(self.store.delivery_enabled)
        self.assertFalse(self.store.pickup_enabled)
        self.assertEqual(self.store.delivery_fee, Decimal('45.00'))
        self.assertEqual(self.store.free_delivery_above, Decimal('750.00'))
        self.assertEqual(self.store.minimum_order_amount, Decimal('150.00'))
        self.assertEqual(self.store.delivery_note, 'Delivered within 45 mins')
        self.assertTrue(self.store.accept_upi_qr)
        self.assertFalse(self.store.accept_cod)
        self.assertEqual(self.store.theme_color, '#10b981')

        # Staff cannot update store settings
        staff_client = Client()
        staff_client.login(username='dash3_staff1', password='ComplexPassword123!')
        staff_resp = staff_client.post(
            reverse('dashboard:settings'),
            {'name': 'Hacked Name', 'slug': 'prime-grocers', 'template_key': 'classic'},
        )
        self.assertIn(staff_resp.status_code, (403, 404))

    def test_orders_inbox_filters_status_transitions_mark_paid_and_new_count(self):
        # Create 2 orders:
        # Order 1: delivery, UPI QR, attributed to staff1
        order1 = place_online_order(
            store=self.store,
            customer=self.customer,
            cart_items=[{'product': self.product, 'quantity': 1}],
            fulfilment_type=Order.FULFILMENT_DELIVERY,
            payment_method=Order.PAYMENT_METHOD_UPI_QR,
            payment_reference='UPI-REF-111',
            address=self.address,
            placed_by=self.staff1,
        )
        # Order 2: pickup, COD, unattributed (owner direct)
        order2 = place_online_order(
            store=self.store,
            customer=self.customer,
            cart_items=[{'product': self.product, 'quantity': 1}],
            fulfilment_type=Order.FULFILMENT_PICKUP,
            payment_method=Order.PAYMENT_METHOD_COD,
            placed_by=None,
        )
        # Order in other store
        other_order = Order.objects.create(
            store=self.other_store,
            customer_name='Other Cust',
            customer_phone='9000000000',
            status=Order.STATUS_NEW,
        )

        owner_client = Client()
        owner_client.login(username='dash3_owner', password='ComplexPassword123!')
        staff1_client = Client()
        staff1_client.login(username='dash3_staff1', password='ComplexPassword123!')
        staff2_client = Client()
        staff2_client.login(username='dash3_staff2', password='ComplexPassword123!')

        # 1. Check /dashboard/orders/new-count/ scoped per store and role
        owner_count_resp = owner_client.get(reverse('dashboard:orders_new_count'))
        self.assertEqual(owner_count_resp.status_code, 200)
        self.assertEqual(owner_count_resp.json()['new_count'], 2)

        staff1_count_resp = staff1_client.get(reverse('dashboard:orders_new_count'))
        self.assertEqual(staff1_count_resp.status_code, 200)
        self.assertEqual(staff1_count_resp.json()['new_count'], 1)

        staff2_count_resp = staff2_client.get(reverse('dashboard:orders_new_count'))
        self.assertEqual(staff2_count_resp.status_code, 200)
        self.assertEqual(staff2_count_resp.json()['new_count'], 0)

        # 2. Check fulfilment filter on /dashboard/orders/
        deliv_list = owner_client.get(reverse('dashboard:order_list') + '?fulfilment=delivery')
        self.assertContains(deliv_list, order1.order_number)
        self.assertNotContains(deliv_list, order2.order_number)
        self.assertNotContains(deliv_list, other_order.order_number)

        # 3. Staff1 can advance order1 along allowed flow and mark payment received; Staff2 gets 404
        staff2_attempt = staff2_client.post(
            reverse('dashboard:order_status', kwargs={'pk': order1.pk}),
            {'status': Order.STATUS_CONFIRMED},
        )
        self.assertIn(staff2_attempt.status_code, (403, 404))

        # Invalid jump from 'new' to 'completed' rejected with 400
        invalid_jump = staff1_client.post(
            reverse('dashboard:order_status', kwargs={'pk': order1.pk}),
            {'status': Order.STATUS_COMPLETED},
        )
        self.assertEqual(invalid_jump.status_code, 400)
        order1.refresh_from_db()
        self.assertEqual(order1.status, Order.STATUS_NEW)

        # Valid transition by staff1: new -> confirmed
        valid_step = staff1_client.post(
            reverse('dashboard:order_status', kwargs={'pk': order1.pk}),
            {'status': Order.STATUS_CONFIRMED},
        )
        self.assertEqual(valid_step.status_code, 302)
        order1.refresh_from_db()
        self.assertEqual(order1.status, Order.STATUS_CONFIRMED)
        latest_event = order1.status_events.last()
        self.assertEqual(latest_event.status, Order.STATUS_CONFIRMED)
        self.assertEqual(latest_event.changed_by, self.staff1)

        # Mark payment received
        mark_paid_resp = owner_client.post(
            reverse('dashboard:order_mark_paid', kwargs={'pk': order1.pk})
        )
        self.assertEqual(mark_paid_resp.status_code, 302)
        order1.refresh_from_db()
        self.assertEqual(order1.payment_status, Order.PAYMENT_PAID)

        # New count for owner is now 1 (since order1 is now 'confirmed', only order2 is 'new')
        self.assertEqual(
            owner_client.get(reverse('dashboard:orders_new_count')).json()['new_count'],
            1,
        )

    def test_price_snapshot_immutability_and_referral_sales_report_integration(self):
        cust_client = Client()
        # Visit storefront with staff1 referral code
        cust_client.get(
            reverse('storefront:detail', kwargs={'store_slug': self.store.slug})
            + f"?ref={self.m_staff1.referral_code}"
        )
        cust_client.post(
            reverse('storefront:customer_login', kwargs={'store_slug': self.store.slug}),
            {'phone': self.customer.phone, 'password': 'ComplexPassword123!'},
        )
        cust_client.post(
            reverse('storefront:cart_add', kwargs={'store_slug': self.store.slug}),
            {'product_id': self.product.pk, 'quantity': 2},
        )
        resp = cust_client.post(
            reverse('storefront:online_checkout', kwargs={'store_slug': self.store.slug}),
            {
                'fulfilment_type': 'pickup',
                'payment_method': 'cod',
            },
        )
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.for_store(self.store).first()
        self.assertEqual(order.placed_by, self.staff1)
        self.assertEqual(order.total, Decimal('600.00'))

        # Change product name and price; historical OrderItem snapshot and Order total must NOT change
        self.product.name = 'Renamed Mangoes'
        self.product.price = Decimal('999.00')
        self.product.save()

        item = order.items.first()
        item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(item.product_name_snapshot, 'Alphonso Mangoes')
        self.assertEqual(item.unit_price_snapshot, Decimal('300.00'))
        self.assertEqual(order.total, Decimal('600.00'))

        # Staff1 sees the order in their inbox and completes it along the pickup flow
        staff1_client = Client()
        staff1_client.login(username='dash3_staff1', password='ComplexPassword123!')
        inbox_resp = staff1_client.get(reverse('dashboard:order_list'))
        self.assertContains(inbox_resp, order.order_number)

        for next_status in (
            Order.STATUS_CONFIRMED,
            Order.STATUS_PREPARING,
            Order.STATUS_READY_FOR_PICKUP,
            Order.STATUS_COMPLETED,
        ):
            step_resp = staff1_client.post(
                reverse('dashboard:order_status', kwargs={'pk': order.pk}),
                {'status': next_status},
            )
            self.assertEqual(step_resp.status_code, 302)

        # Owner sales report includes the completed online order under Staff One
        owner_client = Client()
        owner_client.login(username='dash3_owner', password='ComplexPassword123!')
        report_resp = owner_client.get(reverse('dashboard:sales_report'))
        self.assertEqual(report_resp.status_code, 200)
        self.assertContains(report_resp, 'Staff One')
        self.assertContains(report_resp, '600.00')

