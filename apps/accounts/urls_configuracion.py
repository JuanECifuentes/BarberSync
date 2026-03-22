from django.urls import path

from . import views_configuracion as views

app_name = "configuracion"

urlpatterns = [
    path("", views.ConfiguracionIndexView.as_view(), name="index"),
    path("api/organizacion/update/", views.OrganizacionUpdateAPI.as_view(), name="api_org_update"),
    path("api/organizacion/logo/", views.OrganizacionLogoAPI.as_view(), name="api_org_logo"),
    path("api/sucursales/create/", views.SucursalCreateAPI.as_view(), name="api_sucursal_create"),
    path("api/sucursales/<int:pk>/update/", views.SucursalUpdateAPI.as_view(), name="api_sucursal_update"),
    path("api/sucursales/<int:pk>/deactivate/", views.SucursalDeactivateAPI.as_view(), name="api_sucursal_deactivate"),
    path("api/sucursales/<int:pk>/reactivate/", views.SucursalReactivateAPI.as_view(), name="api_sucursal_reactivate"),
]
