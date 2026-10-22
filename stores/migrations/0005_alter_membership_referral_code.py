from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0004_backfill_referral_codes_and_franchise_plan'),
    ]

    operations = [
        migrations.AlterField(
            model_name='membership',
            name='referral_code',
            field=models.CharField(blank=True, max_length=32, unique=True),
        ),
    ]
