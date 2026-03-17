"""
Finance business logic – dashboard metrics, sale creation.

ALL calculations happen here, not in the frontend.
Queries always apply the 6-month default window.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.utils import timezone

from apps.accounts.models import Barbershop
from apps.inventory.models import StockMovement
from apps.scheduling.models import Appointment, AppointmentService

from .models import Sale, SaleItem


# ─────────────────────────────────────────────
# Sale creation from a completed appointment
# ─────────────────────────────────────────────
@transaction.atomic
def create_sale_from_appointment(appointment: Appointment, product_items=None, discount=0, created_by=None):
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
# Dashboard metrics (barbershop level)
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
        total=Coalesce(Sum(F("unit_price") * F("quantity")), Value(0), output_field=DecimalField())
    )["total"]

    total_product_revenue = SaleItem.objects.filter(
        sale__barbershop=barbershop,
        sale__completed_at__gte=cutoff,
        item_type=SaleItem.ItemType.PRODUCT,
    ).aggregate(
        total=Coalesce(Sum(F("unit_price") * F("quantity")), Value(0), output_field=DecimalField())
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
        "avg_ticket": total_revenue / total_sales_count if total_sales_count > 0 else Decimal("0"),
    }


# ─────────────────────────────────────────────
# Revenue by month (for charts)
# ─────────────────────────────────────────────
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
        Sale.objects.filter(barbershop=barbershop, completed_at__gte=cutoff, barber__isnull=False)
        .values("barber__membership__user__first_name", "barber__membership__user__last_name")
        .annotate(revenue=Sum("total"), count=Count("id"))
        .order_by("-revenue")
    )


# ─────────────────────────────────────────────
# Organization-level metrics (global view)
# ─────────────────────────────────────────────
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
        sales_qs
        .values("barbershop__name")
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
