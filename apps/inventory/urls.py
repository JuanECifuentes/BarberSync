from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="list"),
    path("api/products/create/", views.ProductCreateAPI.as_view(), name="api_product_create"),
    path("api/categories/", views.CategoryCreateAPI.as_view(), name="api_categories"),
]
