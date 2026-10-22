from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from catalog.models import Category, Product
from stores.models import Plan, Store, Membership

User = get_user_model()


class CatalogModelTests(TestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(username='owner_a', password='password123')
        self.owner_b = User.objects.create_user(username='owner_b', password='password123')
        self.plan = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
        self.store_a = Store.objects.create(
            owner=self.owner_a,
            name='Store A',
            slug='store-a',
            plan=self.plan,
        )
        Membership.objects.create(user=self.owner_a, store=self.store_a, role=Membership.ROLE_OWNER)
        self.store_b = Store.objects.create(
            owner=self.owner_b,
            name='Store B',
            slug='store-b',
            plan=self.plan,
        )
        Membership.objects.create(user=self.owner_b, store=self.store_b, role=Membership.ROLE_OWNER)

    def test_category_and_product_scoping(self):
        cat_a = Category.objects.create(store=self.store_a, name='Drinks', sort_order=1)
        prod_a = Product.objects.create(
            store=self.store_a,
            category=cat_a,
            name='Iced Latte',
            price=Decimal('150.00'),
            created_by=self.owner_a,
        )
        cat_b = Category.objects.create(store=self.store_b, name='Bakery', sort_order=1)
        prod_b = Product.objects.create(
            store=self.store_b,
            category=cat_b,
            name='Croissant',
            price=Decimal('95.50'),
            created_by=self.owner_b,
        )

        self.assertQuerySetEqual(Category.objects.for_user(self.owner_a), [cat_a])
        self.assertQuerySetEqual(Product.objects.for_user(self.owner_a), [prod_a])
        self.assertQuerySetEqual(Category.objects.for_user(self.owner_b), [cat_b])
        self.assertQuerySetEqual(Product.objects.for_user(self.owner_b), [prod_b])
