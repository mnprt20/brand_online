from decimal import Decimal
from django.core.management.base import BaseCommand
from stores.models import Plan


DEFAULT_PLANS = [
    {
        'slug': Plan.SLUG_OFFLINE,
        'name': 'Offline Catalogue',
        'max_users': 1,
        'features': {
            'qr_catalogue': True,
            'manual_payment_qr': True,
            'multi_seller': False,
            'online_app': False,
            'staff': False,
            'sales_report': False,
        },
        'price': Decimal('0.00'),
    },
    {
        'slug': Plan.SLUG_FRANCHISE,
        'name': 'Franchise',
        'max_users': 2,
        'features': {
            'qr_catalogue': True,
            'manual_payment_qr': True,
            'multi_seller': True,
            'online_app': False,
            'staff': True,
            'sales_report': True,
        },
        'price': Decimal('49.00'),
    },
    {
        'slug': Plan.SLUG_ONLINE,
        'name': 'Online App',
        'max_users': 5,
        'features': {
            'qr_catalogue': True,
            'manual_payment_qr': True,
            'multi_seller': True,
            'online_app': True,
            'staff': True,
            'sales_report': True,
        },
        'price': Decimal('99.00'),
    },
]


class Command(BaseCommand):
    help = 'Seed the 3 SaaS plans (offline, franchise, online).'

    def handle(self, *args, **options):
        for plan_data in DEFAULT_PLANS:
            plan, created = Plan.objects.update_or_create(
                slug=plan_data['slug'],
                defaults={
                    'name': plan_data['name'],
                    'max_users': plan_data['max_users'],
                    'features': plan_data['features'],
                    'price': plan_data['price'],
                },
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f"{action} plan: {plan.name} ({plan.slug})"))
