from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from catalog.models import Category, Product
from orders.models import Order, OrderStatusEvent
from orders.services import place_online_order
from stores.models import Customer, CustomerAddress, Membership, Plan, Store

User = get_user_model()


class Plan3OrderTrackingAndStatusFlowTests(TestCase):
    def setUp(self):
        self.plan_online, _ = Plan.objects.update_or_create(
            slug=Plan.SLUG_ONLINE,
            defaults={'name': 'Online App', 'max_users': 5},
        )
        self.owner = User.objects.create_user(
            username='track_owner',
            password='ComplexPassword123!',
        )
        self.staff = User.objects.create_user(
            username='track_staff',
            password='ComplexPassword123!',
        )
        self.store = Store.objects.create(
            name='Metro Mart Online',
            slug='metro-mart',
            owner=self.owner,
            plan=self.plan_online,
            online_ordering_open=True,
            delivery_enabled=True,
            pickup_enabled=True,
            delivery_fee=Decimal('30.00'),
            minimum_order_amount=Decimal('50.00'),
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
            display_name='Staff Arjun',
            is_active=True,
        )

        self.category = Category.objects.create(store=self.store, name='Snacks')
        self.product = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Roasted Almonds',
            price=Decimal('150.00'),
            stock=10,
            is_available=True,
            created_by=self.owner,
        )

        self.customer1 = Customer(
            store=self.store,
            name='Customer One',
            phone='9800000001',
        )
        self.customer1.set_password('ComplexPassword123!')
        self.customer1.save()
        self.addr1 = CustomerAddress.objects.create(
            customer=self.customer1,
            label='Home',
            address_line='101 MG Road',
            pincode='560001',
            is_default=True,
        )

        self.customer2 = Customer(
            store=self.store,
            name='Customer Two',
            phone='9800000002',
        )
        self.customer2.set_password('ComplexPassword123!')
        self.customer2.save()

    def _login_customer(self, client, customer):
        client.post(
            reverse('storefront:customer_login', kwargs={'store_slug': self.store.slug}),
            {'phone': customer.phone, 'password': 'ComplexPassword123!'},
        )

    def test_online_status_flow_and_status_events_timeline_ordering(self):
        # 1. Pickup order flow: new -> confirmed -> preparing -> ready_for_pickup -> completed
        pickup_order = place_online_order(
            store=self.store,
            customer=self.customer1,
            cart_items=[{'product': self.product, 'quantity': 1}],
            fulfilment_type=Order.FULFILMENT_PICKUP,
            payment_method=Order.PAYMENT_METHOD_COD,
        )
        # Cannot jump directly to completed or out_for_delivery on a pickup order
        with self.assertRaises(ValidationError):
            pickup_order.transition_status(Order.STATUS_COMPLETED, changed_by=self.owner)

        pickup_order.transition_status(Order.STATUS_CONFIRMED, changed_by=self.owner)
        pickup_order.transition_status(Order.STATUS_PREPARING, changed_by=self.owner)
        with self.assertRaises(ValidationError):
            pickup_order.transition_status(Order.STATUS_OUT_FOR_DELIVERY, changed_by=self.owner)

        pickup_order.transition_status(Order.STATUS_READY_FOR_PICKUP, changed_by=self.owner)
        pickup_order.transition_status(Order.STATUS_COMPLETED, changed_by=self.owner)

        events = list(pickup_order.status_events.values_list('status', flat=True))
        self.assertEqual(
            events,
            [
                Order.STATUS_NEW,
                Order.STATUS_CONFIRMED,
                Order.STATUS_PREPARING,
                Order.STATUS_READY_FOR_PICKUP,
                Order.STATUS_COMPLETED,
            ],
        )

        # 2. Delivery order flow: new -> confirmed -> preparing -> out_for_delivery -> completed
        delivery_order = place_online_order(
            store=self.store,
            customer=self.customer1,
            cart_items=[{'product': self.product, 'quantity': 1}],
            fulfilment_type=Order.FULFILMENT_DELIVERY,
            payment_method=Order.PAYMENT_METHOD_COD,
            address=self.addr1,
        )
        delivery_order.transition_status(Order.STATUS_CONFIRMED, changed_by=self.owner)
        delivery_order.transition_status(Order.STATUS_PREPARING, changed_by=self.owner)
        with self.assertRaises(ValidationError):
            delivery_order.transition_status(Order.STATUS_READY_FOR_PICKUP, changed_by=self.owner)

        delivery_order.transition_status(Order.STATUS_OUT_FOR_DELIVERY, changed_by=self.owner)
        delivery_order.transition_status(Order.STATUS_COMPLETED, changed_by=self.owner)
        self.assertEqual(
            list(delivery_order.status_events.values_list('status', flat=True)),
            [
                Order.STATUS_NEW,
                Order.STATUS_CONFIRMED,
                Order.STATUS_PREPARING,
                Order.STATUS_OUT_FOR_DELIVERY,
                Order.STATUS_COMPLETED,
            ],
        )

    def test_customer_order_history_isolation_and_cancel_rules(self):
        order1 = place_online_order(
            store=self.store,
            customer=self.customer1,
            cart_items=[{'product': self.product, 'quantity': 2}],
            fulfilment_type=Order.FULFILMENT_PICKUP,
            payment_method=Order.PAYMENT_METHOD_COD,
        )
        order2 = place_online_order(
            store=self.store,
            customer=self.customer2,
            cart_items=[{'product': self.product, 'quantity': 1}],
            fulfilment_type=Order.FULFILMENT_PICKUP,
            payment_method=Order.PAYMENT_METHOD_COD,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)

        client1 = Client()
        self._login_customer(client1, self.customer1)

        # Customer 1 sees only order1 on list page
        list_resp = client1.get(
            reverse('storefront:customer_order_list', kwargs={'store_slug': self.store.slug})
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, order1.order_number)
        self.assertNotContains(list_resp, order2.order_number)

        # Customer 1 gets 404 when trying to view or cancel Customer 2's order
        detail_other = client1.get(
            reverse(
                'storefront:customer_order_detail',
                kwargs={'store_slug': self.store.slug, 'order_number': order2.order_number},
            )
        )
        self.assertEqual(detail_other.status_code, 404)
        cancel_other = client1.post(
            reverse(
                'storefront:customer_order_cancel',
                kwargs={'store_slug': self.store.slug, 'order_number': order2.order_number},
            )
        )
        self.assertEqual(cancel_other.status_code, 404)

        # Customer 1 can cancel order1 while status is 'new', restoring stock by 2 (7 -> 9)
        cancel_ok = client1.post(
            reverse(
                'storefront:customer_order_cancel',
                kwargs={'store_slug': self.store.slug, 'order_number': order1.order_number},
            )
        )
        self.assertEqual(cancel_ok.status_code, 302)
        order1.refresh_from_db()
        self.assertEqual(order1.status, Order.STATUS_CANCELLED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 9)
        self.assertEqual(
            list(order1.status_events.values_list('status', flat=True)),
            [Order.STATUS_NEW, Order.STATUS_CANCELLED],
        )

        # Customer 2 cannot cancel order2 after owner confirms it
        order2.transition_status(Order.STATUS_CONFIRMED, changed_by=self.owner)
        client2 = Client()
        self._login_customer(client2, self.customer2)
        cancel_late = client2.post(
            reverse(
                'storefront:customer_order_cancel',
                kwargs={'store_slug': self.store.slug, 'order_number': order2.order_number},
            )
        )
        self.assertEqual(cancel_late.status_code, 400)
        order2.refresh_from_db()
        self.assertEqual(order2.status, Order.STATUS_CONFIRMED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 9)
