from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from storefront.auth import (
    clear_customer_login_failures,
    get_client_ip,
    is_customer_login_locked,
    record_customer_login_failure,
)
from stores.models import Customer, CustomerAddress


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(max_length=200, label='Your Name')
    customer_phone = forms.CharField(max_length=50, label='Phone Number')
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        label='Order Note (Optional)',
    )


class CustomerRegisterForm(forms.Form):
    name = forms.CharField(max_length=200, label='Full Name')
    phone = forms.CharField(max_length=50, label='Phone Number')
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label='Password',
    )

    def __init__(self, *args, store=None, **kwargs):
        self.store = store
        super().__init__(*args, **kwargs)

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not phone:
            raise ValidationError("Phone number is required.")
        if self.store and Customer.objects.filter(store=self.store, phone=phone).exists():
            raise ValidationError("An account with this phone number already exists at this store.")
        return phone

    def clean_password(self):
        password = self.cleaned_data.get('password')
        validate_password(password)
        return password

    def save(self):
        customer = Customer(
            store=self.store,
            name=self.cleaned_data['name'].strip(),
            phone=self.cleaned_data['phone'],
            is_active=True,
        )
        customer.set_password(self.cleaned_data['password'])
        customer.save()
        return customer


class CustomerLoginForm(forms.Form):
    phone = forms.CharField(max_length=50, label='Phone Number')
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label='Password',
    )

    def __init__(self, *args, store=None, request=None, **kwargs):
        self.store = store
        self.request = request
        self.customer = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        phone = (cleaned_data.get('phone') or '').strip()
        password = cleaned_data.get('password') or ''
        if not phone or not password or self.store is None:
            return cleaned_data

        ip = get_client_ip(self.request) if self.request else '127.0.0.1'
        if is_customer_login_locked(self.store, phone, ip):
            raise ValidationError(
                "Too many failed login attempts. Account is locked for 10 minutes."
            )

        customer = Customer.objects.filter(
            store=self.store,
            phone=phone,
            is_active=True,
        ).first()
        if customer is None or not customer.check_password(password):
            record_customer_login_failure(self.store, phone, ip)
            if is_customer_login_locked(self.store, phone, ip):
                raise ValidationError(
                    "Too many failed login attempts. Account is locked for 10 minutes."
                )
            raise ValidationError("Invalid phone number or password.")

        clear_customer_login_failures(self.store, phone, ip)
        self.customer = customer
        return cleaned_data


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name']


class CustomerAddressForm(forms.ModelForm):
    class Meta:
        model = CustomerAddress
        fields = ['label', 'address_line', 'landmark', 'pincode', 'is_default']
        widgets = {
            'address_line': forms.Textarea(attrs={'rows': 2}),
        }


class OnlineCheckoutForm(forms.Form):
    fulfilment_type = forms.ChoiceField(
        choices=[
            ('pickup', 'Store Pickup'),
            ('delivery', 'Home Delivery'),
        ],
        widget=forms.RadioSelect,
    )
    address_id = forms.CharField(required=False)
    new_address_label = forms.CharField(max_length=100, required=False, initial='Home')
    new_address_line = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
    )
    new_address_landmark = forms.CharField(max_length=200, required=False)
    new_address_pincode = forms.CharField(max_length=20, required=False)
    delivery_address_text = forms.CharField(required=False)
    save_new_address = forms.BooleanField(required=False, initial=True)

    payment_method = forms.ChoiceField(
        choices=[
            ('upi_qr', 'UPI QR Payment'),
            ('cod', 'Cash on Delivery / Pay on Pickup'),
        ],
        widget=forms.RadioSelect,
    )
    payment_reference = forms.CharField(max_length=200, required=False)
    customer_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    def __init__(self, *args, store=None, customer=None, **kwargs):
        self.store = store
        self.customer = customer
        self.selected_address = None
        self.new_address_data = None
        self.resolved_delivery_address_text = ''
        super().__init__(*args, **kwargs)

        if self.store:
            if not self.is_bound:
                if self.store.delivery_enabled:
                    self.fields['fulfilment_type'].initial = 'delivery'
                elif self.store.pickup_enabled:
                    self.fields['fulfilment_type'].initial = 'pickup'

                if self.store.accept_upi_qr:
                    self.fields['payment_method'].initial = 'upi_qr'
                elif self.store.accept_cod:
                    self.fields['payment_method'].initial = 'cod'

        if self.customer and not self.is_bound:
            default_addr = (
                self.customer.addresses.filter(is_default=True).first()
                or self.customer.addresses.first()
            )
            if default_addr:
                self.fields['address_id'].initial = str(default_addr.pk)

    def clean(self):
        cleaned_data = super().clean()
        fulfilment_type = cleaned_data.get('fulfilment_type')

        if fulfilment_type == 'delivery':
            raw_addr_id = (cleaned_data.get('address_id') or '').strip()
            if raw_addr_id and raw_addr_id != 'new':
                if not raw_addr_id.isdigit() or self.customer is None:
                    raise ValidationError("Invalid saved delivery address selected.")
                addr = CustomerAddress.objects.filter(
                    pk=int(raw_addr_id),
                    customer=self.customer,
                ).first()
                if addr is None:
                    raise ValidationError("Selected delivery address does not belong to your account.")
                self.selected_address = addr
                self.resolved_delivery_address_text = addr.as_snapshot_text()
            else:
                direct_text = (cleaned_data.get('delivery_address_text') or '').strip()
                new_line = (cleaned_data.get('new_address_line') or '').strip()
                if new_line:
                    label = (cleaned_data.get('new_address_label') or 'Delivery Address').strip() or 'Delivery Address'
                    landmark = (cleaned_data.get('new_address_landmark') or '').strip()
                    pincode = (cleaned_data.get('new_address_pincode') or '').strip()
                    parts = [f"{label}: {new_line}"]
                    if landmark:
                        parts.append(f"Landmark: {landmark}")
                    if pincode:
                        parts.append(f"PIN: {pincode}")
                    self.resolved_delivery_address_text = " | ".join(parts)
                    if self.customer and cleaned_data.get('save_new_address', True):
                        self.new_address_data = {
                            'label': label,
                            'address_line': new_line,
                            'landmark': landmark,
                            'pincode': pincode,
                        }
                elif direct_text:
                    self.resolved_delivery_address_text = direct_text
                else:
                    raise ValidationError(
                        "Please select a saved delivery address or enter a new delivery address."
                    )

        return cleaned_data

