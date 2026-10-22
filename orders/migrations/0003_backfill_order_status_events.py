from django.db import migrations


def backfill_order_status_events(apps, schema_editor=None):
    Order = apps.get_model('orders', 'Order')
    OrderStatusEvent = apps.get_model('orders', 'OrderStatusEvent')

    existing_order_ids = set(
        OrderStatusEvent.objects.values_list('order_id', flat=True).distinct()
    )
    for order in Order.objects.exclude(id__in=existing_order_ids).iterator():
        event = OrderStatusEvent.objects.create(
            order_id=order.id,
            status=order.status,
            changed_by_id=order.placed_by_id,
        )
        if order.created_at:
            OrderStatusEvent.objects.filter(pk=event.pk).update(created_at=order.created_at)


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_order_customer_order_customer_note_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_order_status_events, migrations.RunPython.noop),
    ]
