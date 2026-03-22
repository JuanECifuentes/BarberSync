"""
Inventory views – product list, category & product CRUD, stock movements.
"""

import json
from collections import OrderedDict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F, Q
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from apps.core.mixins import TenantViewMixin, RoleRequiredMixin
from apps.accounts.models import Barbershop

from .models import Product, ProductCategory, StockMovement


class ProductListView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/product_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        barbershop = self.request.barbershop

        # Determine which barbershop(s) to show
        sucursal_filter = self.request.GET.get("sucursal")
        all_sucursales = Barbershop.objects.filter(organization=org, is_active=True).order_by("name")
        ctx["sucursales"] = all_sucursales

        if sucursal_filter:
            try:
                target_shop = Barbershop.objects.get(pk=sucursal_filter, organization=org, is_active=True)
            except Barbershop.DoesNotExist:
                target_shop = barbershop
        else:
            target_shop = barbershop

        ctx["selected_sucursal"] = target_shop

        # Base queryset
        qs = Product.objects.filter(barbershop=target_shop, is_active=True).select_related("category")

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

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)

        # Group products by category for accordion
        products = qs.order_by("category__name", "name")
        grouped = OrderedDict()
        uncategorized = []
        for p in products:
            if p.category:
                cat_name = p.category.name
                if cat_name not in grouped:
                    grouped[cat_name] = {"category": p.category, "products": []}
                grouped[cat_name]["products"].append(p)
            else:
                uncategorized.append(p)

        if uncategorized:
            grouped["Sin categoría"] = {"category": None, "products": uncategorized}

        ctx["grouped_products"] = grouped
        ctx["total_products"] = qs.count()
        ctx["low_stock_count"] = (
            Product.objects
            .filter(barbershop=target_shop, is_active=True, stock_quantity__lte=F("low_stock_threshold"))
            .count()
        )
        ctx["categories"] = ProductCategory.objects.filter(barbershop=target_shop)
        ctx["barbershop"] = target_shop
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


class ProductUpdateAPI(View):
    """API para editar un producto existente."""

    def post(self, request, pk):
        barbershop = request.barbershop
        try:
            product = Product.objects.get(pk=pk, barbershop=barbershop, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        category_id = data.get("category_id")
        if category_id:
            product.category = ProductCategory.objects.filter(pk=category_id, barbershop=barbershop).first()
        elif category_id == "" or category_id is None:
            product.category = None

        product.name = name
        product.description = data.get("description", product.description)
        product.sku = data.get("sku", product.sku)
        product.price = data.get("price", product.price)
        product.cost = data.get("cost", product.cost)
        product.low_stock_threshold = data.get("low_stock_threshold", product.low_stock_threshold)
        product.updated_by = request.user
        product.save()
        return JsonResponse({"ok": True})


class ProductDeleteAPI(View):
    """Soft delete: sets is_active=False."""

    def post(self, request, pk):
        barbershop = request.barbershop
        try:
            product = Product.objects.get(pk=pk, barbershop=barbershop, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        product.is_active = False
        product.updated_by = request.user
        product.save(update_fields=["is_active", "updated_by"])
        return JsonResponse({"ok": True})


class ProductDetailAPI(View):
    """Returns product data for the edit modal."""

    def get(self, request, pk):
        barbershop = request.barbershop
        try:
            p = Product.objects.select_related("category").get(pk=pk, barbershop=barbershop, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        return JsonResponse({
            "id": p.pk,
            "name": p.name,
            "description": p.description,
            "sku": p.sku,
            "price": str(p.price),
            "cost": str(p.cost),
            "stock_quantity": p.stock_quantity,
            "low_stock_threshold": p.low_stock_threshold,
            "category_id": p.category_id or "",
        })


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
