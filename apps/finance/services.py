"""
Finance business logic – dashboard metrics, sale creation and BI analytics.

All calculations are scoped to the user's organization and respect RBAC:
- Owners/Admins: can filter by any barbershop/barber/service.
- Barbers: only see data for their assigned barbershop(s) and their own profile.

Core metric: interventions with estado='realizada' (the operational truth
for services actually rendered), matching the Clients module.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db.models import (
    Count,
    DecimalField,
    F,
    Min,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import (
    Coalesce,
    ExtractHour,
    ExtractWeekDay,
    TruncDate,
    TruncMonth,
    TruncWeek,
)
from django.utils import timezone

from apps.accounts.models import BarberProfile, Barbershop, Membership
from apps.clients.models import Client
from apps.inventory.models import StockMovement
from apps.scheduling.models import (
    Appointment,
    Intervencion,
    IntervencionProducto,
    IntervencionServicio,
    Service,
    WorkSchedule,
)

from .models import Sale, SaleItem


# ─────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────
def _money(value: Decimal | float | int | None) -> str:
    """Colombian-style money formatting with dot thousands separator."""
    if value is None:
        return "0"
    try:
        rounded = int(Decimal(str(value)).quantize(Decimal("1")))
        return f"{rounded:,}".replace(",", ".")
    except Exception:
        return str(value)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


# ─────────────────────────────────────────────
# Sale creation from a completed appointment
# ─────────────────────────────────────────────
def create_sale_from_appointment(
    appointment: Appointment,
    product_items=None,
    discount=0,
    created_by=None,
):
    """
    Creates a Sale when an appointment is completed.
    Optionally includes product_items sold during the visit.

    product_items: list of {"product_id": int, "quantity": int}
    """
    has_products = bool(product_items)
    sale_type = Sale.SaleType.MIXED if has_products else Sale.SaleType.SERVICE

    sale = Sale.objects.create(
        barbershop=appointment.barbershop,
        appointment=appointment,
        barber=appointment.barber,
        client=appointment.client,
        sale_type=sale_type,
        discount=Decimal(str(discount)),
        updated_by=created_by,
    )

    # Service items (from appointment price snapshots)
    for apt_svc in appointment.services.select_related("service").all():
        SaleItem.objects.create(
            sale=sale,
            item_type=SaleItem.ItemType.SERVICE,
            service=apt_svc.service,
            description=apt_svc.service.name,
            quantity=1,
            unit_price=apt_svc.price_charged,
        )

    # Product items
    if product_items:
        from apps.inventory.models import Product

        for item in product_items:
            product = Product.objects.get(pk=item["product_id"])
            qty = item["quantity"]

            SaleItem.objects.create(
                sale=sale,
                item_type=SaleItem.ItemType.PRODUCT,
                product=product,
                description=product.name,
                quantity=qty,
                unit_price=product.price,
            )

            # Deduct stock
            StockMovement.objects.create(
                product=product,
                quantity=-qty,
                reason=StockMovement.Reason.SALE,
                notes=f"Venta #{sale.pk}",
                updated_by=created_by,
            )

    sale.recalculate()
    return sale


# ─────────────────────────────────────────────
# Dashboard metrics (barbershop level) – legacy
# ─────────────────────────────────────────────
def get_dashboard_metrics(barbershop: Barbershop, months: int | None = None):
    """
    Returns aggregated financial metrics for the dashboard.
    Applies the 6-month default history window.
    """
    if months is None:
        months = settings.BARBERSYNC_DEFAULT_HISTORY_MONTHS

    cutoff = timezone.now() - timedelta(days=30 * months)
    sales_qs = Sale.objects.filter(barbershop=barbershop, completed_at__gte=cutoff)

    total_revenue = sales_qs.aggregate(
        total=Coalesce(Sum("total"), Value(0), output_field=DecimalField())
    )["total"]

    total_services_revenue = SaleItem.objects.filter(
        sale__barbershop=barbershop,
        sale__completed_at__gte=cutoff,
        item_type=SaleItem.ItemType.SERVICE,
    ).aggregate(
        total=Coalesce(
            Sum(F("unit_price") * F("quantity")),
            Value(0),
            output_field=DecimalField(),
        )
    )["total"]

    total_product_revenue = SaleItem.objects.filter(
        sale__barbershop=barbershop,
        sale__completed_at__gte=cutoff,
        item_type=SaleItem.ItemType.PRODUCT,
    ).aggregate(
        total=Coalesce(
            Sum(F("unit_price") * F("quantity")),
            Value(0),
            output_field=DecimalField(),
        )
    )["total"]

    total_appointments = Appointment.objects.filter(
        barbershop=barbershop,
        start_time__gte=cutoff,
        status=Appointment.Status.COMPLETED,
    ).count()

    total_sales_count = sales_qs.count()

    return {
        "total_revenue": total_revenue,
        "services_revenue": total_services_revenue,
        "product_revenue": total_product_revenue,
        "total_appointments": total_appointments,
        "total_sales": total_sales_count,
        "avg_ticket": (
            total_revenue / total_sales_count if total_sales_count > 0 else Decimal("0")
        ),
    }


def get_revenue_by_month(barbershop: Barbershop, months: int | None = None):
    """Returns revenue grouped by month for chart rendering."""
    if months is None:
        months = settings.BARBERSYNC_DEFAULT_HISTORY_MONTHS

    cutoff = timezone.now() - timedelta(days=30 * months)
    return (
        Sale.objects.filter(barbershop=barbershop, completed_at__gte=cutoff)
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(revenue=Sum("total"), count=Count("id"))
        .order_by("month")
    )


def get_revenue_by_barber(barbershop: Barbershop, months: int | None = None):
    """Returns revenue grouped by barber."""
    if months is None:
        months = settings.BARBERSYNC_DEFAULT_HISTORY_MONTHS

    cutoff = timezone.now() - timedelta(days=30 * months)
    return (
        Sale.objects.filter(
            barbershop=barbershop, completed_at__gte=cutoff, barber__isnull=False
        )
        .values(
            "barber__membership__user__first_name",
            "barber__membership__user__last_name",
        )
        .annotate(revenue=Sum("total"), count=Count("id"))
        .order_by("-revenue")
    )


def get_organization_metrics(organization, months: int | None = None):
    """Global metrics across all barbershops in the organization."""
    if months is None:
        months = settings.BARBERSYNC_DEFAULT_HISTORY_MONTHS

    cutoff = timezone.now() - timedelta(days=30 * months)
    sales_qs = Sale.objects.filter(
        barbershop__organization=organization,
        completed_at__gte=cutoff,
    )

    per_shop = (
        sales_qs.values("barbershop__name")
        .annotate(revenue=Sum("total"), count=Count("id"))
        .order_by("-revenue")
    )

    total = sales_qs.aggregate(
        total=Coalesce(Sum("total"), Value(0), output_field=DecimalField())
    )["total"]

    return {
        "total_revenue": total,
        "per_barbershop": list(per_shop),
    }


# ─────────────────────────────────────────────
# RBAC helpers
# ─────────────────────────────────────────────
def _allowed_barbershops(membership: Membership) -> list[int]:
    """Return the barbershop IDs the user is allowed to see."""
    if membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN):
        return list(
            Barbershop.objects.filter(
                organization=membership.organization, is_active=True
            ).values_list("id", flat=True)
        )

    ids = set()
    if membership.barbershop_id:
        ids.add(membership.barbershop_id)
    ids.update(membership.sucursales.values_list("id", flat=True))
    profile = getattr(membership, "barber_profile", None)
    if profile:
        ids.update(profile.sucursales.values_list("id", flat=True))
    return list(ids)


def _allowed_barbers(
    membership: Membership, barbershop_ids: list[int] | None = None
) -> list[int]:
    """Return the barber IDs the user is allowed to see."""
    qs = BarberProfile.objects.filter(is_active=True)
    if membership.role == Membership.Role.BARBER:
        profile = getattr(membership, "barber_profile", None)
        if profile:
            return [profile.pk]
        return []

    if barbershop_ids:
        qs = qs.filter(
            Q(membership__barbershop_id__in=barbershop_ids)
            | Q(sucursales__id__in=barbershop_ids)
        ).distinct()
    else:
        qs = qs.filter(membership__organization=membership.organization)
    return list(qs.values_list("id", flat=True))


def _validate_filters(
    filters: dict[str, Any], membership: Membership
) -> dict[str, Any]:
    """Sanitize filters and enforce RBAC boundaries."""
    allowed_shops = _allowed_barbershops(membership)
    allowed_barbers = _allowed_barbers(membership, allowed_shops)

    requested_shops = [
        int(x) for x in filters.get("barbershop_ids", []) if str(x).isdigit()
    ]
    if membership.role == Membership.Role.BARBER:
        barbershop_ids = allowed_shops
    else:
        barbershop_ids = [
            x for x in requested_shops if x in allowed_shops
        ] or allowed_shops

    requested_barbers = [
        int(x) for x in filters.get("barber_ids", []) if str(x).isdigit()
    ]
    barber_ids = [
        x for x in requested_barbers if x in allowed_barbers
    ] or allowed_barbers

    requested_services = [
        int(x) for x in filters.get("service_ids", []) if str(x).isdigit()
    ]
    available_services = list(
        Service.objects.filter(
            barbershop__organization=membership.organization, is_active=True
        ).values_list("id", flat=True)
    )
    service_ids = [x for x in requested_services if x in available_services]

    date_from = _parse_date(filters.get("date_from")) or (
        timezone.localdate() - timedelta(days=180)
    )
    date_to = _parse_date(filters.get("date_to")) or timezone.localdate()
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    days_of_week = [
        int(x)
        for x in filters.get("days_of_week", [])
        if str(x).isdigit() and 0 <= int(x) <= 6
    ]

    time_start = _parse_time(filters.get("time_start"))
    time_end = _parse_time(filters.get("time_end"))

    return {
        "barbershop_ids": barbershop_ids,
        "barber_ids": barber_ids,
        "service_ids": service_ids,
        "date_from": date_from,
        "date_to": date_to,
        "days_of_week": days_of_week,
        "time_start": time_start,
        "time_end": time_end,
    }


# ─────────────────────────────────────────────
# Base queryset builder
# ─────────────────────────────────────────────
def _base_intervenciones_qs(filters: dict[str, Any]):
    """Return a queryset of Intervencion estado='realizada' filtered by filters."""
    qs = Intervencion.objects.filter(
        estado=Intervencion.Estado.REALIZADA,
        barbershop_id__in=filters["barbershop_ids"],
        fecha__date__gte=filters["date_from"],
        fecha__date__lte=filters["date_to"],
    )

    if filters["barber_ids"]:
        qs = qs.filter(barber_id__in=filters["barber_ids"])

    if filters["service_ids"]:
        qs = qs.filter(servicios__servicio_id__in=filters["service_ids"]).distinct()

    if filters["days_of_week"]:
        qs = qs.filter(fecha__week_day__in=[d + 1 for d in filters["days_of_week"]])

    if filters["time_start"]:
        qs = qs.filter(fecha__time__gte=filters["time_start"])
    if filters["time_end"]:
        qs = qs.filter(fecha__time__lte=filters["time_end"])

    return qs


def _base_servicios_qs(filters: dict[str, Any]):
    """Return IntervencionServicio lines for realized interventions matching filters."""
    qs = IntervencionServicio.objects.filter(
        intervencion__estado=Intervencion.Estado.REALIZADA,
        intervencion__barbershop_id__in=filters["barbershop_ids"],
        intervencion__fecha__date__gte=filters["date_from"],
        intervencion__fecha__date__lte=filters["date_to"],
    )

    if filters["barber_ids"]:
        qs = qs.filter(intervencion__barber_id__in=filters["barber_ids"])
    if filters["service_ids"]:
        qs = qs.filter(servicio_id__in=filters["service_ids"])
    if filters["days_of_week"]:
        qs = qs.filter(
            intervencion__fecha__week_day__in=[d + 1 for d in filters["days_of_week"]]
        )
    if filters["time_start"]:
        qs = qs.filter(intervencion__fecha__time__gte=filters["time_start"])
    if filters["time_end"]:
        qs = qs.filter(intervencion__fecha__time__lte=filters["time_end"])

    return qs


# ─────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────
def _calc_ingresos_brutos(filters: dict[str, Any]) -> Decimal:
    servicios = _base_servicios_qs(filters).aggregate(
        total=Coalesce(Sum("precio_cobrado"), Value(Decimal("0")))
    )["total"]
    productos = IntervencionProducto.objects.filter(
        intervencion__estado=Intervencion.Estado.REALIZADA,
        intervencion__barbershop_id__in=filters["barbershop_ids"],
        intervencion__fecha__date__gte=filters["date_from"],
        intervencion__fecha__date__lte=filters["date_to"],
        incluido_en_precio=False,
    )
    if filters["barber_ids"]:
        productos = productos.filter(intervencion__barber_id__in=filters["barber_ids"])
    if filters["service_ids"]:
        productos = productos.filter(
            intervencion__servicios__servicio_id__in=filters["service_ids"]
        )
    if filters["days_of_week"]:
        productos = productos.filter(
            intervencion__fecha__week_day__in=[d + 1 for d in filters["days_of_week"]]
        )
    if filters["time_start"]:
        productos = productos.filter(
            intervencion__fecha__time__gte=filters["time_start"]
        )
    if filters["time_end"]:
        productos = productos.filter(intervencion__fecha__time__lte=filters["time_end"])

    productos_total = productos.aggregate(
        total=Coalesce(Sum(F("cantidad") * F("precio_unitario")), Value(Decimal("0")))
    )["total"]
    return servicios + productos_total


def _calc_volumen_intervenciones(filters: dict[str, Any]) -> int:
    return _base_intervenciones_qs(filters).count()


def _calc_nuevos_clientes(filters: dict[str, Any]) -> int:
    """Clients created in the date range whose first realized intervention matches filters."""
    qs = Client.objects.filter(
        organization_id=filters["organization_id"],
        is_active=True,
        created_at__date__gte=filters["date_from"],
        created_at__date__lte=filters["date_to"],
    )

    first_interv = (
        Intervencion.objects.filter(
            client=OuterRef("pk"),
            estado=Intervencion.Estado.REALIZADA,
            barbershop_id__in=filters["barbershop_ids"],
        )
        .values("client")
        .annotate(min_fecha=Min("fecha"))
        .values("min_fecha")[:1]
    )
    qs = qs.annotate(first_interv_date=Subquery(first_interv)).filter(
        first_interv_date__date__gte=filters["date_from"],
        first_interv_date__date__lte=filters["date_to"],
    )

    if filters["barber_ids"]:
        qs = qs.filter(
            intervenciones__barber_id__in=filters["barber_ids"],
            intervenciones__estado=Intervencion.Estado.REALIZADA,
            intervenciones__fecha__date__gte=filters["date_from"],
            intervenciones__fecha__date__lte=filters["date_to"],
        ).distinct()

    return qs.count()


def _calc_tasa_retencion(filters: dict[str, Any]) -> float:
    """Percentage of clients (in org history) with >1 intervention that also attended in period."""
    retained_base = (
        Client.objects.filter(
            organization_id=filters["organization_id"], is_active=True
        )
        .annotate(
            total_historic=Count(
                "intervenciones",
                filter=Q(intervenciones__estado=Intervencion.Estado.REALIZADA),
                distinct=True,
            )
        )
        .filter(total_historic__gt=1)
    )

    attended_in_period = retained_base.filter(
        intervenciones__estado=Intervencion.Estado.REALIZADA,
        intervenciones__barbershop_id__in=filters["barbershop_ids"],
        intervenciones__fecha__date__gte=filters["date_from"],
        intervenciones__fecha__date__lte=filters["date_to"],
    )
    if filters["barber_ids"]:
        attended_in_period = attended_in_period.filter(
            intervenciones__barber_id__in=filters["barber_ids"]
        )

    total_retained = retained_base.count()
    if total_retained == 0:
        return 0.0
    return round((attended_in_period.count() / total_retained) * 100, 1)


def _calc_tasa_ocupacion(filters: dict[str, Any]) -> float:
    """Occupied minutes vs total weekly-schedule capacity minutes for selected barbers and period."""
    if not filters["barber_ids"]:
        return 0.0

    occupied = _base_servicios_qs(filters).aggregate(
        total=Coalesce(
            Sum(F("servicio__duration_minutes"), output_field=DecimalField()),
            Value(Decimal("0")),
        )
    )["total"]

    date_from = filters["date_from"]
    date_to = filters["date_to"]
    days_span = (date_to - date_from).days + 1
    weeks = days_span / 7.0

    total_weekly_minutes = 0
    for ws in WorkSchedule.objects.filter(barber_id__in=filters["barber_ids"]):
        start_min = ws.start_time.hour * 60 + ws.start_time.minute
        end_min = ws.end_time.hour * 60 + ws.end_time.minute
        total_weekly_minutes += max(0, end_min - start_min)

    capacity = float(total_weekly_minutes) * float(weeks)
    if capacity <= 0:
        return 0.0
    return round((float(occupied) / capacity) * 100, 1)


# ─────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────
def _evolucion_step(date_from: date, date_to: date) -> str:
    """Return 'day', 'week' or 'month' based on range length."""
    span_days = (date_to - date_from).days + 1
    if span_days <= 31:
        return "day"
    if span_days <= 90:
        return "week"
    return "month"


def _make_trunc(field: str, step: str):
    if step == "day":
        return TruncDate(field)
    if step == "week":
        return TruncWeek(field)
    return TruncMonth(field)


def _chart_evolucion(filters: dict[str, Any]):
    step = _evolucion_step(filters["date_from"], filters["date_to"])

    trunc_service = _make_trunc("intervencion__fecha", step)
    trunc_interv = _make_trunc("fecha", step)

    revenue_qs = (
        _base_servicios_qs(filters)
        .annotate(period=trunc_service)
        .values("period")
        .annotate(revenue=Coalesce(Sum("precio_cobrado"), Value(Decimal("0"))))
        .order_by("period")
    )
    revenue_map = {item["period"]: item["revenue"] for item in revenue_qs}

    product_qs = (
        IntervencionProducto.objects.filter(
            intervencion__estado=Intervencion.Estado.REALIZADA,
            intervencion__barbershop_id__in=filters["barbershop_ids"],
            intervencion__fecha__date__gte=filters["date_from"],
            intervencion__fecha__date__lte=filters["date_to"],
            incluido_en_precio=False,
        )
        .annotate(period=trunc_service)
        .values("period")
        .annotate(
            total=Coalesce(
                Sum(F("cantidad") * F("precio_unitario")), Value(Decimal("0"))
            )
        )
        .order_by("period")
    )
    for item in product_qs:
        revenue_map[item["period"]] = (
            revenue_map.get(item["period"], Decimal("0")) + item["total"]
        )

    volume_qs = (
        _base_intervenciones_qs(filters)
        .annotate(period=trunc_interv)
        .values("period")
        .annotate(count=Count("id"))
        .order_by("period")
    )
    volume_map = {item["period"]: item["count"] for item in volume_qs}

    labels = []
    revenue_values = []
    volume_values = []
    current = filters["date_from"]
    while current <= filters["date_to"]:
        labels.append(current.isoformat())
        revenue_values.append(float(revenue_map.get(current, Decimal("0"))))
        volume_values.append(volume_map.get(current, 0))

        if step == "month":
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)
        elif step == "week":
            current += timedelta(days=7)
        else:
            current += timedelta(days=1)

    return {
        "labels": labels,
        "revenue": revenue_values,
        "volume": volume_values,
    }


def _chart_rendimiento_barbero(filters: dict[str, Any]):
    if not filters["barber_ids"]:
        return {"labels": [], "values": [], "counts": []}

    qs = (
        _base_servicios_qs(filters)
        .values(
            "intervencion__barber_id",
            "intervencion__barber__membership__user__first_name",
            "intervencion__barber__membership__user__last_name",
        )
        .annotate(
            revenue=Coalesce(Sum("precio_cobrado"), Value(Decimal("0"))),
            count=Count("intervencion_id", distinct=True),
        )
        .order_by("-revenue")[:15]
    )

    product_qs = (
        IntervencionProducto.objects.filter(
            intervencion__estado=Intervencion.Estado.REALIZADA,
            intervencion__barbershop_id__in=filters["barbershop_ids"],
            intervencion__fecha__date__gte=filters["date_from"],
            intervencion__fecha__date__lte=filters["date_to"],
            incluido_en_precio=False,
        )
        .values("intervencion__barber_id")
        .annotate(
            total=Coalesce(
                Sum(F("cantidad") * F("precio_unitario")), Value(Decimal("0"))
            )
        )
    )
    product_map = {
        item["intervencion__barber_id"]: item["total"] for item in product_qs
    }

    labels = []
    values = []
    counts = []
    for item in qs:
        name = (
            " ".join(
                filter(
                    None,
                    [
                        item["intervencion__barber__membership__user__first_name"],
                        item["intervencion__barber__membership__user__last_name"],
                    ],
                )
            ).strip()
            or "Barbero"
        )
        barber_id = item["intervencion__barber_id"]
        revenue = item["revenue"] + product_map.get(barber_id, Decimal("0"))
        labels.append(name)
        values.append(float(revenue))
        counts.append(item["count"])

    return {"labels": labels, "values": values, "counts": counts}


def _chart_horas_pico(filters: dict[str, Any]):
    """Return a 7x24 matrix: count of interventions by day-of-week and hour."""
    qs = (
        _base_intervenciones_qs(filters)
        .annotate(
            dow=ExtractWeekDay("fecha"),
            hour=ExtractHour("fecha"),
        )
        .values("dow", "hour")
        .annotate(count=Count("id"))
    )

    # Django ExtractWeekDay: 1=Sunday, 7=Saturday. Convert to ISO: Mon=0
    matrix = [[0 for _ in range(24)] for _ in range(7)]
    max_count = 0
    for item in qs:
        django_dow = item["dow"]
        hour = item["hour"]
        iso_dow = (django_dow + 5) % 7
        matrix[iso_dow][hour] = item["count"]
        max_count = max(max_count, item["count"])

    return {"matrix": matrix, "max_count": max_count}


def _chart_embudo_retencion(filters: dict[str, Any]):
    """Distribution of clients by number of realized interventions."""
    qs = (
        Client.objects.filter(
            organization_id=filters["organization_id"], is_active=True
        )
        .annotate(
            visitas=Count(
                "intervenciones",
                filter=Q(intervenciones__estado=Intervencion.Estado.REALIZADA),
                distinct=True,
            )
        )
        .values("visitas")
        .annotate(count=Count("id"))
        .order_by("visitas")
    )

    buckets = {
        "1 visita": 0,
        "2 visitas": 0,
        "3-5 visitas": 0,
        "6-10 visitas": 0,
        "10+ visitas": 0,
    }
    for item in qs:
        v = item["visitas"]
        c = item["count"]
        if v == 1:
            buckets["1 visita"] += c
        elif v == 2:
            buckets["2 visitas"] += c
        elif 3 <= v <= 5:
            buckets["3-5 visitas"] += c
        elif 6 <= v <= 10:
            buckets["6-10 visitas"] += c
        elif v > 10:
            buckets["10+ visitas"] += c

    return {
        "labels": list(buckets.keys()),
        "values": list(buckets.values()),
    }


def _chart_ocupacion_tendencia(filters: dict[str, Any]):
    """Monthly trend of occupancy rate vs capacity."""
    if not filters["barber_ids"]:
        return {"labels": [], "occupancy": [], "capacity": []}

    occupied_qs = (
        _base_servicios_qs(filters)
        .annotate(month=TruncMonth("intervencion__fecha"))
        .values("month")
        .annotate(
            minutes=Coalesce(
                Sum(F("servicio__duration_minutes"), output_field=DecimalField()),
                Value(Decimal("0")),
            )
        )
        .order_by("month")
    )
    occupied_map = {item["month"]: item["minutes"] for item in occupied_qs}

    weekly_minutes = 0
    for ws in WorkSchedule.objects.filter(barber_id__in=filters["barber_ids"]):
        start_min = ws.start_time.hour * 60 + ws.start_time.minute
        end_min = ws.end_time.hour * 60 + ws.end_time.minute
        weekly_minutes += max(0, end_min - start_min)

    labels = []
    occupancy_values = []
    capacity_values = []

    current = date(filters["date_from"].year, filters["date_from"].month, 1)
    end_month = date(filters["date_to"].year, filters["date_to"].month, 1)
    while current <= end_month:
        if current.month == 12:
            next_month = date(current.year + 1, 1, 1)
        else:
            next_month = date(current.year, current.month + 1, 1)
        days_in_month = (next_month - current).days
        weeks = days_in_month / 7.0
        capacity = weekly_minutes * weeks

        month_start = max(current, filters["date_from"])
        month_end = min((next_month - timedelta(days=1)), filters["date_to"])
        if month_start <= month_end:
            labels.append(current.isoformat()[:7])
            occupied = occupied_map.get(current, 0)
            capacity_values.append(round(capacity, 1))
            occupancy_values.append(
                round((occupied / capacity) * 100, 1) if capacity > 0 else 0
            )

        current = next_month

    return {
        "labels": labels,
        "occupancy": occupancy_values,
        "capacity": capacity_values,
    }


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
def get_finance_filters_context(membership: Membership) -> dict[str, Any]:
    """Return the filter options available to the current user."""
    org = membership.organization
    barbershop_ids = _allowed_barbershops(membership)

    barbers = (
        BarberProfile.objects.filter(
            Q(membership__barbershop_id__in=barbershop_ids)
            | Q(sucursales__id__in=barbershop_ids),
            is_active=True,
        )
        .select_related("membership__user")
        .distinct()
    )

    barbershops = Barbershop.objects.filter(
        organization=org, id__in=barbershop_ids, is_active=True
    ).order_by("name")

    services = (
        Service.objects.filter(barbershop__organization=org, is_active=True)
        .select_related("category")
        .order_by("category__name", "name")
    )

    return {
        "barbers": barbers,
        "barbershops": barbershops,
        "services": services,
        "is_barber": membership.role == Membership.Role.BARBER,
        "is_admin": membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN),
    }


def get_finance_analytics(
    filters: dict[str, Any], membership: Membership
) -> dict[str, Any]:
    """Main entry point: validate filters, compute KPIs and chart data."""
    filters = _validate_filters(filters, membership)
    filters["organization_id"] = membership.organization_id

    ingresos = _calc_ingresos_brutos(filters)
    volumen = _calc_volumen_intervenciones(filters)
    nuevos = _calc_nuevos_clientes(filters)
    ticket = (ingresos / volumen) if volumen > 0 else Decimal("0")
    retencion = _calc_tasa_retencion(filters)
    ocupacion = _calc_tasa_ocupacion(filters)

    return {
        "filters": {
            "date_from": filters["date_from"].isoformat(),
            "date_to": filters["date_to"].isoformat(),
            "barbershop_ids": filters["barbershop_ids"],
            "barber_ids": filters["barber_ids"],
            "service_ids": filters["service_ids"],
        },
        "kpis": {
            "ingresos_brutos": float(ingresos),
            "ingresos_brutos_fmt": _money(ingresos),
            "volumen_intervenciones": volumen,
            "nuevos_clientes": nuevos,
            "ticket_promedio": float(ticket),
            "ticket_promedio_fmt": _money(ticket),
            "tasa_retencion": float(retencion),
            "tasa_ocupacion": float(ocupacion),
        },
        "charts": {
            "evolucion": _chart_evolucion(filters),
            "rendimiento_barbero": _chart_rendimiento_barbero(filters),
            "horas_pico": _chart_horas_pico(filters),
            "embudo_retencion": _chart_embudo_retencion(filters),
            "ocupacion_tendencia": _chart_ocupacion_tendencia(filters),
        },
    }
