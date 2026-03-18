from django.urls import path, re_path

from . import views

app_name = "booking"

# Accepts both formats:
# /book/<uuid>/  (backward compat)
# /book/<slug>-<uuid>/  (new format with barbershop name)
UUID_PATTERN = r"(?:[\w-]+-)?" r"(?P<booking_uid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"

urlpatterns = [
    re_path(rf"^{UUID_PATTERN}/$", views.BookingPageView.as_view(), name="page"),
    re_path(rf"^{UUID_PATTERN}/api/barbers/$", views.BookingBarbersAPI.as_view(), name="api_barbers"),
    re_path(rf"^{UUID_PATTERN}/api/slots/$", views.BookingSlotsAPI.as_view(), name="api_slots"),
    re_path(rf"^{UUID_PATTERN}/api/book/$", views.BookingCreateAPI.as_view(), name="api_book"),
    re_path(rf"^{UUID_PATTERN}/api/my-bookings/$", views.MyBookingsAPI.as_view(), name="api_my_bookings"),
]
