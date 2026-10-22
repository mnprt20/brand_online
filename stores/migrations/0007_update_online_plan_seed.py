from decimal import Decimal
from django.db import migrations


def update_online_plan(apps, schema_editor):
    Plan = apps.get_model('stores', 'Plan')
    Plan.objects.update_or_create(
        slug='online',
        defaults={
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
    )


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0006_store_accept_cod_store_accept_upi_qr_and_more'),
    ]

    operations = [
        migrations.RunPython(update_online_plan, migrations.RunPython.noop),
    ]
