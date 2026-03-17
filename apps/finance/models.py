"""
Finance models – tracks all revenue (services + product sales).

Sale      – a financial transaction
SaleItem  – line items (service from appointment OR product)
"""

from django.db import models
from django.core.validators import MinValueValidator

from apps.core.models import TenantModel


class Sale(TenantModel):
    """
    A financial transaction. Linked to an appointment (service revenue)
    or standalone (product-only sale).
    """

    class SaleType(models.TextChoices):
        SERVICE = "service", "Servicio"
        PRODUCT = "product", "Venta de producto"
        MIXED = "mixed", "Mixta"

    appointment = models.OneToOneField(
        "scheduling.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sale",
        help_text="Vinculada a una cita completada.",
    )
    barber = models.ForeignKey(
        "accounts.BarberProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    sale_type = models.CharField(
        "tipo", max_length=10, choices=SaleType.choices,
    )
    subtotal = models.DecimalField(
        "subtotal", max_digits=12, decimal_places=2, default=0,
    )
    discount = models.DecimalField(
        "descuento", max_digits=12, decimal_places=2, default=0,
    )
    total = models.DecimalField(
        "total", max_digits=12, decimal_places=2, default=0,
    )
    notes = models.TextField("notas", blank=True)
    completed_at = models.DateTimeField("fecha cierre", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "finance_sale"
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        ordering = ["-completed_at"]
        indexes = [
            models.Index(fields=["barbershop", "completed_at"]),
        ]

    def __str__(self):
        return f"Venta #{self.pk} – ${self.total}"

    def recalculate(self):
        self.subtotal = sum(item.line_total for item in self.items.all())
        self.total = self.subtotal - self.discount
        self.save(update_fields=["subtotal", "total"])


class SaleItem(models.Model):
    """
    A line item within a sale.
    Either a service (from the appointment) or a product.
    """

    class ItemType(models.TextChoices):
        SERVICE = "service", "Servicio"
        PRODUCT = "product", "Producto"

    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_type = models.CharField(
        "tipo", max_length=10, choices=ItemType.choices,
    )

    # Service reference (nullable)
    service = models.ForeignKey(
        "scheduling.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Product reference (nullable)
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    description = models.CharField("descripción", max_length=200)
    quantity = models.PositiveIntegerField("cantidad", default=1)
    unit_price = models.DecimalField(
        "precio unitario", max_digits=10, decimal_places=2,
    )

    class Meta:
        db_table = "finance_sale_item"
        verbose_name = "ítem de venta"
        verbose_name_plural = "ítems de venta"

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.description} x{self.quantity} = ${self.line_total}"
