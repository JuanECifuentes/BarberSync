from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

from apps.accounts.views import SendOTPView, VerifyOTPView
from apps.core.views import LandingPageView


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect("scheduling:calendar")
    return redirect("accounts:phone_login")


urlpatterns = [
    path("", LandingPageView.as_view(), name="root"),
    path("admin/", admin.site.urls),
    # Auth (allauth handles Google OAuth + email login)
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("allauth.urls")),
    # Internal app (requires login)
    path("app/schedule/", include("apps.scheduling.urls")),
    path("app/clients/", include("apps.clients.urls")),
    path("app/inventory/", include("apps.inventory.urls")),
    path("app/finance/", include("apps.finance.urls")),
    path("app/intervenciones/", include("apps.scheduling.urls_intervenciones")),
    path("app/configuracion/", include("apps.accounts.urls_configuracion")),
    path("app/barberos/", include("apps.accounts.urls_barberos")),
    # Billing / Payments
    path("billing/", include("apps.billing.urls")),
    # Public booking page (no login required – clients use Google Auth)
    path("book/", include("apps.booking.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
