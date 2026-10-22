from django.urls import path
from accounts.views import OwnerSignupView, OwnerLoginView, OwnerLogoutView

app_name = 'accounts'

urlpatterns = [
    path('signup/', OwnerSignupView.as_view(), name='signup'),
    path('login/', OwnerLoginView.as_view(), name='login'),
    path('logout/', OwnerLogoutView.as_view(), name='logout'),
]
