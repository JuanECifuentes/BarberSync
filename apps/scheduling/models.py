"""
Scheduling models – the core of BarberSync.

Service           – catalogue of services per barbershop
BarberService     – which barber can perform which service
WorkSchedule      – weekly recurring hours per barber
ScheduleException – one-off blocks: vacations, lunch breaks, etc.
Appointment       – a booking (can include multiple services)
AppointmentService – individual service line within an appointment
"""

from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import AuditModel, TenantModel


# ─────────────────────────────────────────────
# Service catalogue
# ─────────────────────────────────────────────
class Service(TenantModel):
    """A service offered by a barbershop (e.g., corte clásico, afeitado)."""

    name = models.CharField("nombre", max_length=80)
    description = models.TextField("descripción", blank=True)
    duration_minutes = models.PositiveIntegerField(
        "duración (min)",
        validators=[MinValueValidator(5)],
        help_text="Duración estimada en minutos.",
    )
    price = models.DecimalField(
        "precio", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "scheduling_service"
        verbose_name = "servicio"
        verbose_name_plural = "servicios"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} – ${self.price}"


# ─────────────────────────────────────────────
# Barber ↔ Service (specialization)
# ─────────────────────────────────────────────
class BarberService(AuditModel):
    """Defines which services a barber can perform."""

    barber = models.ForeignKey(
        "accounts.BarberProfile",
        on_delete=models.CASCADE,
        related_name="barber_services",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="barber_services",
    )
    custom_price = models.DecimalField(
        "precio personalizado",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Si se deja vacío, se usa el precio del servicio.",
    )

    class Meta:
        db_table = "scheduling_barber_service"
        verbose_name = "servicio de barbero"
        verbose_name_plural = "servicios de barbero"
        constraints = [
            models.UniqueConstraint(
                fields=["barber", "service"],
                name="unique_barber_service",
            ),
        ]

    def __str__(self):
        return f"{self.barber} → {self.service.name}"

    @property
    def effective_price(self):
        return self.custom_price if self.custom_price is not None else self.service.price


# ─────────────────────────────────────────────
# Work schedule (recurring weekly hours)
# ─────────────────────────────────────────────
class WorkSchedule(AuditModel):
    """
    Regular weekly schedule for a barber.
    One row per day of the week the barber works.
    """

    class DayOfWeek(models.IntegerChoices):
        MONDAY = 0, "Lunes"
        TUESDAY = 1, "Martes"
        WEDNESDAY = 2, "Miércoles"
        THURSDAY = 3, "Jueves"
        FRIDAY = 4, "Viernes"
        SATURDAY = 5, "Sábado"
        SUNDAY = 6, "Domingo"

    barber = models.ForeignKey(
        "accounts.BarberProfile",
        on_delete=models.CASCADE,
        related_name="work_schedules",
    )
    day_of_week = models.IntegerField(choices=DayOfWeek.choices)
    start_time = models.TimeField("hora inicio")
    end_time = models.TimeField("hora fin")

    class Meta:
        db_table = "scheduling_work_schedule"
        verbose_name = "horario laboral"
        verbose_name_plural = "horarios laborales"
        constraints = [
            models.UniqueConstraint(
                fields=["barber", "day_of_week"],
                name="unique_barber_day",
            ),
        ]
        ordering = ["day_of_week", "start_time"]

    def __str__(self):
        return f"{self.barber} – {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"


# ─────────────────────────────────────────────
# Schedule exceptions (one-off blocks)
# ─────────────────────────────────────────────
class ScheduleException(AuditModel):
    """
    One-off schedule blocks: vacations, sick leave, lunch break, etc.
    Replaces the old AnomaliasHorario model.
    """

    class ExceptionType(models.TextChoices):
        VACATION = "vacation", "Vacaciones"
        SICK_LEAVE = "sick_leave", "Permiso médico"
        PERSONAL = "personal", "Permiso personal"
        LUNCH = "lunch", "Almuerzo"
        BREAK = "break", "Descanso"
        OTHER = "other", "Otro"

    barber = models.ForeignKey(
        "accounts.BarberProfile",
        on_delete=models.CASCADE,
        related_name="schedule_exceptions",
    )
    exception_type = models.CharField(
        "tipo", max_length=20, choices=ExceptionType.choices,
    )
    description = models.TextField("descripción", blank=True)
    start = models.DateTimeField("inicio")
    end = models.DateTimeField("fin")
    is_recurring = models.BooleanField(
        "recurrente", default=False,
        help_text="Si es True, se repite semanalmente (ej: almuerzo diario).",
    )

    class Meta:
        db_table = "scheduling_exception"
        verbose_name = "excepción de horario"
        verbose_name_plural = "excepciones de horario"
        ordering = ["start"]

    def __str__(self):
        return f"{self.barber} – {self.get_exception_type_display()} ({self.start:%d/%m %H:%M})"


# ─────────────────────────────────────────────
# Appointment
# ─────────────────────────────────────────────
class Appointment(TenantModel):
    """
    A client's booking. Can contain one or more services.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        CONFIRMED = "confirmed", "Confirmada"
        IN_PROGRESS = "in_progress", "En progreso"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"
        NO_SHOW = "no_show", "No asistió"

    class PaymentMethod(models.TextChoices):
        IN_STORE = "in_store", "Pago en el local"

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    barber = models.ForeignKey(
        "accounts.BarberProfile",
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    start_time = models.DateTimeField("inicio programado", db_index=True)
    end_time = models.DateTimeField(
        "fin estimado",
        help_text="Calculado automáticamente según la duración de los servicios + buffer.",
    )
    status = models.CharField(
        "estado",
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    payment_method = models.CharField(
        "método de pago",
        max_length=15,
        choices=PaymentMethod.choices,
        default=PaymentMethod.IN_STORE,
    )
    notes = models.TextField("notas", blank=True)
    cancelled_reason = models.TextField("motivo cancelación", blank=True)
    reminder_24h_sent = models.BooleanField(default=False)
    reminder_1h_sent = models.BooleanField(default=False)

    class Meta:
        db_table = "scheduling_appointment"
        verbose_name = "cita"
        verbose_name_plural = "citas"
        ordering = ["start_time"]
        indexes = [
            models.Index(fields=["barber", "start_time"]),
            models.Index(fields=["status", "start_time"]),
        ]

    def __str__(self):
        return f"Cita #{self.pk} – {self.client} con {self.barber} @ {self.start_time:%d/%m %H:%M}"

    @property
    def total_price(self):
        return sum(s.price_charged for s in self.services.all())

    @property
    def total_duration(self):
        return sum(s.service.duration_minutes for s in self.services.all())


# ─────────────────────────────────────────────
# Appointment ↔ Service (many services per appointment)
# ─────────────────────────────────────────────
class AppointmentService(models.Model):
    """
    A single service line within an appointment.
    Stores a price snapshot so historical data survives price changes.
    """

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="services",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="+",
    )
    price_charged = models.DecimalField(
        "precio cobrado",
        max_digits=10,
        decimal_places=2,
        help_text="Snapshot del precio al momento de la reserva.",
    )

    class Meta:
        db_table = "scheduling_appointment_service"
        verbose_name = "servicio de cita"
        verbose_name_plural = "servicios de cita"

    def __str__(self):
        return f"{self.service.name} (${self.price_charged})"
