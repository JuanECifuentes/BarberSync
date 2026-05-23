import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import Plan, PlanPrice, ProcessedWebhookEvent, Subscription, Invoice
from .providers import BillingProviderFactory

logger = logging.getLogger(__name__)

from apps.core.utils import resolve_country_code

ALLOWED_PROVIDERS = ["stripe", "wompi"]


def _resolve_provider_and_price(request, plan_code):
    chosen_provider = request.POST.get("chosen_provider", "").strip().lower()
    user = request.user

    membership = user.memberships.filter(is_active=True).first()
    organization = membership.organization if membership else None
    country_code = resolve_country_code(request)

    country_config = settings.BILLING_COUNTRY_PROVIDER_MAP.get(country_code.upper(), {})
    default_provider = country_config.get("default", settings.BILLING_DEFAULT_PROVIDER)
    allowed = country_config.get("allowed", [settings.BILLING_DEFAULT_PROVIDER])


    if chosen_provider and chosen_provider in allowed:
        provider_name = chosen_provider
    elif chosen_provider and chosen_provider not in allowed:
        provider_name = default_provider
    else:
        provider_name = default_provider

    currency = settings.BILLING_COUNTRY_CURRENCY_MAP.get(
        country_code.upper(),
        settings.BILLING_DEFAULT_CURRENCY,
    )

    plan = Plan.objects.get(code=plan_code, is_active=True)
    plan_price = (
        PlanPrice.objects.filter(
            plan=plan, is_current=True, provider=provider_name, currency=currency
        )
        .order_by("-valid_from")
        .first()
    )

    if not plan_price:
        plan_price = (
            PlanPrice.objects.filter(plan=plan, is_current=True, provider=provider_name)
            .order_by("-valid_from")
            .first()
        )

    if not plan_price:
        plan_price = (
            PlanPrice.objects.filter(plan=plan, is_current=True)
            .order_by("-valid_from")
            .first()
        )

    return provider_name, plan_price, organization


class CheckoutView(LoginRequiredMixin, View):
    def post(self, request):
        plan_code = request.POST.get("plan_code")
        if not plan_code:
            return redirect("root")

        try:
            provider_name, plan_price, organization = _resolve_provider_and_price(
                request, plan_code
            )
        except Plan.DoesNotExist:
            return redirect("root")

        if not plan_price:
            logger.error("No PlanPrice found for plan_code=%s", plan_code)
            return redirect("root")

        provider = BillingProviderFactory.get_provider(provider_name)
        base_url = getattr(settings, "BILLING_BASE_URL", "").rstrip("/")
        if base_url:
            success_url = f"{base_url}/billing/success/"
            cancel_url = f"{base_url}/billing/cancel/"
        else:
            success_url = request.build_absolute_uri("/billing/success/")
            cancel_url = request.build_absolute_uri("/billing/cancel/")

        try:
            session_data = provider.create_checkout_session(
                user=request.user,
                plan_price=plan_price,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except Exception:
            logger.exception("Error creating checkout session for plan %s", plan_code)
            return redirect("root")

        return redirect(session_data["checkout_url"])


class BillingSuccessView(LoginRequiredMixin, TemplateView):
    template_name = "billing/success.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["message"] = (
            "Tu pago está siendo procesado. Recibirás una confirmación "
            "en los próximos minutos. Puedes cerrar esta página."
        )
        return ctx


class BillingCancelView(LoginRequiredMixin, TemplateView):
    template_name = "billing/cancel.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["message"] = (
            "El proceso de pago fue cancelado. Puedes intentarlo de nuevo cuando quieras."
        )
        return ctx


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    def post(self, request):
        provider = BillingProviderFactory.get_provider("stripe")

        if not provider.validate_webhook_signature(request):
            return HttpResponse(status=403)

        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return HttpResponse(status=400)

        event_type = provider.get_event_type(payload)
        event_id = provider.get_event_id(payload)

        with transaction.atomic():
            _, created = (
                ProcessedWebhookEvent.objects.select_for_update().get_or_create(
                    provider="stripe",
                    event_id=event_id,
                    defaults={
                        "event_type": event_type,
                        "status": ProcessedWebhookEvent.EventStatus.PROCESSING,
                        "raw_payload": payload,
                    },
                )
            )

            if not created:
                return HttpResponse(status=200)

        if event_type == "checkout.session.completed":
            self._handle_checkout_completed(payload)
        elif event_type == "customer.subscription.updated":
            self._handle_subscription_updated(payload)
        elif event_type == "customer.subscription.deleted":
            self._handle_subscription_deleted(payload)

        ProcessedWebhookEvent.objects.filter(
            provider="stripe", event_id=event_id
        ).update(
            status=ProcessedWebhookEvent.EventStatus.PROCESSED,
            processed_at=timezone.now(),
        )

        return HttpResponse(status=200)

    def _activate_subscription(self, payload, provider_name, plan_key="plan_code"):
        from django.contrib.auth import get_user_model
        from apps.accounts.models import Organization

        data = payload.get("data", {}).get("object", {})
        metadata = data.get("metadata", {})
        plan_code = metadata.get(plan_key)
        organization_id = metadata.get("organization_id")
        user_id = metadata.get("user_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")

        if not plan_code:
            logger.warning("Webhook missing %s: %s", plan_key, payload.get("id"))
            return

        User = get_user_model()
        user = None
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                logger.error("User %s not found", user_id)

        organization = None
        if organization_id:
            try:
                organization = Organization.objects.get(pk=organization_id)
            except Organization.DoesNotExist:
                logger.error("Organization %s not found", organization_id)
                return

        try:
            plan = Plan.objects.get(code=plan_code, is_active=True)
        except Plan.DoesNotExist:
            logger.error("Plan %s not found", plan_code)
            return

        plan_price = (
            PlanPrice.objects.filter(plan=plan, is_current=True, provider=provider_name)
            .order_by("-valid_from")
            .first()
        )
        if not plan_price:
            logger.error(
                "No current price for plan %s provider %s", plan_code, provider_name
            )
            return

        if organization:
            Subscription.objects.filter(organization=organization).exclude(
                status__in=["canceled", "expired"]
            ).update(status="canceled")
        elif user:
            Subscription.objects.filter(user=user, organization__isnull=True).exclude(
                status__in=["canceled", "expired"]
            ).update(status="canceled")

        sub = Subscription.objects.create(
            organization=organization,
            user=user,
            plan=plan,
            plan_price=plan_price,
            provider=provider_name,
            provider_subscription_id=subscription_id or "",
            provider_customer_id=customer_id or "",
            status=Subscription.Status.ACTIVE,
        )

        invoice_id = (
            data.get("payment_intent")
            or f"{provider_name}_{subscription_id or payload.get('id', '')}"
        )

        Invoice.objects.create(
            organization=organization,
            user=user,
            subscription=sub,
            plan_price_snapshot=plan_price,
            amount_paid_minor=plan_price.amount_minor,
            currency=plan_price.currency,
            provider=provider_name,
            provider_invoice_id=invoice_id,
            status=Invoice.InvoiceStatus.PAID,
            paid_at=timezone.now(),
            raw_webhook_data=payload,
        )

    def _handle_checkout_completed(self, payload):
        self._activate_subscription(payload, "stripe")

    def _handle_subscription_updated(self, payload):
        data = payload.get("data", {}).get("object", {})
        subscription_id = data.get("id")
        if not subscription_id:
            return

        try:
            sub = Subscription.objects.get(provider_subscription_id=subscription_id)
            status_map = {
                "active": Subscription.Status.ACTIVE,
                "trialing": Subscription.Status.TRIALING,
                "past_due": Subscription.Status.PAST_DUE,
                "canceled": Subscription.Status.CANCELED,
            }
            sub.status = status_map.get(data.get("status"), Subscription.Status.EXPIRED)
            sub.save(update_fields=["status", "updated_at"])
        except Subscription.DoesNotExist:
            logger.warning("Subscription %s not found for update", subscription_id)

    def _handle_subscription_deleted(self, payload):
        data = payload.get("data", {}).get("object", {})
        subscription_id = data.get("id")
        if not subscription_id:
            return

        Subscription.objects.filter(provider_subscription_id=subscription_id).update(
            status=Subscription.Status.CANCELED
        )


@method_decorator(csrf_exempt, name="dispatch")
class WompiWebhookView(View):
    def post(self, request):
        provider = BillingProviderFactory.get_provider("wompi")

        if not provider.validate_webhook_signature(request):
            return HttpResponse(status=403)

        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return HttpResponse(status=400)

        event_type = provider.get_event_type(payload)
        event_id = provider.get_event_id(payload)

        with transaction.atomic():
            _, created = (
                ProcessedWebhookEvent.objects.select_for_update().get_or_create(
                    provider="wompi",
                    event_id=event_id,
                    defaults={
                        "event_type": event_type,
                        "status": ProcessedWebhookEvent.EventStatus.PROCESSING,
                        "raw_payload": payload,
                    },
                )
            )

            if not created:
                return HttpResponse(status=200)

        if event_type == "transaction.updated":
            self._handle_transaction_updated(payload)

        ProcessedWebhookEvent.objects.filter(
            provider="wompi", event_id=event_id
        ).update(
            status=ProcessedWebhookEvent.EventStatus.PROCESSED,
            processed_at=timezone.now(),
        )

        return HttpResponse(status=200)

    def _handle_transaction_updated(self, payload):
        data = payload.get("data", {}).get("transaction", {})
        status = data.get("status", "")
        reference = data.get("reference", "")
        transaction_id = str(data.get("id", ""))

        if status not in ("APPROVED", "PAYED"):
            return

        plan_code = ""
        organization_id = None
        user_id = None

        metadata = data.get("metadata", {})
        if metadata:
            plan_code = metadata.get("plan_code", "")
            organization_id = metadata.get("organization_id")
            user_id = metadata.get("user_id")

        if reference and reference.startswith("bs_"):
            parts = reference.split("_")
            if len(parts) >= 5:
                if not plan_code:
                    plan_code = parts[1]
                if not user_id and parts[2].isdigit():
                    user_id = int(parts[2])
                if not organization_id and parts[3].isdigit() and int(parts[3]) > 0:
                    organization_id = int(parts[3])

        if not plan_code:
            logger.warning(
                "Wompi webhook missing plan_code in reference: %s", reference
            )
            return

        from django.contrib.auth import get_user_model
        from apps.accounts.models import Organization

        User = get_user_model()
        user = None
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                logger.error("Wompi: User %s not found", user_id)

        organization = None
        if organization_id:
            try:
                organization = Organization.objects.get(pk=organization_id)
            except Organization.DoesNotExist:
                logger.error("Wompi: Organization %s not found", organization_id)
                return

        try:
            plan = Plan.objects.get(code=plan_code, is_active=True)
        except Plan.DoesNotExist:
            logger.error("Wompi: Plan %s not found", plan_code)
            return

        plan_price = (
            PlanPrice.objects.filter(plan=plan, is_current=True, provider="wompi")
            .order_by("-valid_from")
            .first()
        )
        if not plan_price:
            logger.error("Wompi: No current price for plan %s", plan_code)
            return

        if organization:
            Subscription.objects.filter(organization=organization).exclude(
                status__in=["canceled", "expired"]
            ).update(status="canceled")
        elif user:
            Subscription.objects.filter(user=user, organization__isnull=True).exclude(
                status__in=["canceled", "expired"]
            ).update(status="canceled")

        sub = Subscription.objects.create(
            organization=organization,
            user=user,
            plan=plan,
            plan_price=plan_price,
            provider="wompi",
            provider_subscription_id=reference,
            provider_customer_id="",
            wompi_transaction_id=transaction_id,
            status=Subscription.Status.ACTIVE,
        )

        Invoice.objects.create(
            organization=organization,
            user=user,
            subscription=sub,
            plan_price_snapshot=plan_price,
            amount_paid_minor=plan_price.amount_minor,
            currency=plan_price.currency,
            provider="wompi",
            provider_invoice_id=f"wompi_{transaction_id}",
            status=Invoice.InvoiceStatus.PAID,
            paid_at=timezone.now(),
            raw_webhook_data=payload,
        )
