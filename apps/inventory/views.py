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

from .models import Product, ProductCategory, StockMovement, HistorialPrecioProducto, InventoryMovement, InventoryMovementItem
from .services import process_restock, process_bulk_restock, process_transfer


class ProductListView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/product_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization

        ctx["sucursales"] = Barbershop.objects.filter(
            organization=org, is_active=True
        ).order_by("name")

        # All active products across ALL barbershops in the org
        qs = (
            Product.objects
            .filter(barbershop__organization=org, barbershop__is_active=True, is_active=True)
            .select_related("category", "barbershop")
            .order_by("category__name", "name")
        )

        # Group by category for accordion rendering
        grouped = OrderedDict()
        uncategorized = []
        for p in qs:
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
            .filter(
                barbershop__organization=org, barbershop__is_active=True,
                is_active=True, stock_quantity__lte=F("low_stock_threshold"),
            )
            .count()
        )
        ctx["categories"] = ProductCategory.objects.filter(
            organization=org, is_active=True
        ).distinct().order_by("name")
        return ctx


class ProductCreateAPI(View):
    """API para crear productos desde el panel admin."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        # Determinar sucursal: viene del body (obligatorio)
        barbershop_id = data.get("barbershop_id")
        if not barbershop_id:
            return JsonResponse({"error": "Sucursal requerida"}, status=400)

        org = request.organization
        try:
            barbershop = Barbershop.objects.get(
                pk=barbershop_id, organization=org, is_active=True
            )
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal no válida"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        category_id = data.get("category_id")
        category = None
        if category_id:
            category = ProductCategory.objects.filter(pk=category_id, organization=org, is_active=True).first()

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

        # Record initial price/cost in history
        HistorialPrecioProducto.objects.create(
            product=product,
            price=product.price,
            cost=product.cost,
            changed_by=request.user,
        )

        return JsonResponse({"message": "Producto creado", "id": product.pk}, status=201)


class ProductUpdateAPI(View):
    """API para editar un producto existente."""

    def post(self, request, pk):
        org = request.organization
        try:
            product = Product.objects.get(pk=pk, barbershop__organization=org, is_active=True)
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
            product.category = ProductCategory.objects.filter(pk=category_id, organization=org, is_active=True).first()
        elif category_id == "" or category_id is None:
            product.category = None

        old_price = product.price
        old_cost = product.cost

        product.name = name
        product.description = data.get("description", product.description)
        product.sku = data.get("sku", product.sku)
        product.price = data.get("price", product.price)
        product.cost = data.get("cost", product.cost)
        product.low_stock_threshold = data.get("low_stock_threshold", product.low_stock_threshold)
        product.updated_by = request.user
        product.save()

        # Record price/cost change in history if either changed
        from decimal import Decimal
        new_price = Decimal(str(product.price))
        new_cost = Decimal(str(product.cost))
        if new_price != old_price or new_cost != old_cost:
            HistorialPrecioProducto.objects.create(
                product=product,
                price=product.price,
                cost=product.cost,
                changed_by=request.user,
            )

        return JsonResponse({"ok": True})


class ProductDeleteAPI(View):
    """Soft delete: sets is_active=False."""

    def post(self, request, pk):
        org = request.organization
        try:
            product = Product.objects.get(pk=pk, barbershop__organization=org, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        product.is_active = False
        product.updated_by = request.user
        product.save(update_fields=["is_active", "updated_by"])
        return JsonResponse({"ok": True})


class ProductDetailAPI(View):
    """Returns product data for the edit modal."""

    def get(self, request, pk):
        org = request.organization
        try:
            p = Product.objects.get(pk=pk, barbershop__organization=org, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        response = {
            "id": p.pk,
            "name": p.name,
            "description": p.description,
            "sku": p.sku,
            "price": str(p.price),
            "cost": str(p.cost),
            "stock_quantity": p.stock_quantity,
            "low_stock_threshold": p.low_stock_threshold,
            "category_id": p.category_id or "",
        }

        return JsonResponse(response)


class ProductPriceHistoryAPI(View):
    """Paginated price/cost history for a product (30 per page)."""

    def get(self, request, pk):
        from django.core.paginator import Paginator

        org = request.organization
        try:
            product = Product.objects.get(pk=pk, barbershop__organization=org, is_active=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        qs = HistorialPrecioProducto.objects.filter(product=product).select_related("changed_by")
        paginator = Paginator(qs, 30)
        page_num = request.GET.get("page", 1)
        page = paginator.get_page(page_num)

        items = []
        for h in page:
            who = ""
            if h.changed_by:
                who = " ".join(filter(None, [h.changed_by.first_name, h.changed_by.last_name])) or "Sistema"
            items.append({
                "price": str(h.price),
                "cost": str(h.cost),
                "changed_at": h.changed_at.isoformat(),
                "changed_by": who or "Sistema",
            })

        return JsonResponse({
            "results": items,
            "page": page.number,
            "has_next": page.has_next(),
        })


class CategoryCreateAPI(View):
    """API para crear categorías desde el panel admin."""

    def post(self, request):
        org = request.organization
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        cat = ProductCategory.objects.create(
            organization=org,
            name=name,
            description=data.get("description", ""),
            updated_by=request.user,
        )
        return JsonResponse({"message": "Categoría creada", "id": cat.pk}, status=201)

    def get(self, request):
        org = request.organization
        cats = ProductCategory.objects.filter(organization=org, is_active=True)
        return JsonResponse([
            {"id": c.pk, "name": c.name} for c in cats
        ], safe=False)


class CategoryUpdateAPI(View):
    """API para editar el nombre de una categoría."""

    def post(self, request, pk):
        org = request.organization
        try:
            category = ProductCategory.objects.get(pk=pk, organization=org, is_active=True)
        except ProductCategory.DoesNotExist:
            return JsonResponse({"error": "Categoría no encontrada"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Nombre requerido"}, status=400)

        category.name = name
        category.description = data.get("description", category.description)
        category.updated_by = request.user
        category.save(update_fields=["name", "description", "updated_by"])

        return JsonResponse({"ok": True})


class CategoryDeleteAPI(View):
    """Soft delete: set is_active=False y desasocia productos."""

    def post(self, request, pk):
        org = request.organization
        try:
            category = ProductCategory.objects.get(pk=pk, organization=org, is_active=True)
        except ProductCategory.DoesNotExist:
            return JsonResponse({"error": "Categoría no encontrada"}, status=404)

        # Desasociar productos (category_id = Null)
        Product.objects.filter(category=category).update(category=None)

        # Borrado lógico
        category.is_active = False
        category.updated_by = request.user
        category.save(update_fields=["is_active", "updated_by"])

        return JsonResponse({"ok": True})


class RestockAPI(View):
    """API para procesar un reestock individual."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        product_id = data.get("product_id")
        quantity = data.get("quantity")
        notes = data.get("notes", "")
        
        if not product_id:
            return JsonResponse({"error": "Producto requerido"}, status=400)
        if not quantity or int(quantity) <= 0:
            return JsonResponse({"error": "Cantidad debe ser mayor a 0"}, status=400)

        try:
            product = Product.objects.get(pk=product_id, barbershop__organization=request.organization, is_active=True)
            barbershop = product.barbershop
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        try:
            movement = process_restock(
                barbershop=barbershop,
                user=request.user,
                items=[{"product_id": int(product_id), "quantity": int(quantity)}],
                notes=notes,
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({
            "message": "Reestock procesado",
            "movement_id": movement.pk,
            "new_stock": movement.items.first().stock_resulting,
        }, status=201)


class BulkRestockAPI(View):
    """API para procesar reestock múltiple."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        items = data.get("items", [])
        notes = data.get("notes", "")

        if not items:
            return JsonResponse({"error": "No se proporcionaron ítems"}, status=400)

        from django.db import transaction
        from collections import defaultdict
        
        product_ids = [int(item["product_id"]) for item in items]
        products = Product.objects.filter(pk__in=product_ids, barbershop__organization=request.organization, is_active=True)
        product_dict = {p.id: p for p in products}

        items_by_barbershop = defaultdict(list)
        for item in items:
            pid = int(item["product_id"])
            if pid not in product_dict:
                return JsonResponse({"error": f"Producto ID {pid} no encontrado"}, status=400)
            items_by_barbershop[product_dict[pid].barbershop].append(item)

        updated_stocks = {}
        total_items = 0

        try:
            with transaction.atomic():
                for barbershop, bs_items in items_by_barbershop.items():
                    movement = process_bulk_restock(
                        barbershop=barbershop,
                        user=request.user,
                        items=bs_items,
                        notes=notes,
                    )
                    total_items += movement.items.count()
                    for item in movement.items.all():
                        updated_stocks[item.product_id] = item.stock_resulting
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({
            "message": "Reestock múltiple procesado",
            "total_items": total_items,
            "updated_stocks": updated_stocks
        }, status=201)


class TransferAPI(View):
    """API para procesar una transferencia individual."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        product_id = data.get("product_id")
        quantity = data.get("quantity")
        notes = data.get("notes", "")
        barbershop_destiny_id = data.get("barbershop_destiny_id")

        if not product_id:
            return JsonResponse({"error": "Producto requerido"}, status=400)
        if not barbershop_destiny_id:
            return JsonResponse({"error": "Sucursal de destino requerida"}, status=400)
        if not quantity or int(quantity) <= 0:
            return JsonResponse({"error": "Cantidad debe ser mayor a 0"}, status=400)

        try:
            product = Product.objects.get(pk=product_id, barbershop__organization=request.organization, is_active=True)
            barbershop = product.barbershop
        except Product.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        from apps.accounts.models import Barbershop
        try:
            barbershop_destiny = Barbershop.objects.get(
                pk=barbershop_destiny_id, organization=request.organization, is_active=True
            )
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal de destino no válida"}, status=400)

        try:
            movement = process_transfer(
                barbershop_origin=barbershop,
                barbershop_destiny=barbershop_destiny,
                user=request.user,
                items=[{"product_id": int(product_id), "quantity": int(quantity)}],
                notes=notes,
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({
            "message": "Transferencia procesada",
            "movement_id": movement.pk,
        }, status=201)


class BulkTransferAPI(View):
    """API para procesar transferencia múltiple."""

    def post(self, request):
        org = request.organization
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        items = data.get("items", [])
        notes = data.get("notes", "")
        barbershop_origin_id = data.get("barbershop_origin_id")
        barbershop_destiny_id = data.get("barbershop_destiny_id")

        if not barbershop_origin_id:
            return JsonResponse({"error": "Sucursal de origen requerida"}, status=400)
        if not barbershop_destiny_id:
            return JsonResponse({"error": "Sucursal de destino requerida"}, status=400)
        if not items:
            return JsonResponse({"error": "No se proporcionaron ítems"}, status=400)

        from apps.accounts.models import Barbershop
        try:
            barbershop_origin = Barbershop.objects.get(
                pk=barbershop_origin_id, organization=org, is_active=True
            )
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal de origen no válida"}, status=400)

        try:
            barbershop_destiny = Barbershop.objects.get(
                pk=barbershop_destiny_id, organization=org, is_active=True
            )
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal de destino no válida"}, status=400)

        try:
            movement = process_transfer(
                barbershop_origin=barbershop_origin,
                barbershop_destiny=barbershop_destiny,
                user=request.user,
                items=items,
                notes=notes,
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({
            "message": "Transferencia múltiple procesada",
            "movement_id": movement.pk,
            "total_items": movement.items.count(),
        }, status=201)


class MovementHistoryAPI(View):
    """API para historial de movimientos con paginación (30 por página)."""

    def get(self, request):
        from django.core.paginator import Paginator

        org = request.organization
        qs = (
            InventoryMovement.objects
            .filter(barbershop_destiny__organization=org)
            .select_related("barbershop_destiny", "created_by")
            .prefetch_related("items__product")
            .order_by("-created_at")
        )

        paginator = Paginator(qs, 30)
        page_num = request.GET.get("page", 1)
        page = paginator.get_page(page_num)

        results = []
        for m in page:
            user_name = ""
            if m.created_by:
                user_name = " ".join(filter(None, [m.created_by.first_name, m.created_by.last_name])) or "Sistema"

            items_data = []
            for item in m.items.all():
                items_data.append({
                    "product_id": item.product.pk,
                    "product_name": item.product.name,
                    "quantity": item.quantity,
                    "stock_previous": item.stock_previous,
                    "stock_resulting": item.stock_resulting,
                })

            results.append({
                "id": m.pk,
                "movement_type": m.movement_type,
                "movement_type_display": m.get_movement_type_display(),
                "barbershop_origin": m.barbershop_origin.name if m.barbershop_origin else None,
                "barbershop_destiny": m.barbershop_destiny.name if m.barbershop_destiny else None,
                "notes": m.notes,
                "created_at": m.created_at.isoformat(),
                "created_by": user_name,
                "items": items_data,
            })

        return JsonResponse({
            "results": results,
            "page": page.number,
            "has_next": page.has_next(),
        })
