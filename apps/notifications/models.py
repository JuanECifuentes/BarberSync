"""
Notification log – tracks every notification sent.
"""

from django.conf import settings
from django.db import models


class NotificationLog(models.Model):
    """Immutable record of every notification dispatched."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Correo electrónico"

    class NotifType(models.TextChoices):
        REMINDER_24H = "reminder_24h", "Recordatorio 24h"
        REMINDER_1H = "reminder_1h", "Recordatorio 1h"
        BARBER_REMINDER = "barber_reminder", "Recordatorio barbero"
        CANCELLATION = "cancellation", "Cancelación"
        CONFIRMATION = "confirmation", "Confirmación"

    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    recipient_email = models.EmailField()
    recipient_name = models.CharField(max_length=150, blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    notif_type = models.CharField(max_length=20, choices=NotifType.choices)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "notifications_log"
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.notif_type} → {self.recipient_email}"
