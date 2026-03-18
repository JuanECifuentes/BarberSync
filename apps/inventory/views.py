"""
Inventory views – product list, category & product CRUD, stock movements.
"""

import json

from django.db.models import F, Q
from django.http import JsonResponse
from django.views import View
from django.views.generic import ListView

from apps.core.mixins import TenantViewMixin

from .models import Product, ProductCategory, StockMovement


class ProductListView(TenantViewMixin, ListView):
    model = Product
    template_name = "inventory/product_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().filter(is_active=True).select_related("category")

        # Column filters
        nombre = self.request.GET.get("nombre")
        if nombre:
            qs = qs.filter(name__icontains=nombre)

        sku = self.request.GET.get("sku")
        if sku:
            qs = qs.filter(sku__icontains=sku)

        category = self.request.GET.get("category")
        if category:
            qs = qs.filter(category_id=category)

        stock_bajo = self.request.GET.get("stock_bajo")
        if stock_bajo:
            qs = qs.filter(stock_quantity__lte=F("low_stock_threshold"))

        # Backward compat
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        barbershop = self.request.barbershop
        ctx["low_stock_count"] = (
            Product.objects
            .filter(barbershop=barbershop, is_active=True, stock_quantity__lte=F("low_stock_threshold"))
            .count()
        )
        ctx["categories"] = ProductCategory.objects.filter(barbershop=barbershop)
        return ctx


class ProductCreateAPI(View):
    """API para crear productos desde el panel admin."""

    def post(self, request):
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        category_id = data.get("category_id")
        category = None
        if category_id:
            category = ProductCategory.objects.filter(pk=category_id, barbershop=barbershop).first()

        product = Product.objects.create(
            barbershop=barbershop,
            category=category,
            name=name,
            description=data.get("description", ""),
            sku=data.get("sku", ""),
            price=data.get("price", 0),
            cost=data.get("cost", 0),
            stock_quantity=data.get("stock_quantity", 0),
            low_stock_threshold=data.get("low_stock_threshold", 5),
            updated_by=request.user,
        )
        return JsonResponse({"message": "Producto creado", "id": product.pk}, status=201)


class CategoryCreateAPI(View):
    """API para crear categorías desde el panel admin."""

    def post(self, request):
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        cat = ProductCategory.objects.create(
            barbershop=barbershop,
            name=name,
            description=data.get("description", ""),
            updated_by=request.user,
        )
        return JsonResponse({"message": "Categoría creada", "id": cat.pk}, status=201)

    def get(self, request):
        barbershop = request.barbershop
        cats = ProductCategory.objects.filter(barbershop=barbershop)
        return JsonResponse([
            {"id": c.pk, "name": c.name} for c in cats
        ], safe=False)
