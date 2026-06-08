"""
Tenant middleware – injects current organization & barbershop into request.

After authentication, the middleware reads the user's membership and sets:
  request.organization  – Organization instance (or None)
  request.barbershop    – Barbershop instance (or None)

Views can then use these to filter querysets automatically.
"""

import threading

from django.utils.deprecation import MiddlewareMixin

# Thread-local storage for the current tenant (used by managers)
_thread_locals = threading.local()


def get_current_barbershop():
    return getattr(_thread_locals, "barbershop", None)


def get_current_organization():
    return getattr(_thread_locals, "organization", None)


class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.organization = None
        request.barbershop = None

        if request.user.is_authenticated:
            membership = getattr(request.user, "membership", None)
            if membership is not None:
                request.organization = membership.organization
                request.barbershop = membership.barbershop

                # Fallback to default barbershop if None (e.g., for invited barbers or multi-branch staff)
                if request.barbershop is None and request.organization is not None:
                    if membership.role == "barber":
                        profile = getattr(membership, "barber_profile", None)
                        if profile:
                            request.barbershop = profile.sucursales.filter(
                                is_active=True
                            ).first()

                    if request.barbershop is None:
                        request.barbershop = request.organization.barbershops.filter(
                            is_active=True
                        ).first()

        _thread_locals.organization = request.organization
        _thread_locals.barbershop = request.barbershop

    def process_response(self, request, response):
        # Clean up thread locals
        _thread_locals.organization = None
        _thread_locals.barbershop = None
        return response


# Reload trigger comment

import json
import logging
from django.apps import apps
from django.http import JsonResponse, HttpResponseForbidden
from django.urls import resolve

try:
    from django_ratelimit.core import is_ratelimited
except ImportError:
    is_ratelimited = None

logger = logging.getLogger(__name__)

# Mapa estricto de sufijos _id o nombres a (app_label, model_name)
ID_MODEL_MAPPING = {
    "cliente_id": ("clients", "Client"),
    "barbero_id": ("accounts", "BarberProfile"),
    "intervencion_id": ("scheduling", "Intervencion"),
    "producto_id": ("inventory", "Product"),
    "servicio_id": ("scheduling", "Service"),
    "sucursal_id": ("accounts", "Barbershop"),
    "cita_id": ("scheduling", "Appointment"),
    "categoria_id": ("inventory", "ProductCategory"),
}

EXEMPT_PATHS = [
    "/accounts/login/",
    "/accounts/signup/",
    "/accounts/password/",
    "/accounts/logout/",
    "/accounts/otp/",
    "/accounts/phone-check/",
    "/accounts/country-code/",
    "/accounts/email-otp/",
    "/accounts/capture-name/",
    "/accounts/phone-login/",
    "/accounts/google/",
    "/accounts/invite/",
    "/accounts/confirm-email/",
    "/accounts/resend-verification/",
    "/onboarding/",
    "/billing/webhook/",
    "/booking/",
    "/static/",
    "/media/",
]


class TenantSecurityMiddleware(MiddlewareMixin):
    """
    Protección contra BOLA / IDOR.
    Intercepta las peticiones y extrae IDs del URL, GET y POST/JSON.
    Valida en BD que el objeto pertenezca a la misma organización del usuario autenticado.
    """

    def process_request(self, request):
        path = request.path
        # Permitir exentos y no autenticados (si no están autenticados, no tienen org para validar cruzada)
        if any(path.startswith(p) for p in EXEMPT_PATHS) or path == "/":
            return None

        if not request.user.is_authenticated:
            return None

        user_org = getattr(request, "organization", None)
        if not user_org:
            return None  # Si el usuario no tiene org, otras lógicas (como Onboarding) lo manejarán

        ids_to_check = []

        # 1. Inspect URL parameters
        try:
            match = resolve(path)
            for key, val in match.kwargs.items():
                ids_to_check.append((key, val))
        except Exception:
            pass

        # 2. Inspect GET params
        for key, val in request.GET.items():
            ids_to_check.append((key, val))

        # 3. Inspect POST params
        if request.method in ["POST", "PUT", "PATCH"]:
            if request.content_type == "application/json":
                try:
                    body_data = json.loads(request.body)
                    if isinstance(body_data, dict):
                        for key, val in body_data.items():
                            ids_to_check.append((key, val))
                except Exception:
                    pass
            else:
                for key, val in request.POST.items():
                    ids_to_check.append((key, val))

        # Validación
        for key, val in ids_to_check:
            if key in ID_MODEL_MAPPING and val:
                app_label, model_name = ID_MODEL_MAPPING[key]
                try:
                    Model = apps.get_model(app_label, model_name)
                    # Convertimos a int si es posible para la búsqueda
                    obj_id = int(val)
                    obj = Model.objects.get(pk=obj_id)

                    # Identificar la org del objeto
                    obj_org_id = None
                    if hasattr(obj, "organization_id"):
                        obj_org_id = obj.organization_id
                    elif hasattr(obj, "barbershop") and hasattr(
                        obj.barbershop, "organization_id"
                    ):
                        obj_org_id = obj.barbershop.organization_id
                    elif hasattr(obj, "organization"):
                        obj_org_id = obj.organization.id if obj.organization else None

                    if obj_org_id is not None and str(obj_org_id) != str(user_org.id):
                        logger.warning(
                            f"INTRUSION ATTEMPT: User {request.user.id} (Org {user_org.id}) tried to access {model_name} {obj_id} (Org {obj_org_id})"
                        )
                        return HttpResponseForbidden(
                            "Acceso denegado: Violación de límites de tenant."
                        )
                except (ValueError, TypeError):
                    pass  # ID no es un número válido
                except Model.DoesNotExist:
                    pass  # Si no existe, dejaremos que la vista retorne 404

        return None


class GlobalRateLimitMiddleware(MiddlewareMixin):
    """
    Protección contra automatización abusiva y fuerza bruta usando django-ratelimit.
    """

    def process_request(self, request):
        if not is_ratelimited:
            return None  # Silenciosamente ignorar si no está instalada la librería (fallback)

        path = request.path

        # 1. Login, Registro y Recuperación (5/m)
        if any(
            path.startswith(p)
            for p in ["/accounts/login/", "/accounts/signup/", "/accounts/password/"]
        ):
            if is_ratelimited(
                request, group="auth", key="ip", rate="5/m", increment=True
            ):
                return JsonResponse(
                    {
                        "error": "Demasiadas peticiones. Intente nuevamente en un minuto."
                    },
                    status=429,
                )

        # 2. Formularios Públicos / Booking / Contacto (10/m)
        elif path.startswith("/booking/") or "contact" in path:
            if is_ratelimited(
                request, group="public_forms", key="ip", rate="10/m", increment=True
            ):
                return JsonResponse(
                    {"error": "Demasiadas peticiones desde esta IP."}, status=429
                )

        # 3. OTP Authentication endpoints (5/m per IP)
        elif (
            path.startswith("/accounts/otp/")
            or path.startswith("/accounts/email-otp/")
            or path.startswith("/accounts/phone-check/")
        ):
            if is_ratelimited(
                request, group="otp_auth", key="ip", rate="5/m", increment=True
            ):
                return JsonResponse(
                    {
                        "error": "Demasiadas peticiones de verificación. Intenta nuevamente en un minuto."
                    },
                    status=429,
                )

        # 4. Webhooks de Pago
        elif path.startswith("/billing/webhook/"):
            # Los proveedores pueden enviar ráfagas; un límite razonable como 30/m por IP
            if is_ratelimited(
                request, group="webhooks", key="ip", rate="30/m", increment=True
            ):
                return JsonResponse(
                    {"error": "Demasiadas peticiones de webhooks."}, status=429
                )

        return None
