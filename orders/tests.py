from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from catalog.models import Category, Product
from orders.models import Order, OrderItem
from stores.models import Plan, Store, Membership

User = get_user_model()


class OrderModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='password123')
        self.plan = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.store = Store.objects.create(
            owner=self.owner,
            name='Coffee Corner',
            slug='coffee-corner',
            plan=self.plan,
        )
        Membership.objects.create(user=self.owner, store=self.store, role=Membership.ROLE_OWNER)
        self.category = Category.objects.create(store=self.store, name='Beverages')
        self.product_1 = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Espresso',
            price=Decimal('120.00'),
            created_by=self.owner,
        )
        self.product_2 = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Muffin',
            price=Decimal('85.50'),
            created_by=self.owner,
        )

    def test_order_creation_snapshots_and_price_immutability(self):
        order = Order.objects.create(
            store=self.store,
            customer_name='Alice',
            customer_phone='9876543210',
            note='Less sugar',
            source=Order.SOURCE_QR,
        )
        item_1 = OrderItem.objects.create(
            order=order,
            product=self.product_1,
            product_name_snapshot=self.product_1.name,
            unit_price_snapshot=self.product_1.price,
            quantity=2,
        )
        item_2 = OrderItem.objects.create(
            order=order,
            product=self.product_2,
            product_name_snapshot=self.product_2.name,
            unit_price_snapshot=self.product_2.price,
            quantity=3,
        )
        order.refresh_from_db()
        expected_total = (Decimal('120.00') * 2) + (Decimal('85.50') * 3)
        self.assertEqual(order.total, expected_total)
        self.assertEqual(item_1.product_name_snapshot, 'Espresso')
        self.assertEqual(item_1.unit_price_snapshot, Decimal('120.00'))

        # Change product name and price afterwards; existing order & items must NOT change
        self.product_1.name = 'Double Espresso'
        self.product_1.price = Decimal('250.00')
        self.product_1.save()

        order.refresh_from_db()
        item_1.refresh_from_db()
        self.assertEqual(item_1.product_name_snapshot, 'Espresso')
        self.assertEqual(item_1.unit_price_snapshot, Decimal('120.00'))
        self.assertEqual(order.total, expected_total)
