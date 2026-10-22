from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView
from accounts.forms import ActiveMembershipAuthenticationForm, OwnerSignupForm


class OwnerSignupView(CreateView):
    form_class = OwnerSignupForm
    template_name = 'accounts/signup.html'
    success_url = reverse_lazy('dashboard:home')

    def get_initial(self):
        initial = super().get_initial()
        theme_key = (self.request.GET.get('theme') or '').strip()
        if theme_key:
            initial['theme'] = theme_key
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class OwnerLoginView(LoginView):
    form_class = ActiveMembershipAuthenticationForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


class OwnerLogoutView(View):
    def get(self, request, *args, **kwargs):
        logout(request)
        return redirect('accounts:login')

    def post(self, request, *args, **kwargs):
        logout(request)
        return redirect('accounts:login')
