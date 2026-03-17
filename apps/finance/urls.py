from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("sales/", views.SaleListView.as_view(), name="sales"),
    path("api/metrics/", views.DashboardMetricsAPI.as_view(), name="api_metrics"),
]
