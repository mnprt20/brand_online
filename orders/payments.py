from abc import ABC, abstractmethod
from django.core.exceptions import ValidationError
from orders.models import Order
from stores.models import PaymentQR


class BasePaymentMethod(ABC):
    """
    Documented Payment Method Interface for store checkouts.

    To integrate a future payment gateway (e.g. Razorpay, Stripe) without refactoring
    checkout views or order services:
    1. Subclass `BasePaymentMethod` and set a unique `code` and human-readable `label`.
    2. Implement `is_enabled(store)` to check store-level configuration.
    3. Implement `validate_submission(store, data)` to validate any method-specific
       fields or tokens submitted during checkout.
    4. Implement `prepare_order_fields(store, data)` to return a dict of `Order`
       fields (`payment_method`, `payment_reference`, `payment_status`).
    5. Register the instance in `PAYMENT_METHOD_REGISTRY`.
    """

    code: str = ''
    label: str = ''
    description: str = ''

    @abstractmethod
    def is_enabled(self, store) -> bool:
        """Return True if this payment method is enabled for the given store."""
        raise NotImplementedError

    @abstractmethod
    def validate_submission(self, store, data: dict) -> dict:
        """
        Validate checkout form data for this payment method.
        Raise django.core.exceptions.ValidationError if invalid.
        Return cleaned payment data dictionary.
        """
        raise NotImplementedError

    @abstractmethod
    def prepare_order_fields(self, store, cleaned_payment_data: dict) -> dict:
        """
        Return dictionary of fields to set on the Order instance at creation time.
        """
        raise NotImplementedError

    def get_checkout_context(self, store) -> dict:
        """Return optional extra context needed to render this method on checkout."""
        return {}

    def get_confirmation_context(self, store, order) -> dict:
        """Return optional extra context needed on the order confirmation / detail page."""
        return {}


class UPIQRPaymentMethod(BasePaymentMethod):
    """
    Manual UPI QR payment method.
    Displays the store owner's PaymentQR image and UPI ID.
    Customer may optionally enter a UPI transaction / payment reference text;
    the store owner manually verifies and marks payment received.
    """

    code = Order.PAYMENT_METHOD_UPI_QR
    label = 'UPI QR Payment'
    description = 'Scan the store UPI QR code or pay to the store UPI ID and optionally enter your payment reference.'

    def is_enabled(self, store) -> bool:
        return bool(store.accept_upi_qr)

    def validate_submission(self, store, data: dict) -> dict:
        if not self.is_enabled(store):
            raise ValidationError("UPI QR payment is not enabled for this store.")
        raw_ref = (data.get('payment_reference') or '').strip()
        if len(raw_ref) > 200:
            raise ValidationError("Payment reference must be 200 characters or fewer.")
        return {'payment_reference': raw_ref}

    def prepare_order_fields(self, store, cleaned_payment_data: dict) -> dict:
        return {
            'payment_method': self.code,
            'payment_reference': cleaned_payment_data.get('payment_reference', ''),
            'payment_status': Order.PAYMENT_UNPAID,
        }

    def get_checkout_context(self, store) -> dict:
        return {
            'payment_qr': PaymentQR.objects.for_store(store).first(),
        }

    def get_confirmation_context(self, store, order) -> dict:
        return {
            'payment_qr': PaymentQR.objects.for_store(store).first(),
        }


class CODPaymentMethod(BasePaymentMethod):
    """
    Cash on Delivery / Pay on Pickup payment method.
    Requires no external payment reference at checkout.
    """

    code = Order.PAYMENT_METHOD_COD
    label = 'Cash on Delivery / Pay on Pickup'
    description = 'Pay directly in cash when your order is delivered or picked up.'

    def is_enabled(self, store) -> bool:
        return bool(store.accept_cod)

    def validate_submission(self, store, data: dict) -> dict:
        if not self.is_enabled(store):
            raise ValidationError("Cash on Delivery / Pickup is not enabled for this store.")
        return {'payment_reference': ''}

    def prepare_order_fields(self, store, cleaned_payment_data: dict) -> dict:
        return {
            'payment_method': self.code,
            'payment_reference': '',
            'payment_status': Order.PAYMENT_UNPAID,
        }


PAYMENT_METHOD_REGISTRY = {
    UPIQRPaymentMethod.code: UPIQRPaymentMethod(),
    CODPaymentMethod.code: CODPaymentMethod(),
}


def get_payment_method_handler(code: str) -> BasePaymentMethod:
    cleaned = (code or '').strip()
    handler = PAYMENT_METHOD_REGISTRY.get(cleaned)
    if handler is None:
        raise ValidationError(f"Unsupported payment method '{cleaned}'.")
    return handler


def get_enabled_payment_methods(store):
    return [
        handler
        for handler in PAYMENT_METHOD_REGISTRY.values()
        if handler.is_enabled(store)
    ]
