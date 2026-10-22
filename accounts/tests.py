from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from stores.models import Plan, Store, Membership

User = get_user_model()


class AccountsAuthTests(TestCase):
    def test_signup_creates_user_store_on_plan1_and_owner_membership(self):
        response = self.client.post(
            reverse('accounts:signup'),
            {
                'username': 'newowner',
                'email': 'newowner@example.com',
                'store_name': 'New Owner Bakery',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newowner')
        store = Store.objects.get(owner=user)
        self.assertEqual(store.name, 'New Owner Bakery')
        self.assertEqual(store.plan.slug, Plan.SLUG_OFFLINE)
        membership = Membership.objects.get(user=user, store=store)
        self.assertEqual(membership.role, Membership.ROLE_OWNER)

    def test_login_and_logout(self):
        User.objects.create_user(username='loginuser', password='StrongPass123!')
        login_resp = self.client.post(
            reverse('accounts:login'),
            {'username': 'loginuser', 'password': 'StrongPass123!'},
        )
        self.assertEqual(login_resp.status_code, 302)
        logout_resp = self.client.post(reverse('accounts:logout'))
        self.assertEqual(logout_resp.status_code, 302)
