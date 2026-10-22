from django.contrib import admin
from orders.models import Order, OrderItem, OrderStatusEvent


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class OrderStatusEventInline(admin.TabularInline):
    model = OrderStatusEvent
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'store',
        'customer_name',
        'customer_phone',
        'fulfilment_type',
        'payment_method',
        'status',
        'payment_status',
        'total',
        'source',
        'created_at',
    )
    list_filter = ('status', 'payment_status', 'source', 'fulfilment_type', 'payment_method', 'store')
    search_fields = ('order_number', 'customer_name', 'customer_phone', 'store__name')
    inlines = [OrderItemInline, OrderStatusEventInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_name_snapshot', 'unit_price_snapshot', 'quantity')
    search_fields = ('order__order_number', 'product_name_snapshot')


@admin.register(OrderStatusEvent)
class OrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'changed_by', 'created_at')
    list_filter = ('status', 'order__store')
    search_fields = ('order__order_number',)

