from django.contrib import admin
from catalog.models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'sort_order')
    list_filter = ('store',)
    search_fields = ('name', 'store__name')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'category', 'price', 'stock', 'is_available', 'created_by')
    list_filter = ('store', 'is_available', 'category')
    search_fields = ('name', 'store__name')
