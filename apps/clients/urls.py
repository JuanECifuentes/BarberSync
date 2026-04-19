from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    # ag-Grid API
    path("api/grid/", views.ClientGridAPI.as_view(), name="api_grid"),
    # CRUD
    path("api/create/", views.ClientCreateAPI.as_view(), name="api_create"),
    path("api/<int:pk>/", views.ClientDetailAPI.as_view(), name="api_detail"),
    path("api/<int:pk>/update/", views.ClientUpdateAPI.as_view(), name="api_update"),
    path("api/<int:pk>/delete/", views.ClientDeleteAPI.as_view(), name="api_delete"),
    path("api/<int:pk>/notes/", views.ClientNotesUpdateAPI.as_view(), name="api_notes"),
    # Intervention history (infinite scroll)
    path("api/<int:pk>/history/", views.ClientInterventionHistoryAPI.as_view(), name="api_history"),
    # Ficha clínica
    path("api/<int:pk>/ficha/", views.FichaClinicaAPI.as_view(), name="api_ficha"),
    path("api/<int:pk>/ficha/pdf/", views.FichaClinicaPDFView.as_view(), name="api_ficha_pdf"),
    # Autocomplete search (used by other modules)
    path("api/search/", views.ClientSearchAPI.as_view(), name="api_search"),
]
