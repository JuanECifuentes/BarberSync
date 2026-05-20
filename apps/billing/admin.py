from django.contrib import admin

from .models import Plan, PlanPrice, Subscription, Invoice, ProcessedWebhookEvent


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "max_barbers", "max_branches")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    prepopulated_fields = {}


@admin.register(PlanPrice)
class PlanPriceAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "amount_minor",
        "currency",
        "interval",
        "provider",
        "is_current",
        "valid_from",
    )
    list_filter = ("provider", "currency", "interval", "is_current")
    raw_id_fields = ("plan",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "plan",
        "status",
        "provider",
        "provider_subscription_id",
        "created_at",
    )
    list_filter = ("status", "provider")
    raw_id_fields = ("organization", "plan", "plan_price")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "provider_invoice_id",
        "amount_paid_minor",
        "currency",
        "status",
        "paid_at",
    )
    list_filter = ("status", "provider", "currency")
    raw_id_fields = ("organization", "subscription", "plan_price_snapshot")


@admin.register(ProcessedWebhookEvent)
class ProcessedWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "event_type", "status", "received_at")
    list_filter = ("provider", "status", "event_type")
    readonly_fields = ("raw_payload",)
