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
# Service category
# ─────────────────────────────────────────────
class CategoriaServicio(TenantModel):
    """Category to group services (e.g., Cortes, Barba, Tratamientos)."""

    name = models.CharField("nombre", max_length=80)
    description = models.TextField("descripción", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "scheduling_categoria_servicio"
        verbose_name = "categoría de servicio"
        verbose_name_plural = "categorías de servicio"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────
# Service catalogue
# ─────────────────────────────────────────────
class Service(TenantModel):
    """A service offered by a barbershop (e.g., corte clásico, afeitado)."""

    category = models.ForeignKey(
        CategoriaServicio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
        verbose_name="categoría",
    )
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
# Service price history
# ─────────────────────────────────────────────
class HistorialPrecioServicio(models.Model):
    """Tracks price changes for a service over time."""

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="price_history",
    )
    price = models.DecimalField(
        "precio", max_digits=10, decimal_places=2,
    )
    changed_at = models.DateTimeField("fecha de cambio", auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "scheduling_historial_precio_servicio"
        verbose_name = "historial de precio"
        verbose_name_plural = "historial de precios"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.service.name}: ${self.price} @ {self.changed_at:%d/%m/%Y}"


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


# ─────────────────────────────────────────────
# Intervención (registro de servicio prestado)
# ─────────────────────────────────────────────
class Intervencion(TenantModel):
    """
    Registro de cada servicio prestado a un cliente.
    Puede originarse de una cita (Appointment) o ser creada manualmente
    por el administrador desde el panel.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_PROGRESO = "en_progreso", "En progreso"
        REALIZADA = "realizada", "Realizada"
        CANCELADA = "cancelada", "Cancelada"

    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intervencion",
        help_text="Cita de origen, si aplica.",
    )
    barber = models.ForeignKey(
        "accounts.BarberProfile",
        on_delete=models.CASCADE,
        related_name="intervenciones",
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.CASCADE,
        related_name="intervenciones",
    )
    estado = models.CharField(
        "estado",
        max_length=15,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        db_index=True,
    )
    fecha = models.DateTimeField("fecha de intervención", db_index=True)
    fecha_fin = models.DateTimeField("fin de intervención", null=True, blank=True)
    notas = models.TextField("notas", blank=True)

    class Meta:
        db_table = "scheduling_intervencion"
        verbose_name = "intervención"
        verbose_name_plural = "intervenciones"
        ordering = ["-fecha"]
        indexes = [
            models.Index(fields=["barber", "fecha"]),
            models.Index(fields=["estado", "fecha"]),
        ]

    def __str__(self):
        return f"Intervención #{self.pk} – {self.client} con {self.barber} @ {self.fecha:%d/%m %H:%M}"

    @property
    def total_precio(self):
        return sum(s.precio_cobrado for s in self.servicios.all())

    @property
    def total_duracion(self):
        return sum(s.servicio.duration_minutes for s in self.servicios.all())


class IntervencionServicio(models.Model):
    """Servicio individual realizado dentro de una intervención."""

    intervencion = models.ForeignKey(
        Intervencion,
        on_delete=models.CASCADE,
        related_name="servicios",
    )
    servicio = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="+",
    )
    precio_cobrado = models.DecimalField(
        "precio cobrado",
        max_digits=10,
        decimal_places=2,
        help_text="Snapshot del precio al momento de la intervención.",
    )

    class Meta:
        db_table = "scheduling_intervencion_servicio"
        verbose_name = "servicio de intervención"
        verbose_name_plural = "servicios de intervención"

    def __str__(self):
        return f"{self.servicio.name} (${self.precio_cobrado})"


class IntervencionProducto(models.Model):
    """Producto utilizado durante una intervención."""

    intervencion = models.ForeignKey(
        Intervencion,
        on_delete=models.CASCADE,
        related_name="productos_usados",
    )
    producto = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        related_name="uso_intervenciones",
    )
    cantidad = models.PositiveIntegerField("cantidad", default=1)
    precio_unitario = models.DecimalField(
        "precio unitario",
        max_digits=10,
        decimal_places=2,
        help_text="Precio unitario al momento de uso.",
    )

    class Meta:
        db_table = "scheduling_intervencion_producto"
        verbose_name = "producto de intervención"
        verbose_name_plural = "productos de intervención"

    def __str__(self):
        return f"{self.producto.name} x{self.cantidad}"

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario
