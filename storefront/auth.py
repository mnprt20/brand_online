from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from stores.models import Customer, Store

LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 600  # 10 minutes


def get_online_store_or_404(slug):
    store = get_object_or_404(Store.objects.select_related('plan'), slug=slug, is_active=True)
    if not store.has_online_features():
        raise Http404("Online app is not enabled for this store.")
    return store


def get_store_customer(request, store):
    if not store.has_online_features():
        return None
    store_customers = request.session.get('store_customers', {})
    customer_id = store_customers.get(str(store.pk))
    if not customer_id:
        return None
    customer = Customer.objects.filter(
        pk=customer_id,
        store=store,
        is_active=True,
    ).first()
    if customer is None:
        logout_store_customer(request, store)
    return customer


def login_store_customer(request, store, customer):
    store_customers = dict(request.session.get('store_customers', {}))
    store_customers[str(store.pk)] = customer.pk
    request.session['store_customers'] = store_customers
    request.session.modified = True


def logout_store_customer(request, store):
    store_customers = dict(request.session.get('store_customers', {}))
    if str(store.pk) in store_customers:
        store_customers.pop(str(store.pk), None)
        request.session['store_customers'] = store_customers
        request.session.modified = True


def get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def _phone_fail_key(store_pk, phone):
    return f"cust_login_fail_phone:{store_pk}:{phone.strip()}"


def _phone_lock_key(store_pk, phone):
    return f"cust_login_lock_phone:{store_pk}:{phone.strip()}"


def _ip_fail_key(store_pk, ip):
    return f"cust_login_fail_ip:{store_pk}:{ip}"


def _ip_lock_key(store_pk, ip):
    return f"cust_login_lock_ip:{store_pk}:{ip}"


def is_customer_login_locked(store, phone, ip):
    phone_locked = bool(cache.get(_phone_lock_key(store.pk, phone)))
    ip_locked = bool(cache.get(_ip_lock_key(store.pk, ip))) if ip else False
    return phone_locked or ip_locked


def record_customer_login_failure(store, phone, ip):
    p_fail_key = _phone_fail_key(store.pk, phone)
    p_fails = int(cache.get(p_fail_key, 0)) + 1
    cache.set(p_fail_key, p_fails, LOCKOUT_SECONDS)
    if p_fails >= LOCKOUT_THRESHOLD:
        cache.set(_phone_lock_key(store.pk, phone), True, LOCKOUT_SECONDS)

    if ip:
        i_fail_key = _ip_fail_key(store.pk, ip)
        i_fails = int(cache.get(i_fail_key, 0)) + 1
        cache.set(i_fail_key, i_fails, LOCKOUT_SECONDS)
        if i_fails >= LOCKOUT_THRESHOLD:
            cache.set(_ip_lock_key(store.pk, ip), True, LOCKOUT_SECONDS)


def clear_customer_login_failures(store, phone, ip=None):
    cache.delete(_phone_fail_key(store.pk, phone))
    cache.delete(_phone_lock_key(store.pk, phone))
    if ip:
        cache.delete(_ip_fail_key(store.pk, ip))
        cache.delete(_ip_lock_key(store.pk, ip))


class OnlineStoreMixin:
    """Enforces that the store is active and on the Online plan (404 otherwise)."""

    def dispatch(self, request, *args, **kwargs):
        self.store = get_online_store_or_404(kwargs['store_slug'])
        self.current_customer = get_store_customer(request, self.store)
        return super().dispatch(request, *args, **kwargs)

    def get_base_context(self, **kwargs):
        from storefront.context_processors import build_theme_context_for_store
        ctx = {
            'store': self.store,
            'current_customer': self.current_customer,
            **build_theme_context_for_store(self.store),
        }
        ctx.update(kwargs)
        return ctx


class CustomerLoginRequiredMixin(OnlineStoreMixin):
    """Requires an authenticated customer session for this specific Online-plan store."""

    def dispatch(self, request, *args, **kwargs):
        self.store = get_online_store_or_404(kwargs['store_slug'])
        self.current_customer = get_store_customer(request, self.store)
        if self.current_customer is None:
            login_url = reverse('storefront:customer_login', kwargs={'store_slug': self.store.slug})
            return redirect(f"{login_url}?next={request.path}")
        return super(OnlineStoreMixin, self).dispatch(request, *args, **kwargs)
