from django.contrib import admin
from stores.models import Customer, CustomerAddress, Membership, PaymentQR, Plan, Store


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'max_users', 'price')
    list_editable = ('max_users',)
    search_fields = ('name', 'slug')


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'owner',
        'plan',
        'extra_seats',
        'online_ordering_open',
        'template_key',
        'is_active',
    )
    list_editable = ('plan', 'extra_seats', 'online_ordering_open', 'is_active')
    list_filter = ('plan', 'template_key', 'online_ordering_open', 'is_active')
    search_fields = ('name', 'slug', 'owner__username')
    fields = (
        'owner',
        'name',
        'slug',
        'plan',
        'extra_seats',
        'template_key',
        'logo',
        'description',
        'is_active',
        'online_ordering_open',
        'pickup_enabled',
        'delivery_enabled',
        'delivery_fee',
        'free_delivery_above',
        'minimum_order_amount',
        'delivery_note',
        'theme_color',
        'accept_upi_qr',
        'accept_cod',
    )


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'display_name',
        'store',
        'role',
        'referral_code',
        'is_active',
        'created_at',
    )
    list_filter = ('role', 'is_active', 'store')
    search_fields = ('user__username', 'display_name', 'store__name', 'referral_code')


@admin.register(PaymentQR)
class PaymentQRAdmin(admin.ModelAdmin):
    list_display = ('store', 'upi_id')
    search_fields = ('store__name', 'upi_id')


class CustomerAddressInline(admin.TabularInline):
    model = CustomerAddress
    extra = 0


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'store', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'phone', 'store__name')
    exclude = ('password',)
    inlines = [CustomerAddressInline]


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = ('customer', 'label', 'address_line', 'pincode', 'is_default')
    list_filter = ('is_default', 'customer__store')
    search_fields = ('customer__name', 'customer__phone', 'address_line', 'pincode')

