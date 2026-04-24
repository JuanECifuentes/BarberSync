from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="list"),
    path("api/products/create/", views.ProductCreateAPI.as_view(), name="api_product_create"),
    path("api/products/<int:pk>/", views.ProductDetailAPI.as_view(), name="api_product_detail"),
    path("api/products/<int:pk>/update/", views.ProductUpdateAPI.as_view(), name="api_product_update"),
    path("api/products/<int:pk>/delete/", views.ProductDeleteAPI.as_view(), name="api_product_delete"),
    path("api/products/<int:pk>/price-history/", views.ProductPriceHistoryAPI.as_view(), name="api_product_price_history"),
    path("api/categories/", views.CategoryCreateAPI.as_view(), name="api_categories"),
    path("api/restock/", views.RestockAPI.as_view(), name="api_restock"),
    path("api/restock/bulk/", views.BulkRestockAPI.as_view(), name="api_restock_bulk"),
    path("api/restock/history/", views.MovementHistoryAPI.as_view(), name="api_restock_history"),
]
