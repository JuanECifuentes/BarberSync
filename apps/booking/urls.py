from django.urls import path

from . import views

app_name = "booking"

urlpatterns = [
    path("<uuid:booking_uid>/", views.BookingPageView.as_view(), name="page"),
    path("<uuid:booking_uid>/api/barbers/", views.BookingBarbersAPI.as_view(), name="api_barbers"),
    path("<uuid:booking_uid>/api/slots/", views.BookingSlotsAPI.as_view(), name="api_slots"),
    path("<uuid:booking_uid>/api/book/", views.BookingCreateAPI.as_view(), name="api_book"),
    path("<uuid:booking_uid>/api/my-bookings/", views.MyBookingsAPI.as_view(), name="api_my_bookings"),
]
