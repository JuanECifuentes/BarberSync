"""
Async tasks for notifications – scheduled via Django Q2.

schedule_appointment_reminders() – queues 24h + 1h reminders for client & barber.
send_reminder()                  – the actual email sender (executed by Q2 worker).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def schedule_appointment_reminders(appointment_id: int):
    """
    Schedules two reminders for the client and one for the barber.
    Called after appointment creation.
    Uses Django Q2's `schedule()` for deferred execution.
    """
    try:
        from django_q.tasks import schedule
        from django_q.models import Schedule

        from apps.scheduling.models import Appointment
        appointment = Appointment.objects.select_related(
            "client", "barber__membership__user"
        ).get(pk=appointment_id)

        start = appointment.start_time

        # Client reminder: 24 hours before
        reminder_24h = start - timedelta(hours=24)
        if reminder_24h > timezone.now():
            schedule(
                "apps.notifications.tasks.send_reminder",
                appointment_id,
                "reminder_24h",
                "client",
                name=f"reminder_24h_apt_{appointment_id}",
                schedule_type=Schedule.ONCE,
                next_run=reminder_24h,
            )

        # Client reminder: 1 hour before
        reminder_1h = start - timedelta(hours=1)
        if reminder_1h > timezone.now():
            schedule(
                "apps.notifications.tasks.send_reminder",
                appointment_id,
                "reminder_1h",
                "client",
                name=f"reminder_1h_apt_{appointment_id}",
                schedule_type=Schedule.ONCE,
                next_run=reminder_1h,
            )

        # Barber reminder: 1 hour before
        if reminder_1h > timezone.now():
            schedule(
                "apps.notifications.tasks.send_reminder",
                appointment_id,
                "barber_reminder",
                "barber",
                name=f"barber_reminder_apt_{appointment_id}",
                schedule_type=Schedule.ONCE,
                next_run=reminder_1h,
            )

    except Exception:
        logger.exception("Error scheduling reminders for appointment %s", appointment_id)


def send_reminder(appointment_id: int, notif_type: str, recipient_type: str):
    """
    Sends an email reminder. Executed asynchronously by Django Q2.
    """
    from apps.notifications.models import NotificationLog
    from apps.scheduling.models import Appointment

    try:
        appointment = Appointment.objects.select_related(
            "client", "barber__membership__user", "barbershop"
        ).get(pk=appointment_id)
    except Appointment.DoesNotExist:
        logger.warning("Appointment %s not found for reminder", appointment_id)
        return

    # Skip if cancelled
    if appointment.status in ("cancelled", "no_show"):
        return

    # Determine recipient
    if recipient_type == "client":
        email = appointment.client.email
        name = appointment.client.name
    else:
        email = appointment.barber.user.email
        name = str(appointment.barber)

    if not email:
        logger.info("No email for %s on appointment %s", recipient_type, appointment_id)
        return

    # Build email content
    service_names = ", ".join(
        appointment.services.values_list("service__name", flat=True)
    )

    context = {
        "appointment": appointment,
        "recipient_name": name,
        "service_names": service_names,
        "barbershop_name": appointment.barbershop.name,
        "barber_name": str(appointment.barber),
        "start_time": appointment.start_time,
    }

    subject_map = {
        "reminder_24h": f"Recordatorio: tu cita mañana en {appointment.barbershop.name}",
        "reminder_1h": f"Tu cita en {appointment.barbershop.name} es en 1 hora",
        "barber_reminder": f"Cita en 1 hora: {appointment.client.name}",
    }

    subject = subject_map.get(notif_type, "Recordatorio de cita – BarberSync")

    try:
        body = render_to_string(f"notifications/{notif_type}.html", context)
    except Exception:
        body = (
            f"Hola {name},\n\n"
            f"Te recordamos tu cita en {appointment.barbershop.name} "
            f"el {appointment.start_time:%d/%m/%Y a las %I:%M %p}.\n"
            f"Servicios: {service_names}\n"
            f"Barbero: {appointment.barber}\n\n"
            f"¡Te esperamos!\n– BarberSync"
        )

    success = True
    error_msg = ""
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        success = False
        error_msg = str(e)
        logger.exception("Failed to send %s to %s", notif_type, email)

    # Log notification
    NotificationLog.objects.create(
        appointment=appointment,
        recipient_email=email,
        recipient_name=name,
        channel=NotificationLog.Channel.EMAIL,
        notif_type=notif_type,
        subject=subject,
        body=body,
        success=success,
        error_message=error_msg,
    )

    # Mark flags on appointment
    if success and recipient_type == "client":
        if notif_type == "reminder_24h":
            appointment.reminder_24h_sent = True
        elif notif_type == "reminder_1h":
            appointment.reminder_1h_sent = True
        appointment.save(update_fields=["reminder_24h_sent", "reminder_1h_sent"])
