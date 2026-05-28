"""
Views for the Barberos module.
CRUD for barbers with modal-based editing, schedule management, and soft delete.
"""

import json
from collections import OrderedDict
from datetime import time
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from django.utils import timezone

from apps.core.mixins import RoleRequiredMixin
from apps.scheduling.models import (
    Appointment,
    ComisionProductoBarbero,
    ComisionServicioBarbero,
    HistorialComisionesBarbero,
    Intervencion,
    BarberService,
    CategoriaServicio,
    HistorialCambiosConfiguracionBarbero,
    ScheduleException,
    Service,
    WorkSchedule,
)
from apps.inventory.models import Product, ProductCategory
from .models import BarberProfile, Barbershop, Membership, User


class BarberoListView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "barberos/barbero_list.html"
    allowed_roles = ["owner", "admin", "staff", "barber"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        barbershop = self.request.barbershop

        barberos = (
            BarberProfile.objects.filter(
                membership__organization=org,
                is_active=True,
                membership__is_active=True,
            )
            .select_related("membership__user", "membership__barbershop")
            .prefetch_related("sucursales", "barber_services__service")
        )

        print("barberos", barberos.values())

        if barbershop:
            print("barbershop", barbershop)
            barberos = barberos.filter(sucursales=barbershop) | barberos.filter(
                membership__barbershop=barbershop
            )
            barberos = barberos.distinct()

        ctx["barberos"] = barberos
        ctx["barberos_inactivos"] = BarberProfile.objects.filter(
            membership__organization=org,
            is_active=False,
        ).select_related("membership__user")

        ctx["miembros_disponibles"] = (
            Membership.objects.filter(organization=org, is_active=True)
            .exclude(user_id__in=barberos.values_list("membership__user_id", flat=True))
            .exclude(barber_profile__is_active=False)
            .select_related("user")
        )

        print("miembros_disponibles", ctx["miembros_disponibles"].values())

        ctx["sucursales"] = Barbershop.objects.filter(organization=org, is_active=True)
        # Services grouped by category for accordion display
        servicios_qs = (
            Service.objects.filter(barbershop=barbershop, is_active=True)
            .select_related("category")
            .order_by("category__name", "name")
            if barbershop
            else Service.objects.none()
        )
        grouped_servicios = OrderedDict()
        for svc_obj in servicios_qs:
            cat_name = svc_obj.category.name if svc_obj.category else "Sin Categoría"
            cat_id = svc_obj.category.pk if svc_obj.category else 0
            if cat_name not in grouped_servicios:
                grouped_servicios[cat_name] = {"category_id": cat_id, "services": []}
            grouped_servicios[cat_name]["services"].append(svc_obj)
        ctx["grouped_servicios"] = grouped_servicios
        ctx["servicios"] = servicios_qs

        productos_qs = (
            Product.objects.filter(barbershop=barbershop, is_active=True)
            .select_related("category")
            .order_by("category__name", "name")
            if barbershop
            else Product.objects.none()
        )
        grouped_productos = OrderedDict()
        for prod in productos_qs:
            cat_name = prod.category.name if prod.category else "Sin Categoría"
            cat_id = prod.category.pk if prod.category else 0
            if cat_name not in grouped_productos:
                grouped_productos[cat_name] = {"category_id": cat_id, "products": []}
            grouped_productos[cat_name]["products"].append(prod)
        ctx["grouped_productos"] = grouped_productos
        ctx["productos"] = productos_qs
        ctx["por_defecto_servicio"] = COMISION_POR_DEFECTO_SERVICIO
        ctx["por_defecto_producto"] = COMISION_POR_DEFECTO_PRODUCTO
        return ctx


class BarberoDetailAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin", "staff", "barber"]

    def get(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.select_related(
                "membership__user", "membership__barbershop"
            ).get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        user = barber.user
        sucursal_ids = list(barber.sucursales.values_list("id", flat=True))
        sucursal_names = list(barber.sucursales.values_list("name", flat=True))
        servicio_ids = list(
            BarberService.objects.filter(barber=barber).values_list(
                "service_id", flat=True
            )
        )
        servicio_names = list(
            BarberService.objects.filter(barber=barber).values_list(
                "service__name", flat=True
            )
        )

        # Barber service configs (for customization UI)
        barber_service_configs = []
        for bs in BarberService.objects.filter(barber=barber).select_related(
            "service", "service__category"
        ):
            barber_service_configs.append(
                {
                    "barber_service_id": bs.pk,
                    "service_id": bs.service_id,
                    "service_name": bs.service.name,
                    "category_name": bs.service.category.name
                    if bs.service.category
                    else "Sin Categoría",
                    "category_id": bs.service.category_id
                    if bs.service.category
                    else None,
                    "global_price": str(bs.service.price),
                    "global_duration": bs.service.duration_minutes,
                    "custom_price": str(bs.custom_price)
                    if bs.custom_price is not None
                    else None,
                    "custom_duration": bs.custom_duration,
                    "effective_price": str(bs.effective_price),
                    "effective_duration": bs.effective_duration,
                }
            )

        schedules = list(
            WorkSchedule.objects.filter(barber=barber).values(
                "id", "day_of_week", "start_time", "end_time"
            )
        )
        for s in schedules:
            s["start_time"] = s["start_time"].strftime("%H:%M")
            s["end_time"] = s["end_time"].strftime("%H:%M")

        exceptions = list(
            ScheduleException.objects.filter(barber=barber)
            .order_by("-start")
            .values(
                "id", "exception_type", "description", "start", "end", "is_recurring"
            )
        )
        for e in exceptions:
            e["start"] = e["start"].isoformat()
            e["end"] = e["end"].isoformat()

        return JsonResponse(
            {
                "id": barber.pk,
                "user_id": user.pk,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": barber.display_name,
                "phone": barber.phone,
                "bio": barber.bio,
                "instagram": barber.instagram,
                "buffer_minutes": barber.buffer_minutes,
                "lunch_start": barber.lunch_start.strftime("%H:%M")
                if barber.lunch_start
                else "",
                "lunch_end": barber.lunch_end.strftime("%H:%M")
                if barber.lunch_end
                else "",
                "is_active": barber.is_active,
                "sucursal_ids": sucursal_ids,
                "sucursal_names": sucursal_names,
                "servicio_ids": servicio_ids,
                "servicio_names": servicio_names,
                "barber_service_configs": barber_service_configs,
                "schedules": schedules,
                "exceptions": exceptions,
            }
        )


class BarberoCreateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request):
        org = request.organization
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        user_id = data.get("user_id")
        if not user_id:
            return JsonResponse(
                {"error": "Debe seleccionar un usuario válido"}, status=400
            )

        # Get the selected membership/user
        try:
            membership = Membership.objects.get(
                user_id=user_id, organization=org, is_active=True
            )
        except Membership.DoesNotExist:
            return JsonResponse(
                {"error": "El usuario seleccionado no es miembro de la organización"},
                status=400,
            )

        # Update role to Barber if not already (or keep their higher role like owner/admin but they now act as barber too)
        if membership.role not in [Membership.Role.OWNER, Membership.Role.ADMIN]:
            membership.role = Membership.Role.BARBER
            membership.save(update_fields=["role"])

        # Create barber profile
        barber, bp_created = BarberProfile.objects.get_or_create(
            membership=membership,
            defaults={
                "display_name": data.get("display_name", ""),
                "phone": data.get("phone", ""),
                "bio": data.get("bio", ""),
                "instagram": data.get("instagram", ""),
                "is_active": True,
            },
        )

        # Assign to sucursales
        sucursal_ids = data.get("sucursal_ids", [])
        if sucursal_ids:
            sucursales = Barbershop.objects.filter(
                pk__in=sucursal_ids, organization=org, is_active=True
            )
            barber.sucursales.set(sucursales)
        elif barbershop:
            barber.sucursales.add(barbershop)

        # Assign services
        servicio_ids = data.get("servicio_ids", [])
        if servicio_ids:
            for sid in servicio_ids:
                try:
                    service = Service.objects.get(
                        pk=sid, barbershop=barbershop, is_active=True
                    )
                    BarberService.objects.get_or_create(barber=barber, service=service)
                except Service.DoesNotExist:
                    pass

        # Apply customizations (price/duration per service)
        customizations = data.get("customizations", {})
        if customizations:
            _apply_customizations(barber, customizations, request.user)

        return JsonResponse({"ok": True, "id": barber.pk})


class BarberoUpdateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin", "staff", "barber"]

    def post(self, request, pk):
        org = request.organization
        barbershop = request.barbershop
        try:
            barber = BarberProfile.objects.select_related("membership__user").get(
                pk=pk, membership__organization=org
            )
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        if request.user.membership.role == "barber" and barber.user != request.user:
            return JsonResponse(
                {"error": "No tienes permiso para editar este barbero"}, status=403
            )

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        with transaction.atomic():
            # Update user info (first_name and last_name are no longer updated from this modal)
            user = barber.user

            # Update barber profile
            barber.display_name = data.get("display_name", barber.display_name)
            barber.phone = data.get("phone", barber.phone)
            barber.bio = data.get("bio", barber.bio)
            barber.instagram = data.get("instagram", barber.instagram)

            barber.save()

            # Update sucursales
            if "sucursal_ids" in data:
                sucursales = Barbershop.objects.filter(
                    pk__in=data["sucursal_ids"], organization=org, is_active=True
                )
                barber.sucursales.set(sucursales)

            # Update services
            if "servicio_ids" in data:
                current_ids = set(
                    BarberService.objects.filter(barber=barber).values_list(
                        "service_id", flat=True
                    )
                )
                new_ids = set(data["servicio_ids"])

                # Remove old
                BarberService.objects.filter(barber=barber).exclude(
                    service_id__in=new_ids
                ).delete()
                # Add new
                for sid in new_ids - current_ids:
                    try:
                        service = Service.objects.get(pk=sid, is_active=True)
                        BarberService.objects.get_or_create(
                            barber=barber, service=service
                        )
                    except Service.DoesNotExist:
                        pass

            # Apply customizations (price/duration per service)
            customizations = data.get("customizations", {})
            if customizations:
                _apply_customizations(barber, customizations, request.user)

        return JsonResponse({"ok": True})


def _get_available_barbers_data(org):
    barbers = BarberProfile.objects.filter(
        membership__organization=org, is_active=True
    ).select_related("membership__user")
    data = []
    now = timezone.now()
    for b in barbers:
        schedules = list(
            WorkSchedule.objects.filter(barber=b).values(
                "day_of_week", "start_time", "end_time"
            )
        )
        for s in schedules:
            s["start_time"] = s["start_time"].strftime("%H:%M")
            s["end_time"] = s["end_time"].strftime("%H:%M")

        exceptions = list(
            ScheduleException.objects.filter(barber=b, end__gte=now).values(
                "start", "end", "is_recurring"
            )
        )
        for e in exceptions:
            e["start"] = e["start"].isoformat()
            e["end"] = e["end"].isoformat()

        future_appointments = list(
            Appointment.objects.filter(barber=b, start_time__gte=now)
            .exclude(status__in=["cancelled", "no_show"])
            .values("start_time", "end_time")
        )
        for app in future_appointments:
            app["start_time"] = app["start_time"].isoformat()
            app["end_time"] = app["end_time"].isoformat()

        data.append(
            {
                "id": b.id,
                "name": b.display_name
                or (
                    f"{b.user.first_name} {b.user.last_name}".strip()
                    if b.user.first_name
                    else b.user.email
                ),
                "schedules": schedules,
                "exceptions": exceptions,
                "future_appointments": future_appointments,
            }
        )
    return data


class BarberoDeactivateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    """Soft delete with future appointments bulk reassignment check."""

    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(
                pk=pk, membership__organization=org, is_active=True
            )
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = {}

        now = timezone.now()
        future_appointments_qs = (
            Appointment.objects.filter(barber=barber, start_time__gte=now)
            .exclude(status__in=["cancelled", "no_show"])
            .order_by("start_time")
        )

        if "reassignments" not in data:
            if future_appointments_qs.exists():
                appointments_data = []
                for app in future_appointments_qs:
                    services_str = ", ".join(
                        [s.service.name for s in app.services.all()]
                    )
                    appointments_data.append(
                        {
                            "id": app.pk,
                            "date": app.start_time.strftime("%d/%m/%Y"),
                            "time": app.start_time.strftime("%I:%M %p"),
                            "start_time_iso": app.start_time.isoformat(),
                            "client_name": app.client.name.strip(),
                            "services": services_str,
                            "total_duration": app.total_duration,
                        }
                    )

                return JsonResponse(
                    {
                        "requires_reassignment": True,
                        "appointments": appointments_data,
                        "available_barbers": _get_available_barbers_data(org),
                    }
                )

            # No future appointments, safe to deactivate directly
            barber.is_active = False
            barber.save(update_fields=["is_active"])
            return JsonResponse({"ok": True})

        # Process reassignments
        reassignments = data.get("reassignments", [])
        reassign_map = {int(r["cita_id"]): r for r in reassignments}

        with transaction.atomic():
            for app in future_appointments_qs:
                action_data = reassign_map.get(app.pk)
                if not action_data:
                    return JsonResponse(
                        {"error": f"Falta resolver la cita #{app.pk}"}, status=400
                    )

                action = action_data.get("accion")
                if action == "cancelar":
                    app.status = "cancelled"
                    app.cancelled_reason = (
                        "Cancelada por el sistema debido a desactivación del barbero"
                    )
                    app.save(update_fields=["status", "cancelled_reason"])
                    Intervencion.objects.filter(appointment=app).update(
                        estado="cancelada"
                    )
                elif action == "reasignar":
                    new_barber_id = action_data.get("nuevo_barbero_id")
                    if not new_barber_id:
                        raise ValueError(
                            f"Falta ID del nuevo barbero para la cita #{app.pk}"
                        )
                    new_barber = BarberProfile.objects.get(
                        pk=new_barber_id, is_active=True, membership__organization=org
                    )
                    app.barber = new_barber
                    app.save(update_fields=["barber"])
                    Intervencion.objects.filter(appointment=app).update(
                        barber=new_barber
                    )
                else:
                    raise ValueError(f"Acción inválida para cita #{app.pk}: {action}")

            # Finally, deactivate the barber
            barber.is_active = False
            barber.save(update_fields=["is_active"])

        return JsonResponse({"ok": True})


class BarberoReactivateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(
                pk=pk, membership__organization=org, is_active=False
            )
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        barber.is_active = True
        barber.save(update_fields=["is_active"])
        return JsonResponse({"ok": True})


# ─── Customization helper ──────────────────────────────


def _apply_customizations(barber, customizations, user):
    """
    Apply custom price/duration to barber-service configs.
    customizations: dict keyed by service_id (as string from JSON)
    with values: { custom_price: str|null, custom_duration: int|null }
    """
    for svc_id_str, cust in customizations.items():
        svc_id = int(svc_id_str)
        try:
            bs = BarberService.objects.get(barber=barber, service_id=svc_id)
        except BarberService.DoesNotExist:
            continue

        changes = []

        # Custom price
        raw_price = cust.get("custom_price")
        new_price = Decimal(str(raw_price)) if raw_price else None
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
        raw_dur = cust.get("custom_duration")
        new_dur = int(raw_dur) if raw_dur else None
        if new_dur != bs.custom_duration:
            old_val = (
                str(bs.custom_duration)
                if bs.custom_duration is not None
                else "(heredado global)"
            )
            new_val = str(new_dur) if new_dur is not None else "(heredado global)"
            changes.append(("duracion_personalizada", old_val, new_val))
            bs.custom_duration = new_dur

        if changes:
            bs.updated_by = user
            bs.save()
            for campo, old_val, new_val in changes:
                HistorialCambiosConfiguracionBarbero.objects.create(
                    barber_service=bs,
                    campo=campo,
                    valor_anterior=old_val,
                    valor_nuevo=new_val,
                    changed_by=user,
                )


# ─── Horarios ───────────────────────────────────────


class HorarioSaveAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    """Save/replace the full weekly schedule for a barber, including lunch and buffer."""

    allowed_roles = ["owner", "admin", "staff", "barber"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        if request.user.membership.role == "barber" and barber.user != request.user:
            return JsonResponse(
                {"error": "No tienes permiso para editar este horario"}, status=403
            )

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        # Save lunch and buffer settings
        barber.buffer_minutes = int(data.get("buffer_minutes", barber.buffer_minutes))
        lunch_start = data.get("lunch_start", "")
        lunch_end = data.get("lunch_end", "")
        if lunch_start:
            h, m = map(int, lunch_start.split(":"))
            barber.lunch_start = time(h, m)
        else:
            barber.lunch_start = None
        if lunch_end:
            h, m = map(int, lunch_end.split(":"))
            barber.lunch_end = time(h, m)
        else:
            barber.lunch_end = None
        barber.save(update_fields=["buffer_minutes", "lunch_start", "lunch_end"])

        schedules = data.get("schedules", [])

        # Replace all schedules
        WorkSchedule.objects.filter(barber=barber).delete()
        for s in schedules:
            try:
                sh, sm = map(int, s["start_time"].split(":"))
                eh, em = map(int, s["end_time"].split(":"))
                WorkSchedule.objects.create(
                    barber=barber,
                    day_of_week=int(s["day_of_week"]),
                    start_time=time(sh, sm),
                    end_time=time(eh, em),
                )
            except (ValueError, KeyError):
                continue

        return JsonResponse({"ok": True})


class ExcepcionCreateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin", "staff", "barber"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        if request.user.membership.role == "barber" and barber.user != request.user:
            return JsonResponse(
                {"error": "No tienes permiso para agregar excepciones"}, status=403
            )

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        exception_type = data.get("exception_type", "personal")
        start = data.get("start")
        end = data.get("end")
        if not start or not end:
            return JsonResponse({"error": "Inicio y fin son requeridos"}, status=400)

        from django.utils.dateparse import parse_datetime

        start_dt = parse_datetime(start)
        end_dt = parse_datetime(end)
        if not start_dt or not end_dt:
            return JsonResponse({"error": "Formato de fecha inválido"}, status=400)

        exc = ScheduleException.objects.create(
            barber=barber,
            exception_type=exception_type,
            description=data.get("description", ""),
            start=start_dt,
            end=end_dt,
            is_recurring=data.get("is_recurring", False),
        )
        return JsonResponse({"ok": True, "id": exc.pk})


class ExcepcionDeleteAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin", "staff", "barber"]

    def post(self, request, pk, exc_pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        if request.user.membership.role == "barber" and barber.user != request.user:
            return JsonResponse(
                {"error": "No tienes permiso para eliminar esta excepción"}, status=403
            )

        deleted, _ = ScheduleException.objects.filter(pk=exc_pk, barber=barber).delete()
        if not deleted:
            return JsonResponse({"error": "Excepción no encontrada"}, status=404)
        return JsonResponse({"ok": True})


# ─── Comisiones ───────────────────────────────────────

COMISION_POR_DEFECTO_SERVICIO = 50
COMISION_POR_DEFECTO_PRODUCTO = 0
COMISION_PAGINACION = 30


class ComisionesDataAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin", "staff", "barber"]

    def get(self, request, pk):
        org = request.organization
        barbershop = request.barbershop
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        servicios = (
            Service.objects.filter(
                barbershop=barbershop, is_active=True
            ).select_related("category")
            if barbershop
            else Service.objects.none()
        )

        comisiones_servicios = ComisionServicioBarbero.objects.filter(
            barber=barber, servicio__in=servicios
        )
        com_serv_map = {cs.servicio_id: cs.porcentaje for cs in comisiones_servicios}

        servicios_data = []
        for svc in servicios:
            porcentaje = com_serv_map.get(svc.id, COMISION_POR_DEFECTO_SERVICIO)
            precio_base = float(svc.price)
            monto_barbero = round(precio_base * porcentaje / 100, 2)
            monto_barberia = round(precio_base - monto_barbero, 2)
            servicios_data.append(
                {
                    "id": svc.id,
                    "nombre": svc.name,
                    "precio_base": str(svc.price),
                    "categoria": svc.category.name if svc.category else "Sin Categoría",
                    "categoria_id": svc.category_id if svc.category else 0,
                    "porcentaje": porcentaje,
                    "monto_barbero": monto_barbero,
                    "monto_barberia": monto_barberia,
                }
            )

        productos = (
            Product.objects.filter(
                barbershop=barbershop, is_active=True
            ).select_related("category")
            if barbershop
            else Product.objects.none()
        )

        comisiones_productos = ComisionProductoBarbero.objects.filter(
            barber=barber, producto__in=productos
        )
        com_prod_map = {cp.producto_id: cp.porcentaje for cp in comisiones_productos}

        productos_data = []
        for prod in productos:
            porcentaje = com_prod_map.get(prod.id, COMISION_POR_DEFECTO_PRODUCTO)
            precio_base = float(prod.price)
            monto_barbero = round(precio_base * porcentaje / 100, 2)
            monto_barberia = round(precio_base - monto_barbero, 2)
            productos_data.append(
                {
                    "id": prod.id,
                    "nombre": prod.name,
                    "precio_base": str(prod.price),
                    "categoria": prod.category.name
                    if prod.category
                    else "Sin Categoría",
                    "categoria_id": prod.category_id if prod.category else 0,
                    "porcentaje": porcentaje,
                    "monto_barbero": monto_barbero,
                    "monto_barberia": monto_barberia,
                }
            )

        return JsonResponse(
            {
                "barber_id": barber.pk,
                "barber_nombre": barber.display_name or str(barber.user),
                "servicios": servicios_data,
                "productos": productos_data,
                "por_defecto_servicio": COMISION_POR_DEFECTO_SERVICIO,
                "por_defecto_producto": COMISION_POR_DEFECTO_PRODUCTO,
            }
        )


class ComisionesSaveAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        barbershop = request.barbershop
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        cambios_servicios = data.get("servicios", [])
        cambios_productos = data.get("productos", [])

        with transaction.atomic():
            for cambio in cambios_servicios:
                svc_id = cambio.get("id")
                porcentaje = cambio.get("porcentaje")
                if svc_id is None or porcentaje is None:
                    continue
                porcentaje = int(porcentaje)
                if porcentaje < 0 or porcentaje > 100:
                    continue
                try:
                    servicio = Service.objects.get(
                        pk=svc_id, barbershop=barbershop, is_active=True
                    )
                except Service.DoesNotExist:
                    continue

                comision, created = ComisionServicioBarbero.objects.get_or_create(
                    barber=barber,
                    servicio=servicio,
                    defaults={"porcentaje": porcentaje, "barbershop": barbershop},
                )
                if not created:
                    valor_anterior = comision.porcentaje
                    if valor_anterior != porcentaje:
                        HistorialComisionesBarbero.objects.create(
                            barber=barber,
                            tipo=HistorialComisionesBarbero.TipoItem.SERVICIO,
                            item_id=servicio.id,
                            item_nombre=servicio.name,
                            valor_anterior=valor_anterior,
                            valor_nuevo=porcentaje,
                            changed_by=request.user,
                        )
                        comision.porcentaje = porcentaje
                        comision.save(update_fields=["porcentaje"])
                else:
                    valor_por_defecto = COMISION_POR_DEFECTO_SERVICIO
                    if porcentaje != valor_por_defecto:
                        HistorialComisionesBarbero.objects.create(
                            barber=barber,
                            tipo=HistorialComisionesBarbero.TipoItem.SERVICIO,
                            item_id=servicio.id,
                            item_nombre=servicio.name,
                            valor_anterior=valor_por_defecto,
                            valor_nuevo=porcentaje,
                            changed_by=request.user,
                        )

            for cambio in cambios_productos:
                prod_id = cambio.get("id")
                porcentaje = cambio.get("porcentaje")
                if prod_id is None or porcentaje is None:
                    continue
                porcentaje = int(porcentaje)
                if porcentaje < 0 or porcentaje > 100:
                    continue
                try:
                    producto = Product.objects.get(
                        pk=prod_id, barbershop=barbershop, is_active=True
                    )
                except Product.DoesNotExist:
                    continue

                comision, created = ComisionProductoBarbero.objects.get_or_create(
                    barber=barber,
                    producto=producto,
                    defaults={"porcentaje": porcentaje, "barbershop": barbershop},
                )
                if not created:
                    valor_anterior = comision.porcentaje
                    if valor_anterior != porcentaje:
                        HistorialComisionesBarbero.objects.create(
                            barber=barber,
                            tipo=HistorialComisionesBarbero.TipoItem.PRODUCTO,
                            item_id=producto.id,
                            item_nombre=producto.name,
                            valor_anterior=valor_anterior,
                            valor_nuevo=porcentaje,
                            changed_by=request.user,
                        )
                        comision.porcentaje = porcentaje
                        comision.save(update_fields=["porcentaje"])
                else:
                    valor_por_defecto = COMISION_POR_DEFECTO_PRODUCTO
                    if porcentaje != valor_por_defecto:
                        HistorialComisionesBarbero.objects.create(
                            barber=barber,
                            tipo=HistorialComisionesBarbero.TipoItem.PRODUCTO,
                            item_id=producto.id,
                            item_nombre=producto.name,
                            valor_anterior=valor_por_defecto,
                            valor_nuevo=porcentaje,
                            changed_by=request.user,
                        )

        return JsonResponse({"ok": True})


class HistorialComisionesAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin", "staff"]

    def get(self, request):
        org = request.organization
        barbershop = request.barbershop
        page = int(request.GET.get("page", 1))

        barber_id = request.GET.get("barber_id")
        qs = HistorialComisionesBarbero.objects.filter(
            barber__membership__organization=org
        ).select_related("barber", "barber__membership__user")

        if barber_id:
            qs = qs.filter(barber_id=barber_id)

        if barbershop:
            comisiones_svc = ComisionServicioBarbero.objects.filter(
                barbershop=barbershop
            ).values_list("servicio_id", flat=True)
            comisiones_prod = ComisionProductoBarbero.objects.filter(
                barbershop=barbershop
            ).values_list("producto_id", flat=True)

        total = qs.count()
        start = (page - 1) * COMISION_PAGINACION
        end = start + COMISION_PAGINACION
        registros = qs[start:end]

        results = []
        for r in registros:
            barber_name = r.barber.display_name or str(r.barber.user)
            results.append(
                {
                    "id": r.pk,
                    "barber_nombre": barber_name,
                    "tipo": r.tipo,
                    "tipo_display": r.get_tipo_display(),
                    "item_nombre": r.item_nombre,
                    "item_id": r.item_id,
                    "valor_anterior": r.valor_anterior,
                    "valor_nuevo": r.valor_nuevo,
                    "changed_by": str(r.changed_by) if r.changed_by else "Sistema",
                    "created_at": r.created_at.isoformat(),
                }
            )

        has_next = end < total

        return JsonResponse(
            {
                "results": results,
                "total": total,
                "page": page,
                "has_next": has_next,
            }
        )
