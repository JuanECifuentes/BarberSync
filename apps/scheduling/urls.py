from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    # Pages
    path("", views.CalendarView.as_view(), name="calendar"),
    path("services/", views.ServiceListView.as_view(), name="services"),

    # Service CRUD APIs
    path("api/services/create/", views.ServiceCreateAPI.as_view(), name="api_service_create"),
    path("api/services/<int:pk>/delete/", views.ServiceDeleteAPI.as_view(), name="api_service_delete"),

    # Calendar & appointment APIs
    path("api/events/", views.CalendarEventsAPI.as_view(), name="api_events"),
    path("api/slots/", views.AvailableSlotsAPI.as_view(), name="api_slots"),
    path("api/appointments/create/", views.AppointmentCreateAPI.as_view(), name="api_appointment_create"),
    path("api/appointments/<int:pk>/action/", views.AppointmentActionAPI.as_view(), name="api_appointment_action"),
]
