from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth (allauth handles Google OAuth + email login)
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("apps.accounts.urls")),

    # Internal app (requires login)
    path("app/schedule/", include("apps.scheduling.urls")),
    path("app/clients/", include("apps.clients.urls")),
    path("app/inventory/", include("apps.inventory.urls")),
    path("app/finance/", include("apps.finance.urls")),

    # Public booking page (no login required – clients use Google Auth)
    path("book/", include("apps.booking.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
