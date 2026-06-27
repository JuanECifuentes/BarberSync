from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    features = models.JSONField(default=list)
    max_barbers = models.PositiveIntegerField(null=True, blank=True)
    max_branches = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_plan"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class PlanPrice(models.Model):
    PROVIDER_CHOICES = [
        ("stripe", "Stripe"),
        ("wompi", "Wompi"),
    ]
    INTERVAL_CHOICES = [
        ("month", "Mensual"),
        ("year", "Anual"),
    ]
    # Cantidad de intervalos facturados en un ciclo:
    #   month × 1  = mensual
    #   month × 3  = trimestral (3 meses por adelantado)
    #   month × 12 = anual (12 meses por adelantado)
    INTERVAL_COUNT_MONTHS = [(1, "1 mes"), (3, "3 meses"), (12, "12 meses")]

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="prices")
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    interval = models.CharField(max_length=10, choices=INTERVAL_CHOICES)
    interval_count = models.PositiveIntegerField(
        default=1,
        help_text="Cantidad de intervalos por ciclo (1, 3 o 12 para month).",
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    provider_price_id = models.CharField(max_length=100)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "billing_plan_price"
        ordering = ["-is_current", "-valid_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "provider", "currency", "interval", "interval_count"],
                condition=models.Q(is_current=True),
                name="unique_active_price_per_plan_provider_interval",
            ),
        ]
        indexes = [
            models.Index(fields=["plan", "is_current"]),
            models.Index(
                fields=["plan", "provider", "interval", "interval_count", "is_current"],
                name="bp_interval_idx",
            ),
            models.Index(fields=["provider", "provider_price_id"]),
        ]

    def __str__(self):
        return (
            f"{self.plan.code} – {self.amount_minor} {self.currency}/"
            f"{self.interval}×{self.interval_count} ({self.provider})"
        )

    @property
    def months_in_cycle(self) -> int:
        """Cantidad de meses totales que abarca un ciclo de pago."""
        if self.interval == "year":
            return (self.interval_count or 1) * 12
        return self.interval_count or 1


class Subscription(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En checkout"
        TRIALING = "trialing", "En prueba"
        ACTIVE = "active", "Activa"
        PAST_DUE = "past_due", "Pago pendiente"
        CANCELED = "canceled", "Cancelada"
        EXPIRED = "expired", "Expirada"

    ACTIVE_STATUSES = ["trialing", "active", "past_due"]

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="subscriptions",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    plan_price = models.ForeignKey(
        PlanPrice,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    provider = models.CharField(max_length=20, choices=PlanPrice.PROVIDER_CHOICES)
    provider_subscription_id = models.CharField(max_length=100, blank=True)
    provider_customer_id = models.CharField(max_length=100, blank=True)
    wompi_transaction_id = models.CharField(max_length=100, blank=True, db_index=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.TRIALING
    )
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_subscription"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(status__in=["trialing", "active", "past_due"]),
                name="one_active_subscription_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=["provider_subscription_id"]),
            models.Index(fields=["provider_customer_id"]),
            models.Index(
                fields=["status", "provider", "organization"],
                name="bs_sub_status_org_idx",
            ),
            models.Index(
                fields=["status", "provider", "user"],
                name="bs_sub_status_user_idx",
            ),
        ]

    def __str__(self):
        org_name = (
            self.organization.name
            if self.organization
            else (self.user.email if self.user else "Sin asignar")
        )
        return f"{org_name} – {self.plan.code} ({self.status})"

    def compute_period_end(self, start=None) -> "datetime":
        """
        Calcula la fecha de vencimiento a partir de `plan_price.months_in_cycle`.
        Usado por Wompi (pago único por adelantado) y como fallback cuando la
        pasarela no entrega `current_period_end` explícitamente.
        """
        if start is None:
            start = timezone.now()
        return start + relativedelta(months=self.plan_price.months_in_cycle)

    @property
    def dynamic_current_period_end(self):
        """Calcula dinámicamente la fecha de vencimiento a partir del inicio de ciclo y precio."""
        if self.current_period_end:
            return self.current_period_end
        if self.current_period_start:
            return self.compute_period_end(self.current_period_start)
        return None

    def is_active(self) -> bool:
        return self.status in Subscription.ACTIVE_STATUSES


class Invoice(models.Model):
    class InvoiceStatus(models.TextChoices):
        PAID = "paid", "Pagada"
        PENDING = "pending", "Pendiente"
        FAILED = "failed", "Fallida"

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="invoices",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invoices",
        null=True,
        blank=True,
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="invoices"
    )
    plan_price_snapshot = models.ForeignKey(
        PlanPrice, on_delete=models.PROTECT, related_name="invoices"
    )
    amount_paid_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    provider = models.CharField(max_length=20, choices=PlanPrice.PROVIDER_CHOICES)
    provider_invoice_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=15, choices=InvoiceStatus.choices, default=InvoiceStatus.PENDING
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    raw_webhook_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "billing_invoice"
        ordering = ["-paid_at"]

    def __str__(self):
        return f"Invoice {self.provider_invoice_id} – {self.amount_paid_minor} {self.currency}"


class ProcessedWebhookEvent(models.Model):
    class EventStatus(models.TextChoices):
        RECEIVED = "received", "Recibido"
        PROCESSING = "processing", "Procesando"
        PROCESSED = "processed", "Procesado"
        FAILED = "failed", "Fallido"

    provider = models.CharField(max_length=20, choices=PlanPrice.PROVIDER_CHOICES)
    event_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=80)
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=15, choices=EventStatus.choices, default=EventStatus.RECEIVED
    )
    raw_payload = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "billing_webhook_event"
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="unique_provider_event",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "event_id"]),
        ]

    def __str__(self):
        return f"{self.provider}:{self.event_id} – {self.status}"
