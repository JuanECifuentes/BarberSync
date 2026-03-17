from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("api/search/", views.ClientSearchAPI.as_view(), name="api_search"),
]
