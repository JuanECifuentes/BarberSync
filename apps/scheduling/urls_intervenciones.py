from django.urls import path

from . import views_intervenciones as views
from . import views as scheduling_views

app_name = "intervenciones"

urlpatterns = [
    path("", views.IntervencionListView.as_view(), name="list"),
    path("api/grid/", views.IntervencionGridAPI.as_view(), name="api_grid"),
    path("api/data/", views.IntervencionDataAPI.as_view(), name="api_data"),
    path("api/crear/", views.IntervencionCreateView.as_view(), name="api_create"),
    path("api/<int:pk>/", views.IntervencionDetailAPI.as_view(), name="api_detail"),
    path("api/<int:pk>/editar/", views.IntervencionUpdateView.as_view(), name="api_update"),
    path("api/<int:pk>/eliminar/", views.IntervencionDeleteView.as_view(), name="api_delete"),
    path("api/<int:pk>/estado/", views.IntervencionChangeStatusAPI.as_view(), name="api_change_status"),
    # Barber services for the intervenciones modal (barber → services selector)
    path("api/barber-services/<int:barber_id>/", scheduling_views.BarberServicesAPI.as_view(), name="api_barber_services"),
]
