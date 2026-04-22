"""
Intervenciones views – CRUD and ag-Grid API.
"""

import json
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import F, Q, Prefetch, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import BarberProfile, Barbershop
from apps.clients.models import Client
from apps.inventory.models import Product, ProductCategory, StockMovement
from .models import (
    CategoriaServicio, Intervencion, IntervencionProducto,
    IntervencionServicio, Service, ServicioProducto,
)


# ─────────────────────────────────────────────
# Main list page (renders the ag-Grid template)
# ─────────────────────────────────────────────
class IntervencionListView(LoginRequiredMixin, TemplateView):
    template_name = "intervenciones/intervencion_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        barbershop = self.request.barbershop

        ctx["barbers"] = BarberProfile.objects.filter(
            Q(membership__barbershop=barbershop) | Q(sucursales=barbershop),
            is_active=True,
        ).select_related("membership__user").distinct()
        services = Service.objects.filter(
            barbershop=barbershop, is_active=True,
        ).select_related("category")
        ctx["services"] = services
        ctx["estados"] = Intervencion.Estado.choices
        ctx["sucursales"] = Barbershop.objects.filter(organization=org)
        ctx["sucursal_name"] = str(barbershop)
        ctx["current_barbershop_id"] = barbershop.pk

        # Group services by category for accordion display in modals
        grouped = OrderedDict()
        for svc_obj in services:
            cat_name = svc_obj.category.name if svc_obj.category else "Sin Categoría"
            cat_id = svc_obj.category.pk if svc_obj.category else ""
            if cat_name not in grouped:
                grouped[cat_name] = {"category_id": cat_id, "services": []}
            grouped[cat_name]["services"].append(svc_obj)
        ctx["grouped_services"] = grouped

        # Products grouped by category for the product selector
        products = Product.objects.filter(
            barbershop=barbershop, is_active=True,
        ).select_related("category").order_by("category__name", "name")
        grouped_products = OrderedDict()
        for prod in products:
            cat_name = prod.category.name if prod.category else "Sin Categoría"
            if cat_name not in grouped_products:
                grouped_products[cat_name] = []
            grouped_products[cat_name].append(prod)
        ctx["grouped_products"] = grouped_products

        return ctx


# ─────────────────────────────────────────────
# ag-Grid API: filtrado, ordenamiento, paginación
# ─────────────────────────────────────────────
class IntervencionGridAPI(LoginRequiredMixin, View):
    """
    API endpoint for ag-Grid infinite row model.
    Supports external filters: multi-select checkboxes, date range, price range.
    """

    def get(self, request):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        org = barbershop.organization
        qs = Intervencion.objects.filter(
            barbershop__organization=org,
        ).select_related(
            "barber__membership__user", "client",
        ).prefetch_related(
            Prefetch(
                "servicios",
                queryset=IntervencionServicio.objects.select_related("servicio"),
            ),
            Prefetch(
                "productos_usados",
                queryset=IntervencionProducto.objects.select_related("producto"),
            ),
        )

        # ── Filtros externos (multi-select checkboxes) ──

        # Barberos (comma-separated IDs)
        filter_barberos = request.GET.get("filter_barberos", "").strip()
        if filter_barberos:
            ids = [int(x) for x in filter_barberos.split(",") if x.strip().isdigit()]
            if ids:
                qs = qs.filter(barber_id__in=ids)

        # Servicios (comma-separated IDs or "venta") – intervenciones que contengan AL MENOS uno
        filter_servicios = request.GET.get("filter_servicios", "").strip()
        if filter_servicios:
            values = [v.strip() for v in filter_servicios.split(",") if v.strip()]
            has_venta = "venta" in values
            ids = [int(x) for x in values if x.isdigit()]
            if has_venta and ids:
                qs = qs.filter(
                    Q(servicios__servicio_id__in=ids) | Q(servicios__isnull=True)
                ).distinct()
            elif has_venta:
                qs = qs.filter(servicios__isnull=True)
            elif ids:
                qs = qs.filter(servicios__servicio_id__in=ids).distinct()

        # Sucursales (comma-separated IDs)
        filter_sucursales = request.GET.get("filter_sucursales", "").strip()
        if filter_sucursales:
            ids = [int(x) for x in filter_sucursales.split(",") if x.strip().isdigit()]
            if ids:
                qs = qs.filter(barbershop_id__in=ids)

        # Estados (comma-separated values)
        filter_estados = request.GET.get("filter_estados", "").strip()
        if filter_estados:
            vals = [v.strip() for v in filter_estados.split(",") if v.strip()]
            if vals:
                qs = qs.filter(estado__in=vals)

        # ── Filtros de rango ──

        # Fecha rango
        filter_fecha_desde = request.GET.get("filter_fecha_desde", "").strip()
        if filter_fecha_desde:
            qs = qs.filter(fecha__date__gte=filter_fecha_desde)

        filter_fecha_hasta = request.GET.get("filter_fecha_hasta", "").strip()
        if filter_fecha_hasta:
            qs = qs.filter(fecha__date__lte=filter_fecha_hasta)

        # Precio total rango (requires annotation — services + products)
        filter_total_min = request.GET.get("filter_total_min", "").strip()
        filter_total_max = request.GET.get("filter_total_max", "").strip()
        if filter_total_min or filter_total_max:
            qs = qs.annotate(
                _total_servicios=Coalesce(Sum("servicios__precio_cobrado"), Value(Decimal("0"))),
                _total_productos=Coalesce(
                    Sum(
                        F("productos_usados__cantidad") * F("productos_usados__precio_unitario"),
                        filter=Q(productos_usados__incluido_en_precio=False),
                    ),
                    Value(Decimal("0")),
                ),
                _precio_total=F("_total_servicios") + F("_total_productos"),
            )
            if filter_total_min:
                try:
                    qs = qs.filter(_precio_total__gte=Decimal(filter_total_min))
                except (InvalidOperation, ValueError):
                    pass
            if filter_total_max:
                try:
                    qs = qs.filter(_precio_total__lte=Decimal(filter_total_max))
                except (InvalidOperation, ValueError):
                    pass

        # ── Ordenamiento ──
        sort_field = request.GET.get("sort", "fecha")
        sort_order = request.GET.get("order", "desc")

        sort_map = {
            "fecha": "fecha",
            "cliente": "client__name",
            "barbero": "barber__membership__user__first_name",
            "estado": "estado",
            "sucursal": "barbershop__name",
        }
        db_field = sort_map.get(sort_field, "fecha")
        if sort_order == "desc":
            db_field = f"-{db_field}"
        qs = qs.order_by(db_field)

        # ── Paginación ──
        total_count = qs.count()

        try:
            start_row = int(request.GET.get("startRow", 0))
            end_row = int(request.GET.get("endRow", 30))
        except (ValueError, TypeError):
            start_row, end_row = 0, 30

        page = qs[start_row:end_row]

        # ── Serializar ──
        rows = []
        for inv in page:
            servicios = list(inv.servicios.all())
            productos = list(inv.productos_usados.all())
            total_servicios = sum(s.precio_cobrado for s in servicios)
            total_productos = sum(p.cantidad * p.precio_unitario for p in productos if not p.incluido_en_precio)
            total = total_servicios + total_productos
            fecha_local = timezone.localtime(inv.fecha) if inv.fecha else None

            rows.append({
                "id": inv.pk,
                "fecha": fecha_local.strftime("%d/%m/%Y %H:%M") if fecha_local else "",
                "fecha_iso": fecha_local.isoformat() if fecha_local else "",
                "cliente": inv.client.name if inv.client else "",
                "cliente_id": inv.client_id,
                "barbero": str(inv.barber) if inv.barber else "",
                "barbero_id": inv.barber_id,
                "servicios": [
                    {"nombre": s.servicio.name, "precio": str(s.precio_cobrado)}
                    for s in servicios
                ],
                "productos": [
                    {"nombre": p.producto.name, "cantidad": p.cantidad, "precio": str(p.precio_unitario), "incluido": p.incluido_en_precio}
                    for p in productos
                ],
                "sucursal": str(inv.barbershop) if inv.barbershop else "",
                "precio_total": str(total),
                "precio_total_fmt": f"${_format_money(total)}",
                "estado": inv.estado,
                "estado_display": inv.get_estado_display(),
                "notas": inv.notas,
            })

        last_row = total_count if end_row >= total_count else -1
        return JsonResponse({"rows": rows, "lastRow": last_row})


def _format_money(value):
    """Format number with dot as thousands separator (Colombian style)."""
    try:
        rounded = int(Decimal(str(value)).quantize(Decimal("1")))
        return f"{rounded:,}".replace(",", ".")
    except Exception:
        return str(value)


def _freeze_product_prices(intervencion):
    """Freeze product prices to current catalog price when intervention is completed.
    Must be called inside transaction.atomic()."""
    for ip in intervencion.productos_usados.select_related("producto").all():
        ip.precio_unitario = ip.producto.price
        ip.save(update_fields=["precio_unitario"])


def _deduct_stock(intervencion, user):
    """Deduct stock for all products in an intervention. Must be called inside transaction.atomic()."""
    for ip in intervencion.productos_usados.select_related("producto").all():
        product = Product.objects.select_for_update().get(pk=ip.producto_id)
        StockMovement(
            product=product,
            quantity=-ip.cantidad,
            reason=StockMovement.Reason.SALE,
            notes=f"Intervención #{intervencion.pk}",
            resulting_stock=0,  # will be set by save()
            updated_by=user,
        ).save()


def _restore_stock(intervencion, user):
    """Restore stock for all products in an intervention (for edits/deletes). Must be called inside transaction.atomic()."""
    for ip in intervencion.productos_usados.select_related("producto").all():
        product = Product.objects.select_for_update().get(pk=ip.producto_id)
        StockMovement(
            product=product,
            quantity=ip.cantidad,
            reason=StockMovement.Reason.ADJUSTMENT,
            notes=f"Reversión Intervención #{intervencion.pk}",
            resulting_stock=0,
            updated_by=user,
        ).save()


# ─────────────────────────────────────────────
# Crear intervención (POST JSON)
# ─────────────────────────────────────────────
class IntervencionCreateView(LoginRequiredMixin, View):

    def post(self, request):
        barbershop = request.barbershop
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        barber_id = data.get("barber_id")
        client_id = data.get("client_id")
        service_ids = data.get("service_ids", [])
        producto_items = data.get("productos", [])
        notas = data.get("notas", "")
        fecha_str = data.get("fecha")
        estado = data.get("estado", Intervencion.Estado.PENDIENTE)
        sucursal_id = data.get("sucursal_id")

        # Venta directa: allow no services if at least one product
        if not barber_id or not client_id:
            return JsonResponse({"error": "Faltan campos requeridos"}, status=400)
        if not service_ids and not producto_items:
            return JsonResponse({"error": "Debe incluir al menos un servicio o un producto"}, status=400)

        if estado not in dict(Intervencion.Estado.choices):
            estado = Intervencion.Estado.PENDIENTE

        # Resolve target barbershop (sucursal)
        target_barbershop = barbershop
        if sucursal_id:
            target_barbershop = Barbershop.objects.filter(
                pk=sucursal_id, organization=barbershop.organization,
            ).first() or barbershop

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop=barbershop,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        client = Client.objects.filter(
            pk=client_id, organization=barbershop.organization,
        ).first()
        if not client:
            return JsonResponse({"error": "Cliente no encontrado"}, status=404)

        try:
            fecha = datetime.fromisoformat(fecha_str) if fecha_str else timezone.now()
            if timezone.is_naive(fecha):
                fecha = timezone.make_aware(fecha)
        except (ValueError, TypeError):
            fecha = timezone.now()

        services = Service.objects.filter(
            pk__in=service_ids, barbershop=barbershop, is_active=True,
        ) if service_ids else Service.objects.none()

        if service_ids and not services.exists():
            return JsonResponse({"error": "No se encontraron servicios válidos"}, status=400)

        from datetime import timedelta
        total_duration = sum(s.duration_minutes for s in services)
        fecha_fin = fecha + timedelta(minutes=total_duration) if total_duration else fecha

        with transaction.atomic():
            intervencion = Intervencion.objects.create(
                barbershop=target_barbershop,
                barber=barber,
                client=client,
                estado=estado,
                fecha=fecha,
                fecha_fin=fecha_fin,
                notas=notas,
                updated_by=request.user,
            )

            for service in services:
                is_svc = IntervencionServicio.objects.create(
                    intervencion=intervencion,
                    servicio=service,
                    precio_cobrado=service.price,
                )

            # Explicit products from the modal
            for item in producto_items:
                prod_id = item.get("producto_id")
                cantidad = int(item.get("cantidad", 1))
                if not prod_id or cantidad <= 0:
                    continue
                product = Product.objects.select_for_update().filter(
                    pk=prod_id, barbershop=target_barbershop, is_active=True,
                ).first()
                if not product:
                    continue
                # Respect incluido_en_precio from modal; default False
                incluido = bool(item.get("incluido_en_precio", False))
                IntervencionProducto.objects.create(
                    intervencion=intervencion,
                    intervencion_servicio=None,
                    producto=product,
                    cantidad=cantidad,
                    precio_unitario=product.price,
                    incluido_en_precio=incluido,
                )

            # Auto-consume products linked to services via ServicioProducto
            for service in services:
                is_svc = IntervencionServicio.objects.filter(
                    intervencion=intervencion, servicio=service,
                ).first()
                for sp in service.productos_consumidos.select_related("producto").filter(producto__is_active=True):
                    product = Product.objects.select_for_update().get(pk=sp.producto_id)
                    # Check if already added explicitly; if so, add to existing quantity
                    existing = IntervencionProducto.objects.filter(
                        intervencion=intervencion, producto=product,
                    ).first()
                    if existing:
                        existing.cantidad += sp.cantidad_consumida
                        existing.save(update_fields=["cantidad"])
                    else:
                        IntervencionProducto.objects.create(
                            intervencion=intervencion,
                            intervencion_servicio=is_svc,
                            producto=product,
                            cantidad=sp.cantidad_consumida,
                            precio_unitario=product.price,
                            incluido_en_precio=sp.incluido_en_precio,
                        )

            # Deduct stock for all products used
            _deduct_stock(intervencion, request.user)

        return JsonResponse({
            "message": "Intervención creada",
            "id": intervencion.pk,
        }, status=201)


# ─────────────────────────────────────────────
# Editar intervención (PUT JSON)
# ─────────────────────────────────────────────
class IntervencionUpdateView(LoginRequiredMixin, View):

    def put(self, request, pk):
        barbershop = request.barbershop
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop__organization=org,
        )
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        barber_id = data.get("barber_id")
        client_id = data.get("client_id")
        service_ids = data.get("service_ids", [])
        producto_items = data.get("productos", [])
        notas = data.get("notas", "")
        fecha_str = data.get("fecha")
        estado = data.get("estado")
        sucursal_id = data.get("sucursal_id")

        if not barber_id or not client_id:
            return JsonResponse({"error": "Faltan campos requeridos"}, status=400)
        if not service_ids and not producto_items:
            return JsonResponse({"error": "Debe incluir al menos un servicio o un producto"}, status=400)

        # Resolve target barbershop (sucursal)
        target_barbershop = intervencion.barbershop
        if sucursal_id:
            resolved = Barbershop.objects.filter(
                pk=sucursal_id, organization=org,
            ).first()
            if resolved:
                target_barbershop = resolved

        barber = BarberProfile.objects.filter(
            pk=barber_id, membership__barbershop__organization=org,
        ).first()
        if not barber:
            return JsonResponse({"error": "Barbero no encontrado"}, status=404)

        client = Client.objects.filter(
            pk=client_id, organization=org,
        ).first()
        if not client:
            return JsonResponse({"error": "Cliente no encontrado"}, status=404)

        try:
            fecha = datetime.fromisoformat(fecha_str) if fecha_str else intervencion.fecha
            if timezone.is_naive(fecha):
                fecha = timezone.make_aware(fecha)
        except (ValueError, TypeError):
            fecha = intervencion.fecha

        services = Service.objects.filter(
            pk__in=service_ids, barbershop__organization=org, is_active=True,
        ) if service_ids else Service.objects.none()

        if service_ids and not services.exists():
            return JsonResponse({"error": "No se encontraron servicios válidos"}, status=400)

        from datetime import timedelta
        total_duration = sum(s.duration_minutes for s in services)
        fecha_fin = fecha + timedelta(minutes=total_duration) if total_duration else fecha

        with transaction.atomic():
            # Restore stock from previous products before replacing
            _restore_stock(intervencion, request.user)

            intervencion.barbershop = target_barbershop
            intervencion.barber = barber
            intervencion.client = client
            intervencion.fecha = fecha
            intervencion.fecha_fin = fecha_fin
            intervencion.notas = notas
            intervencion.updated_by = request.user

            if estado and estado in dict(Intervencion.Estado.choices):
                intervencion.estado = estado
                if estado == Intervencion.Estado.REALIZADA and not intervencion.fecha_fin:
                    intervencion.fecha_fin = timezone.now()

            intervencion.save()

            # Replace services
            intervencion.servicios.all().delete()
            for service in services:
                IntervencionServicio.objects.create(
                    intervencion=intervencion,
                    servicio=service,
                    precio_cobrado=service.price,
                )

            # Replace products — the modal sends ALL products (including auto-consumed),
            # so we just save exactly what the user submitted without auto-adding.
            intervencion.productos_usados.all().delete()

            for item in producto_items:
                prod_id = item.get("producto_id")
                cantidad = int(item.get("cantidad", 1))
                if not prod_id or cantidad <= 0:
                    continue
                # Allow both active and inactive (deleted) products in edits
                # Deleted products are kept as historical records (readonly in UI)
                product = Product.objects.select_for_update().filter(
                    pk=prod_id, barbershop=target_barbershop,
                ).first()
                if not product:
                    continue
                IntervencionProducto.objects.create(
                    intervencion=intervencion,
                    producto=product,
                    cantidad=cantidad,
                    precio_unitario=product.price,
                    incluido_en_precio=bool(item.get("incluido_en_precio", False)),
                )

            # Deduct stock only for active products
            for ip in intervencion.productos_usados.select_related("producto").all():
                if not ip.producto.is_active:
                    continue
                product = Product.objects.select_for_update().get(pk=ip.producto_id)
                StockMovement(
                    product=product,
                    quantity=-ip.cantidad,
                    reason=StockMovement.Reason.SALE,
                    notes=f"Intervención #{intervencion.pk}",
                    resulting_stock=0,
                    updated_by=request.user,
                ).save()

        return JsonResponse({"message": "Intervención actualizada", "id": intervencion.pk})


# ─────────────────────────────────────────────
# Eliminar intervención (DELETE)
# ─────────────────────────────────────────────
class IntervencionDeleteView(LoginRequiredMixin, View):

    def delete(self, request, pk):
        barbershop = request.barbershop
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop__organization=org,
        )
        with transaction.atomic():
            _restore_stock(intervencion, request.user)
            intervencion.delete()
        return JsonResponse({"message": "Intervención eliminada"})


# ─────────────────────────────────────────────
# Cambiar estado (POST JSON)
# ─────────────────────────────────────────────
class IntervencionChangeStatusAPI(LoginRequiredMixin, View):
    def post(self, request, pk):
        barbershop = request.barbershop
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion, pk=pk, barbershop__organization=org,
        )
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        nuevo_estado = data.get("estado")
        if nuevo_estado not in dict(Intervencion.Estado.choices):
            return JsonResponse({"error": "Estado inválido"}, status=400)

        with transaction.atomic():
            intervencion.estado = nuevo_estado
            if nuevo_estado == Intervencion.Estado.REALIZADA:
                if not intervencion.fecha_fin:
                    intervencion.fecha_fin = timezone.now()
                # Freeze product prices at the moment of completion
                _freeze_product_prices(intervencion)
            intervencion.updated_by = request.user
            intervencion.save()

        return JsonResponse({"message": f"Estado actualizado a {intervencion.get_estado_display()}"})


# ─────────────────────────────────────────────
# Datos para formulario (barberos + servicios)
# ─────────────────────────────────────────────
class IntervencionDataAPI(LoginRequiredMixin, View):

    def get(self, request):
        barbershop = request.barbershop
        if not barbershop:
            return JsonResponse({"error": "Sin barbería"}, status=403)

        barbers = BarberProfile.objects.filter(
            membership__barbershop=barbershop, is_active=True,
        ).select_related("membership__user")

        services = Service.objects.filter(
            barbershop=barbershop, is_active=True,
        )

        sucursales = Barbershop.objects.filter(
            organization=barbershop.organization,
        )

        return JsonResponse({
            "barbers": [
                {"id": b.pk, "name": str(b)}
                for b in barbers
            ],
            "services": [
                {"id": s.pk, "name": s.name, "price": str(s.price), "duration": s.duration_minutes}
                for s in services
            ],
            "sucursales": [
                {"id": s.pk, "name": s.name}
                for s in sucursales
            ],
        })


# ─────────────────────────────────────────────
# Detalle de intervención (GET JSON)
# ─────────────────────────────────────────────
class IntervencionDetailAPI(LoginRequiredMixin, View):

    def get(self, request, pk):
        barbershop = request.barbershop
        org = barbershop.organization
        intervencion = get_object_or_404(
            Intervencion.objects.select_related(
                "barber__membership__user", "client",
            ).prefetch_related(
                "servicios__servicio",
                "productos_usados__producto",
            ),
            pk=pk,
            barbershop__organization=org,
        )

        servicios = list(intervencion.servicios.all())
        productos = list(intervencion.productos_usados.all())

        # Identify auto-consumed products (from ServicioProducto links)
        auto_product_ids = set()
        for s in servicios:
            for sp in ServicioProducto.objects.filter(servicio_id=s.servicio_id):
                auto_product_ids.add(sp.producto_id)

        return JsonResponse({
            "id": intervencion.pk,
            "barber_id": intervencion.barber_id,
            "barbero": str(intervencion.barber),
            "client_id": intervencion.client_id,
            "cliente": intervencion.client.name,
            "fecha": timezone.localtime(intervencion.fecha).strftime("%Y-%m-%dT%H:%M") if intervencion.fecha else "",
            "estado": intervencion.estado,
            "notas": intervencion.notas,
            "sucursal_id": intervencion.barbershop_id,
            "service_ids": [s.servicio_id for s in servicios],
            "servicios": [
                {"id": s.servicio_id, "nombre": s.servicio.name, "precio": str(s.precio_cobrado)}
                for s in servicios
            ],
            "productos": [
                {"producto_id": p.producto_id, "nombre": p.producto.name,
                 "cantidad": p.cantidad, "precio": str(p.precio_unitario),
                 "auto": p.producto_id in auto_product_ids,
                 "is_deleted": not p.producto.is_active,
                 "incluido": p.incluido_en_precio}
                for p in productos
            ],
        })
