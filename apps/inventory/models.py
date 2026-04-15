"""
Inventory models – product stock per barbershop.

ProductCategory  – grouping (e.g., ceras, aceites, shampoos)
Product          – a physical product for sale
StockMovement    – every stock change is tracked (in/out)
"""

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator

from apps.core.models import TenantModel, AuditModel


class ProductCategory(TenantModel):
    name = models.CharField("nombre", max_length=80)
    description = models.TextField("descripción", blank=True)

    class Meta:
        db_table = "inventory_category"
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(TenantModel):
    """A physical product available for sale at a barbershop."""

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField("nombre", max_length=120)
    description = models.TextField("descripción", blank=True)
    sku = models.CharField("SKU", max_length=50, blank=True)
    price = models.DecimalField(
        "precio venta", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    cost = models.DecimalField(
        "costo", max_digits=10, decimal_places=2,
        default=0, validators=[MinValueValidator(0)],
    )
    stock_quantity = models.IntegerField(
        "cantidad en stock", default=0,
        help_text="Se actualiza automáticamente con cada movimiento.",
    )
    low_stock_threshold = models.PositiveIntegerField(
        "alerta stock bajo", default=5,
    )
    photo = models.ImageField(upload_to="products/", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "inventory_product"
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (stock: {self.stock_quantity})"

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold


class HistorialPrecioProducto(models.Model):
    """Tracks price and cost changes for a product over time."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="price_history",
    )
    price = models.DecimalField(
        "precio venta", max_digits=10, decimal_places=2,
    )
    cost = models.DecimalField(
        "costo", max_digits=10, decimal_places=2,
    )
    changed_at = models.DateTimeField("fecha de cambio", auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "inventory_historial_precio_producto"
        verbose_name = "historial de precio de producto"
        verbose_name_plural = "historial de precios de producto"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.product.name}: ${self.price} / ${self.cost} @ {self.changed_at:%d/%m/%Y}"


class StockMovement(AuditModel):
    """
    Immutable log of every stock change.
    Positive quantity = restock, negative = sale/loss.
    """

    class Reason(models.TextChoices):
        RESTOCK = "restock", "Reabastecimiento"
        SALE = "sale", "Venta"
        ADJUSTMENT = "adjustment", "Ajuste"
        LOSS = "loss", "Pérdida"
        RETURN = "return", "Devolución"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="movements",
    )
    quantity = models.IntegerField(
        "cantidad",
        help_text="Positivo = entrada, negativo = salida.",
    )
    reason = models.CharField(
        "motivo", max_length=15, choices=Reason.choices,
    )
    notes = models.TextField("notas", blank=True)
    resulting_stock = models.IntegerField(
        "stock resultante",
        help_text="Stock del producto después de este movimiento.",
    )

    class Meta:
        db_table = "inventory_stock_movement"
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        ordering = ["-created_at"]

    def __str__(self):
        sign = "+" if self.quantity > 0 else ""
        return f"{self.product.name} {sign}{self.quantity} ({self.reason})"

    def save(self, *args, **kwargs):
        # Update product stock
        self.product.stock_quantity += self.quantity
        self.resulting_stock = self.product.stock_quantity
        self.product.save(update_fields=["stock_quantity"])
        super().save(*args, **kwargs)
