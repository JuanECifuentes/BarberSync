"""
Intervenciones views – CRUD and management.
"""

import json
from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.models import BarberProfile
from apps.clients.models import Client
from apps.core.mixins import TenantViewMixin

from .models import Intervencion, IntervencionProducto, IntervencionServicio, Service


class IntervencionListView(TenantViewMixin, ListView):
    model = Intervencion
    template_name = "intervenciones/intervencion_list.html"
    context_object_name = "intervenciones"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            "barber__membership__user", "client",
        )
        # Filtros por columna
        estado = self.request.GET.get("estado")
        if estado:
            qs = qs.filter(estado=estado)

        barbero = self.request.GET.get("barbero")
        if barbero:
            qs = qs.filter(barber_id=barbero)

        cliente = self.request.GET.get("cliente")
        if cliente:
            qs = qs.filter(
                Q(client__name__icontains=cliente)
                | Q(client__email__icontains=cliente)
            )

        fecha_desde = self.request.GET.get("fecha_desde")
        if fecha_desde:
            qs = qs.filter(fecha__date__gte=fecha_desde)

        fecha_hasta = self.request.GET.get("fecha_hasta")
        if fecha_hasta:
            qs = qs.filter(fecha__date__lte=fecha_hasta)

        return qs.order_by("-fecha")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["barbers"] = BarberProfile.objects.filter(
            membership__barbershop=self.request.barbershop,
            is_active=True,
        ).select_related("membership__user")
        ctx["estados"] = Intervencion.Estado.choices
        return ctx


class IntervencionDetailView(TenantViewMixin, DetailView):
    model = Intervencion
    template_name = "intervenciones/intervencion_detail.html"
    context_object_name = "intervencion"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "barber__membership__user", "client", "appointment",
        ).prefetch_related("servicios__servicio", "productos_usados__producto")


class IntervencionCreateView(LoginRequiredMixin, TemplateView):
    template_name = "intervenciones/intervencion_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        barbershop = self.request.barbershop
        ctx["barbers"] = BarberProfile.objects.filter(
            membership__barbershop=barbershop, is_active=True,
        ).select_related("membership__user")
        ctx["services"] = Service.objects.filter(
            barbershop=barbershop, is_active=True,
        )
        return ctx

    def post(self, request):
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        barber_id = data.get("barber_id")
        client_id = data.get("client_id")
        service_ids = data.get("service_ids", [])
        notas = data.get("notas", "")
        fecha_str = data.get("fecha")

        if not all([barber_id, client_id, service_ids]):
            return JsonResponse({"error": "Faltan campos requeridos"}, status=400)

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop=barbershop,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        client = Client.objects.filter(
            pk=client_id, organization=barbershop.organization,
        ).first()
        if not client:
            return JsonResponse({"error": "Cliente no encontrado"}, status=404)

        try:
            fecha = datetime.fromisoformat(fecha_str) if fecha_str else timezone.now()
            if timezone.is_naive(fecha):
                fecha = timezone.make_aware(fecha)
        except (ValueError, TypeError):
            fecha = timezone.now()

        services = Service.objects.filter(
            pk__in=service_ids, barbershop=barbershop, is_active=True,
        )
        if not services.exists():
            return JsonResponse({"error": "No se encontraron servicios válidos"}, status=400)

        # Calculate end time
        total_duration = sum(s.duration_minutes for s in services)
        from datetime import timedelta
        fecha_fin = fecha + timedelta(minutes=total_duration)

        intervencion = Intervencion.objects.create(
            barbershop=barbershop,
            barber=barber,
            client=client,
            estado=Intervencion.Estado.PENDIENTE,
            fecha=fecha,
            fecha_fin=fecha_fin,
            notas=notas,
            updated_by=request.user,
        )

        for service in services:
            IntervencionServicio.objects.create(
                intervencion=intervencion,
                servicio=service,
                precio_cobrado=service.price,
            )

        return JsonResponse({
            "message": "Intervención creada",
            "id": intervencion.pk,
        }, status=201)


class IntervencionChangeStatusAPI(LoginRequiredMixin, View):
    def post(self, request, pk):
        barbershop = request.barbershop
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop=barbershop,
        )
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        nuevo_estado = data.get("estado")
        if nuevo_estado not in dict(Intervencion.Estado.choices):
            return JsonResponse({"error": "Estado inválido"}, status=400)

        intervencion.estado = nuevo_estado
        if nuevo_estado == Intervencion.Estado.REALIZADA and not intervencion.fecha_fin:
            intervencion.fecha_fin = timezone.now()
        intervencion.updated_by = request.user
        intervencion.save()

        return JsonResponse({"message": f"Estado actualizado a {intervencion.get_estado_display()}"})


class IntervencionDataAPI(LoginRequiredMixin, View):
    """API for getting barbers and services data for the create form."""

    def get(self, request):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        barbers = BarberProfile.objects.filter(
            membership__barbershop=barbershop, is_active=True,
        ).select_related("membership__user")

        services = Service.objects.filter(
            barbershop=barbershop, is_active=True,
        )

        return JsonResponse({
            "barbers": [
                {"id": b.pk, "name": str(b)}
                for b in barbers
            ],
            "services": [
                {"id": s.pk, "name": s.name, "price": str(s.price), "duration": s.duration_minutes}
                for s in services
            ],
        })
