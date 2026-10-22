from django.urls import path
from stores.views import (
    CategoryCreateView,
    CategoryDeleteView,
    CategoryDetailView,
    CategoryListView,
    CategoryUpdateView,
    CounterOrderCreateView,
    DashboardHomeView,
    OrderDeleteView,
    OrderDetailView,
    OrderListView,
    OrderMarkPaidView,
    OrderNewCountView,
    OrderStatusUpdateView,
    PaymentQRUpdateView,
    ProductCreateView,
    ProductDeleteView,
    ProductDetailView,
    ProductListView,
    ProductUpdateView,
    SalesReportView,
    StaffCatalogListView,
    StaffCreateView,
    StaffListView,
    StaffMyQRDownloadView,
    StaffMyQRView,
    StaffPasswordResetView,
    StaffQRByOwnerView,
    StaffToggleActiveView,
    StoreAppearancePreviewView,
    StoreAppearanceView,
    StoreQRDownloadView,
    StoreSettingsView,
)

app_name = 'dashboard'

urlpatterns = [
    path('', DashboardHomeView.as_view(), name='home'),
    path('store-qr/', StoreQRDownloadView.as_view(), name='store_qr'),

    # Categories CRUD
    path('categories/', CategoryListView.as_view(), name='category_list'),
    path('categories/add/', CategoryCreateView.as_view(), name='category_add'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category_detail'),
    path('categories/<int:pk>/edit/', CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', CategoryDeleteView.as_view(), name='category_delete'),

    # Products CRUD
    path('products/', ProductListView.as_view(), name='product_list'),
    path('products/add/', ProductCreateView.as_view(), name='product_add'),
    path('products/<int:pk>/', ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:pk>/edit/', ProductUpdateView.as_view(), name='product_edit'),
    path('products/<int:pk>/delete/', ProductDeleteView.as_view(), name='product_delete'),

    # Store Settings & Appearance
    path('appearance/', StoreAppearanceView.as_view(), name='appearance'),
    path(
        'appearance/preview/<slug:theme_key>/',
        StoreAppearancePreviewView.as_view(),
        name='appearance_preview',
    ),
    path('settings/', StoreSettingsView.as_view(), name='settings'),
    path('settings/<int:pk>/', StoreSettingsView.as_view(), name='settings_by_id'),
    path('settings/<int:pk>/edit/', StoreSettingsView.as_view(), name='settings_edit'),
    path('settings/<int:pk>/delete/', StoreSettingsView.as_view(), name='settings_delete'),

    # Payment QR
    path('payment-qr/', PaymentQRUpdateView.as_view(), name='payment_qr'),
    path('payment-qr/<int:pk>/', PaymentQRUpdateView.as_view(), name='payment_qr_by_id'),

    # Orders & Counter Orders
    path('orders/', OrderListView.as_view(), name='order_list'),
    path('orders/new-count/', OrderNewCountView.as_view(), name='orders_new_count'),
    path('orders/counter/add/', CounterOrderCreateView.as_view(), name='counter_order_add'),
    path('orders/<int:pk>/', OrderDetailView.as_view(), name='order_detail'),
    path('orders/<int:pk>/edit/', OrderStatusUpdateView.as_view(), name='order_edit'),
    path('orders/<int:pk>/status/', OrderStatusUpdateView.as_view(), name='order_status'),
    path('orders/<int:pk>/mark-paid/', OrderMarkPaidView.as_view(), name='order_mark_paid'),
    path('orders/<int:pk>/delete/', OrderDeleteView.as_view(), name='order_delete'),

    # Read-only Catalogue & Personal QR (Staff / Owner)
    path('catalog/', StaffCatalogListView.as_view(), name='staff_catalog'),
    path('my-qr/', StaffMyQRView.as_view(), name='my_qr'),
    path('my-qr/download/', StaffMyQRDownloadView.as_view(), name='my_qr_download'),

    # Staff Management & Sales Report (Owner only, Franchise plan)
    path('staff/', StaffListView.as_view(), name='staff_list'),
    path('staff/add/', StaffCreateView.as_view(), name='staff_add'),
    path('staff/<int:pk>/toggle/', StaffToggleActiveView.as_view(), name='staff_toggle'),
    path('staff/<int:pk>/reset-password/', StaffPasswordResetView.as_view(), name='staff_reset_password'),
    path('staff/<int:pk>/qr/', StaffQRByOwnerView.as_view(), name='staff_qr'),
    path('reports/sales/', SalesReportView.as_view(), name='sales_report'),
]


