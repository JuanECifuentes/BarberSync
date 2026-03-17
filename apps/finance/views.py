"""
Finance views – dashboard with charts and sales list.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.core.mixins import RoleRequiredMixin, TenantViewMixin

from . import services as fin_svc
from .models import Sale


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


class SaleListView(TenantViewMixin, ListView):
    model = Sale
    template_name = "finance/sale_list.html"
    context_object_name = "sales"
    paginate_by = 25
    ordering = ["-completed_at"]


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

        return JsonResponse({
            "metrics": {k: float(v) if hasattr(v, "as_tuple") else v for k, v in metrics.items()},
            "revenue_by_month": revenue_by_month,
        })
