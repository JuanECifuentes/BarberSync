"""
Views for the Barberos module.
CRUD for barbers with modal-based editing, schedule management, and soft delete.
"""

import json
from datetime import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from apps.core.mixins import RoleRequiredMixin
from apps.scheduling.models import (
    BarberService,
    ScheduleException,
    Service,
    WorkSchedule,
)
from .models import BarberProfile, Barbershop, Membership, User


class BarberoListView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "barberos/barbero_list.html"
    allowed_roles = ["owner", "admin"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        barbershop = self.request.barbershop

        barberos = BarberProfile.objects.filter(
            membership__organization=org,
            is_active=True,
        ).select_related(
            "membership__user", "membership__barbershop"
        ).prefetch_related("sucursales", "barber_services__service")

        if barbershop:
            barberos = barberos.filter(
                sucursales=barbershop
            ) | barberos.filter(membership__barbershop=barbershop)
            barberos = barberos.distinct()

        ctx["barberos"] = barberos
        ctx["barberos_inactivos"] = BarberProfile.objects.filter(
            membership__organization=org,
            is_active=False,
        ).select_related("membership__user")
        ctx["sucursales"] = Barbershop.objects.filter(organization=org, is_active=True)
        ctx["servicios"] = Service.objects.filter(
            barbershop=barbershop, is_active=True
        ) if barbershop else Service.objects.none()
        return ctx


class BarberoDetailAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

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
            BarberService.objects.filter(barber=barber).values_list("service_id", flat=True)
        )
        servicio_names = list(
            BarberService.objects.filter(barber=barber).values_list("service__name", flat=True)
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
            ScheduleException.objects.filter(barber=barber).order_by("-start").values(
                "id", "exception_type", "description", "start", "end", "is_recurring"
            )
        )
        for e in exceptions:
            e["start"] = e["start"].isoformat()
            e["end"] = e["end"].isoformat()

        return JsonResponse({
            "id": barber.pk,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": barber.display_name,
            "phone": barber.phone,
            "bio": barber.bio,
            "instagram": barber.instagram,
            "buffer_minutes": barber.buffer_minutes,
            "lunch_start": barber.lunch_start.strftime("%H:%M") if barber.lunch_start else "",
            "lunch_end": barber.lunch_end.strftime("%H:%M") if barber.lunch_end else "",
            "is_active": barber.is_active,
            "sucursal_ids": sucursal_ids,
            "sucursal_names": sucursal_names,
            "servicio_ids": servicio_ids,
            "servicio_names": servicio_names,
            "schedules": schedules,
            "exceptions": exceptions,
        })


class BarberoCreateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request):
        org = request.organization
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        email = data.get("email", "").strip().lower()
        first_name = data.get("first_name", "").strip()
        last_name = data.get("last_name", "").strip()
        if not email or not first_name:
            return JsonResponse({"error": "Email y nombre son requeridos"}, status=400)

        # Get or create user
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": first_name,
                "last_name": last_name,
            },
        )
        if created:
            user.set_unusable_password()
            user.save()
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=["first_name", "last_name"])

        # Create membership
        membership, _ = Membership.objects.get_or_create(
            user=user,
            organization=org,
            barbershop=barbershop,
            defaults={"role": Membership.Role.BARBER, "is_active": True},
        )

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
                    service = Service.objects.get(pk=sid, barbershop=barbershop, is_active=True)
                    BarberService.objects.get_or_create(barber=barber, service=service)
                except Service.DoesNotExist:
                    pass

        return JsonResponse({"ok": True, "id": barber.pk})


class BarberoUpdateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        barbershop = request.barbershop
        try:
            barber = BarberProfile.objects.select_related("membership__user").get(
                pk=pk, membership__organization=org
            )
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        # Update user info
        user = barber.user
        if data.get("first_name"):
            user.first_name = data["first_name"].strip()
        if data.get("last_name") is not None:
            user.last_name = data["last_name"].strip()
        user.save(update_fields=["first_name", "last_name"])

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
                BarberService.objects.filter(barber=barber).values_list("service_id", flat=True)
            )
            new_ids = set(data["servicio_ids"])

            # Remove old
            BarberService.objects.filter(barber=barber).exclude(service_id__in=new_ids).delete()
            # Add new
            for sid in new_ids - current_ids:
                try:
                    service = Service.objects.get(pk=sid, is_active=True)
                    BarberService.objects.get_or_create(barber=barber, service=service)
                except Service.DoesNotExist:
                    pass

        return JsonResponse({"ok": True})


class BarberoDeactivateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    """Soft delete: sets is_active=False."""
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org, is_active=True)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        barber.is_active = False
        barber.save(update_fields=["is_active"])
        return JsonResponse({"ok": True})


class BarberoReactivateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org, is_active=False)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        barber.is_active = True
        barber.save(update_fields=["is_active"])
        return JsonResponse({"ok": True})


# ─── Horarios ───────────────────────────────────────

class HorarioSaveAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    """Save/replace the full weekly schedule for a barber, including lunch and buffer."""
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

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
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

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
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk, exc_pk):
        org = request.organization
        try:
            barber = BarberProfile.objects.get(pk=pk, membership__organization=org)
        except BarberProfile.DoesNotExist:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        deleted, _ = ScheduleException.objects.filter(pk=exc_pk, barber=barber).delete()
        if not deleted:
            return JsonResponse({"error": "Excepción no encontrada"}, status=404)
        return JsonResponse({"ok": True})
