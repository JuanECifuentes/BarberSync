from django.contrib import admin

from .models import (
    Appointment,
    AppointmentService,
    BarberService,
    Intervencion,
    IntervencionProducto,
    IntervencionServicio,
    ScheduleException,
    Service,
    WorkSchedule,
)


class AppointmentServiceInline(admin.TabularInline):
    model = AppointmentService
    extra = 0
    readonly_fields = ("price_charged",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "barbershop", "duration_minutes", "price", "is_active")
    list_filter = ("barbershop", "is_active")
    search_fields = ("name",)


@admin.register(BarberService)
class BarberServiceAdmin(admin.ModelAdmin):
    list_display = ("barber", "service", "custom_price")
    list_filter = ("barber", "service")


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = ("barber", "day_of_week", "start_time", "end_time")
    list_filter = ("barber", "day_of_week")


@admin.register(ScheduleException)
class ScheduleExceptionAdmin(admin.ModelAdmin):
    list_display = ("barber", "exception_type", "start", "end", "is_recurring")
    list_filter = ("exception_type", "barber")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("pk", "client", "barber", "start_time", "end_time", "status")
    list_filter = ("status", "barbershop", "barber")
    search_fields = ("client__name", "client__email")
    inlines = [AppointmentServiceInline]
    date_hierarchy = "start_time"


# ─────────────────────────────────────────────
# Intervención
# ─────────────────────────────────────────────
class IntervencionServicioInline(admin.TabularInline):
    model = IntervencionServicio
    extra = 0
    readonly_fields = ("precio_cobrado",)


class IntervencionProductoInline(admin.TabularInline):
    model = IntervencionProducto
    extra = 0


@admin.register(Intervencion)
class IntervencionAdmin(admin.ModelAdmin):
    list_display = ("pk", "client", "barber", "estado", "fecha", "fecha_fin")
    list_filter = ("estado", "barbershop", "barber")
    search_fields = ("client__name", "client__email")
    inlines = [IntervencionServicioInline, IntervencionProductoInline]
    date_hierarchy = "fecha"
