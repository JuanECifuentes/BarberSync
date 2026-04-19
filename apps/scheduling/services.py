"""
Scheduling business logic – all calculations happen here (backend-only).

Key functions:
  get_available_slots()  – returns free time slots for a barber on a date
  create_appointment()   – validates & books an appointment with conflict detection
  cancel_appointment()   – cancels and optionally reschedules
  get_calendar_events()  – returns events for FullCalendar rendering
"""

from datetime import datetime, date, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import BarberProfile, Barbershop
from apps.clients.models import Client
from apps.notifications.tasks import schedule_appointment_reminders

from .models import (
    Appointment,
    AppointmentService,
    BarberService,
    Intervencion,
    IntervencionProducto,
    IntervencionServicio,
    ScheduleException,
    Service,
    ServicioProducto,
    WorkSchedule,
)

from apps.inventory.models import Product, StockMovement


# ─────────────────────────────────────────────
# Available slots calculator
# ─────────────────────────────────────────────
def get_available_slots(
    barber: BarberProfile,
    target_date: date,
    requested_duration: int,
) -> list[dict]:
    """
    Returns a list of available time slots for the given barber on target_date.

    Each slot is: {"start": datetime, "end": datetime}

    Algorithm:
    1. Get the barber's working hours for that day of the week
    2. Collect all blocking events (appointments + schedule exceptions)
    3. Calculate free windows
    4. Filter windows that can fit the requested_duration + buffer
    """
    barbershop = barber.barbershop
    day_of_week = target_date.weekday()

    # 1. Is the barbershop open this day?
    if day_of_week in (barbershop.closed_days or []):
        return []

    # 2. Barber's working hours for this day
    try:
        schedule = WorkSchedule.objects.get(barber=barber, day_of_week=day_of_week)
    except WorkSchedule.DoesNotExist:
        return []

    day_start = datetime.combine(target_date, schedule.start_time)
    day_end = datetime.combine(target_date, schedule.end_time)

    # Make timezone-aware
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(day_start, tz)
    day_end = timezone.make_aware(day_end, tz)

    # Don't show past slots
    now = timezone.now()
    if day_start < now:
        # Round up to next 30-min slot
        day_start = now.replace(second=0, microsecond=0)
        if day_start.minute < 30:
            day_start = day_start.replace(minute=30)
        else:
            day_start = (day_start + timedelta(hours=1)).replace(minute=0)

    if day_start >= day_end:
        return []

    # 3. Collect all blocking events for the day
    blocks = []

    # 3a. Existing appointments (not cancelled/no_show)
    active_statuses = [
        Appointment.Status.PENDING,
        Appointment.Status.CONFIRMED,
        Appointment.Status.IN_PROGRESS,
    ]
    appointments = Appointment.objects.filter(
        barber=barber,
        start_time__date=target_date,
        status__in=active_statuses,
    ).order_by("start_time")

    buffer = timedelta(minutes=barber.buffer_minutes)
    for apt in appointments:
        block_start = apt.start_time
        block_end = apt.end_time + buffer
        blocks.append((block_start, block_end))

    # 3b. Schedule exceptions
    exceptions = ScheduleException.objects.filter(
        barber=barber,
        start__date=target_date,
    )
    for exc in exceptions:
        blocks.append((exc.start, exc.end))

    # 3c. Lunch break (from barber profile)
    if barber.lunch_start and barber.lunch_end:
        lunch_start = timezone.make_aware(
            datetime.combine(target_date, barber.lunch_start), tz
        )
        lunch_end = timezone.make_aware(
            datetime.combine(target_date, barber.lunch_end), tz
        )
        blocks.append((lunch_start, lunch_end))

    # Sort blocks by start time
    blocks.sort(key=lambda b: b[0])

    # 4. Calculate free windows
    free_slots = []
    current_start = day_start

    for block_start, block_end in blocks:
        if block_start > current_start:
            free_slots.append((current_start, block_start))
        if block_end > current_start:
            current_start = block_end

    if current_start < day_end:
        free_slots.append((current_start, day_end))

    # 5. Generate bookable time slots from free windows
    slot_duration = timedelta(minutes=requested_duration)
    available = []

    for window_start, window_end in free_slots:
        slot_start = window_start
        while slot_start + slot_duration <= window_end:
            available.append({
                "start": slot_start,
                "end": slot_start + slot_duration,
            })
            slot_start += timedelta(minutes=30)  # 30-min intervals

    return available


def get_available_dates(barber: BarberProfile, days_ahead: int = 7) -> list[date]:
    """Returns dates in the next `days_ahead` days where the barber has working hours."""
    barbershop = barber.barbershop
    today = timezone.localdate()
    dates = []
    for i in range(days_ahead + 1):
        d = today + timedelta(days=i)
        dow = d.weekday()
        if dow in (barbershop.closed_days or []):
            continue
        if WorkSchedule.objects.filter(barber=barber, day_of_week=dow).exists():
            dates.append(d)
    return dates


# ─────────────────────────────────────────────
# Appointment creation
# ─────────────────────────────────────────────
@transaction.atomic
def create_appointment(
    barbershop: Barbershop,
    barber: BarberProfile,
    client: Client,
    start_time: datetime,
    service_ids: list[int],
    notes: str = "",
    created_by=None,
) -> Appointment:
    """
    Creates an appointment with conflict detection.
    Calculates end_time from the sum of service durations + buffer.
    Stores price snapshots per service.
    Raises ValueError on conflicts.
    """
    # Validate services exist and barber can perform them
    services = Service.objects.filter(pk__in=service_ids, is_active=True) #POR AHORA LOS SERVICIOS FUNCIONAN SIN DISCRIMINAR LA BARBERIA , FALTA AGREGAR PARA HACER ESTA DISCRIMINACION barbershop=barbershop
    if services.count() != len(service_ids):
        raise ValueError("Uno o más servicios no existen o no están activos.")

    barber_service_map = {
        bs.service_id: bs
        for bs in BarberService.objects.filter(barber=barber, service__in=services)
    }
    for svc_obj in services:
        if svc_obj.pk not in barber_service_map:
            raise ValueError(f"El barbero no realiza el servicio: {svc_obj.name}")

    # Calculate total duration using custom durations where available
    total_minutes = sum(
        barber_service_map[s.pk].effective_duration for s in services
    )
    buffer = timedelta(minutes=barber.buffer_minutes)
    end_time = start_time + timedelta(minutes=total_minutes)

    # Conflict detection: check overlapping active appointments
    active_statuses = [
        Appointment.Status.PENDING,
        Appointment.Status.CONFIRMED,
        Appointment.Status.IN_PROGRESS,
    ]
    conflict = Appointment.objects.filter(
        barber=barber,
        status__in=active_statuses,
    ).filter(
        Q(start_time__lt=end_time + buffer) & Q(end_time__gt=start_time - buffer)
    ).exists()

    if conflict:
        raise ValueError("El horario seleccionado ya está ocupado.")

    # Check schedule exceptions
    exception_conflict = ScheduleException.objects.filter(
        barber=barber,
        start__lt=end_time,
        end__gt=start_time,
    ).exists()

    if exception_conflict:
        raise ValueError("El barbero tiene un bloqueo de horario en ese período.")

    # Create appointment
    appointment = Appointment.objects.create(
        barbershop=barbershop,
        client=client,
        barber=barber,
        start_time=start_time,
        end_time=end_time,
        status=Appointment.Status.PENDING,
        notes=notes,
        updated_by=created_by,
    )

    # Create service lines with price snapshots
    service_prices = []
    for svc_obj in services:
        # Use custom price if barber has one, otherwise service price
        barber_svc = barber_service_map.get(svc_obj.pk)
        price = barber_svc.effective_price if barber_svc else svc_obj.price

        AppointmentService.objects.create(
            appointment=appointment,
            service=svc_obj,
            price_charged=price,
        )
        service_prices.append((svc_obj, price))

    # Create linked Intervencion with service snapshots
    intervencion = Intervencion.objects.create(
        barbershop=barbershop,
        appointment=appointment,
        barber=barber,
        client=client,
        estado=Intervencion.Estado.PENDIENTE,
        fecha=start_time,
        fecha_fin=end_time,
        notas=notes,
        updated_by=created_by,
    )

    for svc_obj, price in service_prices:
        IntervencionServicio.objects.create(
            intervencion=intervencion,
            servicio=svc_obj,
            precio_cobrado=price,
        )

    # Auto-consume products linked to services via ServicioProducto
    # Only include active products (soft-deleted products are excluded)
    for svc_obj, _price in service_prices:
        for sp in ServicioProducto.objects.filter(
            servicio=svc_obj,
            producto__is_active=True,
        ).select_related("producto"):
            product = Product.objects.select_for_update().get(pk=sp.producto_id)
            existing = IntervencionProducto.objects.filter(
                intervencion=intervencion, producto=product,
            ).first()
            if existing:
                existing.cantidad += sp.cantidad_consumida
                existing.save(update_fields=["cantidad"])
            else:
                IntervencionProducto.objects.create(
                    intervencion=intervencion,
                    producto=product,
                    cantidad=sp.cantidad_consumida,
                    precio_unitario=product.price,
                )

    # Deduct stock for all auto-consumed products
    for ip in intervencion.productos_usados.select_related("producto").all():
        product = Product.objects.select_for_update().get(pk=ip.producto_id)
        StockMovement(
            product=product,
            quantity=-ip.cantidad,
            reason=StockMovement.Reason.SALE,
            notes=f"Reserva online – Intervención #{intervencion.pk}",
            resulting_stock=0,
            updated_by=created_by,
        ).save()

    # Schedule async reminders (24h + 1h before)
    schedule_appointment_reminders(appointment.pk)

    return appointment


# ─────────────────────────────────────────────
# Appointment cancellation / reschedule
# ─────────────────────────────────────────────
@transaction.atomic
def cancel_appointment(appointment: Appointment, reason: str = "", cancelled_by=None):
    """Cancel an appointment and update audit trail."""
    appointment.status = Appointment.Status.CANCELLED
    appointment.cancelled_reason = reason
    appointment.updated_by = cancelled_by
    appointment.save()


@transaction.atomic
def reschedule_appointment(
    appointment: Appointment,
    new_start: datetime,
    rescheduled_by=None,
):
    """Reschedule by cancelling the old one and creating a new one."""
    service_ids = list(appointment.services.values_list("service_id", flat=True))
    client = appointment.client
    barber = appointment.barber
    barbershop = appointment.barbershop
    notes = appointment.notes

    # Cancel old
    cancel_appointment(appointment, reason="Reagendada", cancelled_by=rescheduled_by)

    # Create new
    return create_appointment(
        barbershop=barbershop,
        barber=barber,
        client=client,
        start_time=new_start,
        service_ids=service_ids,
        notes=notes,
        created_by=rescheduled_by,
    )


# ─────────────────────────────────────────────
# Calendar events (for FullCalendar)
# ─────────────────────────────────────────────
def get_calendar_events(
    barbershop: Barbershop,
    barber: BarberProfile | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """
    Returns events formatted for FullCalendar.
    If barber is None, returns events for all barbers in the barbershop.
    Default range: last 6 months to 1 month ahead.
    """
    if start_date is None:
        start_date = timezone.localdate() - timedelta(
            days=30 * settings.BARBERSYNC_DEFAULT_HISTORY_MONTHS
        )
    if end_date is None:
        end_date = timezone.localdate() + timedelta(days=30)

    today = timezone.localdate()

    # Active statuses: always show
    active_statuses = [
        Appointment.Status.PENDING,
        Appointment.Status.CONFIRMED,
        Appointment.Status.IN_PROGRESS,
        Appointment.Status.COMPLETED,
    ]

    # Base queryset: all non-cancelled in the range
    qs = Appointment.objects.filter(
        barbershop=barbershop,
        start_time__date__gte=start_date,
        start_time__date__lte=end_date,
        status__in=active_statuses,
    )

    # Also include cancelled events from today onward (not past)
    cancelled_qs = Appointment.objects.filter(
        barbershop=barbershop,
        start_time__date__gte=today,
        start_time__date__lte=end_date,
        status=Appointment.Status.CANCELLED,
    )

    qs = (qs | cancelled_qs).select_related(
        "client", "barber__membership__user"
    ).prefetch_related(
        "services__service",
        "intervencion__servicios__servicio",
        "intervencion__productos_usados__producto",
    )

    if barber is not None:
        qs = qs.filter(barber=barber)

    events = []
    for apt in qs:
        service_names = ", ".join(
            apt.services.values_list("service__name", flat=True)
        )

        # Services detail with prices
        services_detail = [
            {"name": s.service.name, "price": str(s.price_charged)}
            for s in apt.services.all()
        ]

        # Intervencion data (if exists)
        intervencion_estado = None
        intervencion_estado_display = None
        intervencion_notas = ""
        intervencion_productos = []

        intervencion = getattr(apt, "intervencion", None)
        try:
            intervencion = apt.intervencion
        except Intervencion.DoesNotExist:
            intervencion = None

        if intervencion:
            intervencion_estado = intervencion.estado
            intervencion_estado_display = intervencion.get_estado_display()
            intervencion_notas = intervencion.notas
            # Build set of auto-consumed product IDs from services
            servicio_ids = list(
                intervencion.servicios.values_list("servicio_id", flat=True)
            )
            auto_product_ids = set(
                ServicioProducto.objects.filter(
                    servicio_id__in=servicio_ids,
                ).values_list("producto_id", flat=True)
            )
            intervencion_productos = [
                {
                    "product_id": p.producto_id,
                    "name": p.producto.name,
                    "cantidad": p.cantidad,
                    "subtotal": str(p.subtotal),
                    "precio_unitario": str(p.precio_unitario),
                    "is_deleted": not p.producto.is_active,
                    "auto": p.producto_id in auto_product_ids,
                }
                for p in intervencion.productos_usados.select_related("producto").all()
            ]

        events.append({
            "id": apt.pk,
            "title": f"{apt.client.name} – {service_names}",
            "start": apt.start_time.isoformat(),
            "end": apt.end_time.isoformat(),
            "color": _status_color(apt.status),
            "extendedProps": {
                "client_name": apt.client.name,
                "client_phone": apt.client.phone,
                "client_email": apt.client.email,
                "barber_name": str(apt.barber),
                "services": service_names,
                "services_detail": services_detail,
                "total_price": str(apt.total_price),
                "status": apt.status,
                "status_display": apt.get_status_display(),
                "notes": apt.notes,
                "intervencion_estado": intervencion_estado,
                "intervencion_estado_display": intervencion_estado_display,
                "intervencion_notas": intervencion_notas,
                "intervencion_productos": intervencion_productos,
            },
        })

    return events


def _status_color(status: str) -> str:
    return {
        "pending": "#f59e0b",     # amber
        "confirmed": "#3b82f6",   # blue
        "in_progress": "#ff2301", # brand orange
        "completed": "#10b981",   # green
        "cancelled": "#ef4444",   # red
    }.get(status, "#6b7280")      # gray
