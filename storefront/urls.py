from django.urls import path
from storefront.pwa import (
    StoreIcon192View,
    StoreIcon512View,
    StoreManifestView,
    StoreOfflineView,
    StoreServiceWorkerView,
)
from storefront.views import (
    CartAddView,
    CartRemoveView,
    CartUpdateView,
    CheckoutView,
    CustomerAccountView,
    CustomerAddressCreateView,
    CustomerAddressDeleteView,
    CustomerAddressSetDefaultView,
    CustomerAddressUpdateView,
    CustomerLoginView,
    CustomerLogoutView,
    CustomerOrderCancelView,
    CustomerOrderDetailView,
    CustomerOrderListView,
    CustomerRegisterView,
    OnlineCheckoutView,
    OrderConfirmationView,
    PublicStoreQRView,
    StorefrontDetailView,
)

app_name = 'storefront'

urlpatterns = [
    path('<slug:store_slug>/', StorefrontDetailView.as_view(), name='detail'),
    path('<slug:store_slug>/qr/', PublicStoreQRView.as_view(), name='store_qr'),
    path('<slug:store_slug>/cart/add/', CartAddView.as_view(), name='cart_add'),
    path('<slug:store_slug>/cart/update/', CartUpdateView.as_view(), name='cart_update'),
    path('<slug:store_slug>/cart/remove/', CartRemoveView.as_view(), name='cart_remove'),
    path('<slug:store_slug>/checkout/', CheckoutView.as_view(), name='checkout'),
    path(
        '<slug:store_slug>/online-checkout/',
        OnlineCheckoutView.as_view(),
        name='online_checkout',
    ),
    path(
        '<slug:store_slug>/order/<str:order_number>/',
        OrderConfirmationView.as_view(),
        name='order_confirmation',
    ),

    # Plan 3: Customer Auth, Account, Address Book & Order Tracking
    path('<slug:store_slug>/account/', CustomerAccountView.as_view(), name='customer_account'),
    path('<slug:store_slug>/account/register/', CustomerRegisterView.as_view(), name='customer_register'),
    path('<slug:store_slug>/account/login/', CustomerLoginView.as_view(), name='customer_login'),
    path('<slug:store_slug>/account/logout/', CustomerLogoutView.as_view(), name='customer_logout'),
    path(
        '<slug:store_slug>/account/addresses/add/',
        CustomerAddressCreateView.as_view(),
        name='address_add',
    ),
    path(
        '<slug:store_slug>/account/addresses/<int:pk>/edit/',
        CustomerAddressUpdateView.as_view(),
        name='address_edit',
    ),
    path(
        '<slug:store_slug>/account/addresses/<int:pk>/delete/',
        CustomerAddressDeleteView.as_view(),
        name='address_delete',
    ),
    path(
        '<slug:store_slug>/account/addresses/<int:pk>/default/',
        CustomerAddressSetDefaultView.as_view(),
        name='address_set_default',
    ),
    path(
        '<slug:store_slug>/account/orders/',
        CustomerOrderListView.as_view(),
        name='customer_order_list',
    ),
    path(
        '<slug:store_slug>/account/orders/<str:order_number>/',
        CustomerOrderDetailView.as_view(),
        name='customer_order_detail',
    ),
    path(
        '<slug:store_slug>/account/orders/<str:order_number>/cancel/',
        CustomerOrderCancelView.as_view(),
        name='customer_order_cancel',
    ),

    # Plan 3: Per-Store Installable PWA
    path(
        '<slug:store_slug>/manifest.webmanifest',
        StoreManifestView.as_view(),
        name='pwa_manifest',
    ),
    path(
        '<slug:store_slug>/icon-192.png',
        StoreIcon192View.as_view(),
        name='pwa_icon_192',
    ),
    path(
        '<slug:store_slug>/icon-512.png',
        StoreIcon512View.as_view(),
        name='pwa_icon_512',
    ),
    path(
        '<slug:store_slug>/sw.js',
        StoreServiceWorkerView.as_view(),
        name='pwa_sw',
    ),
    path(
        '<slug:store_slug>/offline/',
        StoreOfflineView.as_view(),
        name='pwa_offline',
    ),
]

