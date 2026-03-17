from django.contrib import admin

from .models import Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("pk", "barbershop", "sale_type", "barber", "total", "completed_at")
    list_filter = ("barbershop", "sale_type")
    date_hierarchy = "completed_at"
    inlines = [SaleItemInline]
