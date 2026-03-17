"""
View mixins for BarberSync.

TenantViewMixin  – auto-filters querysets by the user's barbershop.
OrganizationViewMixin – filters by organization (for CRM, global views).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class TenantViewMixin(LoginRequiredMixin):
    """
    Ensures the view only returns objects belonging to the
    current user's barbershop.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        barbershop = getattr(self.request, "barbershop", None)
        if barbershop is None:
            raise PermissionDenied("No tienes una barbería asignada.")
        return qs.filter(barbershop=barbershop)

    def form_valid(self, form):
        form.instance.barbershop = self.request.barbershop
        form.instance.updated_by = self.request.user
        return super().form_valid(form)


class OrganizationViewMixin(LoginRequiredMixin):
    """
    Ensures the view only returns objects belonging to the
    current user's organization.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        org = getattr(self.request, "organization", None)
        if org is None:
            raise PermissionDenied("No tienes una organización asignada.")
        return qs.filter(organization=org)

    def form_valid(self, form):
        form.instance.organization = self.request.organization
        form.instance.updated_by = self.request.user
        return super().form_valid(form)


class RoleRequiredMixin:
    """
    Restricts access to users with one of the allowed roles.
    Usage:  allowed_roles = ["owner", "admin"]
    """

    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        membership = getattr(request.user, "membership", None)
        if membership is None or membership.role not in self.allowed_roles:
            raise PermissionDenied("No tienes permisos para esta acción.")
        return super().dispatch(request, *args, **kwargs)
