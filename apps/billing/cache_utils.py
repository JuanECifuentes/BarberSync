"""
Cache de suscripción activa (Redis prod / LocMem dev).

El middleware de acceso consulta el estado de la suscripción en cada
navegación interna. Para evitar golpear PostgreSQL en cada request, el
resultado se cachea con un TTL dinámico que expira a las 23:59:59 del día
actual (máx 24h), reiniciando el estado al cambiar de día.

Claves:
    barbersync:sub:active:user:{user_id}
    barbersync:sub:active:org:{org_id}

Invalidación:
    Las señales post_save/post_delete de Subscription (apps.billing.signals)
    borran la clave correspondiente al actualizar/cancelar.
"""

from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import Subscription

_USER_KEY = "barbersync:sub:active:user:{uid}"
_ORG_KEY = "barbersync:sub:active:org:{oid}"


def seconds_until_end_of_day(now=None) -> int:
    """Segundos restantes hasta las 23:59:59 del día en curso (TZ local)."""
    if now is None:
        now = timezone.now()
    end_of_day = datetime.combine(now.date(), time(23, 59, 59), tzinfo=now.tzinfo)
    delta = end_of_day - now
    # Mín 60s (evita TTL 0), máx 86_400s
    return max(60, min(int(delta.total_seconds()), 86_400))


def _has_active_subscription_user(user_id: int) -> bool:
    return Subscription.objects.filter(
        user_id=user_id, status__in=Subscription.ACTIVE_STATUSES
    ).exists()


def _has_active_subscription_org(org_id: int) -> bool:
    return Subscription.objects.filter(
        organization_id=org_id, status__in=Subscription.ACTIVE_STATUSES
    ).exists()


def get_user_subscription_status(user) -> bool:
    """Estado cacheado de suscripción activa del usuario (personal)."""
    if not user.is_authenticated:
        return False
    uid = user.pk
    key = _USER_KEY.format(uid=uid)
    cached = cache.get(key)
    if cached is not None:
        return cached is True
    value = _has_active_subscription_user(uid)
    cache.set(key, value, timeout=seconds_until_end_of_day())
    return value


def get_org_subscription_status(org) -> bool:
    """Estado cacheado de suscripción activa de la organización."""
    if org is None:
        return False
    oid = org.pk
    key = _ORG_KEY.format(oid=oid)
    cached = cache.get(key)
    if cached is not None:
        return cached is True
    value = _has_active_subscription_org(oid)
    cache.set(key, value, timeout=seconds_until_end_of_day())
    return value


def invalidate_user(user_id: int) -> None:
    cache.delete(_USER_KEY.format(uid=user_id))


def invalidate_org(org_id: int) -> None:
    cache.delete(_ORG_KEY.format(oid=org_id))


def invalidate_subscription(subscription) -> None:
    """Invalida todas las claves relacionadas con una suscripción."""
    if subscription.user_id:
        invalidate_user(subscription.user_id)
    if subscription.organization_id:
        invalidate_org(subscription.organization_id)
