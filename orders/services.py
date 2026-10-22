from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from catalog.models import Product
from orders.models import Order, OrderItem
from orders.payments import get_payment_method_handler


def calculate_delivery_fee(store, subtotal: Decimal, fulfilment_type: str) -> Decimal:
    """
    Calculate the delivery fee for an online order using Decimal arithmetic.
    - Pickup orders always have 0.00 delivery fee.
    - Delivery orders waive the fee when free_delivery_above is set and subtotal >= free_delivery_above.
    """
    subtotal_dec = Decimal(subtotal).quantize(Decimal('0.01'))
    if fulfilment_type != Order.FULFILMENT_DELIVERY:
        return Decimal('0.00')
    if store.free_delivery_above is not None:
        threshold = Decimal(store.free_delivery_above).quantize(Decimal('0.01'))
        if subtotal_dec >= threshold:
            return Decimal('0.00')
    return Decimal(store.delivery_fee or Decimal('0.00')).quantize(Decimal('0.01'))


def place_online_order(
    *,
    store,
    customer,
    cart_items,
    fulfilment_type: str,
    payment_method: str,
    address=None,
    delivery_address_text: str = '',
    payment_reference: str = '',
    customer_note: str = '',
    placed_by=None,
) -> Order:
    """
    Atomically validate and create an online order, decrementing finite product stock
    with row locking (select_for_update) and writing the initial OrderStatusEvent('new').
    """
    if not store.has_online_features():
        raise ValidationError("Online ordering is not available on this store's plan.")

    if not store.online_ordering_open:
        raise ValidationError("Online ordering is currently closed for this store.")

    if customer is None or customer.store_id != store.pk or not customer.is_active:
        raise ValidationError("A valid store customer account is required for online checkout.")

    if not cart_items:
        raise ValidationError("Your cart is empty.")

    fulfilment_cleaned = (fulfilment_type or '').strip()
    if fulfilment_cleaned not in (Order.FULFILMENT_PICKUP, Order.FULFILMENT_DELIVERY):
        raise ValidationError("Please select a valid fulfilment method (pickup or delivery).")

    if fulfilment_cleaned == Order.FULFILMENT_PICKUP and not store.pickup_enabled:
        raise ValidationError("Pickup is currently disabled for this store.")

    if fulfilment_cleaned == Order.FULFILMENT_DELIVERY and not store.delivery_enabled:
        raise ValidationError("Delivery is currently disabled for this store.")

    resolved_address_text = ''
    if fulfilment_cleaned == Order.FULFILMENT_DELIVERY:
        if address is not None:
            if address.customer_id != customer.pk:
                raise ValidationError("Selected delivery address does not belong to your account.")
            resolved_address_text = address.as_snapshot_text()
        else:
            resolved_address_text = (delivery_address_text or '').strip()
        if not resolved_address_text:
            raise ValidationError("A delivery address is required for delivery orders.")

    handler = get_payment_method_handler(payment_method)
    cleaned_payment = handler.validate_submission(
        store,
        {'payment_reference': payment_reference},
    )
    payment_fields = handler.prepare_order_fields(store, cleaned_payment)

    requested_quantities = {}
    for entry in cart_items:
        product_obj = entry.get('product')
        pid = product_obj.pk if product_obj is not None else int(entry['product_id'])
        qty = int(entry.get('quantity', 0))
        if qty <= 0:
            continue
        requested_quantities[pid] = requested_quantities.get(pid, 0) + qty

    if not requested_quantities:
        raise ValidationError("Your cart is empty.")

    with transaction.atomic():
        locked_products = list(
            Product.objects.select_for_update()
            .filter(store=store, pk__in=sorted(requested_quantities.keys()))
            .order_by('pk')
        )
        product_map = {p.pk: p for p in locked_products}

        subtotal = Decimal('0.00')
        order_line_specs = []

        for pid in sorted(requested_quantities.keys()):
            qty = requested_quantities[pid]
            product = product_map.get(pid)
            if product is None or not product.is_available:
                raise ValidationError("One or more items in your cart are no longer available.")
            if product.stock is not None and product.stock < qty:
                raise ValidationError(
                    f"Insufficient stock for '{product.name}'. "
                    f"Only {product.stock} available."
                )
            line_subtotal = (product.price * Decimal(qty)).quantize(Decimal('0.01'))
            subtotal += line_subtotal
            order_line_specs.append((product, qty))

        subtotal = subtotal.quantize(Decimal('0.01'))
        min_order = Decimal(store.minimum_order_amount or Decimal('0.00')).quantize(Decimal('0.01'))
        if subtotal < min_order:
            raise ValidationError(
                f"Minimum order amount is {min_order}. Your current subtotal is {subtotal}."
            )

        delivery_fee = calculate_delivery_fee(store, subtotal, fulfilment_cleaned)
        total = (subtotal + delivery_fee).quantize(Decimal('0.01'))

        for product, qty in order_line_specs:
            if product.stock is not None:
                product.stock = product.stock - qty
                product.save(update_fields=['stock'])

        cleaned_note = (customer_note or '').strip()
        order = Order.objects.create(
            store=store,
            customer=customer,
            customer_name=customer.name,
            customer_phone=customer.phone,
            note=cleaned_note,
            customer_note=cleaned_note,
            fulfilment_type=fulfilment_cleaned,
            delivery_address_text=resolved_address_text,
            delivery_fee=delivery_fee,
            payment_method=payment_fields['payment_method'],
            payment_reference=payment_fields['payment_reference'],
            payment_status=payment_fields['payment_status'],
            status=Order.STATUS_NEW,
            source=Order.SOURCE_ONLINE,
            placed_by=placed_by,
            total=total,
        )

        for product, qty in order_line_specs:
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name_snapshot=product.name,
                unit_price_snapshot=product.price,
                quantity=qty,
            )

        return order
