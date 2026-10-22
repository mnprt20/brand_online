from django.db import models


def get_user_membership(user, include_inactive=False):
    """Return the Membership for an authenticated user."""
    if not user or not user.is_authenticated:
        return None
    from stores.models import Membership
    qs = Membership.objects.select_related('store', 'store__plan', 'user').filter(user=user)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by('created_at').first()


def get_user_store(user):
    """Return the active store for an authenticated user (via active Membership or ownership)."""
    if not user or not user.is_authenticated:
        return None
    membership = get_user_membership(user, include_inactive=False)
    if membership:
        return membership.store
    from stores.models import Membership, Store
    if Membership.objects.filter(user=user, is_active=False).exists():
        return None
    return Store.objects.select_related('plan').filter(owner=user).first()


class StoreScopedQuerySet(models.QuerySet):
    def for_store(self, store):
        if store is None:
            return self.none()
        return self.filter(store=store)

    def for_user(self, user):
        store = get_user_store(user)
        if store is None:
            return self.none()
        return self.filter(store=store)


class StoreScopedManager(models.Manager):
    def get_queryset(self):
        return StoreScopedQuerySet(self.model, using=self._db)

    def for_store(self, store):
        return self.get_queryset().for_store(store)

    def for_user(self, user):
        return self.get_queryset().for_user(user)
