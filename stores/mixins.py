from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from stores.managers import get_user_membership, get_user_store
from stores.models import Membership, Store


class StoreScopedMixin(LoginRequiredMixin):
    """
    Base mixin that enforces login, verifies active membership, and scopes
    all queries strictly to the authenticated user's Store.
    """
    require_franchise = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        any_membership = get_user_membership(request.user, include_inactive=True)
        if any_membership is not None and not any_membership.is_active:
            logout(request)
            raise PermissionDenied("Your staff account has been deactivated.")

        self._cached_membership = any_membership
        store = self.get_store()
        if self.require_franchise and not store.has_franchise_features():
            raise PermissionDenied("This feature requires the Franchise plan.")

        return super().dispatch(request, *args, **kwargs)

    def get_membership(self):
        if not hasattr(self, '_cached_membership'):
            self._cached_membership = get_user_membership(self.request.user, include_inactive=False)
        return self._cached_membership

    def is_owner_user(self):
        membership = self.get_membership()
        if membership is not None:
            return membership.role == Membership.ROLE_OWNER
        store = self.get_store()
        return store.owner_id == self.request.user.id

    def is_staff_member(self):
        membership = self.get_membership()
        return membership is not None and membership.role == Membership.ROLE_STAFF

    def get_store(self):
        if not hasattr(self, '_cached_store'):
            membership = self.get_membership()
            if membership is not None:
                store = membership.store
            else:
                store = get_user_store(self.request.user)
            if store is None:
                raise Http404("No store associated with this account.")
            self._cached_store = store
        return self._cached_store

    def get_queryset(self):
        qs = super().get_queryset()
        store = self.get_store()
        if qs.model is Store:
            return qs.filter(pk=store.pk)
        if hasattr(qs, 'for_store'):
            return qs.for_store(store)
        return qs.filter(store=store)

    def get_context_data(self, **kwargs):
        if hasattr(super(), 'get_context_data'):
            context = super().get_context_data(**kwargs)
        else:
            context = dict(kwargs)
        store = self.get_store()
        is_owner = self.is_owner_user()
        is_staff = self.is_staff_member()
        context['current_store'] = store
        context['current_membership'] = self.get_membership()
        context['is_owner'] = is_owner
        context['is_store_owner'] = is_owner
        context['is_staff_member'] = is_staff
        context['is_store_staff'] = is_staff
        context['has_franchise'] = store.has_franchise_features()
        return context


class OwnerRequiredMixin(StoreScopedMixin):
    """Permits only the store owner; rejects staff members with 403."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        any_membership = get_user_membership(request.user, include_inactive=True)
        if any_membership is not None and not any_membership.is_active:
            logout(request)
            raise PermissionDenied("Your staff account has been deactivated.")
        self._cached_membership = any_membership
        if not self.is_owner_user():
            raise PermissionDenied("Only the store owner can access this page.")
        store = self.get_store()
        if self.require_franchise and not store.has_franchise_features():
            raise PermissionDenied("This feature requires the Franchise plan.")
        return super(StoreScopedMixin, self).dispatch(request, *args, **kwargs)


class StaffOrOwnerMixin(StoreScopedMixin):
    """Permits both active store owners and active store staff members."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        any_membership = get_user_membership(request.user, include_inactive=True)
        if any_membership is not None and not any_membership.is_active:
            logout(request)
            raise PermissionDenied("Your staff account has been deactivated.")
        self._cached_membership = any_membership
        if not (self.is_owner_user() or self.is_staff_member()):
            raise PermissionDenied("You do not have access to this store.")
        store = self.get_store()
        if self.require_franchise and not store.has_franchise_features():
            raise PermissionDenied("This feature requires the Franchise plan.")
        return super(StoreScopedMixin, self).dispatch(request, *args, **kwargs)

