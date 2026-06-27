"""
SubscriptionAccessMiddleware

Valida que el usuario autenticado tenga una suscripción activa antes de
permitir el acceso a vistas internas (no exentas).

OPTIMIZACIÓN (caché distribuida):
El resultado de la verificación se cachea usando `apps.billing.cache_utils`
con TTL dinámico que expira a las 23:59:59 del día en curso.

    Entorno LOCAL=True       → django.core.cache.backends.locmem.LocMemCache
    Entorno producción       → django_redis.cache.RedisCache (clave REDIS_URL)

Las claves usadas son:
    barbersync:sub:active:user:{user_id}
    barbersync:sub:active:org:{organization_id}

Se invalidan automáticamente mediante `apps.billing.signals` al guardar o
borrar una `Subscription`, garantizando consistencia即便 ante activaciones
vía webhook o cancelaciones administrativas.
"""

from django.shortcuts import redirect

from .cache_utils import get_org_subscription_status, get_user_subscription_status

EXEMPT_PREFIXES = (
    "/accounts/login/",
    "/accounts/signup/",
    "/accounts/logout/",
    "/accounts/google/",
    "/accounts/invite/",
    "/accounts/confirm-email/",
    "/accounts/resend-verification/",
    "/accounts/capture-name/",
    # "/accounts/onboarding/",
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

        if get_user_subscription_status(request.user):
            return self.get_response(request)

        org = getattr(request, "organization", None)
        if org is not None and get_org_subscription_status(org):
            return self.get_response(request)

        return redirect("/?expired=true#planes")
