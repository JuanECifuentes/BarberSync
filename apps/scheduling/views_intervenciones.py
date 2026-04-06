"""
Intervenciones views – CRUD and ag-Grid API.
"""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Prefetch, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import BarberProfile, Barbershop
from apps.clients.models import Client
from .models import CategoriaServicio, Intervencion, IntervencionServicio, Service


# ─────────────────────────────────────────────
# Main list page (renders the ag-Grid template)
# ─────────────────────────────────────────────
class IntervencionListView(LoginRequiredMixin, TemplateView):
    template_name = "intervenciones/intervencion_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        barbershop = self.request.barbershop

        ctx["barbers"] = BarberProfile.objects.filter(
            membership__barbershop=barbershop,
            is_active=True,
        ).select_related("membership__user")
        services = Service.objects.filter(
            barbershop=barbershop, is_active=True,
        ).select_related("category")
        ctx["services"] = services
        ctx["estados"] = Intervencion.Estado.choices
        ctx["sucursales"] = Barbershop.objects.filter(organization=org)
        ctx["sucursal_name"] = str(barbershop)
        ctx["current_barbershop_id"] = barbershop.pk

        # Group services by category for accordion display in modals
        from collections import OrderedDict
        grouped = OrderedDict()
        for svc_obj in services:
            cat_name = svc_obj.category.name if svc_obj.category else "Sin Categoría"
            cat_id = svc_obj.category.pk if svc_obj.category else ""
            if cat_name not in grouped:
                grouped[cat_name] = {"category_id": cat_id, "services": []}
            grouped[cat_name]["services"].append(svc_obj)
        ctx["grouped_services"] = grouped

        return ctx


# ─────────────────────────────────────────────
# ag-Grid API: filtrado, ordenamiento, paginación
# ─────────────────────────────────────────────
class IntervencionGridAPI(LoginRequiredMixin, View):
    """
    API endpoint for ag-Grid infinite row model.
    Supports external filters: multi-select checkboxes, date range, price range.
    """

    def get(self, request):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        org = barbershop.organization
        qs = Intervencion.objects.filter(
            barbershop__organization=org,
        ).select_related(
            "barber__membership__user", "client",
        ).prefetch_related(
            Prefetch(
                "servicios",
                queryset=IntervencionServicio.objects.select_related("servicio"),
            )
        )

        # ── Filtros externos (multi-select checkboxes) ──

        # Barberos (comma-separated IDs)
        filter_barberos = request.GET.get("filter_barberos", "").strip()
        if filter_barberos:
            ids = [int(x) for x in filter_barberos.split(",") if x.strip().isdigit()]
            if ids:
                qs = qs.filter(barber_id__in=ids)

        # Servicios (comma-separated IDs) – intervenciones que contengan AL MENOS uno
        filter_servicios = request.GET.get("filter_servicios", "").strip()
        if filter_servicios:
            ids = [int(x) for x in filter_servicios.split(",") if x.strip().isdigit()]
            if ids:
                qs = qs.filter(servicios__servicio_id__in=ids).distinct()

        # Sucursales (comma-separated IDs)
        filter_sucursales = request.GET.get("filter_sucursales", "").strip()
        if filter_sucursales:
            ids = [int(x) for x in filter_sucursales.split(",") if x.strip().isdigit()]
            if ids:
                qs = qs.filter(barbershop_id__in=ids)

        # Estados (comma-separated values)
        filter_estados = request.GET.get("filter_estados", "").strip()
        if filter_estados:
            vals = [v.strip() for v in filter_estados.split(",") if v.strip()]
            if vals:
                qs = qs.filter(estado__in=vals)

        # ── Filtros de rango ──

        # Fecha rango
        filter_fecha_desde = request.GET.get("filter_fecha_desde", "").strip()
        if filter_fecha_desde:
            qs = qs.filter(fecha__date__gte=filter_fecha_desde)

        filter_fecha_hasta = request.GET.get("filter_fecha_hasta", "").strip()
        if filter_fecha_hasta:
            qs = qs.filter(fecha__date__lte=filter_fecha_hasta)

        # Precio total rango (requires annotation)
        filter_total_min = request.GET.get("filter_total_min", "").strip()
        filter_total_max = request.GET.get("filter_total_max", "").strip()
        if filter_total_min or filter_total_max:
            qs = qs.annotate(
                _precio_total=Sum("servicios__precio_cobrado")
            )
            if filter_total_min:
                try:
                    qs = qs.filter(_precio_total__gte=Decimal(filter_total_min))
                except (InvalidOperation, ValueError):
                    pass
            if filter_total_max:
                try:
                    qs = qs.filter(_precio_total__lte=Decimal(filter_total_max))
                except (InvalidOperation, ValueError):
                    pass

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

        last_row = total_count if end_row >= total_count else -1
        return JsonResponse({"rows": rows, "lastRow": last_row})


def _format_money(value):
    """Format number with dot as thousands separator (Colombian style)."""
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
        estado = data.get("estado", Intervencion.Estado.PENDIENTE)
        sucursal_id = data.get("sucursal_id")

        if not all([barber_id, client_id, service_ids]):
            return JsonResponse({"error": "Faltan campos requeridos"}, status=400)

        if estado not in dict(Intervencion.Estado.choices):
            estado = Intervencion.Estado.PENDIENTE

        # Resolve target barbershop (sucursal)
        target_barbershop = barbershop
        if sucursal_id:
            target_barbershop = Barbershop.objects.filter(
                pk=sucursal_id, organization=barbershop.organization,
            ).first() or barbershop

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

        total_duration = sum(s.duration_minutes for s in services)
        from datetime import timedelta
        fecha_fin = fecha + timedelta(minutes=total_duration)

        intervencion = Intervencion.objects.create(
            barbershop=target_barbershop,
            barber=barber,
            client=client,
            estado=estado,
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
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop__organization=org,
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
        estado = data.get("estado")
        sucursal_id = data.get("sucursal_id")

        if not all([barber_id, client_id, service_ids]):
            return JsonResponse({"error": "Faltan campos requeridos"}, status=400)

        # Resolve target barbershop (sucursal)
        if sucursal_id:
            target_barbershop = Barbershop.objects.filter(
                pk=sucursal_id, organization=org,
            ).first()
            if target_barbershop:
                intervencion.barbershop = target_barbershop

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop__organization=org,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        client = Client.objects.filter(
            pk=client_id, organization=org,
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
            pk__in=service_ids, barbershop__organization=org, is_active=True,
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

        if estado and estado in dict(Intervencion.Estado.choices):
            intervencion.estado = estado
            if estado == Intervencion.Estado.REALIZADA and not intervencion.fecha_fin:
                intervencion.fecha_fin = timezone.now()

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
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop__organization=org,
        )
        intervencion.delete()
        return JsonResponse({"message": "Intervención eliminada"})


# ─────────────────────────────────────────────
# Cambiar estado (POST JSON)
# ─────────────────────────────────────────────
class IntervencionChangeStatusAPI(LoginRequiredMixin, View):
    def post(self, request, pk):
        barbershop = request.barbershop
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop__organization=org,
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

        sucursales = Barbershop.objects.filter(
            organization=barbershop.organization,
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
            "sucursales": [
                {"id": s.pk, "name": s.name}
                for s in sucursales
            ],
        })


# ─────────────────────────────────────────────
# Detalle de intervención (GET JSON)
# ─────────────────────────────────────────────
class IntervencionDetailAPI(LoginRequiredMixin, View):

    def get(self, request, pk):
        barbershop = request.barbershop
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion.objects.select_related(
                "barber__membership__user", "client",
            ).prefetch_related(
                "servicios__servicio",
            ),
            pk=pk,
            barbershop__organization=org,
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
            "sucursal_id": intervencion.barbershop_id,
            "service_ids": [s.servicio_id for s in servicios],
            "servicios": [
                {"id": s.servicio_id, "nombre": s.servicio.name, "precio": str(s.precio_cobrado)}
                for s in servicios
            ],
        })
