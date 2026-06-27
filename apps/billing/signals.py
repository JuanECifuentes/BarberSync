"""
Invalidación automática del caché de suscripción activa.

Cuando una `Subscription` se crea/cambia/borra, se eliminan las claves
`barbersync:sub:active:user:{user_id}` y `barbersync:sub:active:org:{org_id}`
para que el middleware reconstruya el estado en la siguiente petición.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .cache_utils import invalidate_subscription
from .models import Subscription


@receiver(post_save, sender=Subscription)
def _invalidate_on_save(sender, instance: Subscription, **kwargs):
    invalidate_subscription(instance)


@receiver(post_delete, sender=Subscription)
def _invalidate_on_delete(sender, instance: Subscription, **kwargs):
    invalidate_subscription(instance)
