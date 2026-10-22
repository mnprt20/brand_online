from decimal import Decimal
from django.conf import settings
from django.contrib.auth.hashers import (
    check_password as django_check_password,
    is_password_usable,
    make_password,
)
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from stores.managers import StoreScopedManager
from stores.services import (
    generate_unique_referral_code,
    get_active_seat_count,
    get_store_seat_limit,
    validate_store_seat_limit,
)


class Plan(models.Model):
    SLUG_OFFLINE = 'offline'
    SLUG_FRANCHISE = 'franchise'
    SLUG_ONLINE = 'online'

    SLUG_CHOICES = [
        (SLUG_OFFLINE, 'Offline Catalogue'),
        (SLUG_FRANCHISE, 'Franchise'),
        (SLUG_ONLINE, 'Online App'),
    ]

    slug = models.SlugField(max_length=50, unique=True, choices=SLUG_CHOICES)
    name = models.CharField(max_length=100)
    max_users = models.PositiveIntegerField(default=1)
    features = models.JSONField(default=dict, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['price', 'id']

    def __str__(self):
        return f"{self.name} ({self.slug})"


class Store(models.Model):
    TEMPLATE_CLASSIC = 'classic'
    TEMPLATE_MINIMAL = 'minimal'
    TEMPLATE_BOLD = 'bold'

    TEMPLATE_CHOICES = [
        (TEMPLATE_CLASSIC, 'Classic'),
        (TEMPLATE_MINIMAL, 'Minimal'),
        (TEMPLATE_BOLD, 'Bold'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_stores',
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='stores',
    )
    extra_seats = models.PositiveIntegerField(default=0)
    template_key = models.CharField(
        max_length=30,
        default=TEMPLATE_CLASSIC,
    )
    logo = models.ImageField(upload_to='store_logos/', blank=True, null=True)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)

    # Plan 3 (Online App) settings
    online_ordering_open = models.BooleanField(default=False)
    delivery_enabled = models.BooleanField(default=False)
    pickup_enabled = models.BooleanField(default=True)
    delivery_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    free_delivery_above = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    minimum_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    delivery_note = models.TextField(blank=True, default='')
    theme_color = models.CharField(max_length=20, default='#4f46e5', blank=True)
    accept_upi_qr = models.BooleanField(default=True)
    accept_cod = models.BooleanField(default=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name

    @property
    def seat_limit(self):
        return get_store_seat_limit(self)

    @property
    def active_seat_count(self):
        return get_active_seat_count(self)

    def has_franchise_features(self):
        if not self.plan_id:
            return False
        if self.plan.slug in (Plan.SLUG_FRANCHISE, Plan.SLUG_ONLINE):
            return True
        features = self.plan.features or {}
        return bool(features.get('staff') or features.get('sales_report'))

    def has_online_features(self):
        if not self.plan_id:
            return False
        if self.plan.slug == Plan.SLUG_ONLINE:
            return True
        features = self.plan.features or {}
        return bool(features.get('online_app'))

    def _generate_unique_slug(self):
        base_slug = slugify(self.name) or 'store'
        slug = base_slug
        counter = 1
        while Store.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        if not self.theme_color:
            self.theme_color = '#4f46e5'
        super().save(*args, **kwargs)


class Membership(models.Model):
    ROLE_OWNER = 'owner'
    ROLE_STAFF = 'staff'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_STAFF, 'Staff'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_OWNER,
    )
    display_name = models.CharField(max_length=150, blank=True, default='')
    referral_code = models.CharField(max_length=32, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StoreScopedManager()

    class Meta:
        unique_together = [('user', 'store')]
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.get_display_label()} - {self.store} ({self.role})"

    def get_display_label(self):
        if self.display_name and self.display_name.strip():
            return self.display_name.strip()
        if self.user_id:
            return self.user.username
        return ''

    def clean(self):
        super().clean()
        if self.store_id and self.role == self.ROLE_OWNER:
            owner_qs = Membership.objects.filter(store=self.store, role=self.ROLE_OWNER)
            if self.pk:
                owner_qs = owner_qs.exclude(pk=self.pk)
            if owner_qs.exists():
                raise ValidationError("A store can have only one owner membership.")

        if self.store_id and self.store.plan_id:
            validate_store_seat_limit(
                self.store,
                is_active=self.is_active,
                exclude_membership_pk=self.pk,
            )

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = generate_unique_referral_code(Membership)
        if not self.display_name and self.user_id:
            self.display_name = self.user.username
        self.full_clean()
        super().save(*args, **kwargs)


class PaymentQR(models.Model):
    store = models.OneToOneField(
        Store,
        on_delete=models.CASCADE,
        related_name='payment_qr',
    )
    upi_id = models.CharField(max_length=150, blank=True, default='')
    qr_image = models.ImageField(upload_to='payment_qrs/', blank=True, null=True)

    objects = StoreScopedManager()

    class Meta:
        verbose_name = 'Payment QR'
        verbose_name_plural = 'Payment QRs'

    def __str__(self):
        return f"PaymentQR for {self.store.name}"


class Customer(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='customers',
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50)
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StoreScopedManager()

    class Meta:
        unique_together = [('store', 'phone')]
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.name} ({self.phone}) - {self.store.name}"

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return django_check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith(('pbkdf2_', 'argon2', 'bcrypt', 'scrypt', 'md5$', 'sha1$')):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)


class CustomerAddress(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='addresses',
    )
    label = models.CharField(max_length=100, default='Home')
    address_line = models.TextField()
    landmark = models.CharField(max_length=200, blank=True, default='')
    pincode = models.CharField(max_length=20)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_default', 'id']
        verbose_name = 'Customer Address'
        verbose_name_plural = 'Customer Addresses'

    def __str__(self):
        return f"{self.label}: {self.address_line} ({self.pincode})"

    def format_snapshot(self):
        parts = []
        if self.label:
            parts.append(f"[{self.label}]")
        if self.address_line:
            parts.append(self.address_line.strip())
        if self.landmark:
            parts.append(f"Landmark: {self.landmark.strip()}")
        if self.pincode:
            parts.append(f"PIN: {self.pincode.strip()}")
        return ', '.join(parts)

    def as_snapshot_text(self):
        return self.format_snapshot()

    def save(self, *args, **kwargs):
        if self.customer_id:
            if self.is_default:
                CustomerAddress.objects.filter(customer_id=self.customer_id, is_default=True).exclude(
                    pk=self.pk
                ).update(is_default=False)
            elif not CustomerAddress.objects.filter(customer_id=self.customer_id, is_default=True).exclude(
                pk=self.pk
            ).exists():
                self.is_default = True
        super().save(*args, **kwargs)

