from django.contrib import admin

from .models import Product, ProductCategory, StockMovement


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "barbershop")
    list_filter = ("barbershop",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "barbershop", "category", "price", "stock_quantity", "is_low_stock", "is_active")
    list_filter = ("barbershop", "category", "is_active")
    search_fields = ("name", "sku")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "quantity", "reason", "resulting_stock", "created_at")
    list_filter = ("reason",)
    readonly_fields = ("resulting_stock",)
