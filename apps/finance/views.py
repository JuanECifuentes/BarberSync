"""
Finance views – BI dashboard with filters, KPIs and charts.

Permissions:
- Owners, admins and barbers can access.
- Barbers are restricted to their assigned barbershop and own profile.
"""

import json
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.core.mixins import RoleRequiredMixin, TenantViewMixin

from . import services as fin_svc
from .models import Sale


class FinanceDashboardView(LoginRequiredMixin, TemplateView):
    """Main Finanzas BI page with tabs, filters, KPIs and charts."""

    template_name = "finance/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        membership = getattr(request.user, "membership", None)
        if not membership or membership.role not in (
            membership.Role.OWNER,
            membership.Role.ADMIN,
            membership.Role.BARBER,
        ):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("No tienes permisos para acceder a Finanzas.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        membership = self.request.user.membership

        # Default date range: last 6 months
        today = timezone.localdate()
        ctx["default_date_to"] = today.isoformat()
        ctx["default_date_from"] = (today - timedelta(days=180)).isoformat()

        # Filter options (already scoped by RBAC)
        ctx.update(fin_svc.get_finance_filters_context(membership))

        # Pre-selected values for locked barber view
        if ctx.get("is_barber"):
            profile = getattr(membership, "barber_profile", None)
            ctx["locked_barber_id"] = profile.pk if profile else None
            ctx["locked_barbershop_ids"] = fin_svc._allowed_barbershops(membership)

        return ctx


class FinanceAnalyticsAPI(LoginRequiredMixin, View):
    """JSON endpoint for KPIs and charts based on global filters."""

    def get(self, request):
        membership = getattr(request.user, "membership", None)
        if not membership:
            return JsonResponse({"error": "Sin membresía activa"}, status=403)

        filters = {
            "barber_ids": request.GET.getlist("barber_ids"),
            "service_ids": request.GET.getlist("service_ids"),
            "barbershop_ids": request.GET.getlist("barbershop_ids"),
            "date_from": request.GET.get("date_from"),
            "date_to": request.GET.get("date_to"),
            "days_of_week": request.GET.getlist("days_of_week"),
            "time_start": request.GET.get("time_start"),
            "time_end": request.GET.get("time_end"),
        }

        try:
            data = fin_svc.get_finance_analytics(filters, membership)
        except Exception:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Error computing finance analytics")
            return JsonResponse(
                {"error": "Error al calcular los indicadores. Intenta de nuevo."},
                status=500,
            )

        return JsonResponse(data)


class SaleListView(TenantViewMixin, ListView):
    model = Sale
    template_name = "finance/sale_list.html"
    context_object_name = "sales"
    paginate_by = 25
    ordering = ["-completed_at"]


# Legacy dashboard kept for backwards compatibility
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        barbershop = self.request.barbershop
        membership = self.request.user.membership

        if barbershop:
            ctx["metrics"] = fin_svc.get_dashboard_metrics(barbershop)
            ctx["revenue_by_month"] = list(fin_svc.get_revenue_by_month(barbershop))
            ctx["revenue_by_barber"] = list(fin_svc.get_revenue_by_barber(barbershop))

        # Organization-level for owners
        if membership and membership.role == "owner":
            ctx["org_metrics"] = fin_svc.get_organization_metrics(
                membership.organization
            )

        return ctx


class DashboardMetricsAPI(LoginRequiredMixin, View):
    """JSON endpoint for dashboard chart data (AJAX refresh)."""

    def get(self, request):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        months = request.GET.get("months")
        months = int(months) if months else None

        metrics = fin_svc.get_dashboard_metrics(barbershop, months)
        revenue_by_month = list(fin_svc.get_revenue_by_month(barbershop, months))

        # Serialize decimals and dates
        for item in revenue_by_month:
            item["revenue"] = float(item["revenue"])
            item["month"] = item["month"].isoformat()

        return JsonResponse(
            {
                "metrics": {
                    k: float(v) if hasattr(v, "as_tuple") else v
                    for k, v in metrics.items()
                },
                "revenue_by_month": revenue_by_month,
            }
        )
