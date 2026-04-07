"""
Scheduling views – internal app (requires login).

CalendarView        – renders the FullCalendar page
CalendarEventsAPI   – JSON endpoint for FullCalendar events
AvailableSlotsAPI   – JSON endpoint for free time slots
AppointmentCreateAPI – creates a new appointment
AppointmentActionAPI – cancel / reschedule / complete
ServiceListView     – CRUD for services
"""

import json
from collections import OrderedDict
from datetime import datetime, date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import BarberProfile
from . import services as svc
from apps.inventory.models import Product, ProductCategory
from .models import (
    Appointment, CategoriaServicio,
    HistorialPrecioServicio, Service, ServicioProducto,
)


# ─────────────────────────────────────────────
# Calendar page (main view)
# ─────────────────────────────────────────────
class CalendarView(LoginRequiredMixin, TemplateView):
    template_name = "scheduling/calendar.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        barbershop = self.request.barbershop
        membership = self.request.user.membership

        # Barbers for filter dropdown
        barbers = BarberProfile.objects.filter(
            membership__barbershop=barbershop,
            is_active=True,
        ).select_related("membership__user")

        ctx["barbers"] = barbers
        ctx["is_barber"] = membership.role == "barber"

        # If user is a barber, pre-select their own profile
        if membership.role == "barber":
            ctx["selected_barber_id"] = getattr(
                membership, "barber_profile", None
            )
            if ctx["selected_barber_id"]:
                ctx["selected_barber_id"] = ctx["selected_barber_id"].pk

        return ctx


# ─────────────────────────────────────────────
# Calendar events API (FullCalendar JSON feed)
# ─────────────────────────────────────────────
class CalendarEventsAPI(LoginRequiredMixin, View):
    def get(self, request):
        barbershop = request.barbershop
        if barbershop is None:
            return JsonResponse({"error": "Sin barbería asignada"}, status=403)

        barber_id = request.GET.get("barber_id")
        start = request.GET.get("start")
        end = request.GET.get("end")

        barber = None
        if barber_id:
            barber = BarberProfile.objects.filter(
                pk=barber_id,
                membership__barbershop=barbershop,
            ).first()

        # If user is a barber, restrict to their own events
        membership = request.user.membership
        if membership.role == "barber":
            barber = getattr(membership, "barber_profile", None)

        start_date = _parse_date(start)
        end_date = _parse_date(end)

        events = svc.get_calendar_events(
            barbershop=barbershop,
            barber=barber,
            start_date=start_date,
            end_date=end_date,
        )
        return JsonResponse(events, safe=False)


# ─────────────────────────────────────────────
# Available slots API
# ─────────────────────────────────────────────
class AvailableSlotsAPI(LoginRequiredMixin, View):
    def get(self, request):
        barbershop = request.barbershop
        barber_id = request.GET.get("barber_id")
        target_date_str = request.GET.get("date")
        duration = int(request.GET.get("duration", 30))

        if not barber_id or not target_date_str:
            return JsonResponse({"error": "barber_id y date son requeridos"}, status=400)

        barber = BarberProfile.objects.filter(
            pk=barber_id,
            membership__barbershop=barbershop,
        ).first()

        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        target_date = _parse_date(target_date_str)
        if target_date is None:
            return JsonResponse({"error": "Fecha inválida"}, status=400)

        slots = svc.get_available_slots(barber, target_date, duration)
        data = [
            {"start": s["start"].isoformat(), "end": s["end"].isoformat()}
            for s in slots
        ]
        return JsonResponse({"slots": data})


# ─────────────────────────────────────────────
# Appointment create (admin/barber)
# ─────────────────────────────────────────────
class AppointmentCreateAPI(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        barbershop = request.barbershop
        barber_id = data.get("barber_id")
        client_id = data.get("client_id")
        start_time_str = data.get("start_time")
        service_ids = data.get("service_ids", [])
        notes = data.get("notes", "")

        if not all([barber_id, client_id, start_time_str, service_ids]):
            return JsonResponse({"error": "Faltan campos requeridos"}, status=400)

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop=barbershop,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        from apps.clients.models import Client
        client = Client.objects.filter(
            pk=client_id, organization=barbershop.organization,
        ).first()
        if not client:
            return JsonResponse({"error": "Cliente no encontrado"}, status=404)

        try:
            start_time = datetime.fromisoformat(start_time_str)
            if timezone.is_naive(start_time):
                start_time = timezone.make_aware(start_time)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Formato de fecha inválido"}, status=400)

        try:
            appointment = svc.create_appointment(
                barbershop=barbershop,
                barber=barber,
                client=client,
                start_time=start_time,
                service_ids=service_ids,
                notes=notes,
                created_by=request.user,
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=409)

        return JsonResponse({
            "message": "Cita creada exitosamente",
            "appointment_id": appointment.pk,
            "start": appointment.start_time.isoformat(),
            "end": appointment.end_time.isoformat(),
        }, status=201)


# ─────────────────────────────────────────────
# Appointment actions (cancel / complete / reschedule)
# ─────────────────────────────────────────────
class AppointmentActionAPI(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        barbershop = request.barbershop
        appointment = Appointment.objects.filter(
            pk=pk, barbershop=barbershop,
        ).first()
        if not appointment:
            return JsonResponse({"error": "Cita no encontrada"}, status=404)

        action = data.get("action")

        if action == "cancel":
            reason = data.get("reason", "")
            svc.cancel_appointment(appointment, reason=reason, cancelled_by=request.user)
            return JsonResponse({"message": "Cita cancelada"})

        elif action == "complete":
            appointment.status = Appointment.Status.COMPLETED
            appointment.updated_by = request.user
            appointment.save()
            return JsonResponse({"message": "Cita completada"})

        elif action == "reschedule":
            new_start_str = data.get("new_start_time")
            if not new_start_str:
                return JsonResponse({"error": "new_start_time requerido"}, status=400)
            try:
                new_start = datetime.fromisoformat(new_start_str)
                if timezone.is_naive(new_start):
                    new_start = timezone.make_aware(new_start)
            except (ValueError, TypeError):
                return JsonResponse({"error": "Formato de fecha inválido"}, status=400)

            try:
                new_apt = svc.reschedule_appointment(
                    appointment, new_start, rescheduled_by=request.user,
                )
            except ValueError as e:
                return JsonResponse({"error": str(e)}, status=409)

            return JsonResponse({
                "message": "Cita reagendada",
                "new_appointment_id": new_apt.pk,
            })

        return JsonResponse({"error": "Acción no válida"}, status=400)


# ─────────────────────────────────────────────
# Service management
# ─────────────────────────────────────────────
class ServiceListView(LoginRequiredMixin, TemplateView):
    template_name = "scheduling/services.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        barbershop = self.request.barbershop

        services = Service.objects.filter(
            barbershop=barbershop, is_active=True,
        ).select_related("category").order_by("category__name", "name")

        categories = CategoriaServicio.objects.filter(
            barbershop=barbershop, is_active=True,
        ).order_by("name")

        # Group services by category for accordion display
        grouped = OrderedDict()
        for svc_obj in services:
            cat_name = svc_obj.category.name if svc_obj.category else "Sin Categoría"
            cat_id = svc_obj.category.pk if svc_obj.category else ""
            if cat_name not in grouped:
                grouped[cat_name] = {"category_id": cat_id, "services": []}
            grouped[cat_name]["services"].append(svc_obj)

        ctx["grouped_services"] = grouped
        ctx["categories"] = categories
        ctx["total_services"] = services.count()
        ctx["barbershop"] = barbershop

        # Products grouped by category for the product consumption selector
        products = Product.objects.filter(
            barbershop=barbershop, is_active=True,
        ).select_related("category").order_by("category__name", "name")
        grouped_products = OrderedDict()
        for prod in products:
            cat_name = prod.category.name if prod.category else "Sin Categoría"
            if cat_name not in grouped_products:
                grouped_products[cat_name] = []
            grouped_products[cat_name].append(prod)
        ctx["grouped_products"] = grouped_products

        return ctx


class ServiceDetailAPI(LoginRequiredMixin, View):
    """Return service detail + price history as JSON."""

    def get(self, request, pk):
        barbershop = request.barbershop
        try:
            service = Service.objects.select_related("category").get(
                pk=pk, barbershop=barbershop, is_active=True,
            )
        except Service.DoesNotExist:
            return JsonResponse({"error": "Servicio no encontrado"}, status=404)

        history = list(
            HistorialPrecioServicio.objects.filter(service=service).values(
                "price", "changed_at", "changed_by__first_name", "changed_by__last_name",
            )[:50]
        )
        for h in history:
            h["changed_at"] = h["changed_at"].isoformat()
            h["price"] = str(h["price"])

        # Associated products
        productos = ServicioProducto.objects.filter(
            servicio=service,
        ).select_related("producto")
        productos_data = [
            {"producto_id": sp.producto_id, "nombre": sp.producto.name, "cantidad": sp.cantidad_consumida}
            for sp in productos
        ]

        return JsonResponse({
            "id": service.pk,
            "name": service.name,
            "description": service.description,
            "duration_minutes": service.duration_minutes,
            "price": str(service.price),
            "category_id": service.category_id or "",
            "category_name": service.category.name if service.category else "",
            "price_history": history,
            "productos": productos_data,
        })


class ServiceCreateAPI(LoginRequiredMixin, View):
    """API for creating services."""

    def post(self, request):
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        duration = data.get("duration_minutes", 30)
        price = data.get("price", 0)
        category_id = data.get("category_id")

        category = None
        if category_id:
            category = CategoriaServicio.objects.filter(
                pk=category_id, barbershop=barbershop, is_active=True,
            ).first()

        service = Service.objects.create(
            barbershop=barbershop,
            category=category,
            name=name,
            description=data.get("description", ""),
            duration_minutes=duration,
            price=price,
            updated_by=request.user,
        )

        # Record initial price in history
        HistorialPrecioServicio.objects.create(
            service=service,
            price=service.price,
            changed_by=request.user,
        )

        # Save product consumption
        productos = data.get("productos", [])
        for p in productos:
            prod_id = p.get("producto_id")
            cantidad = p.get("cantidad", 1)
            if prod_id and cantidad and int(cantidad) > 0:
                product = Product.objects.filter(
                    pk=prod_id, barbershop=barbershop, is_active=True,
                ).first()
                if product:
                    ServicioProducto.objects.create(
                        servicio=service,
                        producto=product,
                        cantidad_consumida=int(cantidad),
                    )

        return JsonResponse({
            "message": "Servicio creado",
            "id": service.pk,
        }, status=201)


class ServiceUpdateAPI(LoginRequiredMixin, View):
    """API for updating an existing service."""

    def post(self, request, pk):
        barbershop = request.barbershop
        try:
            service = Service.objects.get(pk=pk, barbershop=barbershop, is_active=True)
        except Service.DoesNotExist:
            return JsonResponse({"error": "Servicio no encontrado"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        old_price = service.price

        service.name = name
        service.description = data.get("description", service.description)
        service.duration_minutes = data.get("duration_minutes", service.duration_minutes)
        new_price = data.get("price", service.price)
        service.price = new_price

        category_id = data.get("category_id")
        if category_id == "" or category_id is None:
            service.category = None
        else:
            service.category = CategoriaServicio.objects.filter(
                pk=category_id, barbershop=barbershop, is_active=True,
            ).first()

        service.updated_by = request.user
        service.save()

        # Record price change in history if price changed
        from decimal import Decimal
        if Decimal(str(new_price)) != old_price:
            HistorialPrecioServicio.objects.create(
                service=service,
                price=service.price,
                changed_by=request.user,
            )

        # Update product consumption
        productos = data.get("productos")
        if productos is not None:
            service.productos_consumidos.all().delete()
            for p in productos:
                prod_id = p.get("producto_id")
                cantidad = p.get("cantidad", 1)
                if prod_id and cantidad and int(cantidad) > 0:
                    product = Product.objects.filter(
                        pk=prod_id, barbershop=barbershop, is_active=True,
                    ).first()
                    if product:
                        ServicioProducto.objects.create(
                            servicio=service,
                            producto=product,
                            cantidad_consumida=int(cantidad),
                        )

        return JsonResponse({"ok": True})


class ServiceDeleteAPI(LoginRequiredMixin, View):
    """Soft-delete a service."""

    def post(self, request, pk):
        barbershop = request.barbershop
        service = Service.objects.filter(pk=pk, barbershop=barbershop).first()
        if not service:
            return JsonResponse({"error": "Servicio no encontrado"}, status=404)
        service.is_active = False
        service.updated_by = request.user
        service.save()
        return JsonResponse({"message": "Servicio eliminado"})


# ─────────────────────────────────────────────
# Service category management
# ─────────────────────────────────────────────
class CategoryCreateAPI(LoginRequiredMixin, View):
    """Create a service category."""

    def post(self, request):
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        cat = CategoriaServicio.objects.create(
            barbershop=barbershop,
            name=name,
            updated_by=request.user,
        )
        return JsonResponse({"ok": True, "id": cat.pk, "name": cat.name}, status=201)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _parse_date(val) -> date | None:
    if val is None:
        return None
    try:
        return datetime.fromisoformat(val).date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
