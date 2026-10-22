from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from stores.managers import get_user_membership


class ActiveMembershipMiddleware:
    """
    Ensures that if an already logged-in user's Membership is deactivated,
    their session is immediately terminated on the next request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and not user.is_superuser:
            membership = get_user_membership(user, include_inactive=True)
            if membership is not None and not membership.is_active:
                logout(request)
                if request.path.startswith('/dashboard/'):
                    raise PermissionDenied("Your staff account has been deactivated.")
        return self.get_response(request)
