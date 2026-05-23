from django.shortcuts import redirect


EXEMPT_PREFIXES = (
    "/accounts/login/",
    "/accounts/signup/",
    "/accounts/logout/",
    "/accounts/google/",
    "/accounts/invite/",
    #"/accounts/onboarding/",
    "/billing/",
    "/book/",
    "/static/",
    "/media/",
    "/admin/",
)


class SubscriptionAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info

        if path == "/" or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return self.get_response(request)

        if not request.user.is_authenticated:
            return self.get_response(request)

        # Check if the user has a personal active subscription
        user_has_sub = request.user.subscriptions.filter(
            status__in=["trialing", "active", "past_due"]
        ).exists()

        if user_has_sub:
            return self.get_response(request)

        # Check if the organization has an active subscription
        org = getattr(request, "organization", None)
        if not org or not org.has_active_subscription:
            return redirect("/?expired=true#planes")

        return self.get_response(request)
