from decimal import Decimal
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from catalog.models import Product
from stores.managers import StoreScopedManager
from stores.models import Customer, Store


class Order(models.Model):
    STATUS_NEW = 'new'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_PREPARING = 'preparing'
    STATUS_READY_FOR_PICKUP = 'ready_for_pickup'
    STATUS_OUT_FOR_DELIVERY = 'out_for_delivery'
    STATUS_PAID = 'paid'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_NEW, 'New'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_PREPARING, 'Preparing'),
        (STATUS_READY_FOR_PICKUP, 'Ready for Pickup'),
        (STATUS_OUT_FOR_DELIVERY, 'Out for Delivery'),
        (STATUS_PAID, 'Paid'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    STATUS_ALIASES = {
        'ready for pickup': STATUS_READY_FOR_PICKUP,
        'out for delivery': STATUS_OUT_FOR_DELIVERY,
    }

    PAYMENT_UNPAID = 'unpaid'
    PAYMENT_PAID = 'paid'

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_UNPAID, 'Unpaid'),
        (PAYMENT_PAID, 'Paid'),
    ]

    SOURCE_QR = 'qr'
    SOURCE_ONLINE = 'online'

    SOURCE_CHOICES = [
        (SOURCE_QR, 'QR'),
        (SOURCE_ONLINE, 'Online'),
    ]

    FULFILMENT_PICKUP = 'pickup'
    FULFILMENT_DELIVERY = 'delivery'

    FULFILMENT_CHOICES = [
        (FULFILMENT_PICKUP, 'Pickup'),
        (FULFILMENT_DELIVERY, 'Delivery'),
    ]

    PAYMENT_METHOD_UPI_QR = 'upi_qr'
    PAYMENT_METHOD_COD = 'cod'

    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_UPI_QR, 'UPI QR'),
        (PAYMENT_METHOD_COD, 'Cash on Delivery / Pickup'),
    ]

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='orders',
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    order_number = models.CharField(max_length=50, unique=True, blank=True)
    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=50)
    note = models.TextField(blank=True, default='')
    customer_note = models.TextField(blank=True, default='')
    fulfilment_type = models.CharField(
        max_length=20,
        choices=FULFILMENT_CHOICES,
        blank=True,
        default='',
    )
    delivery_address_text = models.TextField(blank=True, default='')
    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
        default='',
    )
    payment_reference = models.CharField(max_length=200, blank=True, default='')
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_UNPAID,
    )
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_QR,
    )
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='placed_orders',
    )
    stock_restored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StoreScopedManager()

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"Order {self.order_number} ({self.store.name})"

    @classmethod
    def normalize_status(cls, raw_status):
        if not raw_status:
            return raw_status
        cleaned = str(raw_status).strip().lower()
        return cls.STATUS_ALIASES.get(cleaned, cleaned)

    @property
    def is_online_order(self):
        return bool(
            self.fulfilment_type in (self.FULFILMENT_PICKUP, self.FULFILMENT_DELIVERY)
            or self.customer_id is not None
        )

    @property
    def subtotal(self):
        items = list(self.items.all())
        if items:
            return sum(
                (item.unit_price_snapshot * Decimal(item.quantity) for item in items),
                Decimal('0.00'),
            ).quantize(Decimal('0.01'))
        fee = (self.delivery_fee or Decimal('0.00')).quantize(Decimal('0.01'))
        return max(Decimal('0.00'), (self.total - fee).quantize(Decimal('0.01')))

    def get_allowed_next_statuses(self):
        current = self.normalize_status(self.status)
        if current in (self.STATUS_COMPLETED, self.STATUS_CANCELLED):
            return []
        if not self.is_online_order:
            return [
                s for s, _ in self.STATUS_CHOICES
                if s != current
            ]
        if current == self.STATUS_NEW:
            return [self.STATUS_CONFIRMED, self.STATUS_CANCELLED]
        if current == self.STATUS_CONFIRMED:
            return [self.STATUS_PREPARING, self.STATUS_CANCELLED]
        if current == self.STATUS_PREPARING:
            if self.fulfilment_type == self.FULFILMENT_PICKUP:
                return [self.STATUS_READY_FOR_PICKUP, self.STATUS_CANCELLED]
            if self.fulfilment_type == self.FULFILMENT_DELIVERY:
                return [self.STATUS_OUT_FOR_DELIVERY, self.STATUS_CANCELLED]
            return [
                self.STATUS_READY_FOR_PICKUP,
                self.STATUS_OUT_FOR_DELIVERY,
                self.STATUS_CANCELLED,
            ]
        if current in (self.STATUS_READY_FOR_PICKUP, self.STATUS_OUT_FOR_DELIVERY):
            return [self.STATUS_COMPLETED, self.STATUS_CANCELLED]
        if current == self.STATUS_PAID:
            return [self.STATUS_COMPLETED, self.STATUS_CANCELLED]
        return []

    def can_transition_to(self, target_status, by_customer=False):
        target = self.normalize_status(target_status)
        current = self.normalize_status(self.status)
        if by_customer:
            return current == self.STATUS_NEW and target == self.STATUS_CANCELLED
        return target in self.get_allowed_next_statuses()

    @transaction.atomic
    def restore_stock_if_needed(self):
        if not self.pk:
            return False
        locked = Order.objects.select_for_update().get(pk=self.pk)
        if locked.stock_restored:
            self.stock_restored = True
            return False
        for item in locked.items.select_related('product').all():
            if item.product_id:
                prod = Product.objects.select_for_update().filter(pk=item.product_id).first()
                if prod and prod.stock is not None:
                    prod.stock = prod.stock + item.quantity
                    prod.save(update_fields=['stock'])
        Order.objects.filter(pk=locked.pk).update(stock_restored=True)
        self.stock_restored = True
        return True

    @transaction.atomic
    def transition_status(self, target_status, changed_by=None, by_customer=False):
        target = self.normalize_status(target_status)
        if not self.can_transition_to(target, by_customer=by_customer):
            raise ValidationError(
                f"Cannot transition order from '{self.status}' to '{target}'."
            )
        self._status_changed_by = changed_by
        self.status = target
        self.save()
        if target == self.STATUS_CANCELLED:
            self.restore_stock_if_needed()
        return self

    def _generate_order_number(self):
        return f"ORD-{uuid.uuid4().hex[:8].upper()}"

    def recalculate_total(self, save=True):
        items = self.items.all()
        subtotal = sum(
            (item.unit_price_snapshot * Decimal(item.quantity) for item in items),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'))
        fee = (self.delivery_fee or Decimal('0.00')).quantize(Decimal('0.01'))
        self.total = (subtotal + fee).quantize(Decimal('0.01'))
        if save and self.pk:
            Order.objects.filter(pk=self.pk).update(total=self.total)
        return self.total

    def save(self, *args, **kwargs):
        self.status = self.normalize_status(self.status)
        is_new = self.pk is None
        previous_status = None
        if not is_new:
            previous_status = (
                Order.objects.filter(pk=self.pk)
                .values_list('status', flat=True)
                .first()
            )
        if not self.order_number:
            candidate = self._generate_order_number()
            while Order.objects.filter(order_number=candidate).exclude(pk=self.pk).exists():
                candidate = self._generate_order_number()
            self.order_number = candidate
        if self.status == self.STATUS_PAID and self.payment_status != self.PAYMENT_PAID:
            self.payment_status = self.PAYMENT_PAID
        super().save(*args, **kwargs)

        changed_by = getattr(self, '_status_changed_by', None)
        if is_new:
            OrderStatusEvent.objects.create(
                order=self,
                status=self.status,
                changed_by=changed_by if changed_by is not None else self.placed_by,
            )
        elif previous_status != self.status:
            OrderStatusEvent.objects.create(
                order=self,
                status=self.status,
                changed_by=changed_by,
            )
            if self.status == self.STATUS_CANCELLED:
                self.restore_stock_if_needed()


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
    )
    product_name_snapshot = models.CharField(max_length=200)
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity} x {self.product_name_snapshot}"

    @property
    def subtotal(self):
        return (self.unit_price_snapshot * Decimal(self.quantity)).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        if self.product:
            if not self.product_name_snapshot:
                self.product_name_snapshot = self.product.name
            if self.unit_price_snapshot is None:
                self.unit_price_snapshot = self.product.price
        super().save(*args, **kwargs)


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_events',
    )
    status = models.CharField(max_length=30, choices=Order.STATUS_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_status_events',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.order.order_number} -> {self.status}"

