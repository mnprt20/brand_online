import secrets
import string
from django.core.exceptions import ValidationError


REFERRAL_ALPHABET = string.ascii_lowercase + string.digits


def generate_referral_token(length=10):
    return ''.join(secrets.choice(REFERRAL_ALPHABET) for _ in range(length))


def generate_unique_referral_code(membership_model=None):
    if membership_model is None:
        from stores.models import Membership
        membership_model = Membership

    while True:
        code = generate_referral_token(10)
        if not membership_model.objects.filter(referral_code=code).exists():
            return code


def backfill_membership_referral_codes(membership_model=None):
    if membership_model is None:
        from stores.models import Membership
        membership_model = Membership

    qs = membership_model.objects.filter(referral_code__isnull=True) | membership_model.objects.filter(referral_code='')
    for membership in qs:
        membership.referral_code = generate_unique_referral_code(membership_model)
        membership.save(update_fields=['referral_code'])


def get_store_seat_limit(store):
    if not store or not store.plan_id:
        return 0
    return int(store.plan.max_users) + int(getattr(store, 'extra_seats', 0) or 0)


def get_active_seat_count(store, exclude_membership_pk=None):
    from stores.models import Membership
    qs = Membership.objects.filter(store=store, is_active=True)
    if exclude_membership_pk is not None:
        qs = qs.exclude(pk=exclude_membership_pk)
    return qs.count()


def validate_store_seat_limit(store, is_active=True, exclude_membership_pk=None):
    if not is_active or not store or not store.plan_id:
        return
    seat_limit = get_store_seat_limit(store)
    active_count = get_active_seat_count(store, exclude_membership_pk=exclude_membership_pk)
    if active_count >= seat_limit:
        raise ValidationError(
            f"Seat limit reached ({active_count}/{seat_limit} active seats). "
            f"Plan '{store.plan.name}' includes {store.plan.max_users} seat(s) "
            f"plus {store.extra_seats} extra seat(s)."
        )
