"""
Legacy shim – delegates to the centralized notification engine.

The function signatures are preserved so that existing django_q
scheduled tasks (reminder_24h_apt_*, etc.) continue to resolve.

New code should import from apps.notifications.notifications instead.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def schedule_appointment_reminders(appointment_id: int):
    """
    Schedules reminders for the client and barber.
    Delegates to the centralized engine.
    Called after appointment creation or reschedule.
    """
    from apps.notifications.notifications import send_appointment_reminders

    send_appointment_reminders(appointment_id)


def send_reminder(appointment_id: int, notif_type: str, recipient_type: str):
    """
    Legacy entry-point for django_q scheduled tasks.
    Delegates to the new centralized notification engine.
    """
    from apps.notifications.notifications import _send_reminder_task

    _send_reminder_task(appointment_id, notif_type, recipient_type)
