from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    # Pages
    path("", views.CalendarView.as_view(), name="calendar"),
    path("services/", views.ServiceListView.as_view(), name="services"),

    # Service CRUD APIs
    path("api/services/create/", views.ServiceCreateAPI.as_view(), name="api_service_create"),
    path("api/services/<int:pk>/", views.ServiceDetailAPI.as_view(), name="api_service_detail"),
    path("api/services/<int:pk>/update/", views.ServiceUpdateAPI.as_view(), name="api_service_update"),
    path("api/services/<int:pk>/delete/", views.ServiceDeleteAPI.as_view(), name="api_service_delete"),
    path("api/services/<int:pk>/price-history/", views.ServicePriceHistoryAPI.as_view(), name="api_service_price_history"),

    # Category APIs
    path("api/categories/create/", views.CategoryCreateAPI.as_view(), name="api_category_create"),

    # Calendar & appointment APIs
    path("api/events/", views.CalendarEventsAPI.as_view(), name="api_events"),
    path("api/slots/", views.AvailableSlotsAPI.as_view(), name="api_slots"),
    path("api/appointments/create/", views.AppointmentCreateAPI.as_view(), name="api_appointment_create"),
    path("api/appointments/<int:pk>/action/", views.AppointmentActionAPI.as_view(), name="api_appointment_action"),
    path("api/appointments/<int:pk>/products/", views.AppointmentProductsAPI.as_view(), name="api_appointment_products"),
    path("api/barber-services/<int:barber_id>/", views.BarberServicesAPI.as_view(), name="api_barber_services"),
    path("api/barber-service/<int:barber_service_id>/customize/", views.BarberServiceCustomizeAPI.as_view(), name="api_barber_service_customize"),
    path("api/barber-service/<int:barber_service_id>/history/", views.BarberServiceHistoryAPI.as_view(), name="api_barber_service_history"),
]
