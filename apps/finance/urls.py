from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.FinanceDashboardView.as_view(), name="dashboard"),
    path("api/analytics/", views.FinanceAnalyticsAPI.as_view(), name="api_analytics"),
    path("sales/", views.SaleListView.as_view(), name="sales"),
    path("api/metrics/", views.DashboardMetricsAPI.as_view(), name="api_metrics"),
]
