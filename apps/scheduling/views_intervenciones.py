"""
Intervenciones views – CRUD and ag-Grid API.
"""

import json
from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import BarberProfile
from apps.clients.models import Client
from .models import Intervencion, IntervencionServicio, Service


# ─────────────────────────────────────────────
# Main list page (renders the ag-Grid template)
# ─────────────────────────────────────────────
class IntervencionListView(LoginRequiredMixin, TemplateView):
    template_name = "intervenciones/intervencion_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["barbers"] = BarberProfile.objects.filter(
            membership__barbershop=self.request.barbershop,
            is_active=True,
        ).select_related("membership__user")
        ctx["services"] = Service.objects.filter(
            barbershop=self.request.barbershop, is_active=True,
        )
        ctx["estados"] = Intervencion.Estado.choices
        ctx["sucursal_name"] = str(self.request.barbershop)
        return ctx


# ─────────────────────────────────────────────
# ag-Grid API: filtrado, ordenamiento, paginación
# ─────────────────────────────────────────────
class IntervencionGridAPI(LoginRequiredMixin, View):
    """
    API endpoint for ag-Grid infinite row model.
    Accepts: startRow, endRow, sort, order, and filter_* params.
    Returns: { rows: [...], lastRow: int }
    """

    def get(self, request):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        qs = Intervencion.objects.filter(
            barbershop=barbershop,
        ).select_related(
            "barber__membership__user", "client",
        ).prefetch_related(
            Prefetch(
                "servicios",
                queryset=IntervencionServicio.objects.select_related("servicio"),
            )
        )

        # ── Filtros por columna ──
        # Fecha
        filter_fecha = request.GET.get("filter_fecha", "").strip()
        if filter_fecha:
            qs = qs.filter(fecha__date=filter_fecha)

        # Cliente (text contains)
        filter_cliente = request.GET.get("filter_cliente", "").strip()
        if filter_cliente:
            qs = qs.filter(
                Q(client__name__icontains=filter_cliente)
                | Q(client__email__icontains=filter_cliente)
            )

        # Barbero (text contains on display name)
        filter_barbero = request.GET.get("filter_barbero", "").strip()
        if filter_barbero:
            qs = qs.filter(
                Q(barber__membership__user__first_name__icontains=filter_barbero)
                | Q(barber__membership__user__last_name__icontains=filter_barbero)
                | Q(barber__display_name__icontains=filter_barbero)
            )

        # Estado (exact match)
        filter_estado = request.GET.get("filter_estado", "").strip()
        if filter_estado:
            qs = qs.filter(estado=filter_estado)

        # Sucursal (text contains on barbershop name)
        filter_sucursal = request.GET.get("filter_sucursal", "").strip()
        if filter_sucursal:
            qs = qs.filter(barbershop__name__icontains=filter_sucursal)

        # ── Ordenamiento ──
        sort_field = request.GET.get("sort", "fecha")
        sort_order = request.GET.get("order", "desc")

        sort_map = {
            "fecha": "fecha",
            "cliente": "client__name",
            "barbero": "barber__membership__user__first_name",
            "estado": "estado",
            "sucursal": "barbershop__name",
        }
        db_field = sort_map.get(sort_field, "fecha")
        if sort_order == "desc":
            db_field = f"-{db_field}"
        qs = qs.order_by(db_field)

        # ── Paginación ──
        total_count = qs.count()

        try:
            start_row = int(request.GET.get("startRow", 0))
            end_row = int(request.GET.get("endRow", 30))
        except (ValueError, TypeError):
            start_row, end_row = 0, 30

        page = qs[start_row:end_row]

        # ── Serializar ──
        rows = []
        for inv in page:
            servicios = list(inv.servicios.all())
            total = sum(s.precio_cobrado for s in servicios)
            rows.append({
                "id": inv.pk,
                "fecha": inv.fecha.strftime("%d/%m/%Y %H:%M") if inv.fecha else "",
                "fecha_iso": inv.fecha.isoformat() if inv.fecha else "",
                "cliente": inv.client.name if inv.client else "",
                "cliente_id": inv.client_id,
                "barbero": str(inv.barber) if inv.barber else "",
                "barbero_id": inv.barber_id,
                "servicios": [
                    {"nombre": s.servicio.name, "precio": str(s.precio_cobrado)}
                    for s in servicios
                ],
                "sucursal": str(inv.barbershop) if inv.barbershop else "",
                "precio_total": str(total),
                "precio_total_fmt": f"${_format_money(total)}",
                "estado": inv.estado,
                "estado_display": inv.get_estado_display(),
                "notas": inv.notas,
            })

        # lastRow: si no hay más filas, lastRow = total_count; sino -1
        last_row = total_count if end_row >= total_count else -1

        return JsonResponse({"rows": rows, "lastRow": last_row})


def _format_money(value):
    """Format number with dot as thousands separator (Colombian style)."""
    from decimal import Decimal
    try:
        rounded = int(Decimal(str(value)).quantize(Decimal("1")))
        return f"{rounded:,}".replace(",", ".")
    except Exception:
        return str(value)


# ─────────────────────────────────────────────
# Crear intervención (POST JSON)
# ─────────────────────────────────────────────
class IntervencionCreateView(LoginRequiredMixin, View):

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


# ─────────────────────────────────────────────
# Editar intervención (PUT JSON)
# ─────────────────────────────────────────────
class IntervencionUpdateView(LoginRequiredMixin, View):

    def put(self, request, pk):
        barbershop = request.barbershop
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop=barbershop,
        )
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
            fecha = datetime.fromisoformat(fecha_str) if fecha_str else intervencion.fecha
            if timezone.is_naive(fecha):
                fecha = timezone.make_aware(fecha)
        except (ValueError, TypeError):
            fecha = intervencion.fecha

        services = Service.objects.filter(
            pk__in=service_ids, barbershop=barbershop, is_active=True,
        )
        if not services.exists():
            return JsonResponse({"error": "No se encontraron servicios válidos"}, status=400)

        total_duration = sum(s.duration_minutes for s in services)
        from datetime import timedelta
        fecha_fin = fecha + timedelta(minutes=total_duration)

        intervencion.barber = barber
        intervencion.client = client
        intervencion.fecha = fecha
        intervencion.fecha_fin = fecha_fin
        intervencion.notas = notas
        intervencion.updated_by = request.user
        intervencion.save()

        # Replace services
        intervencion.servicios.all().delete()
        for service in services:
            IntervencionServicio.objects.create(
                intervencion=intervencion,
                servicio=service,
                precio_cobrado=service.price,
            )

        return JsonResponse({"message": "Intervención actualizada", "id": intervencion.pk})


# ─────────────────────────────────────────────
# Eliminar intervención (DELETE)
# ─────────────────────────────────────────────
class IntervencionDeleteView(LoginRequiredMixin, View):

    def delete(self, request, pk):
        barbershop = request.barbershop
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop=barbershop,
        )
        intervencion.delete()
        return JsonResponse({"message": "Intervención eliminada"})


# ─────────────────────────────────────────────
# Cambiar estado (POST JSON)
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# Datos para formulario (barberos + servicios)
# ─────────────────────────────────────────────
class IntervencionDataAPI(LoginRequiredMixin, View):

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


# ─────────────────────────────────────────────
# Detalle de intervención (GET JSON)
# ─────────────────────────────────────────────
class IntervencionDetailAPI(LoginRequiredMixin, View):

    def get(self, request, pk):
        barbershop = request.barbershop
        intervencion = get_object_or_404(
            Intervencion.objects.select_related(
                "barber__membership__user", "client",
            ).prefetch_related(
                "servicios__servicio",
            ),
            pk=pk,
            barbershop=barbershop,
        )

        servicios = list(intervencion.servicios.all())
        return JsonResponse({
            "id": intervencion.pk,
            "barber_id": intervencion.barber_id,
            "barbero": str(intervencion.barber),
            "client_id": intervencion.client_id,
            "cliente": intervencion.client.name,
            "fecha": intervencion.fecha.strftime("%Y-%m-%dT%H:%M") if intervencion.fecha else "",
            "estado": intervencion.estado,
            "notas": intervencion.notas,
            "service_ids": [s.servicio_id for s in servicios],
            "servicios": [
                {"id": s.servicio_id, "nombre": s.servicio.name, "precio": str(s.precio_cobrado)}
                for s in servicios
            ],
        })
