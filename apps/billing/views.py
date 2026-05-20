import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Plan, PlanPrice, ProcessedWebhookEvent, Subscription, Invoice
from .providers import BillingProviderFactory

logger = logging.getLogger(__name__)


class CheckoutView(LoginRequiredMixin, View):
    def post(self, request):
        plan_code = request.POST.get("plan_code")
        if not plan_code:
            return redirect("root")

        try:
            plan = Plan.objects.get(code=plan_code, is_active=True)
        except Plan.DoesNotExist:
            return redirect("root")

        plan_price = (
            PlanPrice.objects.filter(plan=plan, is_current=True, provider="stripe")
            .order_by("-valid_from")
            .first()
        )

        print("PROBANDO PLAN_CODE", plan_code)
        print("PROBANDO PLAN", plan)
        print("PROBANDO PLAN PRICE", plan_price)

        if not plan_price:
            return redirect("root")

        provider = BillingProviderFactory.get_provider("stripe")

        success_url = request.build_absolute_uri("/billing/success/")
        cancel_url = request.build_absolute_uri("/billing/cancel/")

        try:
            session_data = provider.create_checkout_session(
                user=request.user,
                plan_price=plan_price,
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
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

        import json

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
            processed_at=__import__("django").utils.timezone.now(),
        )

        return HttpResponse(status=200)

    def _handle_checkout_completed(self, payload):
        data = payload.get("data", {}).get("object", {})
        metadata = data.get("metadata", {})
        plan_code = metadata.get("plan_code")
        organization_id = metadata.get("organization_id")
        user_id = metadata.get("user_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")

        if not plan_code:
            logger.warning("Webhook missing plan_code: %s", payload.get("id"))
            return

        from django.contrib.auth import get_user_model
        from apps.accounts.models import Organization

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
            PlanPrice.objects.filter(plan=plan, is_current=True, provider="stripe")
            .order_by("-valid_from")
            .first()
        )
        if not plan_price:
            logger.error("No current price for plan %s", plan_code)
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
            provider="stripe",
            provider_subscription_id=subscription_id or "",
            provider_customer_id=customer_id or "",
            status=Subscription.Status.ACTIVE,
        )

        Invoice.objects.create(
            organization=organization,
            user=user,
            subscription=sub,
            plan_price_snapshot=plan_price,
            amount_paid_minor=plan_price.amount_minor,
            currency=plan_price.currency,
            provider="stripe",
            provider_invoice_id=data.get("payment_intent") or f"sub_{subscription_id}",
            status=Invoice.InvoiceStatus.PAID,
            paid_at=__import__("django").utils.timezone.now(),
            raw_webhook_data=payload,
        )

        if user and not organization:
            from apps.accounts.models import Membership
            if not user.memberships.exists():
                Membership.objects.create(
                    user=user,
                    organization=None,
                    role=Membership.Role.OWNER,
                    is_active=True
                )

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
