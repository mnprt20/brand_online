from decimal import Decimal
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from orders.models import OrderItem, Order


def _update_order_total(order_id):
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return
    order.recalculate_total(save=True)


@receiver(post_save, sender=OrderItem)
def order_item_saved(sender, instance, **kwargs):
    _update_order_total(instance.order_id)


@receiver(post_delete, sender=OrderItem)
def order_item_deleted(sender, instance, **kwargs):
    _update_order_total(instance.order_id)
