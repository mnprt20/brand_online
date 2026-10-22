import secrets
import string
from django.db import migrations


ALPHABET = string.ascii_lowercase + string.digits


def _generate_code(Membership):
    while True:
        code = ''.join(secrets.choice(ALPHABET) for _ in range(10))
        if not Membership.objects.filter(referral_code=code).exists():
            return code


def backfill_and_update_plans(apps, schema_editor):
    Membership = apps.get_model('stores', 'Membership')
    Plan = apps.get_model('stores', 'Plan')

    for m in Membership.objects.all():
        updated_fields = []
        if not m.referral_code:
            m.referral_code = _generate_code(Membership)
            updated_fields.append('referral_code')
        if not m.display_name and m.user_id:
            m.display_name = m.user.username
            updated_fields.append('display_name')
        if updated_fields:
            m.save(update_fields=updated_fields)

    Plan.objects.filter(slug='franchise').update(
        max_users=2,
        features={
            'qr_catalogue': True,
            'manual_payment_qr': True,
            'multi_seller': True,
            'online_app': False,
            'staff': True,
            'sales_report': True,
        },
    )
    Plan.objects.filter(slug='online').update(
        features={
            'qr_catalogue': True,
            'manual_payment_qr': True,
            'multi_seller': True,
            'online_app': True,
            'staff': True,
            'sales_report': True,
        },
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0003_store_extra_seats_membership_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_and_update_plans, noop_reverse),
    ]
