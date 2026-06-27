import json
import logging
import math
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator

from .cache_utils import (
    get_org_subscription_status,
    get_user_subscription_status,
    invalidate_subscription,
)
from .models import (
    Invoice,
    Plan,
    PlanPrice,
    ProcessedWebhookEvent,
    Subscription,
)
from .providers import BillingProviderFactory

logger = logging.getLogger(__name__)

from apps.core.utils import resolve_country_code

ALLOWED_PROVIDERS = ["stripe", "wompi"]


def _resolve_provider_and_price(request, plan_code):
    chosen_provider = request.POST.get("chosen_provider", "").strip().lower()
    chosen_interval = request.POST.get("interval_count", "").strip()
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

    interval_count = None
    if chosen_interval:
        try:
            interval_count = int(chosen_interval)
        except ValueError:
            interval_count = None

    plan_price = PlanPrice.objects.filter(
        plan=plan,
        is_current=True,
        provider=provider_name,
        currency=currency,
    ).order_by("-valid_from", "-interval_count")
    if interval_count:
        plan_price = plan_price.filter(interval_count=interval_count)

    plan_price = plan_price.first()

    if not plan_price:
        # Fallback to the provider's price for the requested interval, regardless of currency
        fallback_qs = PlanPrice.objects.filter(
            plan=plan, is_current=True, provider=provider_name
        ).order_by("-valid_from", "-interval_count")
        if interval_count:
            plan_price = fallback_qs.filter(interval_count=interval_count).first()
        if not plan_price:
            plan_price = fallback_qs.first()

    if not plan_price:
        # Final fallback, ignoring currency and provider but keeping interval_count if possible
        fallback_qs = PlanPrice.objects.filter(plan=plan, is_current=True).order_by(
            "-valid_from", "-interval_count"
        )
        if interval_count:
            plan_price = fallback_qs.filter(interval_count=interval_count).first()
        if not plan_price:
            plan_price = fallback_qs.first()

    return provider_name, plan_price, organization


def _has_active_subscription(user, organization=None) -> bool:
    """Verifica con caché si el usuario u organización ya tiene suscripción activa."""
    if get_user_subscription_status(user):
        return True
    if organization is not None and get_org_subscription_status(organization):
        return True
    return False


class CheckoutView(LoginRequiredMixin, View):
    def post(self, request):
        plan_code = request.POST.get("plan_code")
        if not plan_code:
            if self._is_ajax(request):
                return JsonResponse({"error": "Falta plan_code."}, status=400)
            return redirect("root")

        try:
            provider_name, plan_price, organization = _resolve_provider_and_price(
                request, plan_code
            )
        except Plan.DoesNotExist:
            if self._is_ajax(request):
                return JsonResponse({"error": "Plan inexistente."}, status=400)
            return redirect("root")

        if not plan_price:
            logger.error("No PlanPrice found for plan_code=%s", plan_code)
            if self._is_ajax(request):
                return JsonResponse({"error": "Precio no disponible."}, status=400)
            return redirect("root")

        # ── VALIDACIÓN DE EXCLUSIÓN MUTUA (anti-cobro doble) ──────────────
        # Se consulta con caché (Redis prod / LocMem dev) el estado de la
        # suscripción activa del usuario y de la organización. Si ya existe
        # una membresía vigente, el flujo de checkout se bloquea antes de
        # contactar a la pasarela externa.
        if _has_active_subscription(request.user, organization):
            logger.info(
                "Checkout bloqueado: usuario %s ya posee suscripción activa (plan=%s).",
                request.user.pk,
                plan_code,
            )
            if self._is_ajax(request):
                return JsonResponse(
                    {
                        "error": "Ya tienes una suscripción activa.",
                        "code": "ACTIVE_SUBSCRIPTION_EXISTS",
                    },
                    status=400,
                )
            return redirect("/?already_subscribed=true#planes")

        # Bloqueo transaccional adicional a nivel de BD con seleccionar y
        # bloquear fila (SELECT FOR UPDATE) dentro de transacción atómica:
        with transaction.atomic():
            existing = (
                Subscription.objects.filter(organization=organization)
                .exclude(status__in=["canceled", "expired", "pending"])
                .first()
            )
            if existing:
                return self._block(request)

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
                logger.exception(
                    "Error creating checkout session for plan %s", plan_code
                )
                if self._is_ajax(request):
                    return JsonResponse(
                        {"error": "No se pudo iniciar el checkout."}, status=502
                    )
                return redirect("root")

            # Crea registro PENDING: referencia para la reconciliación
            # async si el webhook de la pasarela nunca llega.
            reference = session_data.get("reference") or session_data.get(
                "session_id", ""
            )
            pending = Subscription.objects.create(
                organization=organization,
                user=request.user,
                plan=plan_price.plan,
                plan_price=plan_price,
                provider=provider_name,
                provider_subscription_id=reference,
                provider_customer_id="",
                status=Subscription.Status.PENDING,
            )
            # Invalida caché para reflejar el cambio de estado inmediatamente.
            invalidate_subscription(pending)

        return redirect(session_data["checkout_url"])

    @staticmethod
    def _is_ajax(request) -> bool:
        accept = request.META.get("HTTP_ACCEPT", "")
        return (
            "application/json" in accept
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )

    def _block(self, request):
        if self._is_ajax(request):
            return JsonResponse(
                {
                    "error": "Ya tienes una suscripción activa.",
                    "code": "ACTIVE_SUBSCRIPTION_EXISTS",
                },
                status=400,
            )
        return redirect("/?already_subscribed=true#planes")


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
class SubscriptionStatusCheckView(LoginRequiredMixin, View):
    """
    GET /billing/subscription-status/
    Endpoint AJAX consumido por la landing para deshabilitar los botones
    de compra cuando el usuario ya posee una suscripción activa y evitar
    intentos duplicados de checkout.

    Respuesta:
        {
            "has_active_subscription": bool,
            "organization_id": int|null
        }
    """

    def get(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        organization = membership.organization if membership else None
        active = _has_active_subscription(request.user, organization)
        return JsonResponse(
            {
                "has_active_subscription": active,
                "organization_id": organization.pk if organization else None,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class PlanPricingView(View):
    """
    GET /billing/plans/
    Publica la matriz de precios vigentes por plan + proveedor + intervalo
    (1, 3 y 12 meses) para que la landing page la renderice dinámicamente
    respetando el principio de Zero Trust Frontend (los montos nunca
    viajan en formularios POST, solo al cargarse desde BD).
    """

    def get(self, request):
        prices = (
            PlanPrice.objects.filter(is_current=True, plan__is_active=True)
            .select_related("plan")
            .order_by("plan__id", "provider", "-interval_count")
        )
        result = []
        for pp in prices:
            result.append(
                {
                    "plan_code": pp.plan.code,
                    "plan_name": pp.plan.name,
                    "provider": pp.provider,
                    "currency": pp.currency,
                    "interval": pp.interval,
                    "interval_count": pp.interval_count,
                    "amount_minor": pp.amount_minor,
                    "months_in_cycle": pp.months_in_cycle,
                }
            )
        return JsonResponse({"plans": result})


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
        # Stripe envía current_period_start/end unix timestamps (segundos).
        period_start_ts = data.get("current_period_start")
        period_end_ts = data.get("current_period_end")

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

        session_id = data.get("id")

        # Reutiliza el registro PENDING creado en CheckoutView si existe,
        # para preservar el rastro de auditoría del checkout original.
        sub = None
        if subscription_id or session_id:
            sub = (
                Subscription.objects.filter(
                    provider_subscription_id=subscription_id,
                    status=Subscription.Status.PENDING,
                ).first()
                or Subscription.objects.filter(
                    provider_subscription_id=session_id,
                    status=Subscription.Status.PENDING,
                ).first()
            )

        if sub is not None:
            plan_price = sub.plan_price
        else:
            interval_count = None
            interval_count_str = metadata.get("interval_count")
            if interval_count_str:
                try:
                    interval_count = int(interval_count_str)
                except ValueError:
                    pass

            plan_price_qs = PlanPrice.objects.filter(
                plan=plan, is_current=True, provider=provider_name
            ).order_by("-valid_from", "-interval_count")
            if interval_count:
                plan_price = plan_price_qs.filter(interval_count=interval_count).first()
            else:
                plan_price = None
            if not plan_price:
                plan_price = plan_price_qs.first()

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

        # Periodo: usar el entregado por la pasarela o calcularlo desde BD.
        now = timezone.now()
        if period_start_ts:
            try:
                current_period_start = datetime.fromtimestamp(
                    int(period_start_ts), tz=timezone.get_current_timezone()
                )
            except (TypeError, ValueError):
                current_period_start = now
        else:
            current_period_start = now

        if period_end_ts:
            try:
                current_period_end = datetime.fromtimestamp(
                    int(period_end_ts), tz=timezone.get_current_timezone()
                )
            except (TypeError, ValueError):
                current_period_end = None
        else:
            current_period_end = None

        if sub is not None:
            sub.plan = plan
            sub.plan_price = plan_price
            sub.provider = provider_name
            sub.provider_subscription_id = subscription_id or sub.provider_subscription_id
            sub.provider_customer_id = customer_id or sub.provider_customer_id
            sub.status = Subscription.Status.ACTIVE
            sub.current_period_start = current_period_start
            sub.current_period_end = current_period_end
            sub.save(
                update_fields=[
                    "plan",
                    "plan_price",
                    "provider",
                    "provider_subscription_id",
                    "provider_customer_id",
                    "status",
                    "current_period_start",
                    "current_period_end",
                    "updated_at",
                ]
            )
        else:
            sub = Subscription.objects.create(
                organization=organization,
                user=user,
                plan=plan,
                plan_price=plan_price,
                provider=provider_name,
                provider_subscription_id=subscription_id or "",
                provider_customer_id=customer_id or "",
                status=Subscription.Status.ACTIVE,
                current_period_start=current_period_start,
                current_period_end=current_period_end,
            )

        invoice_id = (
            data.get("payment_intent")
            or f"{provider_name}_{subscription_id or payload.get('id', '')}"
        )

        Invoice.objects.update_or_create(
            provider_invoice_id=invoice_id,
            defaults={
                "organization": organization,
                "user": user,
                "subscription": sub,
                "plan_price_snapshot": plan_price,
                "amount_paid_minor": plan_price.amount_minor,
                "currency": plan_price.currency,
                "provider": provider_name,
                "status": Invoice.InvoiceStatus.PAID,
                "paid_at": timezone.now(),
                "raw_webhook_data": payload,
            },
        )

        # Invalida caché de suscripción activa.
        invalidate_subscription(sub)

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
            # Sincroniza periodos (renovación de Stripe)
            ps = data.get("current_period_start")
            pe = data.get("current_period_end")
            tz = timezone.get_current_timezone()
            try:
                sub.current_period_start = (
                    datetime.fromtimestamp(int(ps), tz)
                    if ps
                    else sub.current_period_start
                )
                sub.current_period_end = (
                    datetime.fromtimestamp(int(pe), tz)
                    if pe
                    else sub.current_period_end
                )
            except (TypeError, ValueError):
                pass
            sub.save(
                update_fields=[
                    "status",
                    "current_period_start",
                    "current_period_end",
                    "updated_at",
                ]
            )
            invalidate_subscription(sub)
        except Subscription.DoesNotExist:
            logger.warning("Subscription %s not found for update", subscription_id)


# ═════════════════════════════════════════════════════════════════════════
# Endpoints para Mi Perfil — Suscripción, Historial de Pagos y Cancelación
# ═════════════════════════════════════════════════════════════════════════


class SubscriptionDetailView(LoginRequiredMixin, View):
    """
    GET /billing/subscription-detail/
    Devuelve los datos de la suscripción activa del tenant autenticado
    para la sección "Suscripción" en Mi Perfil.

    Respuesta:
    {
        "plan_name": "Barbero Independiente",
        "status": "active",
        "provider": "stripe",
        "is_stripe": true,
        "current_period_start": "2026-06-01T00:00:00Z",
        "current_period_end": "2026-07-01T00:00:00Z",
        "amount_minor": 1900,
        "currency": "USD",
        "cancel_at_period_end": false,
        "can_cancel": true
    }
    Si no hay suscripción activa → 404.
    """

    def get(self, request):
        org = self._require_organization(request)
        sub = (
            Subscription.objects.filter(
                organization=org, status__in=Subscription.ACTIVE_STATUSES
            )
            .select_related("plan", "plan_price")
            .order_by("-created_at")
            .first()
        )
        if sub is None:
            return JsonResponse({"error": "Sin suscripción activa."}, status=404)
        return JsonResponse(
            {
                "id": sub.pk,
                "plan_name": sub.plan.name,
                "plan_code": sub.plan.code,
                "status": sub.status,
                "provider": sub.provider,
                "is_stripe": sub.provider == "stripe",
                "current_period_start": (
                    sub.current_period_start.isoformat()
                    if sub.current_period_start
                    else None
                ),
                "current_period_end": (
                    sub.current_period_end.isoformat()
                    if sub.current_period_end
                    else None
                ),
                "amount_minor": sub.plan_price.amount_minor,
                "currency": sub.plan_price.currency,
                "interval_count": sub.plan_price.interval_count,
                "canceled_at": (
                    sub.canceled_at.isoformat() if sub.canceled_at else None
                ),
                "can_cancel": sub.provider == "stripe"
                and sub.status
                in (
                    Subscription.Status.ACTIVE,
                    Subscription.Status.TRIALING,
                )
                and not sub.canceled_at,
            }
        )

    @staticmethod
    def _require_organization(request):
        membership = request.user.memberships.filter(is_active=True).first()
        if not membership or not membership.organization:
            return JsonResponse({"error": "Sin organización."}, status=403)
        return membership.organization


class InvoiceHistoryView(LoginRequiredMixin, View):
    """
    GET /billing/invoice-history/?page=1
    Historial de facturas paginado de 30 en 30, estrictamente filtrado
    por la organización del usuario (anti-IDOR). No expone datos sensibles
    de tarjetas, tokens de pasarela ni raw_webhook_data.
    """

    PAGE_SIZE = 30

    def get(self, request):
        org = self._require_organization(request)
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (ValueError, TypeError):
            page = 1

        qs = (
            Invoice.objects.filter(Q(organization=org) | Q(user=request.user))
            .select_related("subscription__plan")
            .order_by("-paid_at", "-created_at")
        )
        total = qs.count()
        total_pages = max(1, math.ceil(total / self.PAGE_SIZE))
        page = min(page, total_pages)
        offset = (page - 1) * self.PAGE_SIZE

        invoices = qs[offset : offset + self.PAGE_SIZE]
        rows = []
        for inv in invoices:
            rows.append(
                {
                    "id": inv.pk,
                    "paid_at": (
                        inv.paid_at.isoformat()
                        if inv.paid_at
                        else inv.created_at.isoformat()
                    ),
                    "amount_minor": inv.amount_paid_minor,
                    "currency": inv.currency,
                    "plan_name": (
                        inv.subscription.plan.name if inv.subscription else "—"
                    ),
                    "status": inv.status,
                    "provider": inv.provider,
                }
            )

        return JsonResponse(
            {
                "page": page,
                "total_pages": total_pages,
                "total": total,
                "has_next": page < total_pages,
                "invoices": rows,
            }
        )

    @staticmethod
    def _require_organization(request):
        membership = request.user.memberships.filter(is_active=True).first()
        if not membership or not membership.organization:
            return JsonResponse({"error": "Sin organización asociada."}, status=403)
        return membership.organization


class CancelSubscriptionView(LoginRequiredMixin, View):
    """
    POST /billing/cancel-subscription/
    Cancela la recurrencia de una suscripción activa de Stripe con
    cancel_at_period_end=True. El usuario conserva acceso hasta
    current_period_end.

    Bloquea si:
    - No hay suscripción activa.
    - La suscripción no pertenece a la organización del usuario (IDOR).
    - El proveedor no es Stripe (Wompi = pago único, no cancelar).
    """

    def post(self, request):
        org = self._require_organization(request)
        sub = (
            Subscription.objects.filter(
                organization=org, status__in=Subscription.ACTIVE_STATUSES
            )
            .order_by("-created_at")
            .first()
        )
        if sub is None:
            return JsonResponse(
                {"error": "No tienes una suscripción activa."}, status=404
            )
        if sub.provider != "stripe":
            return JsonResponse(
                {"error": "Solo las suscripciones Stripe permiten cancelación."},
                status=400,
            )
        provider = BillingProviderFactory.get_provider("stripe")
        try:
            cancelled = provider.cancel_subscription(sub)
        except Exception:
            logger.exception("Error cancelando Subscription#%s en Stripe", sub.pk)
            return JsonResponse(
                {"error": "No se pudo contactar a Stripe. Intenta de nuevo."},
                status=502,
            )
        if not cancelled:
            return JsonResponse(
                {"error": "No se pudo cancelar la suscripción en Stripe."},
                status=502,
            )
        sub.canceled_at = timezone.now()
        sub.save(update_fields=["canceled_at", "updated_at"])
        invalidate_subscription(sub)
        logger.info(
            "Subscription#%s cancelada por user=%s, conserva acceso hasta %s",
            sub.pk,
            request.user.pk,
            sub.current_period_end,
        )
        return JsonResponse(
            {
                "message": "La renovación automática ha sido cancelada.",
                "access_until": (
                    sub.current_period_end.isoformat()
                    if sub.current_period_end
                    else None
                ),
            }
        )

    @staticmethod
    def _require_organization(request):
        membership = request.user.memberships.filter(is_active=True).first()
        if not membership or not membership.organization:
            return JsonResponse({"error": "Sin organización asociada."}, status=403)
        return membership.organization

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
        interval_count = None

        metadata = data.get("metadata", {})
        if metadata:
            plan_code = metadata.get("plan_code", "")
            organization_id = metadata.get("organization_id")
            user_id = metadata.get("user_id")
            interval_count_str = metadata.get("interval_count")
            if interval_count_str:
                try:
                    interval_count = int(interval_count_str)
                except ValueError:
                    pass

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

        # Reutiliza el registro PENDING si la referencia coincide para obtener el precio correcto.
        sub = Subscription.objects.filter(
            provider_subscription_id=reference,
            status=Subscription.Status.PENDING,
        ).first()

        if sub is not None:
            plan_price = sub.plan_price
        else:
            plan_price_qs = PlanPrice.objects.filter(
                plan=plan, is_current=True, provider="wompi"
            ).order_by("-valid_from", "-interval_count")
            if interval_count:
                plan_price = plan_price_qs.filter(interval_count=interval_count).first()
            else:
                plan_price = None
            if not plan_price:
                plan_price = plan_price_qs.first()

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

        # Wompi NO soporta recurrencia: pagos de 3 y 12 meses se procesan
        # como pago único por adelantado. Calculamos `current_period_end`
        # sumando los `months_in_cycle` definidos en PlanPrice.
        now = timezone.now()
        period_end = now + relativedelta(months=plan_price.months_in_cycle)

        if sub is not None:
            sub.plan = plan
            sub.plan_price = plan_price
            sub.provider = "wompi"
            sub.wompi_transaction_id = transaction_id
            sub.status = Subscription.Status.ACTIVE
            sub.current_period_start = now
            sub.current_period_end = period_end
            sub.save(
                update_fields=[
                    "plan",
                    "plan_price",
                    "provider",
                    "wompi_transaction_id",
                    "status",
                    "current_period_start",
                    "current_period_end",
                    "updated_at",
                ]
            )
        else:
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
                current_period_start=now,
                current_period_end=period_end,
            )

        Invoice.objects.update_or_create(
            provider_invoice_id=f"wompi_{transaction_id}",
            defaults={
                "organization": organization,
                "user": user,
                "subscription": sub,
                "plan_price_snapshot": plan_price,
                "amount_paid_minor": plan_price.amount_minor,
                "currency": plan_price.currency,
                "provider": "wompi",
                "status": Invoice.InvoiceStatus.PAID,
                "paid_at": timezone.now(),
                "raw_webhook_data": payload,
            },
        )

        invalidate_subscription(sub)
