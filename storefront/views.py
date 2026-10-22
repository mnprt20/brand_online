from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from catalog.models import Category, Product
from orders.models import Order, OrderItem
from orders.payments import get_enabled_payment_methods
from orders.services import calculate_delivery_fee, place_online_order
from storefront.auth import (
    CustomerLoginRequiredMixin,
    OnlineStoreMixin,
    get_online_store_or_404,
    get_store_customer,
    login_store_customer,
    logout_store_customer,
)
from storefront.forms import (
    CheckoutForm,
    CustomerAddressForm,
    CustomerLoginForm,
    CustomerProfileForm,
    CustomerRegisterForm,
    OnlineCheckoutForm,
)
from stores.models import Customer, CustomerAddress, Membership, PaymentQR, Store


from storefront.context_processors import build_theme_context_for_store
from storefront.themes.registry import resolve_theme_key, theme_template

TEMPLATE_MAP = {
    Store.TEMPLATE_CLASSIC: 'storefront/classic.html',
    Store.TEMPLATE_MINIMAL: 'storefront/minimal.html',
    Store.TEMPLATE_BOLD: 'storefront/bold.html',
}


def get_active_store_or_404(slug):
    return get_object_or_404(Store.objects.select_related('plan'), slug=slug, is_active=True)


def _get_store_cart(session, store):
    carts = session.get('carts', {})
    return dict(carts.get(str(store.pk), {}))


def _save_store_cart(session, store, store_cart):
    carts = dict(session.get('carts', {}))
    if store_cart:
        carts[str(store.pk)] = store_cart
    else:
        carts.pop(str(store.pk), None)
    session['carts'] = carts
    session.modified = True


def _save_store_ref(session, store, ref_code):
    store_refs = dict(session.get('store_refs', {}))
    cleaned_ref = (ref_code or '').strip()
    if cleaned_ref:
        store_refs[str(store.pk)] = cleaned_ref
    else:
        store_refs.pop(str(store.pk), None)
    session['store_refs'] = store_refs
    session.modified = True


def _resolve_referral_staff_user(session, store):
    store_refs = session.get('store_refs', {})
    ref_code = (store_refs.get(str(store.pk)) or '').strip()
    if not ref_code:
        return None
    membership = (
        Membership.objects.filter(
            store=store,
            referral_code=ref_code,
            role=Membership.ROLE_STAFF,
            is_active=True,
        )
        .select_related('user')
        .first()
    )
    if membership and membership.user.is_active:
        return membership.user
    return None


def build_cart_context(session, store):
    raw_cart = _get_store_cart(session, store)
    product_ids = [int(pid) for pid in raw_cart.keys() if str(pid).isdigit()]
    products = Product.objects.for_store(store).filter(
        pk__in=product_ids,
        is_available=True,
    )
    product_map = {p.pk: p for p in products}
    items = []
    cart_total = Decimal('0.00')
    cart_count = 0

    for pid_str, qty in raw_cart.items():
        if not str(pid_str).isdigit():
            continue
        product = product_map.get(int(pid_str))
        if not product or qty <= 0:
            continue
        subtotal = (product.price * Decimal(qty)).quantize(Decimal('0.01'))
        cart_total += subtotal
        cart_count += qty
        items.append({
            'product': product,
            'quantity': qty,
            'subtotal': subtotal,
        })

    return {
        'cart_items': items,
        'cart_total': cart_total.quantize(Decimal('0.01')),
        'cart_count': cart_count,
    }


def _resolve_store_home_template(theme_key):
    resolved_key = resolve_theme_key(theme_key)
    if resolved_key in TEMPLATE_MAP:
        return TEMPLATE_MAP[resolved_key]
    return theme_template(resolved_key, 'home.html')


class StorefrontDetailView(View):
    def get(self, request, store_slug):
        store = get_active_store_or_404(store_slug)
        if 'ref' in request.GET:
            _save_store_ref(request.session, store, request.GET.get('ref', ''))

        categories = Category.objects.for_store(store)
        products = Product.objects.for_store(store).filter(is_available=True).select_related('category')

        selected_category_id = request.GET.get('category')
        selected_category = None
        if selected_category_id and selected_category_id.isdigit():
            selected_category = categories.filter(pk=int(selected_category_id)).first()
            if selected_category:
                products = products.filter(category=selected_category)

        cart_ctx = build_cart_context(request.session, store)
        theme_ctx = build_theme_context_for_store(store)
        template_name = _resolve_store_home_template(store.template_key)
        current_customer = get_store_customer(request, store)

        context = {
            'store': store,
            'current_customer': current_customer,
            'categories': categories,
            'products': products,
            'selected_category': selected_category,
            'checkout_form': CheckoutForm(),
            **cart_ctx,
            **theme_ctx,
        }
        return render(request, template_name, context)


class CartAddView(View):
    def post(self, request, store_slug):
        store = get_active_store_or_404(store_slug)
        product_id = request.POST.get('product_id')
        try:
            quantity = int(request.POST.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1

        if quantity < 1:
            quantity = 1

        product = get_object_or_404(
            Product.objects.for_store(store),
            pk=product_id,
            is_available=True,
        )
        store_cart = _get_store_cart(request.session, store)
        key = str(product.pk)
        store_cart[key] = store_cart.get(key, 0) + quantity
        _save_store_cart(request.session, store, store_cart)
        return redirect('storefront:detail', store_slug=store.slug)


class CartUpdateView(View):
    def post(self, request, store_slug):
        store = get_active_store_or_404(store_slug)
        product_id = request.POST.get('product_id')
        try:
            quantity = int(request.POST.get('quantity', 0))
        except (TypeError, ValueError):
            quantity = 0

        product = get_object_or_404(
            Product.objects.for_store(store),
            pk=product_id,
        )
        store_cart = _get_store_cart(request.session, store)
        key = str(product.pk)
        if quantity <= 0:
            store_cart.pop(key, None)
        else:
            store_cart[key] = quantity
        _save_store_cart(request.session, store, store_cart)
        return redirect('storefront:detail', store_slug=store.slug)


class CartRemoveView(View):
    def post(self, request, store_slug):
        store = get_active_store_or_404(store_slug)
        product_id = request.POST.get('product_id')
        store_cart = _get_store_cart(request.session, store)
        if product_id:
            store_cart.pop(str(product_id), None)
        _save_store_cart(request.session, store, store_cart)
        return redirect('storefront:detail', store_slug=store.slug)


class CheckoutView(View):
    def get(self, request, store_slug):
        store = get_active_store_or_404(store_slug)
        if 'ref' in request.GET:
            _save_store_ref(request.session, store, request.GET.get('ref', ''))
        cart_ctx = build_cart_context(request.session, store)
        theme_ctx = build_theme_context_for_store(store)
        template_name = theme_template(store.template_key, 'checkout.html')
        return render(
            request,
            template_name,
            {
                'store': store,
                'current_customer': get_store_customer(request, store),
                'checkout_form': CheckoutForm(),
                **cart_ctx,
                **theme_ctx,
            },
        )

    @transaction.atomic
    def post(self, request, store_slug):
        store = get_active_store_or_404(store_slug)
        if 'ref' in request.GET:
            _save_store_ref(request.session, store, request.GET.get('ref', ''))
        cart_ctx = build_cart_context(request.session, store)
        theme_ctx = build_theme_context_for_store(store)
        template_name = theme_template(store.template_key, 'checkout.html')
        form = CheckoutForm(request.POST)

        if not cart_ctx['cart_items']:
            form.add_error(None, 'Your cart is empty.')
            return render(
                request,
                template_name,
                {
                    'store': store,
                    'current_customer': get_store_customer(request, store),
                    'checkout_form': form,
                    **cart_ctx,
                    **theme_ctx,
                },
                status=400,
            )

        if not form.is_valid():
            return render(
                request,
                template_name,
                {
                    'store': store,
                    'current_customer': get_store_customer(request, store),
                    'checkout_form': form,
                    **cart_ctx,
                    **theme_ctx,
                },
                status=400,
            )

        placed_by_user = _resolve_referral_staff_user(request.session, store)

        order = Order.objects.create(
            store=store,
            customer_name=form.cleaned_data['customer_name'],
            customer_phone=form.cleaned_data['customer_phone'],
            note=form.cleaned_data.get('note', ''),
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_UNPAID,
            source=Order.SOURCE_QR,
            placed_by=placed_by_user,
            total=Decimal('0.00'),
        )

        for item in cart_ctx['cart_items']:
            product = item['product']
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name_snapshot=product.name,
                unit_price_snapshot=product.price,
                quantity=item['quantity'],
            )

        order.recalculate_total(save=True)
        _save_store_cart(request.session, store, {})

        return redirect(
            'storefront:order_confirmation',
            store_slug=store.slug,
            order_number=order.order_number,
        )


class OrderConfirmationView(View):
    def get(self, request, store_slug, order_number):
        store = get_active_store_or_404(store_slug)
        order = get_object_or_404(
            Order.objects.for_store(store).prefetch_related('items'),
            order_number=order_number,
        )
        payment_qr = PaymentQR.objects.for_store(store).first()
        current_customer = get_store_customer(request, store)
        theme_ctx = build_theme_context_for_store(store)
        template_name = theme_template(store.template_key, 'confirmation.html')
        return render(
            request,
            template_name,
            {
                'store': store,
                'order': order,
                'payment_qr': payment_qr,
                'current_customer': current_customer,
                **theme_ctx,
            },
        )


class PublicStoreQRView(View):
    def get(self, request, store_slug):
        from stores.views import generate_store_qr_png_response
        store = get_active_store_or_404(store_slug)
        return generate_store_qr_png_response(request, store)


def _safe_store_next_url(request, store):
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    store_prefix = f"/s/{store.slug}/"
    if next_url and next_url.startswith(store_prefix):
        return next_url
    return reverse('storefront:customer_account', kwargs={'store_slug': store.slug})


class CustomerRegisterView(OnlineStoreMixin, View):
    template_name = 'storefront/account_register.html'

    def get(self, request, store_slug):
        if self.current_customer:
            return redirect('storefront:customer_account', store_slug=self.store.slug)
        form = CustomerRegisterForm(store=self.store)
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, next_url=request.GET.get('next', '')),
        )

    def post(self, request, store_slug):
        form = CustomerRegisterForm(request.POST, store=self.store)
        if form.is_valid():
            customer = form.save()
            login_store_customer(request, self.store, customer)
            messages.success(request, f"Welcome to {self.store.name}, {customer.name}!")
            return redirect(_safe_store_next_url(request, self.store))
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, next_url=request.POST.get('next', '')),
            status=400,
        )


class CustomerLoginView(OnlineStoreMixin, View):
    template_name = 'storefront/account_login.html'

    def get(self, request, store_slug):
        if self.current_customer:
            return redirect('storefront:customer_account', store_slug=self.store.slug)
        form = CustomerLoginForm(store=self.store, request=request)
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, next_url=request.GET.get('next', '')),
        )

    def post(self, request, store_slug):
        form = CustomerLoginForm(request.POST, store=self.store, request=request)
        if form.is_valid():
            login_store_customer(request, self.store, form.customer)
            messages.success(request, f"Welcome back, {form.customer.name}!")
            return redirect(_safe_store_next_url(request, self.store))
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, next_url=request.POST.get('next', '')),
            status=400,
        )


class CustomerLogoutView(OnlineStoreMixin, View):
    def post(self, request, store_slug):
        logout_store_customer(request, self.store)
        return redirect('storefront:detail', store_slug=self.store.slug)

    def get(self, request, store_slug):
        logout_store_customer(request, self.store)
        return redirect('storefront:detail', store_slug=self.store.slug)


class CustomerAccountView(CustomerLoginRequiredMixin, View):
    template_name = 'storefront/account_profile.html'

    def get(self, request, store_slug):
        profile_form = CustomerProfileForm(instance=self.current_customer)
        address_form = CustomerAddressForm()
        addresses = self.current_customer.addresses.all()
        recent_orders = (
            Order.objects.for_store(self.store)
            .filter(customer=self.current_customer)
            .prefetch_related('items')[:5]
        )
        return render(
            request,
            self.template_name,
            self.get_base_context(
                profile_form=profile_form,
                address_form=address_form,
                addresses=addresses,
                recent_orders=recent_orders,
            ),
        )

    def post(self, request, store_slug):
        profile_form = CustomerProfileForm(request.POST, instance=self.current_customer)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('storefront:customer_account', store_slug=self.store.slug)
        address_form = CustomerAddressForm()
        addresses = self.current_customer.addresses.all()
        recent_orders = (
            Order.objects.for_store(self.store)
            .filter(customer=self.current_customer)
            .prefetch_related('items')[:5]
        )
        return render(
            request,
            self.template_name,
            self.get_base_context(
                profile_form=profile_form,
                address_form=address_form,
                addresses=addresses,
                recent_orders=recent_orders,
            ),
            status=400,
        )


class CustomerAddressCreateView(CustomerLoginRequiredMixin, View):
    template_name = 'storefront/address_form.html'

    def get(self, request, store_slug):
        form = CustomerAddressForm()
        return render(request, self.template_name, self.get_base_context(form=form, is_edit=False))

    def post(self, request, store_slug):
        form = CustomerAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.customer = self.current_customer
            address.save()
            messages.success(request, 'Address saved to your address book.')
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and next_url.startswith(f"/s/{self.store.slug}/"):
                return redirect(next_url)
            return redirect('storefront:customer_account', store_slug=self.store.slug)
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, is_edit=False),
            status=400,
        )


class CustomerAddressUpdateView(CustomerLoginRequiredMixin, View):
    template_name = 'storefront/address_form.html'

    def _get_address(self, pk):
        return get_object_or_404(CustomerAddress, pk=pk, customer=self.current_customer)

    def get(self, request, store_slug, pk):
        address = self._get_address(pk)
        form = CustomerAddressForm(instance=address)
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, address=address, is_edit=True),
        )

    def post(self, request, store_slug, pk):
        address = self._get_address(pk)
        form = CustomerAddressForm(request.POST, instance=address)
        if form.is_valid():
            form.save()
            messages.success(request, 'Address updated.')
            return redirect('storefront:customer_account', store_slug=self.store.slug)
        return render(
            request,
            self.template_name,
            self.get_base_context(form=form, address=address, is_edit=True),
            status=400,
        )


class CustomerAddressDeleteView(CustomerLoginRequiredMixin, View):
    def post(self, request, store_slug, pk):
        address = get_object_or_404(CustomerAddress, pk=pk, customer=self.current_customer)
        was_default = address.is_default
        address.delete()
        if was_default:
            remaining = CustomerAddress.objects.filter(customer=self.current_customer).first()
            if remaining and not remaining.is_default:
                remaining.is_default = True
                remaining.save()
        messages.success(request, 'Address deleted.')
        return redirect('storefront:customer_account', store_slug=self.store.slug)


class CustomerAddressSetDefaultView(CustomerLoginRequiredMixin, View):
    def post(self, request, store_slug, pk):
        address = get_object_or_404(CustomerAddress, pk=pk, customer=self.current_customer)
        address.is_default = True
        address.save()
        messages.success(request, f"'{address.label}' set as your default address.")
        return redirect('storefront:customer_account', store_slug=self.store.slug)


class OnlineCheckoutView(CustomerLoginRequiredMixin, View):
    template_name = 'storefront/online_checkout.html'

    def _build_checkout_context(self, request, form):
        cart_ctx = build_cart_context(request.session, self.store)
        subtotal = cart_ctx['cart_total']
        delivery_fee_preview = calculate_delivery_fee(
            self.store,
            subtotal,
            Order.FULFILMENT_DELIVERY,
        )
        delivery_total_preview = (subtotal + delivery_fee_preview).quantize(Decimal('0.01'))
        pickup_total_preview = subtotal
        payment_qr = PaymentQR.objects.for_store(self.store).first()
        enabled_payment_methods = get_enabled_payment_methods(self.store)
        addresses = self.current_customer.addresses.all()
        return self.get_base_context(
            form=form,
            addresses=addresses,
            payment_qr=payment_qr,
            enabled_payment_methods=enabled_payment_methods,
            delivery_fee_preview=delivery_fee_preview,
            delivery_total_preview=delivery_total_preview,
            pickup_total_preview=pickup_total_preview,
            **cart_ctx,
        )

    def get(self, request, store_slug):
        if 'ref' in request.GET:
            _save_store_ref(request.session, self.store, request.GET.get('ref', ''))
        form = OnlineCheckoutForm(store=self.store, customer=self.current_customer)
        return render(
            request,
            self.template_name,
            self._build_checkout_context(request, form),
        )

    def post(self, request, store_slug):
        if 'ref' in request.GET:
            _save_store_ref(request.session, self.store, request.GET.get('ref', ''))
        form = OnlineCheckoutForm(
            request.POST,
            store=self.store,
            customer=self.current_customer,
        )
        cart_ctx = build_cart_context(request.session, self.store)
        if not cart_ctx['cart_items']:
            form.add_error(None, 'Your cart is empty.')
            return render(
                request,
                self.template_name,
                self._build_checkout_context(request, form),
                status=400,
            )

        if not form.is_valid():
            return render(
                request,
                self.template_name,
                self._build_checkout_context(request, form),
                status=400,
            )

        placed_by_user = _resolve_referral_staff_user(request.session, self.store)
        customer_note = (
            form.cleaned_data.get('customer_note')
            or request.POST.get('note')
            or ''
        )

        try:
            with transaction.atomic():
                selected_address = form.selected_address
                if selected_address is None and form.new_address_data:
                    selected_address = CustomerAddress.objects.create(
                        customer=self.current_customer,
                        **form.new_address_data,
                    )
                order = place_online_order(
                    store=self.store,
                    customer=self.current_customer,
                    cart_items=cart_ctx['cart_items'],
                    fulfilment_type=form.cleaned_data['fulfilment_type'],
                    payment_method=form.cleaned_data['payment_method'],
                    address=selected_address,
                    delivery_address_text=form.resolved_delivery_address_text,
                    payment_reference=form.cleaned_data.get('payment_reference', ''),
                    customer_note=customer_note,
                    placed_by=placed_by_user,
                )
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
            return render(
                request,
                self.template_name,
                self._build_checkout_context(request, form),
                status=400,
            )

        _save_store_cart(request.session, self.store, {})
        return redirect(
            'storefront:order_confirmation',
            store_slug=self.store.slug,
            order_number=order.order_number,
        )


class CustomerOrderListView(CustomerLoginRequiredMixin, View):
    template_name = 'storefront/account_orders.html'

    def get(self, request, store_slug):
        orders = (
            Order.objects.for_store(self.store)
            .filter(customer=self.current_customer)
            .prefetch_related('items', 'status_events')
        )
        return render(
            request,
            self.template_name,
            self.get_base_context(orders=orders),
        )


class CustomerOrderDetailView(CustomerLoginRequiredMixin, View):
    template_name = 'storefront/account_order_detail.html'

    def get(self, request, store_slug, order_number):
        order = get_object_or_404(
            Order.objects.for_store(self.store)
            .filter(customer=self.current_customer)
            .prefetch_related('items', 'status_events__changed_by'),
            order_number=order_number,
        )
        status_events = order.status_events.all()
        can_customer_cancel = order.can_transition_to(
            Order.STATUS_CANCELLED,
            by_customer=True,
        )
        payment_qr = PaymentQR.objects.for_store(self.store).first()
        return render(
            request,
            self.template_name,
            self.get_base_context(
                order=order,
                status_events=status_events,
                can_customer_cancel=can_customer_cancel,
                payment_qr=payment_qr,
            ),
        )


class CustomerOrderCancelView(CustomerLoginRequiredMixin, View):
    def post(self, request, store_slug, order_number):
        order = get_object_or_404(
            Order.objects.for_store(self.store)
            .filter(customer=self.current_customer)
            .prefetch_related('items', 'status_events__changed_by'),
            order_number=order_number,
        )
        if not order.can_transition_to(Order.STATUS_CANCELLED, by_customer=True):
            status_events = order.status_events.all()
            payment_qr = PaymentQR.objects.for_store(self.store).first()
            return render(
                request,
                'storefront/account_order_detail.html',
                self.get_base_context(
                    order=order,
                    status_events=status_events,
                    can_customer_cancel=False,
                    payment_qr=payment_qr,
                    cancel_error='This order can no longer be cancelled because its status is already beyond New.',
                ),
                status=400,
            )

        order.transition_status(Order.STATUS_CANCELLED, changed_by=None, by_customer=True)
        messages.success(request, f"Order {order.order_number} has been cancelled.")
        return redirect(
            'storefront:customer_order_detail',
            store_slug=self.store.slug,
            order_number=order.order_number,
        )




