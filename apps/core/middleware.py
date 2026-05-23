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
                            request.barbershop = profile.sucursales.filter(is_active=True).first()
                    
                    if request.barbershop is None:
                        request.barbershop = request.organization.barbershops.filter(is_active=True).first()

        _thread_locals.organization = request.organization
        _thread_locals.barbershop = request.barbershop

    def process_response(self, request, response):
        # Clean up thread locals
        _thread_locals.organization = None
        _thread_locals.barbershop = None
        return response

# Reload trigger comment

