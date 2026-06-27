"""
Reconciliación de suscripciones ante fallos de Webhooks.

执行 un pulling HTTP directo a las APIs de Stripe y Wompi para detectar
pagos exitosos que nunca impactaron nuestro servidor (webhook perdido,
red caída, etc.) y forzar la creación local de la suscripción.

Ejecución:
    - Tarea asíncrona de django_q (encolada desde un cron o scheduler):
        from apps.billing.tasks import reconcile_subscriptions
        async_task(reconcile_subscriptions)
    - Comando de gestión sincrónico:
        python manage.py reconcile_subscriptions
"""

import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from .models import Invoice, PlanPrice, Subscription
from .providers import BillingProviderFactory

logger = logging.getLogger(__name__)

# Solo se reconcialian suscripciones PENDING con antigüedad mayor a este umbral
# para dar margen al webhook normal.
RECONCILE_MIN_AGE_SECONDS = 60 * 5  # 5 minutos


def _reconcile_stripe(sub: Subscription):
    if not sub.provider_customer_id:
        # Recuperar customer_id vía session metadata checkout:
        sub.provider_customer_id = _lookup_stripe_customer_id(sub)
    provider = BillingProviderFactory.get_provider("stripe")
    customer_id = sub.provider_customer_id
    if not customer_id:
        return False

    data = provider.fetch_customer_active_subscription(customer_id)
    if not data or data.get("status") != "active":
        return False

    now = timezone.now()
    tz = timezone.get_current_timezone()
    period_start = None
    period_end = None
    ps = data.get("current_period_start")
    pe = data.get("current_period_end")
    try:
        period_start = datetime.fromtimestamp(int(ps), tz) if ps else now
        period_end = datetime.fromtimestamp(int(pe), tz) if pe else None
    except (TypeError, ValueError):
        period_start = now

    _activate_subscription_from_remote(
        sub=sub,
        provider_name="stripe",
        provider_subscription_id=data.get("subscription_id")
        or sub.provider_subscription_id,
        provider_customer_id=customer_id,
        wompi_transaction_id="",
        period_start=period_start,
        period_end=period_end,
        raw_payload=data,
    )
    return True


def _reconcile_wompi(sub: Subscription):
    provider = BillingProviderFactory.get_provider("wompi")
    reference = sub.provider_subscription_id
    if not reference:
        return False

    data = provider.fetch_transaction_by_reference(reference)
    status = (data or {}).get("status", "")
    if status not in ("APPROVED", "PAYED"):
        return False

    now = timezone.now()
    period_end = now + relativedelta(months=sub.plan_price.months_in_cycle)
    _activate_subscription_from_remote(
        sub=sub,
        provider_name="wompi",
        provider_subscription_id=reference,
        provider_customer_id="",
        wompi_transaction_id=str(data.get("transaction_id", "")),
        period_start=now,
        period_end=period_end,
        raw_payload=data,
    )
    return True


def _activate_subscription_from_remote(
    *,
    sub: Subscription,
    provider_name: str,
    provider_subscription_id: str,
    provider_customer_id: str,
    wompi_transaction_id: str,
    period_start,
    period_end,
    raw_payload: dict,
):
    """Forzar activación local de una suscripción PENDING detectada como paga."""
    with transaction.atomic():
        # Bloquear la fila para evitar race contra el webhook normal.
        locked = Subscription.objects.select_for_update().filter(pk=sub.pk).first()
        if not locked:
            return
        if locked.status in Subscription.ACTIVE_STATUSES:
            # Ya fue activada por el webhook mientras reconciliábamos.
            return

        # Cancelar otras suscripciones activas del mismo tenant (anti-doble)
        if locked.organization:
            Subscription.objects.filter(organization=locked.organization).exclude(
                pk=locked.pk
            ).exclude(status__in=["canceled", "expired"]).update(status="canceled")

        locked.status = Subscription.Status.ACTIVE
        locked.provider = provider_name
        locked.provider_subscription_id = provider_subscription_id
        if provider_customer_id:
            locked.provider_customer_id = provider_customer_id
        if wompi_transaction_id:
            locked.wompi_transaction_id = wompi_transaction_id
        locked.current_period_start = period_start
        locked.current_period_end = period_end
        locked.save(
            update_fields=[
                "status",
                "provider",
                "provider_subscription_id",
                "provider_customer_id",
                "wompi_transaction_id",
                "current_period_start",
                "current_period_end",
                "updated_at",
            ]
        )

        invoice_id = (
            f"{provider_name}_{wompi_transaction_id or provider_subscription_id}"
        )
        Invoice.objects.update_or_create(
            provider_invoice_id=invoice_id,
            defaults={
                "organization": locked.organization,
                "user": locked.user,
                "subscription": locked,
                "plan_price_snapshot": locked.plan_price,
                "amount_paid_minor": locked.plan_price.amount_minor,
                "currency": locked.plan_price.currency,
                "provider": provider_name,
                "status": Invoice.InvoiceStatus.PAID,
                "paid_at": timezone.now(),
                "raw_webhook_data": {"reconciled": True, "source": raw_payload},
            },
        )

    logger.warning(
        "Reconciliación forzada: Subscription#%s marcada ACTIVE vía %s (webhook perdido).",
        sub.pk,
        provider_name,
    )


def _lookup_stripe_customer_id(sub: Subscription) -> str:
    """Heurística: el último provider_customer_id válido del usuario/org histórico."""
    qs = Subscription.objects.filter(provider__startswith="cus_").order_by(
        "-created_at"
    )
    if sub.organization_id:
        qs = qs.filter(organization_id=sub.organization_id)
    elif sub.user_id:
        qs = qs.filter(user_id=sub.user_id)
    last = qs.values_list("provider_customer_id", flat=True).first()
    return last or ""


_RECONCILERS = {
    "stripe": _reconcile_stripe,
    "wompi": _reconcile_wompi,
}


def reconcile_subscriptions(max_age_seconds: int = RECONCILE_MIN_AGE_SECONDS) -> dict:
    """
    Recorre las suscripciones con `status=pending` y consulta directamente a la
    pasarela para sincronizar estados. Devuelve un resumen con conteos.
    """
    cutoff = timezone.now() - timedelta(seconds=max_age_seconds)
    pending = Subscription.objects.filter(
        status=Subscription.Status.PENDING,
        created_at__lte=cutoff,
    ).order_by("-created_at")

    summary = {"checked": 0, "activated": 0, "still_pending": 0, "errors": 0}

    for sub in pending:
        summary["checked"] += 1
        recon = _RECONCILERS.get(sub.provider)
        if not recon:
            continue
        try:
            ok = recon(sub)
        except Exception:
            logger.exception("Reconcile error on Subscription#%s", sub.pk)
            summary["errors"] += 1
            continue
        if ok:
            summary["activated"] += 1
        else:
            summary["still_pending"] += 1

    logger.info("Reconciliación completada: %s", summary)
    return summary
