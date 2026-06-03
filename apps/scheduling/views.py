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
from datetime import datetime, date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import BarberProfile, Membership
from . import services as svc
from apps.inventory.models import Product, ProductCategory, StockMovement
from apps.notifications.notifications import send_notification
from .models import (
    Appointment,
    BarberService,
    CategoriaServicio,
    HistorialCambiosConfiguracionBarbero,
    HistorialPrecioServicio,
    Intervencion,
    IntervencionProducto,
    Service,
    ServicioProducto,
    WorkSchedule,
    ScheduleException,
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
        if not membership:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "No perteneces a ninguna organización o tu cuenta no tiene rol de empleado."
            )

        # Barbers for filter dropdown
        barbers = (
            BarberProfile.objects.filter(
                Q(membership__barbershop=barbershop) | Q(sucursales=barbershop),
                is_active=True,
            )
            .select_related("membership__user")
            .distinct()
        )

        ctx["barbers"] = barbers
        print("membership", membership, "role", membership.role)
        ctx["is_barber"] = membership.role == "barber"

        # If user is a barber, pre-select their own profile
        if membership.role == "barber":
            ctx["selected_barber_id"] = getattr(membership, "barber_profile", None)
            if ctx["selected_barber_id"]:
                ctx["selected_barber_id"] = ctx["selected_barber_id"].pk

        # Products grouped by category for product consumption in modal
        products = (
            Product.objects.filter(
                barbershop=barbershop,
                is_active=True,
            )
            .select_related("category")
            .order_by("category__name", "name")
        )
        grouped_products = OrderedDict()
        for prod in products:
            cat_name = prod.category.name if prod.category else "Sin Categoría"
            if cat_name not in grouped_products:
                grouped_products[cat_name] = []
            grouped_products[cat_name].append(prod)
        ctx["grouped_products"] = grouped_products

        # Compute active barbers data for optimized initial load
        today = timezone.localdate()

        # Calculate max window of days ahead
        max_days = 15
        for b in barbers:
            max_days = max(max_days, getattr(b, "intervalo_apertura_dias", 15) or 15)
        max_date = today + timedelta(days=max_days + 1)

        # Work schedules grouping
        work_schedules_by_barber = {}
        for ws in WorkSchedule.objects.filter(barber__in=barbers):
            if ws.barber_id not in work_schedules_by_barber:
                work_schedules_by_barber[ws.barber_id] = []
            work_schedules_by_barber[ws.barber_id].append(
                {
                    "day_of_week": ws.day_of_week,
                    "start": ws.start_time.strftime("%H:%M"),
                    "end": ws.end_time.strftime("%H:%M"),
                }
            )

        # Exceptions grouping within date range
        exceptions_by_barber = {}
        for exc in ScheduleException.objects.filter(
            barber__in=barbers, start__date__gte=today, start__date__lte=max_date
        ):
            if exc.barber_id not in exceptions_by_barber:
                exceptions_by_barber[exc.barber_id] = []
            exceptions_by_barber[exc.barber_id].append(
                {"start": exc.start.isoformat(), "end": exc.end.isoformat()}
            )

        # Active appointments grouping within date range
        active_statuses = [
            Appointment.Status.PENDING,
            Appointment.Status.CONFIRMED,
            Appointment.Status.IN_PROGRESS,
        ]
        appointments_by_barber = {}
        for apt in Appointment.objects.filter(
            barber__in=barbers,
            start_time__date__gte=today,
            start_time__date__lte=max_date,
            status__in=active_statuses,
        ):
            if apt.barber_id not in appointments_by_barber:
                appointments_by_barber[apt.barber_id] = []
            appointments_by_barber[apt.barber_id].append(
                {
                    "id": apt.pk,
                    "start": apt.start_time.isoformat(),
                    "end": apt.end_time.isoformat(),
                }
            )

        barbers_data = []
        for b in barbers:
            days_ahead = getattr(b, "intervalo_apertura_dias", 15) or 15
            barbers_data.append(
                {
                    "id": b.pk,
                    "name": str(b),
                    "intervalo_apertura_dias": days_ahead,
                    "buffer_minutes": b.buffer_minutes,
                    "lunch_start": b.lunch_start.strftime("%H:%M")
                    if b.lunch_start
                    else None,
                    "lunch_end": b.lunch_end.strftime("%H:%M") if b.lunch_end else None,
                    "work_schedules": work_schedules_by_barber.get(b.pk, []),
                    "exceptions": exceptions_by_barber.get(b.pk, []),
                    "appointments": appointments_by_barber.get(b.pk, []),
                }
            )
        ctx["barbers_data"] = barbers_data

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
                Q(pk=barber_id)
                & (Q(membership__barbershop=barbershop) | Q(sucursales=barbershop))
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
            return JsonResponse(
                {"error": "barber_id y date son requeridos"}, status=400
            )

        barber = BarberProfile.objects.filter(
            Q(membership__barbershop=barbershop) | Q(sucursales=barbershop),
            pk=barber_id,
        ).first()

        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        target_date = _parse_date(target_date_str)
        if target_date is None:
            return JsonResponse({"error": "Fecha inválida"}, status=400)

        slots = svc.get_available_slots(
            barber, target_date, duration, barbershop=barbershop
        )
        data = [
            {"start": s["start"].isoformat(), "end": s["end"].isoformat()}
            for s in slots
        ]
        days_ahead = getattr(barber, "intervalo_apertura_dias", 15) or 15
        return JsonResponse({"slots": data, "intervalo_apertura_dias": days_ahead})


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
            Q(membership__barbershop=barbershop) | Q(sucursales=barbershop),
            pk=barber_id,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        from apps.clients.models import Client

        client = Client.objects.filter(
            pk=client_id,
            organization=barbershop.organization,
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

        return JsonResponse(
            {
                "message": "Cita creada exitosamente",
                "appointment_id": appointment.pk,
                "start": appointment.start_time.isoformat(),
                "end": appointment.end_time.isoformat(),
            },
            status=201,
        )


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
            pk=pk,
            barbershop=barbershop,
        ).first()
        if not appointment:
            return JsonResponse({"error": "Cita no encontrada"}, status=404)

        action = data.get("action")

        if action == "cancel":
            reason = data.get("reason", "")
            svc.cancel_appointment(
                appointment, reason=reason, cancelled_by=request.user
            )
            # Sync linked Intervencion → cancelada
            try:
                intervencion = appointment.intervencion
                intervencion.estado = Intervencion.Estado.CANCELADA
                intervencion.updated_by = request.user
                intervencion.save(update_fields=["estado", "updated_by", "updated_at"])
            except Intervencion.DoesNotExist:
                pass
            return JsonResponse({"message": "Cita cancelada"})

        elif action == "complete":
            with transaction.atomic():
                appointment.status = Appointment.Status.COMPLETED
                appointment.updated_by = request.user
                appointment.save()
                # Sync linked Intervencion → realizada & freeze product prices
                try:
                    intervencion = appointment.intervencion
                    intervencion.estado = Intervencion.Estado.REALIZADA
                    if not intervencion.fecha_fin:
                        intervencion.fecha_fin = timezone.now()
                    intervencion.updated_by = request.user
                    intervencion.save(
                        update_fields=[
                            "estado",
                            "fecha_fin",
                            "updated_by",
                            "updated_at",
                        ]
                    )
                    # Freeze product prices at the moment of completion
                    for ip in intervencion.productos_usados.select_related(
                        "producto"
                    ).all():
                        ip.precio_unitario = ip.producto.price
                        ip.save(update_fields=["precio_unitario"])
                except Intervencion.DoesNotExist:
                    pass
            return JsonResponse({"message": "Cita realizada"})

        elif action == "reopen":
            appointment.status = Appointment.Status.CONFIRMED
            appointment.updated_by = request.user
            appointment.save()
            # Sync linked Intervencion → pendiente
            try:
                intervencion = appointment.intervencion
                intervencion.estado = Intervencion.Estado.PENDIENTE
                intervencion.updated_by = request.user
                intervencion.save(update_fields=["estado", "updated_by", "updated_at"])
            except Intervencion.DoesNotExist:
                pass
            return JsonResponse({"message": "Cita reabierta"})

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
                    appointment,
                    new_start,
                    rescheduled_by=request.user,
                )
            except ValueError as e:
                return JsonResponse({"error": str(e)}, status=409)

            return JsonResponse(
                {
                    "message": "Cita reagendada",
                    "new_appointment_id": new_apt.pk,
                }
            )

        return JsonResponse({"error": "Acción no válida"}, status=400)


# ─────────────────────────────────────────────
# Service management
# ─────────────────────────────────────────────
class ServiceListView(LoginRequiredMixin, TemplateView):
    template_name = "scheduling/services.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        barbershop = self.request.barbershop
        org = self.request.organization

        if barbershop:
            services = (
                Service.objects.filter(
                    barbershop=barbershop,
                    is_active=True,
                )
                .select_related("category")
                .order_by("category__name", "name")
            )

            categories = CategoriaServicio.objects.filter(
                barbershop=barbershop,
                is_active=True,
            ).order_by("name")

            products = (
                Product.objects.filter(
                    barbershop=barbershop,
                    is_active=True,
                )
                .select_related("category")
                .order_by("category__name", "name")
            )
        else:
            services = (
                Service.objects.filter(
                    barbershop__organization=org,
                    is_active=True,
                )
                .select_related("category")
                .order_by("category__name", "name")
            )

            categories = CategoriaServicio.objects.filter(
                barbershop__organization=org,
                is_active=True,
            ).order_by("name")

            products = (
                Product.objects.filter(
                    barbershop__organization=org,
                    is_active=True,
                )
                .select_related("category")
                .order_by("category__name", "name")
            )

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
                pk=pk,
                barbershop=barbershop,
                is_active=True,
            )
        except Service.DoesNotExist:
            return JsonResponse({"error": "Servicio no encontrado"}, status=404)

        history = list(
            HistorialPrecioServicio.objects.filter(service=service).values(
                "price",
                "changed_at",
                "changed_by__first_name",
                "changed_by__last_name",
            )[:50]
        )
        for h in history:
            h["changed_at"] = h["changed_at"].isoformat()
            h["price"] = str(h["price"])

        # Associated products (exclude soft-deleted products)
        productos = ServicioProducto.objects.filter(
            servicio=service,
            producto__is_active=True,
        ).select_related("producto")
        productos_data = [
            {
                "producto_id": sp.producto_id,
                "nombre": sp.producto.name,
                "cantidad": sp.cantidad_consumida,
                "incluido_en_precio": sp.incluido_en_precio,
            }
            for sp in productos
        ]

        return JsonResponse(
            {
                "id": service.pk,
                "name": service.name,
                "description": service.description,
                "duration_minutes": service.duration_minutes,
                "price": str(service.price),
                "category_id": service.category_id or "",
                "category_name": service.category.name if service.category else "",
                "price_history": history,
                "productos": productos_data,
            }
        )


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
                pk=category_id,
                barbershop=barbershop,
                is_active=True,
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
                    pk=prod_id,
                    barbershop=barbershop,
                    is_active=True,
                ).first()
                if product:
                    ServicioProducto.objects.create(
                        servicio=service,
                        producto=product,
                        cantidad_consumida=int(cantidad),
                        incluido_en_precio=bool(p.get("incluido_en_precio", False)),
                    )

        return JsonResponse(
            {
                "message": "Servicio creado",
                "id": service.pk,
            },
            status=201,
        )


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
        service.duration_minutes = data.get(
            "duration_minutes", service.duration_minutes
        )
        new_price = data.get("price", service.price)
        service.price = new_price

        category_id = data.get("category_id")
        if category_id == "" or category_id is None:
            service.category = None
        else:
            service.category = CategoriaServicio.objects.filter(
                pk=category_id,
                barbershop=barbershop,
                is_active=True,
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
                        pk=prod_id,
                        barbershop=barbershop,
                        is_active=True,
                    ).first()
                    if product:
                        ServicioProducto.objects.create(
                            servicio=service,
                            producto=product,
                            cantidad_consumida=int(cantidad),
                            incluido_en_precio=bool(p.get("incluido_en_precio", False)),
                        )

        return JsonResponse({"ok": True})


class ServicePriceHistoryAPI(LoginRequiredMixin, View):
    """Paginated price history for a service (30 per page)."""

    def get(self, request, pk):
        from django.core.paginator import Paginator

        barbershop = request.barbershop
        try:
            service = Service.objects.get(pk=pk, barbershop=barbershop, is_active=True)
        except Service.DoesNotExist:
            return JsonResponse({"error": "Servicio no encontrado"}, status=404)

        qs = HistorialPrecioServicio.objects.filter(service=service).select_related(
            "changed_by"
        )
        paginator = Paginator(qs, 30)
        page_num = request.GET.get("page", 1)
        page = paginator.get_page(page_num)

        items = []
        for h in page:
            who = ""
            if h.changed_by:
                who = (
                    " ".join(
                        filter(None, [h.changed_by.first_name, h.changed_by.last_name])
                    )
                    or "Sistema"
                )
            items.append(
                {
                    "price": str(h.price),
                    "changed_at": h.changed_at.isoformat(),
                    "changed_by": who or "Sistema",
                }
            )

        return JsonResponse(
            {
                "results": items,
                "page": page.number,
                "has_next": page.has_next(),
            }
        )


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
# Barber services API (for new appointment modal)
# ─────────────────────────────────────────────
class BarberServicesAPI(LoginRequiredMixin, View):
    """Returns services a specific barber can perform."""

    def get(self, request, barber_id):
        barbershop = request.barbershop

        barber = BarberProfile.objects.filter(
            Q(membership__barbershop=barbershop) | Q(sucursales=barbershop),
            pk=barber_id,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        barber_services = BarberService.objects.filter(
            barber=barber,
            service__is_active=True,
        ).select_related("service")

        data = [
            {
                "id": bs.service.pk,
                "name": bs.service.name,
                "duration": bs.effective_duration,
                "price": str(bs.effective_price),
                "global_duration": bs.service.duration_minutes,
                "global_price": str(bs.service.price),
                "custom_duration": bs.custom_duration,
                "custom_price": str(bs.custom_price)
                if bs.custom_price is not None
                else None,
            }
            for bs in barber_services
        ]
        return JsonResponse({"services": data})


class ServiceProductsAPI(LoginRequiredMixin, View):
    """Returns auto-consumed products for a given service (from ServicioProducto)."""

    def get(self, request, service_id):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        servicio_productos = ServicioProducto.objects.filter(
            servicio_id=service_id,
            producto__is_active=True,
        ).select_related("producto")

        data = [
            {
                "producto_id": sp.producto.pk,
                "nombre": sp.producto.name,
                "cantidad_consumida": sp.cantidad_consumida,
                "incluido_en_precio": sp.incluido_en_precio,
                "precio_unitario": str(sp.producto.price),
            }
            for sp in servicio_productos
        ]
        return JsonResponse({"productos": data})


# ─────────────────────────────────────────────
# Appointment product consumption
# ─────────────────────────────────────────────
class AppointmentProductsAPI(LoginRequiredMixin, View):
    """Add/replace products on an appointment's linked Intervencion."""

    def post(self, request, pk):
        barbershop = request.barbershop
        appointment = Appointment.objects.filter(
            pk=pk,
            barbershop=barbershop,
        ).first()
        if not appointment:
            return JsonResponse({"error": "Cita no encontrada"}, status=404)

        try:
            intervencion = appointment.intervencion
        except Intervencion.DoesNotExist:
            return JsonResponse({"error": "Sin intervención vinculada"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        productos = data.get("productos", [])

        with transaction.atomic():
            # Restore stock for existing products
            for ip in intervencion.productos_usados.select_related("producto").all():
                product = Product.objects.select_for_update().get(pk=ip.producto_id)
                StockMovement(
                    product=product,
                    quantity=ip.cantidad,
                    reason=StockMovement.Reason.ADJUSTMENT,
                    notes=f"Reversión Agenda Cita #{appointment.pk}",
                    resulting_stock=0,
                    updated_by=request.user,
                ).save()

            # Clear old products
            intervencion.productos_usados.all().delete()

            # Add new products
            for item in productos:
                prod_id = item.get("producto_id")
                cantidad = int(item.get("cantidad", 1))
                if not prod_id or cantidad <= 0:
                    continue
                product = (
                    Product.objects.select_for_update()
                    .filter(
                        pk=prod_id,
                        barbershop=barbershop,
                        is_active=True,
                    )
                    .first()
                )
                if not product:
                    continue
                IntervencionProducto.objects.create(
                    intervencion=intervencion,
                    producto=product,
                    cantidad=cantidad,
                    precio_unitario=product.price,
                )

            # Deduct stock for new products
            for ip in intervencion.productos_usados.select_related("producto").all():
                product = Product.objects.select_for_update().get(pk=ip.producto_id)
                StockMovement(
                    product=product,
                    quantity=-ip.cantidad,
                    reason=StockMovement.Reason.SALE,
                    notes=f"Agenda Cita #{appointment.pk}",
                    resulting_stock=0,
                    updated_by=request.user,
                ).save()

        return JsonResponse({"message": "Productos actualizados"})


# ─────────────────────────────────────────────
# Barber service customization
# ─────────────────────────────────────────────
class BarberServiceCustomizeAPI(LoginRequiredMixin, View):
    """Save custom price/duration for a barber-service config."""

    def post(self, request, barber_service_id):
        from decimal import Decimal

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        try:
            bs = BarberService.objects.select_related("service").get(
                pk=barber_service_id
            )
        except BarberService.DoesNotExist:
            return JsonResponse({"error": "Configuración no encontrada"}, status=404)

        changes = []

        # Custom price
        new_price_raw = data.get("custom_price")
        if new_price_raw == "" or new_price_raw is None:
            new_price = None
        else:
            new_price = Decimal(str(new_price_raw))

        if new_price != bs.custom_price:
            old_val = (
                str(bs.custom_price)
                if bs.custom_price is not None
                else "(heredado global)"
            )
            new_val = str(new_price) if new_price is not None else "(heredado global)"
            changes.append(("precio_personalizado", old_val, new_val))
            bs.custom_price = new_price

        # Custom duration
        new_dur_raw = data.get("custom_duration")
        if new_dur_raw == "" or new_dur_raw is None:
            new_dur = None
        else:
            new_dur = int(new_dur_raw)

        if new_dur != bs.custom_duration:
            old_val = (
                str(bs.custom_duration)
                if bs.custom_duration is not None
                else "(heredado global)"
            )
            new_val = str(new_dur) if new_dur is not None else "(heredado global)"
            changes.append(("duracion_personalizada", old_val, new_val))
            bs.custom_duration = new_dur

        bs.updated_by = request.user
        bs.save()

        # Record audit entries
        for campo, old_val, new_val in changes:
            HistorialCambiosConfiguracionBarbero.objects.create(
                barber_service=bs,
                campo=campo,
                valor_anterior=old_val,
                valor_nuevo=new_val,
                changed_by=request.user,
            )

        return JsonResponse(
            {
                "ok": True,
                "effective_price": str(bs.effective_price),
                "effective_duration": bs.effective_duration,
            }
        )


class BarberServiceHistoryAPI(LoginRequiredMixin, View):
    """Paginated history for a barber-service config (30 per page, infinite scroll)."""

    def get(self, request, barber_service_id):
        from django.core.paginator import Paginator

        try:
            bs = BarberService.objects.get(pk=barber_service_id)
        except BarberService.DoesNotExist:
            return JsonResponse({"error": "Configuración no encontrada"}, status=404)

        qs = HistorialCambiosConfiguracionBarbero.objects.filter(
            barber_service=bs,
        ).select_related("changed_by")

        paginator = Paginator(qs, 30)
        page_num = request.GET.get("page", 1)
        page = paginator.get_page(page_num)

        items = []
        for h in page:
            who = ""
            if h.changed_by:
                who = (
                    " ".join(
                        filter(None, [h.changed_by.first_name, h.changed_by.last_name])
                    )
                    or "Sistema"
                )
            items.append(
                {
                    "campo": h.campo,
                    "valor_anterior": h.valor_anterior,
                    "valor_nuevo": h.valor_nuevo,
                    "motivo": h.motivo,
                    "changed_by": who or "Sistema",
                    "created_at": h.created_at.isoformat(),
                }
            )

        return JsonResponse(
            {
                "results": items,
                "page": page.number,
                "has_next": page.has_next(),
            }
        )


# ─────────────────────────────────────────────
# Appointment reschedule (with RBAC, atomic, cascade, notifications)
# ─────────────────────────────────────────────
class AppointmentRescheduleAPI(LoginRequiredMixin, View):
    """
    Reschedule an appointment's date/time.

    RBAC: Only org admin or the originally-assigned barber can reschedule.
    Atomic: Updates Appointment + Intervencion in cascade.
    Notifications: Sends email+SMS to client; email+SMS to barber if
    the change was made by an admin (not the barber themselves).
    """

    def post(self, request, pk):
        membership = getattr(request.user, "membership", None)
        if not membership:
            return JsonResponse({"error": "Sin membresía activa"}, status=403)

        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería asignada"}, status=403)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        new_start_str = data.get("new_start_time")
        if not new_start_str:
            return JsonResponse({"error": "new_start_time es requerido"}, status=400)

        try:
            new_start = datetime.fromisoformat(new_start_str)
            if timezone.is_naive(new_start):
                new_start = timezone.make_aware(new_start)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Formato de fecha inválido"}, status=400)

        appointment = (
            Appointment.objects.filter(
                pk=pk,
                barbershop=barbershop,
            )
            .select_related("client", "barber__membership__user", "barbershop")
            .first()
        )
        if not appointment:
            return JsonResponse({"error": "Cita no encontrada"}, status=404)

        if appointment.status in (
            Appointment.Status.CANCELLED,
            Appointment.Status.NO_SHOW,
            Appointment.Status.COMPLETED,
        ):
            return JsonResponse(
                {
                    "error": "No se puede reprogramar una cita cancelada, completada o inasistencia"
                },
                status=409,
            )

        # RBAC: Only admin/owner or the assigned barber
        barber_profile = getattr(membership, "barber_profile", None)
        is_admin = membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
        is_assigned_barber = (
            barber_profile is not None and barber_profile.pk == appointment.barber_id
        )

        if not is_admin and not is_assigned_barber:
            return JsonResponse(
                {"error": "No tienes permisos para reprogramar esta cita"}, status=403
            )

        # Conflict check: verify new time slot is available
        target_date = new_start.date()
        service_ids = list(appointment.services.values_list("service_id", flat=True))
        barber_services = BarberService.objects.filter(
            barber=appointment.barber,
            service_id__in=service_ids,
        )
        total_duration = (
            sum(bs.effective_duration for bs in barber_services)
            if barber_services.exists()
            else 30
        )
        buffer_minutes = appointment.barber.buffer_minutes

        available_slots = svc.get_available_slots(
            appointment.barber, target_date, total_duration, barbershop=barbershop
        )

        new_end = new_start + timedelta(minutes=total_duration)
        slot_available = any(
            s["start"] <= new_start and s["end"] >= new_end for s in available_slots
        )

        if not slot_available:
            return JsonResponse(
                {"error": "El horario seleccionado no está disponible"}, status=409
            )

        old_start_time = appointment.start_time

        with transaction.atomic():
            # Update Appointment
            appointment.start_time = new_start
            appointment.end_time = new_end
            appointment.updated_by = request.user
            appointment.save(
                update_fields=["start_time", "end_time", "updated_by", "updated_at"]
            )

            # Cascade: Update linked Intervencion
            try:
                intervencion = appointment.intervencion
                intervencion.fecha = new_start
                intervencion.fecha_fin = new_end
                intervencion.updated_by = request.user
                intervencion.save(
                    update_fields=["fecha", "fecha_fin", "updated_by", "updated_at"]
                )
            except Intervencion.DoesNotExist:
                pass

        # Reschedule reminders: cancel old ones and schedule new
        try:
            from django_q.models import Schedule

            Schedule.objects.filter(
                name__startswith=f"reminder_24h_apt_{appointment.pk}"
            ).delete()
            Schedule.objects.filter(
                name__startswith=f"reminder_1h_apt_{appointment.pk}"
            ).delete()
            Schedule.objects.filter(
                name__startswith=f"barber_reminder_apt_{appointment.pk}"
            ).delete()
        except Exception:
            pass

        svc.schedule_appointment_reminders(appointment.pk)
        service_names = ", ".join(
            appointment.services.values_list("service__name", flat=True)
        )

        client_channels = ["email"]
        if appointment.client.phone:
            client_channels.append("sms")

        send_notification(
            recipient={
                "email": appointment.client.email,
                "phone": appointment.client.phone,
                "name": appointment.client.name,
            },
            notif_type="reschedule_client",
            context={
                "recipient_name": appointment.client.name,
                "barbershop_name": appointment.barbershop.name,
                "barber_name": str(appointment.barber),
                "service_names": service_names,
                "start_time": appointment.start_time,
                "new_start_time": new_start.strftime("%d/%m/%Y %H:%M"),
            },
            channels=client_channels,
            appointment_id=appointment.pk,
        )

        # Notify barber if the change was made by an admin (not the barber themselves)
        if is_admin and not is_assigned_barber:
            barber_channels = ["email"]
            barber_phone = getattr(appointment.barber, "phone", "") or ""
            if barber_phone:
                barber_channels.append("sms")

            send_notification(
                recipient={
                    "email": appointment.barber.user.email,
                    "phone": barber_phone,
                    "name": str(appointment.barber),
                },
                notif_type="reschedule_barber",
                context={
                    "recipient_name": str(appointment.barber),
                    "barbershop_name": appointment.barbershop.name,
                    "client_name": appointment.client.name,
                    "service_names": service_names,
                    "start_time": appointment.start_time,
                    "new_start_time": new_start.strftime("%d/%m/%Y %H:%M"),
                },
                channels=barber_channels,
                appointment_id=appointment.pk,
            )

        return JsonResponse(
            {
                "message": "Horario actualizado",
                "new_start_time": new_start.isoformat(),
                "new_end_time": new_end.isoformat(),
            }
        )


class AppointmentNotesAPI(LoginRequiredMixin, View):
    """Update appointment notes safely."""

    def post(self, request, pk):
        barbershop = request.barbershop
        appointment = Appointment.objects.filter(
            pk=pk,
            barbershop=barbershop,
        ).first()
        if not appointment:
            return JsonResponse({"error": "Cita no encontrada"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        notes = data.get("notes", "")
        appointment.notes = notes
        appointment.updated_by = request.user
        appointment.save(update_fields=["notes", "updated_by", "updated_at"])

        return JsonResponse(
            {"message": "Notas actualizadas", "notes": appointment.notes}
        )


class BarbersDataAPI(LoginRequiredMixin, View):
    def get(self, request):
        barbershop = request.barbershop
        membership = getattr(request.user, "membership", None)
        if not membership:
            return JsonResponse({"error": "Sin membresía activa"}, status=403)
        if not barbershop:
            return JsonResponse({"error": "Sin sucursal/barbería"}, status=403)

        # Barbers for filter dropdown
        barbers = (
            BarberProfile.objects.filter(
                Q(membership__barbershop=barbershop) | Q(sucursales=barbershop),
                is_active=True,
            )
            .select_related("membership__user")
            .distinct()
        )

        today = timezone.localdate()

        # Calculate max window of days ahead
        max_days = 15
        for b in barbers:
            max_days = max(max_days, getattr(b, "intervalo_apertura_dias", 15) or 15)
        max_date = today + timedelta(days=max_days + 1)

        # Work schedules grouping
        work_schedules_by_barber = {}
        for ws in WorkSchedule.objects.filter(barber__in=barbers):
            if ws.barber_id not in work_schedules_by_barber:
                work_schedules_by_barber[ws.barber_id] = []
            work_schedules_by_barber[ws.barber_id].append(
                {
                    "day_of_week": ws.day_of_week,
                    "start": ws.start_time.strftime("%H:%M"),
                    "end": ws.end_time.strftime("%H:%M"),
                }
            )

        # Exceptions grouping within date range
        exceptions_by_barber = {}
        for exc in ScheduleException.objects.filter(
            barber__in=barbers, start__date__gte=today, start__date__lte=max_date
        ):
            if exc.barber_id not in exceptions_by_barber:
                exceptions_by_barber[exc.barber_id] = []
            exceptions_by_barber[exc.barber_id].append(
                {"start": exc.start.isoformat(), "end": exc.end.isoformat()}
            )

        # Active appointments grouping within date range
        active_statuses = [
            Appointment.Status.PENDING,
            Appointment.Status.CONFIRMED,
            Appointment.Status.IN_PROGRESS,
        ]
        appointments_by_barber = {}
        for apt in Appointment.objects.filter(
            barber__in=barbers,
            start_time__date__gte=today,
            start_time__date__lte=max_date,
            status__in=active_statuses,
        ):
            if apt.barber_id not in appointments_by_barber:
                appointments_by_barber[apt.barber_id] = []
            appointments_by_barber[apt.barber_id].append(
                {
                    "id": apt.pk,
                    "start": apt.start_time.isoformat(),
                    "end": apt.end_time.isoformat(),
                }
            )

        barbers_data = []
        for b in barbers:
            days_ahead = getattr(b, "intervalo_apertura_dias", 15) or 15
            barbers_data.append(
                {
                    "id": b.pk,
                    "name": str(b),
                    "intervalo_apertura_dias": days_ahead,
                    "buffer_minutes": b.buffer_minutes,
                    "lunch_start": b.lunch_start.strftime("%H:%M")
                    if b.lunch_start
                    else None,
                    "lunch_end": b.lunch_end.strftime("%H:%M") if b.lunch_end else None,
                    "work_schedules": work_schedules_by_barber.get(b.pk, []),
                    "exceptions": exceptions_by_barber.get(b.pk, []),
                    "appointments": appointments_by_barber.get(b.pk, []),
                }
            )
        return JsonResponse(barbers_data, safe=False)


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
