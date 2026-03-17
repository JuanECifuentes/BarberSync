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
from datetime import datetime, date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.accounts.models import BarberProfile
from apps.core.mixins import RoleRequiredMixin, TenantViewMixin

from . import services as svc
from .models import Appointment, BarberService, Service, WorkSchedule


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
class ServiceListView(TenantViewMixin, ListView):
    model = Service
    template_name = "scheduling/services.html"
    context_object_name = "services"
    paginate_by = 20

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


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
