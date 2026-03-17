"""
Inventory views – product list, stock movements.
"""

from django.views.generic import ListView

from apps.core.mixins import TenantViewMixin

from .models import Product, StockMovement


class ProductListView(TenantViewMixin, ListView):
    model = Product
    template_name = "inventory/product_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().filter(is_active=True)
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        category = self.request.GET.get("category")
        if category:
            qs = qs.filter(category_id=category)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["low_stock_count"] = (
            Product.objects
            .filter(barbershop=self.request.barbershop, is_active=True)
            .extra(where=["stock_quantity <= low_stock_threshold"])
            .count()
        )
        return ctx
