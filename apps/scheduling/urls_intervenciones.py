from django.urls import path

from . import views_intervenciones as views

app_name = "intervenciones"

urlpatterns = [
    path("", views.IntervencionListView.as_view(), name="list"),
    path("crear/", views.IntervencionCreateView.as_view(), name="create"),
    path("<int:pk>/", views.IntervencionDetailView.as_view(), name="detail"),
    path("<int:pk>/estado/", views.IntervencionChangeStatusAPI.as_view(), name="api_change_status"),
    path("api/data/", views.IntervencionDataAPI.as_view(), name="api_data"),
]
