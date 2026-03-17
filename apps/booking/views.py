"""
Public booking views – client-facing.

Each barbershop has a unique booking URL: /book/<uuid>/
Clients authenticate via Google (allauth) to reserve.
"""

import json
from datetime import datetime

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import BarberProfile, Barbershop
from apps.clients.models import Client
from apps.scheduling import services as svc
from apps.scheduling.models import BarberService, Service


class BookingPageView(TemplateView):
    """
    Public booking page for a barbershop.
    URL: /book/<uuid:booking_uid>/
    """

    template_name = "booking/public_booking.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        uid = self.kwargs["booking_uid"]
        barbershop = get_object_or_404(Barbershop, booking_uid=uid, is_active=True)

        barbers = BarberProfile.objects.filter(
            membership__barbershop=barbershop,
            is_active=True,
        ).select_related("membership__user")

        services = Service.objects.filter(barbershop=barbershop, is_active=True)

        ctx["barbershop"] = barbershop
        ctx["barbers"] = barbers
        ctx["services"] = services
        return ctx


class BookingBarbersAPI(View):
    """Returns barbers + their services for a barbershop."""

    def get(self, request, booking_uid):
        barbershop = get_object_or_404(Barbershop, booking_uid=booking_uid, is_active=True)

        barbers = BarberProfile.objects.filter(
            membership__barbershop=barbershop,
            is_active=True,
        ).select_related("membership__user")

        data = []
        for barber in barbers:
            barber_services = BarberService.objects.filter(
                barber=barber, service__is_active=True,
            ).select_related("service")

            data.append({
                "id": barber.pk,
                "name": str(barber),
                "photo": barber.photo.url if barber.photo else None,
                "services": [
                    {
                        "id": bs.service.pk,
                        "name": bs.service.name,
                        "duration": bs.service.duration_minutes,
                        "price": str(bs.effective_price),
                    }
                    for bs in barber_services
                ],
            })

        return JsonResponse({"barbers": data})


class BookingSlotsAPI(View):
    """Returns available time slots for a barber on a date."""

    def get(self, request, booking_uid):
        barbershop = get_object_or_404(Barbershop, booking_uid=booking_uid, is_active=True)
        barber_id = request.GET.get("barber_id")
        date_str = request.GET.get("date")
        duration = int(request.GET.get("duration", 30))

        if not barber_id or not date_str:
            return JsonResponse({"error": "barber_id y date requeridos"}, status=400)

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop=barbershop,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse({"error": "Fecha inválida"}, status=400)

        # Available dates
        available_dates = [d.isoformat() for d in svc.get_available_dates(barber)]

        slots = svc.get_available_slots(barber, target_date, duration)
        slot_data = [
            {"start": s["start"].isoformat(), "end": s["end"].isoformat()}
            for s in slots
        ]

        return JsonResponse({
            "slots": slot_data,
            "available_dates": available_dates,
        })


class BookingCreateAPI(View):
    """
    Creates a booking from the public page.
    Requires the user to be authenticated (Google Auth).
    """

    def post(self, request, booking_uid):
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "Debes iniciar sesión con Google para reservar."},
                status=401,
            )

        barbershop = get_object_or_404(Barbershop, booking_uid=booking_uid, is_active=True)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        barber_id = data.get("barber_id")
        start_time_str = data.get("start_time")
        service_ids = data.get("service_ids", [])

        if not all([barber_id, start_time_str, service_ids]):
            return JsonResponse({"error": "Faltan campos"}, status=400)

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop=barbershop,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        try:
            start_time = datetime.fromisoformat(start_time_str)
            if timezone.is_naive(start_time):
                start_time = timezone.make_aware(start_time)
        except (ValueError, TypeError):
            return JsonResponse({"error": "Formato de fecha inválido"}, status=400)

        # Get or create client from authenticated user
        client, _ = Client.objects.get_or_create(
            organization=barbershop.organization,
            user=request.user,
            defaults={
                "name": request.user.get_full_name() or request.user.email,
                "email": request.user.email,
                "source": "booking",
                "updated_by": request.user,
            },
        )

        try:
            appointment = svc.create_appointment(
                barbershop=barbershop,
                barber=barber,
                client=client,
                start_time=start_time,
                service_ids=service_ids,
                notes="Reserva online",
                created_by=request.user,
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=409)

        return JsonResponse({
            "message": "¡Reserva confirmada!",
            "appointment_id": appointment.pk,
            "start": appointment.start_time.isoformat(),
            "end": appointment.end_time.isoformat(),
            "barber": str(appointment.barber),
        }, status=201)


class MyBookingsAPI(View):
    """Returns the authenticated client's upcoming bookings."""

    def get(self, request, booking_uid):
        if not request.user.is_authenticated:
            return JsonResponse([], safe=False)

        barbershop = get_object_or_404(Barbershop, booking_uid=booking_uid, is_active=True)

        client = Client.objects.filter(
            organization=barbershop.organization,
            user=request.user,
        ).first()

        if not client:
            return JsonResponse([], safe=False)

        appointments = client.appointments.filter(
            barbershop=barbershop,
            start_time__gte=timezone.now(),
            status__in=["pending", "confirmed"],
        ).select_related("barber__membership__user").order_by("start_time")

        data = [
            {
                "id": apt.pk,
                "barber": str(apt.barber),
                "start": apt.start_time.isoformat(),
                "end": apt.end_time.isoformat(),
                "status": apt.get_status_display(),
                "services": list(apt.services.values_list("service__name", flat=True)),
                "total": str(apt.total_price),
            }
            for apt in appointments
        ]
        return JsonResponse(data, safe=False)
