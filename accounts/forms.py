from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from stores.managers import get_user_membership
from stores.models import Plan, Store, Membership

User = get_user_model()


class ActiveMembershipAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        membership = get_user_membership(user, include_inactive=True)
        if membership is not None and not membership.is_active:
            raise ValidationError(
                "This staff account has been deactivated.",
                code='inactive_membership',
            )


class OwnerSignupForm(UserCreationForm):
    email = forms.EmailField(required=False)
    store_name = forms.CharField(
        max_length=200,
        required=False,
        help_text="Your business or store name (defaults to your username's store).",
    )
    theme = forms.CharField(max_length=30, required=False, widget=forms.HiddenInput())

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    @transaction.atomic
    def save(self, commit=True):
        from storefront.themes.registry import (
            DEFAULT_THEME_KEY,
            get_theme,
            is_theme_allowed_for_plan,
        )

        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email', '')
        if commit:
            user.save()
            plan = Plan.objects.get(slug=Plan.SLUG_OFFLINE)
            raw_store_name = (self.cleaned_data.get('store_name') or '').strip()
            store_name = raw_store_name if raw_store_name else f"{user.username}'s Store"
            requested_theme_key = (self.cleaned_data.get('theme') or '').strip()
            chosen_theme = get_theme(requested_theme_key) if requested_theme_key else get_theme(DEFAULT_THEME_KEY)
            if not is_theme_allowed_for_plan(chosen_theme, plan):
                chosen_theme = get_theme(DEFAULT_THEME_KEY)
            store = Store.objects.create(
                owner=user,
                name=store_name,
                plan=plan,
                template_key=chosen_theme['key'],
                theme_color=chosen_theme.get('default_brand_color') or '#4f46e5',
            )
            Membership.objects.create(
                user=user,
                store=store,
                role=Membership.ROLE_OWNER,
                display_name=user.username,
            )
        return user
