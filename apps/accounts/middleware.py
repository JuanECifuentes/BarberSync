from django.shortcuts import redirect
from django.urls import reverse


class OnboardingMiddleware:
    """
    Middleware that forces newly registered users without an organization
    to complete the onboarding process before using the app.
    Also checks if the organization has services configured.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path_info

            excluded_prefixes = (
                "/accounts/onboarding/",
                "/accounts/capture-name/",
                "/accounts/logout/",
                "/accounts/login/",
                "/accounts/google/",
                "/accounts/signup/",
                "/accounts/invite/",
                "/accounts/confirm-email/",
                "/accounts/resend-verification/",
                "/accounts/profile/",
                "/billing/",
                "/book/",
                "/static/",
                "/media/",
                "/admin/",
            )

            is_excluded = path == "/" or any(
                path.startswith(p) for p in excluded_prefixes
            )

            if not is_excluded:
                membership = request.user.memberships.filter(is_active=True).first()
                if not membership or not membership.organization:
                    return redirect("accounts:onboarding")

                org = membership.organization
                from apps.scheduling.models import Service

                has_services = Service.objects.filter(
                    barbershop__organization=org
                ).exists()
                if not has_services:
                    return redirect("accounts:onboarding")

        return self.get_response(request)


class ProfileCompletionMiddleware:
    """
    Forces authenticated phone-only users (without a first_name) to
    complete their profile by capturing their name before using the app.
    Exempt paths: login, logout, static, capture-name, and API endpoints.
    """

    EXEMPT_PREFIXES = (
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/signup/",
        "/accounts/google/",
        "/accounts/capture-name/",
        "/accounts/otp/",
        "/accounts/phone-check/",
        "/accounts/country-code/",
        "/accounts/confirm-email/",
        "/accounts/resend-verification/",
        "/accounts/email-otp/",
        "/accounts/invite/",
        "/accounts/onboarding/",
        "/accounts/profile/",
        "/accounts/phone/",
        "/accounts/change-password/",
        "/accounts/password-reset/",
        "/accounts/registration/",
        "/billing/",
        "/book/",
        "/static/",
        "/media/",
        "/admin/",
        "/api/",
    )

    EXEMPT_EXACT = {"/", "/accounts/capture-name/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path_info

            is_exempt = path in self.EXEMPT_EXACT or any(
                path.startswith(p) for p in self.EXEMPT_PREFIXES
            )

            if not is_exempt:
                first_name = getattr(request.user, "first_name", "") or ""
                if not first_name.strip():
                    return redirect("accounts:capture_name")

        return self.get_response(request)
