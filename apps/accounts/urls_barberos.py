from django.urls import path

from . import views_barberos as views

app_name = "barberos"

urlpatterns = [
    path("", views.BarberoListView.as_view(), name="list"),
    path("api/<int:pk>/", views.BarberoDetailAPI.as_view(), name="api_detail"),
    path("api/create/", views.BarberoCreateAPI.as_view(), name="api_create"),
    path("api/<int:pk>/update/", views.BarberoUpdateAPI.as_view(), name="api_update"),
    path("api/<int:pk>/deactivate/", views.BarberoDeactivateAPI.as_view(), name="api_deactivate"),
    path("api/<int:pk>/reactivate/", views.BarberoReactivateAPI.as_view(), name="api_reactivate"),
    path("api/<int:pk>/horarios/", views.HorarioSaveAPI.as_view(), name="api_horarios"),
    path("api/<int:pk>/excepciones/create/", views.ExcepcionCreateAPI.as_view(), name="api_excepcion_create"),
    path("api/<int:pk>/excepciones/<int:exc_pk>/delete/", views.ExcepcionDeleteAPI.as_view(), name="api_excepcion_delete"),
]
