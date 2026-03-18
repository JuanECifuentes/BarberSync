"""
Client CRM views – list, search, detail.
Scoped to the user's organization.
"""

import json
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from apps.core.mixins import OrganizationViewMixin

from .models import Client


class ClientListView(OrganizationViewMixin, ListView):
    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            appointment_count=Count("appointments"),
        )
        # Filtros por columna
        nombre = self.request.GET.get("nombre")
        if nombre:
            qs = qs.filter(name__icontains=nombre)

        email = self.request.GET.get("email")
        if email:
            qs = qs.filter(email__icontains=email)

        telefono = self.request.GET.get("telefono")
        if telefono:
            qs = qs.filter(phone__icontains=telefono)

        origen = self.request.GET.get("origen")
        if origen:
            qs = qs.filter(source=origen)

        # Backward compat: general search
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
            )
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Available source values for the filter dropdown
        ctx["sources"] = list(
            Client.objects.filter(organization=self.request.organization)
            .values_list("source", flat=True)
            .distinct()
            .order_by("source")
        )
        return ctx


class ClientDetailView(OrganizationViewMixin, DetailView):
    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Last 6 months of appointments
        cutoff = timezone.now() - timedelta(
            days=30 * settings.BARBERSYNC_DEFAULT_HISTORY_MONTHS
        )
        ctx["appointments"] = (
            self.object.appointments
            .filter(start_time__gte=cutoff)
            .select_related("barber__membership__user")
            .order_by("-start_time")[:20]
        )
        return ctx


class ClientSearchAPI(View):
    """
    Quick search API for autocomplete in appointment creation forms.
    GET /app/clients/api/search/?q=Juan
    """

    def get(self, request):
        org = getattr(request, "organization", None)
        if org is None:
            return JsonResponse([], safe=False)

        q = request.GET.get("q", "").strip()
        if len(q) < 2:
            return JsonResponse([], safe=False)

        clients = Client.objects.filter(
            organization=org,
        ).filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
        )[:10]

        data = [
            {"id": c.pk, "name": c.name, "email": c.email, "phone": c.phone}
            for c in clients
        ]
        return JsonResponse(data, safe=False)
