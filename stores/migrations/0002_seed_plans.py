from decimal import Decimal
from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('stores', 'Plan')
    plans = [
        {
            'slug': 'offline',
            'name': 'Offline Catalogue',
            'max_users': 1,
            'features': {
                'qr_catalogue': True,
                'manual_payment_qr': True,
                'multi_seller': False,
                'online_app': False,
            },
            'price': Decimal('0.00'),
        },
        {
            'slug': 'franchise',
            'name': 'Franchise',
            'max_users': 10,
            'features': {
                'qr_catalogue': True,
                'manual_payment_qr': True,
                'multi_seller': True,
                'online_app': False,
            },
            'price': Decimal('49.00'),
        },
        {
            'slug': 'online',
            'name': 'Online App',
            'max_users': 50,
            'features': {
                'qr_catalogue': True,
                'manual_payment_qr': True,
                'multi_seller': True,
                'online_app': True,
            },
            'price': Decimal('99.00'),
        },
    ]
    for plan_data in plans:
        Plan.objects.update_or_create(
            slug=plan_data['slug'],
            defaults={
                'name': plan_data['name'],
                'max_users': plan_data['max_users'],
                'features': plan_data['features'],
                'price': plan_data['price'],
            },
        )


def unseed_plans(apps, schema_editor):
    Plan = apps.get_model('stores', 'Plan')
    Plan.objects.filter(slug__in=['offline', 'franchise', 'online']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
