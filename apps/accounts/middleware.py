from django.shortcuts import redirect
from django.urls import reverse

class OnboardingMiddleware:
    """
    Middleware that forces newly registered users without an organization
    to complete the onboarding process before using the app.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path_info
            
            # Allow root, allauth, billing, book, onboarding itself, static/media
            excluded_prefixes = (
                "/accounts/onboarding/",
                "/accounts/logout/",
                "/accounts/login/",
                "/accounts/google/", 
                "/accounts/signup/",
                "/accounts/invite/",
                "/billing/",
                "/book/",
                "/static/",
                "/media/",
                "/admin/",
            )
            
            is_excluded = path == "/" or any(path.startswith(p) for p in excluded_prefixes)
            
            if not is_excluded:
                membership = request.user.memberships.filter(is_active=True).first()
                if not membership or not membership.organization:
                    return redirect("accounts:onboarding")
                    
        return self.get_response(request)
