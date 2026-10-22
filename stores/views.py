from datetime import date, timedelta
from decimal import Decimal
import io
import qrcode
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)
from catalog.models import Category, Product
from orders.models import Order, OrderItem
from stores.forms import (
    CategoryForm,
    CounterOrderForm,
    OrderStatusForm,
    PaymentQRForm,
    ProductForm,
    StaffCreateForm,
    StaffPasswordResetForm,
    StoreAppearanceForm,
    StoreSettingsForm,
)
from stores.mixins import OwnerRequiredMixin, StaffOrOwnerMixin
from stores.models import Membership, PaymentQR, Store
from stores.services import validate_store_seat_limit


def generate_qr_png_response_for_url(url, filename):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    response = HttpResponse(buf.getvalue(), content_type='image/png')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-QR-Target-URL'] = url
    return response


def generate_store_qr_png_response(request, store, referral_code=None, filename_prefix=None):
    public_path = reverse('storefront:detail', kwargs={'store_slug': store.slug})
    if referral_code:
        public_path = f"{public_path}?ref={referral_code}"
    public_url = request.build_absolute_uri(public_path)
    prefix = filename_prefix or store.slug
    return generate_qr_png_response_for_url(public_url, f"{prefix}-qr.png")


class StoreQRDownloadView(OwnerRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        store = self.get_store()
        return generate_store_qr_png_response(request, store)


class DashboardHomeView(StaffOrOwnerMixin, TemplateView):
    template_name = 'dashboard/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_store()
        if self.is_staff_member():
            orders_qs = Order.objects.for_store(store).filter(placed_by=self.request.user)
        else:
            orders_qs = Order.objects.for_store(store)
        context['category_count'] = Category.objects.for_store(store).count()
        context['product_count'] = Product.objects.for_store(store).count()
        context['order_count'] = orders_qs.count()
        context['recent_orders'] = orders_qs.select_related('placed_by')[:5]
        return context


class CategoryListView(OwnerRequiredMixin, ListView):
    model = Category
    template_name = 'dashboard/category_list.html'
    context_object_name = 'categories'


class CategoryDetailView(OwnerRequiredMixin, DetailView):
    model = Category
    template_name = 'dashboard/category_detail.html'
    context_object_name = 'category'


class CategoryCreateView(OwnerRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'dashboard/category_form.html'
    success_url = reverse_lazy('dashboard:category_list')

    def form_valid(self, form):
        form.instance.store = self.get_store()
        messages.success(self.request, 'Category created successfully.')
        return super().form_valid(form)


class CategoryUpdateView(OwnerRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'dashboard/category_form.html'
    success_url = reverse_lazy('dashboard:category_list')

    def form_valid(self, form):
        messages.success(self.request, 'Category updated successfully.')
        return super().form_valid(form)


class CategoryDeleteView(OwnerRequiredMixin, DeleteView):
    model = Category
    template_name = 'dashboard/category_confirm_delete.html'
    success_url = reverse_lazy('dashboard:category_list')


class ProductListView(OwnerRequiredMixin, ListView):
    model = Product
    template_name = 'dashboard/product_list.html'
    context_object_name = 'products'

    def get_queryset(self):
        return super().get_queryset().select_related('category')


class ProductDetailView(OwnerRequiredMixin, DetailView):
    model = Product
    template_name = 'dashboard/product_detail.html'
    context_object_name = 'product'


class ProductCreateView(OwnerRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'dashboard/product_form.html'
    success_url = reverse_lazy('dashboard:product_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.get_store()
        return kwargs

    def form_valid(self, form):
        form.instance.store = self.get_store()
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Product created successfully.')
        return super().form_valid(form)


class ProductUpdateView(OwnerRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'dashboard/product_form.html'
    success_url = reverse_lazy('dashboard:product_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.get_store()
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Product updated successfully.')
        return super().form_valid(form)


class ProductDeleteView(OwnerRequiredMixin, DeleteView):
    model = Product
    template_name = 'dashboard/product_confirm_delete.html'
    success_url = reverse_lazy('dashboard:product_list')


class StoreSettingsView(OwnerRequiredMixin, UpdateView):
    model = Store
    form_class = StoreSettingsForm
    template_name = 'dashboard/settings.html'
    success_url = reverse_lazy('dashboard:settings')

    def get_object(self, queryset=None):
        store = self.get_store()
        pk = self.kwargs.get('pk')
        if pk is not None and int(pk) != store.pk:
            raise Http404("Store not found.")
        return store

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        raise Http404("Store deletion is not permitted.")

    def form_valid(self, form):
        messages.success(self.request, 'Store settings updated successfully.')
        return super().form_valid(form)


class PaymentQRUpdateView(OwnerRequiredMixin, UpdateView):
    model = PaymentQR
    form_class = PaymentQRForm
    template_name = 'dashboard/payment_qr.html'
    success_url = reverse_lazy('dashboard:payment_qr')

    def get_object(self, queryset=None):
        store = self.get_store()
        pk = self.kwargs.get('pk')
        if pk is not None:
            return get_object_or_404(PaymentQR.objects.for_store(store), pk=pk)
        obj, _ = PaymentQR.objects.get_or_create(store=store)
        return obj

    def form_valid(self, form):
        form.instance.store = self.get_store()
        messages.success(self.request, 'Payment QR updated successfully.')
        return super().form_valid(form)


class OrderListView(StaffOrOwnerMixin, ListView):
    model = Order
    template_name = 'dashboard/order_list.html'
    context_object_name = 'orders'

    def get_queryset(self):
        qs = super().get_queryset().select_related('placed_by', 'customer').prefetch_related('items')
        store = self.get_store()
        if self.is_staff_member():
            qs = qs.filter(placed_by=self.request.user)
        else:
            staff_filter = self.request.GET.get('staff')
            if staff_filter == 'direct':
                qs = qs.filter(Q(placed_by__isnull=True) | Q(placed_by_id=store.owner_id))
            elif staff_filter and staff_filter.isdigit():
                qs = qs.filter(placed_by_id=int(staff_filter))

        status_filter = (self.request.GET.get('status') or '').strip()
        if status_filter:
            normalized_status = Order.normalize_status(status_filter)
            valid_statuses = {code for code, _ in Order.STATUS_CHOICES}
            if normalized_status in valid_statuses:
                qs = qs.filter(status=normalized_status)

        fulfilment_filter = (
            self.request.GET.get('fulfilment')
            or self.request.GET.get('fulfilment_type')
            or ''
        ).strip()
        if fulfilment_filter in (Order.FULFILMENT_PICKUP, Order.FULFILMENT_DELIVERY):
            qs = qs.filter(fulfilment_type=fulfilment_filter)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_store()
        staff_memberships = Membership.objects.for_store(store).select_related('user').filter(
            role=Membership.ROLE_STAFF
        )
        staff_name_map = {
            m.user_id: m.get_display_label()
            for m in Membership.objects.for_store(store).select_related('user')
        }
        orders = list(context['orders'])
        for order in orders:
            if order.placed_by_id and order.placed_by_id in staff_name_map and order.placed_by_id != store.owner_id:
                order.sold_by_label = staff_name_map[order.placed_by_id]
            else:
                order.sold_by_label = 'Owner/Direct'
        context['orders'] = orders
        context['staff_memberships'] = staff_memberships
        context['selected_staff'] = self.request.GET.get('staff', '')
        context['selected_status'] = Order.normalize_status(self.request.GET.get('status', '')) or ''
        context['selected_fulfilment'] = (
            self.request.GET.get('fulfilment')
            or self.request.GET.get('fulfilment_type')
            or ''
        )
        context['status_choices'] = Order.STATUS_CHOICES
        context['fulfilment_choices'] = Order.FULFILMENT_CHOICES
        return context


def _build_order_detail_extra_context(order):
    status_label_map = dict(Order.STATUS_CHOICES)
    allowed_codes = order.get_allowed_next_statuses()
    allowed_next_statuses = [
        (code, status_label_map.get(code, code.title()))
        for code in allowed_codes
    ]
    status_events = order.status_events.select_related('changed_by').all()
    return {
        'allowed_next_statuses': allowed_next_statuses,
        'status_events': status_events,
    }


class OrderDetailView(StaffOrOwnerMixin, DetailView):
    model = Order
    template_name = 'dashboard/order_detail.html'
    context_object_name = 'order'

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related('placed_by', 'customer')
            .prefetch_related('items', 'status_events__changed_by')
        )
        if self.is_staff_member():
            qs = qs.filter(placed_by=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_form'] = OrderStatusForm(instance=self.object)
        context.update(_build_order_detail_extra_context(self.object))
        return context


class OrderStatusUpdateView(StaffOrOwnerMixin, UpdateView):
    model = Order
    form_class = OrderStatusForm
    template_name = 'dashboard/order_detail.html'

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related('placed_by', 'customer')
            .prefetch_related('items', 'status_events__changed_by')
        )
        if self.is_staff_member():
            qs = qs.filter(placed_by=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['order'] = self.object
        context['status_form'] = context.get('form') or OrderStatusForm(instance=self.object)
        context.update(_build_order_detail_extra_context(self.object))
        return context

    def get_success_url(self):
        return reverse_lazy('dashboard:order_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        form.instance._status_changed_by = self.request.user
        messages.success(self.request, f"Order {self.object.order_number} status updated.")
        return super().form_valid(form)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form), status=400)


class OrderMarkPaidView(StaffOrOwnerMixin, View):
    def post(self, request, pk, *args, **kwargs):
        store = self.get_store()
        qs = Order.objects.for_store(store)
        if self.is_staff_member():
            qs = qs.filter(placed_by=request.user)
        order = get_object_or_404(qs, pk=pk)

        raw_ref = request.POST.get('payment_reference')
        if raw_ref is not None and raw_ref.strip():
            order.payment_reference = raw_ref.strip()[:200]

        order.payment_status = Order.PAYMENT_PAID
        order.save(update_fields=['payment_status', 'payment_reference'])
        messages.success(request, f"Payment marked as received for {order.order_number}.")
        return redirect('dashboard:order_detail', pk=order.pk)


class OrderNewCountView(StaffOrOwnerMixin, View):
    def get(self, request, *args, **kwargs):
        store = self.get_store()
        qs = Order.objects.for_store(store).filter(status=Order.STATUS_NEW)
        if self.is_staff_member():
            qs = qs.filter(placed_by=request.user)
        count = qs.count()
        return JsonResponse({'new_count': count, 'count': count})


class OrderDeleteView(OwnerRequiredMixin, DeleteView):
    model = Order
    template_name = 'dashboard/order_confirm_delete.html'
    success_url = reverse_lazy('dashboard:order_list')


class StaffListView(OwnerRequiredMixin, ListView):
    require_franchise = True
    model = Membership
    template_name = 'dashboard/staff_list.html'
    context_object_name = 'staff_memberships'

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related('user')
            .filter(role=Membership.ROLE_STAFF)
        )


class StaffCreateView(OwnerRequiredMixin, View):
    require_franchise = True
    template_name = 'dashboard/staff_form.html'

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        form = StaffCreateForm(store=store)
        return render(request, self.template_name, self.get_context_data(form=form))

    def post(self, request, *args, **kwargs):
        store = self.get_store()
        form = StaffCreateForm(request.POST, store=store)
        if form.is_valid():
            membership = form.save()
            messages.success(
                request,
                f"Staff member '{membership.get_display_label()}' created successfully.",
            )
            return redirect('dashboard:staff_list')
        return render(
            request,
            self.template_name,
            self.get_context_data(form=form),
            status=400,
        )


class StaffToggleActiveView(OwnerRequiredMixin, View):
    require_franchise = True

    def post(self, request, pk, *args, **kwargs):
        store = self.get_store()
        membership = get_object_or_404(
            Membership.objects.for_store(store).select_related('user'),
            pk=pk,
            role=Membership.ROLE_STAFF,
        )
        action = request.POST.get('action')
        if action == 'deactivate':
            target_active = False
        elif action == 'activate':
            target_active = True
        else:
            target_active = not membership.is_active

        if target_active and not membership.is_active:
            try:
                validate_store_seat_limit(
                    store,
                    is_active=True,
                    exclude_membership_pk=membership.pk,
                )
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
                return redirect('dashboard:staff_list')

        membership.is_active = target_active
        membership.save()
        state_word = 'reactivated' if membership.is_active else 'deactivated'
        messages.success(
            request,
            f"Staff member '{membership.get_display_label()}' {state_word}.",
        )
        return redirect('dashboard:staff_list')


class StaffPasswordResetView(OwnerRequiredMixin, View):
    require_franchise = True
    template_name = 'dashboard/staff_reset_password.html'

    def _get_staff_membership(self, pk):
        store = self.get_store()
        return get_object_or_404(
            Membership.objects.for_store(store).select_related('user'),
            pk=pk,
            role=Membership.ROLE_STAFF,
        )

    def get(self, request, pk, *args, **kwargs):
        membership = self._get_staff_membership(pk)
        form = StaffPasswordResetForm(target_user=membership.user)
        return render(
            request,
            self.template_name,
            self.get_context_data(form=form, staff_membership=membership),
        )

    def post(self, request, pk, *args, **kwargs):
        membership = self._get_staff_membership(pk)
        form = StaffPasswordResetForm(request.POST, target_user=membership.user)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"Password updated for '{membership.get_display_label()}'.",
            )
            return redirect('dashboard:staff_list')
        return render(
            request,
            self.template_name,
            self.get_context_data(form=form, staff_membership=membership),
            status=400,
        )


class StaffQRByOwnerView(OwnerRequiredMixin, View):
    require_franchise = True

    def get(self, request, pk, *args, **kwargs):
        store = self.get_store()
        membership = get_object_or_404(
            Membership.objects.for_store(store).select_related('user'),
            pk=pk,
            role=Membership.ROLE_STAFF,
        )
        return generate_store_qr_png_response(
            request,
            store,
            referral_code=membership.referral_code,
            filename_prefix=f"{store.slug}-{membership.user.username}",
        )


class StaffCatalogListView(StaffOrOwnerMixin, ListView):
    model = Product
    template_name = 'dashboard/staff_catalog.html'
    context_object_name = 'products'

    def get_queryset(self):
        qs = super().get_queryset().select_related('category')
        category_id = self.request.GET.get('category')
        if category_id and category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_store()
        context['categories'] = Category.objects.for_store(store)
        context['selected_category'] = self.request.GET.get('category', '')
        return context


class CounterOrderCreateView(StaffOrOwnerMixin, View):
    template_name = 'dashboard/counter_order_form.html'

    def _get_products(self):
        return (
            Product.objects.for_store(self.get_store())
            .filter(is_available=True)
            .select_related('category')
        )

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        form = CounterOrderForm(store=store)
        return render(
            request,
            self.template_name,
            self.get_context_data(form=form, products=self._get_products()),
        )

    def post(self, request, *args, **kwargs):
        store = self.get_store()
        form = CounterOrderForm(request.POST, store=store)
        if form.is_valid():
            order = form.save(placed_by=request.user)
            messages.success(request, f"Counter order {order.order_number} created successfully.")
            return redirect('dashboard:order_detail', pk=order.pk)
        return render(
            request,
            self.template_name,
            self.get_context_data(form=form, products=self._get_products()),
            status=400,
        )


class StaffMyQRView(StaffOrOwnerMixin, TemplateView):
    require_franchise = True
    template_name = 'dashboard/my_qr.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_store()
        membership = self.get_membership()
        public_path = reverse('storefront:detail', kwargs={'store_slug': store.slug})
        personal_path = f"{public_path}?ref={membership.referral_code}"
        context['personal_storefront_path'] = personal_path
        context['personal_storefront_url'] = self.request.build_absolute_uri(personal_path)
        return context


class StaffMyQRDownloadView(StaffOrOwnerMixin, View):
    require_franchise = True

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        membership = self.get_membership()
        return generate_store_qr_png_response(
            request,
            store,
            referral_code=membership.referral_code,
            filename_prefix=f"{store.slug}-{membership.user.username}",
        )


class SalesReportView(OwnerRequiredMixin, TemplateView):
    require_franchise = True
    template_name = 'dashboard/sales_report.html'

    def _parse_date_range(self):
        today = timezone.now().date()
        default_start = today - timedelta(days=30)
        default_end = today

        raw_start = (self.request.GET.get('start_date') or '').strip()
        raw_end = (self.request.GET.get('end_date') or '').strip()

        try:
            start_date = date.fromisoformat(raw_start) if raw_start else default_start
        except ValueError:
            start_date = default_start

        try:
            end_date = date.fromisoformat(raw_end) if raw_end else default_end
        except ValueError:
            end_date = default_end

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        return start_date, end_date

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_store()
        start_date, end_date = self._parse_date_range()

        staff_memberships = list(
            Membership.objects.for_store(store)
            .filter(role=Membership.ROLE_STAFF)
            .select_related('user')
            .order_by('id')
        )
        staff_user_ids = [m.user_id for m in staff_memberships]

        if staff_user_ids:
            order_seller_expr = Case(
                When(placed_by_id__in=staff_user_ids, then=F('placed_by_id')),
                default=Value(None),
                output_field=IntegerField(),
            )
            item_seller_expr = Case(
                When(order__placed_by_id__in=staff_user_ids, then=F('order__placed_by_id')),
                default=Value(None),
                output_field=IntegerField(),
            )
        else:
            order_seller_expr = Value(None, output_field=IntegerField())
            item_seller_expr = Value(None, output_field=IntegerField())

        order_base_qs = (
            Order.objects.for_store(store)
            .filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
            .exclude(status=Order.STATUS_CANCELLED)
        )

        order_stats_rows = list(
            order_base_qs.values(seller_id=order_seller_expr).annotate(
                orders_count=Count('id'),
                pending_count=Count(
                    Case(
                        When(status__in=[Order.STATUS_NEW, Order.STATUS_CONFIRMED], then=1),
                        output_field=IntegerField(),
                    )
                ),
                paid_completed_count=Count(
                    Case(
                        When(status__in=[Order.STATUS_PAID, Order.STATUS_COMPLETED], then=1),
                        output_field=IntegerField(),
                    )
                ),
                revenue=Coalesce(
                    Sum(
                        Case(
                            When(
                                status__in=[Order.STATUS_PAID, Order.STATUS_COMPLETED],
                                then=F('total'),
                            ),
                            default=Value(Decimal('0.00')),
                            output_field=DecimalField(max_digits=12, decimal_places=2),
                        )
                    ),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
        )

        line_revenue_expr = ExpressionWrapper(
            F('unit_price_snapshot') * F('quantity'),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
        item_base_qs = (
            OrderItem.objects.filter(
                order__store=store,
                order__created_at__date__gte=start_date,
                order__created_at__date__lte=end_date,
            )
            .exclude(order__status=Order.STATUS_CANCELLED)
        )

        seller_units_rows = list(
            item_base_qs.values(seller_id=item_seller_expr).annotate(
                units_sold=Coalesce(Sum('quantity'), Value(0), output_field=IntegerField()),
            )
        )

        product_breakdown_rows = list(
            item_base_qs.values(
                seller_id=item_seller_expr,
                product_name=F('product_name_snapshot'),
            )
            .annotate(
                units_sold=Coalesce(Sum('quantity'), Value(0), output_field=IntegerField()),
                revenue=Coalesce(
                    Sum(
                        Case(
                            When(
                                order__status__in=[Order.STATUS_PAID, Order.STATUS_COMPLETED],
                                then=line_revenue_expr,
                            ),
                            default=Value(Decimal('0.00')),
                            output_field=DecimalField(max_digits=12, decimal_places=2),
                        )
                    ),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
            .order_by('product_name')
        )

        grand_order_agg = order_base_qs.aggregate(
            orders_count=Count('id'),
            pending_count=Count(
                Case(
                    When(status__in=[Order.STATUS_NEW, Order.STATUS_CONFIRMED], then=1),
                    output_field=IntegerField(),
                )
            ),
            paid_completed_count=Count(
                Case(
                    When(status__in=[Order.STATUS_PAID, Order.STATUS_COMPLETED], then=1),
                    output_field=IntegerField(),
                )
            ),
            revenue=Coalesce(
                Sum(
                    Case(
                        When(
                            status__in=[Order.STATUS_PAID, Order.STATUS_COMPLETED],
                            then=F('total'),
                        ),
                        default=Value(Decimal('0.00')),
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    )
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
        grand_item_agg = item_base_qs.aggregate(
            units_sold=Coalesce(Sum('quantity'), Value(0), output_field=IntegerField()),
        )

        order_stats_by_seller = {row['seller_id']: row for row in order_stats_rows}
        units_by_seller = {row['seller_id']: row['units_sold'] for row in seller_units_rows}
        products_by_seller = {}
        for row in product_breakdown_rows:
            products_by_seller.setdefault(row['seller_id'], []).append({
                'product_name': row['product_name'],
                'units_sold': row['units_sold'],
                'revenue': row['revenue'].quantize(Decimal('0.01')),
            })

        def _build_row(seller_id, seller_name, is_direct=False, membership=None):
            o_row = order_stats_by_seller.get(seller_id, {})
            return {
                'seller_id': seller_id,
                'seller_name': seller_name,
                'is_direct': is_direct,
                'membership': membership,
                'user': membership.user if membership else None,
                'orders_count': o_row.get('orders_count', 0),
                'pending_count': o_row.get('pending_count', 0),
                'paid_completed_count': o_row.get('paid_completed_count', 0),
                'units_sold': units_by_seller.get(seller_id, 0),
                'revenue': (o_row.get('revenue') or Decimal('0.00')).quantize(Decimal('0.01')),
                'products': products_by_seller.get(seller_id, []),
            }

        staff_rows = [
            _build_row(
                seller_id=m.user_id,
                seller_name=m.get_display_label(),
                is_direct=False,
                membership=m,
            )
            for m in staff_memberships
        ]
        direct_row = _build_row(
            seller_id=None,
            seller_name='Direct / unattributed',
            is_direct=True,
            membership=None,
        )

        context.update({
            'start_date': start_date,
            'end_date': end_date,
            'start_date_str': start_date.isoformat(),
            'end_date_str': end_date.isoformat(),
            'staff_rows': staff_rows,
            'direct_row': direct_row,
            'report_rows': staff_rows + [direct_row],
            'grand_totals': {
                'orders_count': grand_order_agg['orders_count'] or 0,
                'pending_count': grand_order_agg['pending_count'] or 0,
                'paid_completed_count': grand_order_agg['paid_completed_count'] or 0,
                'units_sold': grand_item_agg['units_sold'] or 0,
                'revenue': (grand_order_agg['revenue'] or Decimal('0.00')).quantize(Decimal('0.01')),
            },
        })
        return context


class StoreAppearanceView(OwnerRequiredMixin, View):
    template_name = 'dashboard/appearance.html'

    def _build_appearance_context(self, store, form):
        from storefront.themes.registry import (
            get_theme,
            is_theme_allowed_for_plan,
            list_themes,
        )

        all_themes = list_themes()
        theme_cards = []
        for t in all_themes:
            allowed = is_theme_allowed_for_plan(t, store.plan)
            theme_cards.append({
                'theme': t,
                'allowed': allowed,
                'is_active': t['key'] == store.template_key,
            })
        return self.get_context_data(
            form=form,
            theme_cards=theme_cards,
            active_theme=get_theme(store.template_key),
        )

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        initial = {}
        preselect = (request.GET.get('select') or '').strip()
        if preselect:
            initial['template_key'] = preselect
        form = StoreAppearanceForm(instance=store, initial=initial)
        return render(
            request,
            self.template_name,
            self._build_appearance_context(store, form),
        )

    def post(self, request, *args, **kwargs):
        store = self.get_store()
        form = StoreAppearanceForm(request.POST, instance=store)
        if form.is_valid():
            form.save()
            messages.success(request, 'Storefront appearance updated successfully.')
            return redirect('dashboard:appearance')
        return render(
            request,
            self.template_name,
            self._build_appearance_context(store, form),
            status=400,
        )


class StoreAppearancePreviewView(OwnerRequiredMixin, View):
    def get(self, request, theme_key, *args, **kwargs):
        from storefront.auth import get_store_customer
        from storefront.context_processors import build_theme_context_for_store
        from storefront.forms import CheckoutForm
        from storefront.themes.registry import (
            THEME_KEY_REGEX,
            THEMES_ROOT,
            load_theme_manifest,
            sanitize_brand_color,
            theme_template,
        )
        from storefront.views import build_cart_context

        cleaned_key = (theme_key or '').strip()
        if not THEME_KEY_REGEX.match(cleaned_key):
            raise Http404("Theme not found.")
        manifest = load_theme_manifest(THEMES_ROOT / cleaned_key)
        if not manifest:
            raise Http404("Theme not found.")

        store = self.get_store()
        categories = Category.objects.for_store(store)
        products = (
            Product.objects.for_store(store)
            .filter(is_available=True)
            .select_related('category')
        )
        selected_category_id = request.GET.get('category')
        selected_category = None
        if selected_category_id and selected_category_id.isdigit():
            selected_category = categories.filter(pk=int(selected_category_id)).first()
            if selected_category:
                products = products.filter(category=selected_category)

        raw_brand_color = (
            request.GET.get('brand_color')
            or store.theme_color
            or manifest.get('default_brand_color')
            or '#4f46e5'
        )
        brand_color = sanitize_brand_color(
            raw_brand_color,
            fallback=manifest.get('default_brand_color') or '#4f46e5',
        )
        cart_ctx = build_cart_context(request.session, store)
        theme_ctx = build_theme_context_for_store(
            store,
            theme_key_override=manifest['key'],
            brand_color_override=brand_color,
        )
        template_name = theme_template(manifest['key'], 'home.html')
        context = self.get_context_data(
            store=store,
            current_customer=get_store_customer(request, store),
            categories=categories,
            products=products,
            selected_category=selected_category,
            checkout_form=CheckoutForm(),
            is_owner_preview=True,
            base_filter_url=reverse('dashboard:appearance_preview', kwargs={'theme_key': manifest['key']}),
            **cart_ctx,
            **theme_ctx,
        )
        return render(request, template_name, context)




