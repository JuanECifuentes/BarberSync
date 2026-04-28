"""
Inventory business logic – stock movements, restocks, transfers.
"""

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import (
    InventoryMovement,
    InventoryMovementItem,
    Product,
    StockMovement,
)


def process_restock(barbershop, user, items, notes=""):
    """
    Atomically processes a restock movement.

    Args:
        barbershop: Barbershop (destination branch).
        user: User performing the action.
        items: list of dicts [{"product_id": int, "quantity": int}, ...].
        notes: optional text note.

    Returns:
        InventoryMovement instance.

    Raises:
        ValueError if a product is not found or quantity is invalid.
    """
    if not items:
        raise ValueError("No se proporcionaron ítems para reestock.")

    movement = None

    with transaction.atomic():
        movement = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.RESTOCK,
            barbershop_origin=None,
            barbershop_destiny=barbershop,
            notes=notes,
            created_by=user,
            updated_by=user,
        )

        for item in items:
            product_id = item["product_id"]
            quantity = int(item["quantity"])

            if quantity <= 0:
                raise ValueError(f"Cantidad inválida para producto ID {product_id}.")

            try:
                product = Product.objects.select_for_update().get(
                    pk=product_id, barbershop=barbershop, is_active=True
                )
            except Product.DoesNotExist:
                raise ValueError(f"Producto ID {product_id} no encontrado o inactivo.")

            stock_previous = product.stock_quantity
            stock_resulting = stock_previous + quantity

            # Let StockMovement.save() handle updating product.stock_quantity.
            product.updated_by = user
            product.save(update_fields=["updated_by"])

            # Create movement line
            InventoryMovementItem.objects.create(
                movement=movement,
                product=product,
                quantity=quantity,
                stock_previous=stock_previous,
                stock_resulting=stock_resulting,
            )

            # Audit log via StockMovement (append-only)
            StockMovement.objects.create(
                product=product,
                quantity=quantity,
                reason=StockMovement.Reason.RESTOCK,
                notes=notes,
                resulting_stock=stock_resulting,
                created_by=user,
                updated_by=user,
            )

    return movement


def process_bulk_restock(barbershop, user, items, notes=""):
    """
    Atomically processes a restock with multiple products.

    Same as process_restock but called explicitly for bulk operations.
    Currently identical – kept separate for future transfer logic.
    """
    return process_restock(barbershop, user, items, notes)


def process_transfer(barbershop_origin, barbershop_destiny, user, items, notes=""):
    """
    Atomically processes a transfer movement between two branches.

    Args:
        barbershop_origin: Barbershop (source branch).
        barbershop_destiny: Barbershop (destination branch).
        user: User performing the action.
        items: list of dicts [{"product_id": int, "quantity": int}, ...].
        notes: optional text note.

    Returns:
        InventoryMovement instance.

    Raises:
        ValueError if a product is not found, quantity is invalid, or
        stock is insufficient at origin.
    """
    if not items:
        raise ValueError("No se proporcionaron ítems para transferencia.")

    if barbershop_origin.pk == barbershop_destiny.pk:
        raise ValueError("La sucursal de origen y destino no pueden ser la misma.")

    movement = None

    with transaction.atomic():
        movement = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.TRANSFER,
            barbershop_origin=barbershop_origin,
            barbershop_destiny=barbershop_destiny,
            notes=notes,
            created_by=user,
            updated_by=user,
        )

        for item in items:
            product_id = item["product_id"]
            quantity = int(item["quantity"])

            if quantity <= 0:
                raise ValueError(f"Cantidad inválida para producto ID {product_id}.")

            # Lock origin product for update
            try:
                product_origin = Product.objects.select_for_update().get(
                    pk=product_id, barbershop=barbershop_origin, is_active=True
                )
            except Product.DoesNotExist:
                raise ValueError(f"Producto ID {product_id} no encontrado o inactivo en la sucursal de origen.")

            stock_previous_origin = product_origin.stock_quantity
            if stock_previous_origin < quantity:
                raise ValueError(
                    f"Stock insuficiente para '{product_origin.name}'. "
                    f"Disponible: {stock_previous_origin}, solicitado: {quantity}."
                )

            # Subtract from origin
            product_origin.updated_by = user
            product_origin.save(update_fields=["updated_by"])

            stock_resulting_origin = stock_previous_origin - quantity

            # StockMovement for origin (negative = outbound)
            StockMovement.objects.create(
                product=product_origin,
                quantity=-quantity,
                reason=StockMovement.Reason.TRANSFER,
                notes=notes,
                resulting_stock=stock_resulting_origin,
                created_by=user,
                updated_by=user,
            )

            # Try to find product at destination
            product_destiny = Product.objects.filter(
                pk=product_id, barbershop=barbershop_destiny, is_active=True
            ).first()

            if product_destiny:
                # Lock destination product for update
                product_destiny = Product.objects.select_for_update().get(
                    pk=product_id, barbershop=barbershop_destiny, is_active=True
                )
                stock_previous_destiny = product_destiny.stock_quantity
                stock_resulting_destiny = stock_previous_destiny + quantity
            else:
                # Product doesn't exist at destination — create it
                stock_previous_destiny = 0
                stock_resulting_destiny = quantity
                product_destiny = Product.objects.create(
                    barbershop=barbershop_destiny,
                    category=product_origin.category,
                    name=product_origin.name,
                    description=product_origin.description,
                    sku=product_origin.sku,
                    price=product_origin.price,
                    cost=product_origin.cost,
                    stock_quantity=stock_resulting_destiny,
                    low_stock_threshold=product_origin.low_stock_threshold,
                    updated_by=user,
                )

            # Record movement item
            InventoryMovementItem.objects.create(
                movement=movement,
                product=product_origin,
                quantity=quantity,
                stock_previous=stock_previous_origin,
                stock_resulting=stock_resulting_origin,
            )

            # StockMovement will update destination product stock automatically
            # via StockMovement.save() -> product.save(update_fields=["stock_quantity"])
            StockMovement.objects.create(
                product=product_destiny,
                quantity=quantity,
                reason=StockMovement.Reason.TRANSFER,
                notes=notes,
                resulting_stock=stock_resulting_destiny,
                created_by=user,
                updated_by=user,
            )

    return movement