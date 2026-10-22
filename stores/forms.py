from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from catalog.models import Category, Product
from orders.models import Order, OrderItem
from stores.models import Membership, PaymentQR, Store
from stores.services import validate_store_seat_limit

User = get_user_model()


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'sort_order']


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'category',
            'name',
            'description',
            'price',
            'image',
            'stock',
            'is_available',
        ]

    def __init__(self, *args, store=None, **kwargs):
        super().__init__(*args, **kwargs)
        if store is not None:
            self.fields['category'].queryset = Category.objects.for_store(store)


class StoreSettingsForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = [
            'name',
            'slug',
            'template_key',
            'logo',
            'description',
            'is_active',
            'online_ordering_open',
            'delivery_enabled',
            'pickup_enabled',
            'delivery_fee',
            'free_delivery_above',
            'minimum_order_amount',
            'delivery_note',
            'accept_upi_qr',
            'accept_cod',
            'theme_color',
        ]
        widgets = {
            'delivery_note': forms.Textarea(attrs={'rows': 2}),
            'theme_color': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delivery_fee'].required = False
        self.fields['minimum_order_amount'].required = False
        self.fields['theme_color'].required = False
        if self.is_bound and self.instance and self.instance.pk:
            # Preserve boolean settings when a partial form payload omits Plan 3 fields
            bool_fields = [
                'is_active',
                'online_ordering_open',
                'delivery_enabled',
                'pickup_enabled',
                'accept_upi_qr',
                'accept_cod',
            ]
            has_any_plan3_key = any(
                k in self.data
                for k in (
                    'online_ordering_open',
                    'delivery_enabled',
                    'pickup_enabled',
                    'delivery_fee',
                    'free_delivery_above',
                    'minimum_order_amount',
                    'delivery_note',
                    'accept_upi_qr',
                    'accept_cod',
                    'theme_color',
                )
            )
            if not has_any_plan3_key:
                self.data = self.data.copy()
                for bf in bool_fields:
                    if bf not in self.data and getattr(self.instance, bf, False):
                        self.data[bf] = 'on'

    def clean_delivery_fee(self):
        val = self.cleaned_data.get('delivery_fee')
        if val is None:
            if self.instance and self.instance.pk and self.instance.delivery_fee is not None:
                return self.instance.delivery_fee
            return Decimal('0.00')
        if val < Decimal('0.00'):
            raise ValidationError("Delivery fee cannot be negative.")
        return val

    def clean_minimum_order_amount(self):
        val = self.cleaned_data.get('minimum_order_amount')
        if val is None:
            if self.instance and self.instance.pk and self.instance.minimum_order_amount is not None:
                return self.instance.minimum_order_amount
            return Decimal('0.00')
        if val < Decimal('0.00'):
            raise ValidationError("Minimum order amount cannot be negative.")
        return val

    def clean_free_delivery_above(self):
        val = self.cleaned_data.get('free_delivery_above')
        if val is not None and val < Decimal('0.00'):
            raise ValidationError("Free delivery threshold cannot be negative.")
        return val

    def clean_template_key(self):
        from storefront.themes.registry import (
            THEME_KEY_REGEX,
            THEMES_ROOT,
            is_theme_allowed_for_plan,
            load_theme_manifest,
        )

        val = (self.cleaned_data.get('template_key') or '').strip()
        if not val:
            if self.instance and self.instance.pk and self.instance.template_key:
                return self.instance.template_key
            return Store.TEMPLATE_CLASSIC
        if not THEME_KEY_REGEX.match(val):
            raise ValidationError("Invalid theme key.")
        manifest = load_theme_manifest(THEMES_ROOT / val)
        if not manifest:
            raise ValidationError("Selected theme does not exist.")
        if self.instance and self.instance.plan_id:
            if not is_theme_allowed_for_plan(manifest, self.instance.plan):
                raise ValidationError(
                    f"The '{manifest['name']}' theme requires the {manifest['min_plan'].title()} plan or higher."
                )
        return val

    def clean_theme_color(self):
        from storefront.themes.registry import is_valid_hex_color

        val = (self.cleaned_data.get('theme_color') or '').strip()
        if not val:
            if self.instance and self.instance.pk and self.instance.theme_color:
                return self.instance.theme_color
            return '#4f46e5'
        if not is_valid_hex_color(val):
            raise ValidationError("Brand color must be a valid 6-digit hex color (#RRGGBB).")
        return val


class StoreAppearanceForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = ['template_key', 'theme_color']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template_key'].required = True
        self.fields['theme_color'].required = False

    def clean_template_key(self):
        from storefront.themes.registry import (
            THEME_KEY_REGEX,
            THEMES_ROOT,
            is_theme_allowed_for_plan,
            load_theme_manifest,
        )

        val = (self.cleaned_data.get('template_key') or '').strip()
        if not THEME_KEY_REGEX.match(val):
            raise ValidationError("Invalid theme key.")
        manifest = load_theme_manifest(THEMES_ROOT / val)
        if not manifest:
            raise ValidationError("Selected theme does not exist.")
        if self.instance and self.instance.plan_id:
            if not is_theme_allowed_for_plan(manifest, self.instance.plan):
                raise ValidationError(
                    f"The '{manifest['name']}' theme requires the {manifest['min_plan'].title()} plan or higher."
                )
        return val

    def clean_theme_color(self):
        from storefront.themes.registry import get_theme, is_valid_hex_color

        val = (self.cleaned_data.get('theme_color') or '').strip()
        if not val:
            t_key = self.cleaned_data.get('template_key') or (
                self.instance.template_key if self.instance else 'classic'
            )
            theme = get_theme(t_key)
            return theme.get('default_brand_color') or '#4f46e5'
        if not is_valid_hex_color(val):
            raise ValidationError("Brand color must be a valid 6-digit hex color (#RRGGBB).")
        return val


class PaymentQRForm(forms.ModelForm):
    class Meta:
        model = PaymentQR
        fields = ['upi_id', 'qr_image']


class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status', 'payment_status']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['payment_status'].required = False

    def clean_status(self):
        target = Order.normalize_status(self.cleaned_data.get('status'))
        if self.instance and self.instance.pk:
            current = Order.normalize_status(self.instance.status)
            if target != current and self.instance.is_online_order:
                if not self.instance.can_transition_to(target, by_customer=False):
                    raise ValidationError(
                        f"Cannot transition online order from '{current}' to '{target}'."
                    )
        return target

    def clean_payment_status(self):
        val = self.cleaned_data.get('payment_status')
        if not val:
            if self.instance and self.instance.pk:
                return self.instance.payment_status
            return Order.PAYMENT_UNPAID
        return val


class StaffCreateForm(forms.Form):
    username = forms.CharField(max_length=150, label='Username')
    display_name = forms.CharField(max_length=150, label='Display Name')
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label='Initial Password',
    )

    def __init__(self, *args, store=None, **kwargs):
        self.store = store
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError("A user with that username already exists.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        username = self.cleaned_data.get('username') or 'staff'
        temp_user = User(username=username)
        validate_password(password, user=temp_user)
        return password

    def clean(self):
        cleaned_data = super().clean()
        if self.store is not None:
            validate_store_seat_limit(self.store, is_active=True)
        return cleaned_data

    @transaction.atomic
    def save(self):
        user = User(username=self.cleaned_data['username'])
        user.set_password(self.cleaned_data['password'])
        user.save()
        membership = Membership.objects.create(
            user=user,
            store=self.store,
            role=Membership.ROLE_STAFF,
            display_name=self.cleaned_data['display_name'].strip(),
            is_active=True,
        )
        return membership


class StaffPasswordResetForm(forms.Form):
    new_password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label='New Password',
    )

    def __init__(self, *args, target_user=None, **kwargs):
        self.target_user = target_user
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        password = self.cleaned_data.get('new_password')
        validate_password(password, user=self.target_user)
        return password

    def save(self):
        self.target_user.set_password(self.cleaned_data['new_password'])
        self.target_user.save(update_fields=['password'])
        return self.target_user


class CounterOrderForm(forms.Form):
    customer_name = forms.CharField(max_length=200, label='Customer Name')
    customer_phone = forms.CharField(max_length=50, label='Customer Phone')
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        label='Order Note',
    )

    def __init__(self, *args, store=None, **kwargs):
        self.store = store
        self.selected_items = []
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.store is None:
            raise ValidationError("Store context is required.")

        available_products = {
            p.pk: p
            for p in Product.objects.for_store(self.store).filter(is_available=True)
        }
        requested_quantities = {}

        # Support quantity_<product_id> inputs from the counter order form table
        for key in self.data.keys():
            if key.startswith('quantity_'):
                pid_str = key[len('quantity_'):]
                if not pid_str.isdigit():
                    continue
                raw_val = self.data.get(key, '0').strip()
                if not raw_val:
                    continue
                try:
                    qty = int(raw_val)
                except (TypeError, ValueError):
                    raise ValidationError("Quantities must be whole numbers.")
                if qty < 0:
                    raise ValidationError("Quantities cannot be negative.")
                if qty > 0:
                    pid = int(pid_str)
                    if pid not in available_products:
                        raise ValidationError("Invalid or unavailable product selected.")
                    requested_quantities[pid] = requested_quantities.get(pid, 0) + qty

        # Also support product_id / quantity pairs (single or list)
        if hasattr(self.data, 'getlist'):
            product_ids = self.data.getlist('product_id')
            quantities = self.data.getlist('quantity')
        else:
            raw_pids = self.data.get('product_id', [])
            raw_qtys = self.data.get('quantity', [])
            product_ids = raw_pids if isinstance(raw_pids, (list, tuple)) else ([raw_pids] if raw_pids else [])
            quantities = raw_qtys if isinstance(raw_qtys, (list, tuple)) else ([raw_qtys] if raw_qtys else [])

        for pid_raw, qty_raw in zip(product_ids, quantities):
            if str(pid_raw).strip() == '' and str(qty_raw).strip() == '':
                continue
            try:
                pid = int(pid_raw)
                qty = int(qty_raw)
            except (TypeError, ValueError):
                raise ValidationError("Invalid product or quantity.")
            if qty < 0:
                raise ValidationError("Quantities cannot be negative.")
            if qty > 0:
                if pid not in available_products:
                    raise ValidationError("Invalid or unavailable product selected.")
                requested_quantities[pid] = requested_quantities.get(pid, 0) + qty

        if not requested_quantities:
            raise ValidationError("Please select at least one product with a quantity of 1 or more.")

        self.selected_items = [
            (available_products[pid], qty)
            for pid, qty in requested_quantities.items()
        ]
        return cleaned_data

    @transaction.atomic
    def save(self, placed_by):
        order = Order.objects.create(
            store=self.store,
            customer_name=self.cleaned_data['customer_name'].strip(),
            customer_phone=self.cleaned_data['customer_phone'].strip(),
            note=self.cleaned_data.get('note', '').strip(),
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_UNPAID,
            source=Order.SOURCE_ONLINE,
            placed_by=placed_by,
            total=Decimal('0.00'),
        )
        for product, qty in self.selected_items:
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name_snapshot=product.name,
                unit_price_snapshot=product.price,
                quantity=qty,
            )
        order.recalculate_total(save=True)
        return order

