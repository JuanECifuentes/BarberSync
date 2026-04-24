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

            # Update product stock
            product.stock_quantity = stock_resulting
            product.save(update_fields=["stock_quantity", "updated_by"])

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