"""
Servicio Unificado de Notificaciones (Multicanal Asíncrono) – BarberSync

Función central: send_notification()
Despacha correos y/o SMS de forma asíncrona vía django_q.

Uso:
    from apps.notifications.notifications import send_notification

    send_notification(
        recipient=user_or_dict,
        notif_type="reschedule_client",
        context={...},
        channels=["email", "sms"],
    )
"""

import logging
import re
from html import unescape

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from apps.notifications.models import NotificationLog

logger = logging.getLogger(__name__)

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def _html_to_plain_text(html_body: str) -> str:
    # Remove style and script blocks and their content to prevent CSS leaking to plain text
    clean_body = re.sub(r"<(style|script)\b[^>]*>([\s\S]*?)<\/\1>", "", html_body, flags=re.IGNORECASE)
    text = HTML_TAG_RE.sub("", clean_body)
    text = unescape(text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def _truncate_for_sms(text: str, max_length: int = 160) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _build_sms_message(context: dict, notif_type: str) -> str:
    barbershop = context.get("barbershop_name", "BarberSync")
    client_name = context.get("recipient_name", "")
    barber_name = context.get("barber_name", "")
    start_time = context.get("start_time")
    service_names = context.get("service_names", "")
    otp_code = context.get("otp_code", "")

    fmt_time = ""
    if start_time:
        try:
            fmt_time = start_time.strftime("%d/%m/%Y %H:%M")
        except Exception:
            fmt_time = str(start_time)

    templates = {
        "reminder_24h": f"{barbershop}: Tu cita manana a las {fmt_time}. Servicios: {service_names}",
        "reminder_1h": f"{barbershop}: Tu cita es en 1 hora ({fmt_time}).",
        "barber_reminder": f"{barbershop}: Cita en 1 hora con {client_name} ({fmt_time}).",
        "cancellation": f"{barbershop}: Tu cita del {fmt_time} ha sido cancelada.",
        "confirmation": f"{barbershop}: Cita confirmada para el {fmt_time} con {barber_name}.",
        "reschedule_client": f"{barbershop}: Tu cita fue reprogramada al {fmt_time} con {barber_name}.",
        "reschedule_barber": f"{barbershop}: Tu cita con {client_name} fue reprogramada al {fmt_time} por administracion.",
        "phone_otp": f"{barbershop}: Tu codigo de verificacion es {otp_code}.",
    }

    msg = templates.get(
        notif_type, f"{barbershop}: Notificacion sobre tu cita del {fmt_time}."
    )
    return _truncate_for_sms(msg, 160)


def _get_aws_client(service_name: str):
    aws_access_key_id = getattr(settings, "AWS_ACCESS_KEY_ID", None)
    aws_secret_access_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
    region_name = getattr(settings, "AWS_REGION_NAME", "us-east-1")

    import boto3

    kwargs = {}
    if aws_access_key_id and aws_secret_access_key:
        kwargs["aws_access_key_id"] = aws_access_key_id
        kwargs["aws_secret_access_key"] = aws_secret_access_key
    if region_name:
        kwargs["region_name"] = region_name

    return boto3.client(service_name, **kwargs)


def _send_email_sync(
    recipient_email: str,
    recipient_name: str,
    subject: str,
    html_body: str,
    notif_type: str,
    appointment_id: int | None,
) -> bool:
    success = True
    error_msg = ""

    try:
        recipient_formatted = recipient_email
        if recipient_name:
            recipient_formatted = f"{recipient_name} <{recipient_email}>"

        send_mail(
            subject=subject,
            message=_html_to_plain_text(html_body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_formatted],
            html_message=html_body,
            fail_silently=False,
        )
    except Exception as e:
        success = False
        error_msg = str(e)
        logger.exception(
            "Failed to send email %s to %s via Django email backend", notif_type, recipient_email
        )

    NotificationLog.objects.create(
        appointment_id=appointment_id,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        channel=NotificationLog.Channel.EMAIL,
        notif_type=notif_type,
        subject=subject,
        body=html_body,
        success=success,
        error_message=error_msg,
    )
    return success


def _send_sms_sync(
    phone: str,
    recipient_name: str,
    message: str,
    notif_type: str,
    appointment_id: int | None,
) -> bool:
    success = True
    error_msg = ""

    aws_configured = bool(
        getattr(settings, "AWS_ACCESS_KEY_ID", None)
        and getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
    ) or not getattr(settings, "LOCAL", False)

    sent_via_sns = False

    if aws_configured:
        try:
            client = _get_aws_client("sns")
            formatted_phone = phone.strip()
            # Basic E.164 normalization for SNS if missing standard + prefix
            if formatted_phone and not formatted_phone.startswith("+"):
                if formatted_phone.isdigit():
                    formatted_phone = f"+{formatted_phone}"

            client.publish(
                PhoneNumber=formatted_phone,
                Message=message,
                MessageAttributes={
                    "AWS.SNS.SMS.SMSType": {
                        "DataType": "String",
                        "StringValue": "Transactional",
                    }
                },
            )
            sent_via_sns = True
        except (ImportError, Exception) as e:
            success = False
            error_msg = str(e)
            logger.exception("Failed to send SMS %s to %s via AWS SNS", notif_type, phone)
    else:
        logger.info(
            "SMS skipped (AWS SNS not configured): %s -> %s (Message: %s)",
            notif_type,
            phone,
            message,
        )

    NotificationLog.objects.create(
        appointment_id=appointment_id,
        recipient_phone=phone,
        recipient_name=recipient_name,
        channel=NotificationLog.Channel.SMS,
        notif_type=notif_type,
        subject="",
        body=message,
        success=success if (sent_via_sns or not aws_configured) else False,
        error_message=error_msg,
    )
    return success



def _dispatch_notification_task(
    recipient_email: str,
    recipient_phone: str,
    recipient_name: str,
    notif_type: str,
    subject: str,
    html_body: str,
    sms_message: str,
    channels: list[str],
    appointment_id: int | None,
):
    if "email" in channels and recipient_email:
        _send_email_sync(
            recipient_email,
            recipient_name,
            subject,
            html_body,
            notif_type,
            appointment_id,
        )

    if "sms" in channels and recipient_phone:
        _send_sms_sync(
            recipient_phone, recipient_name, sms_message, notif_type, appointment_id
        )


def send_notification(
    recipient,
    notif_type: str,
    context: dict | None = None,
    channels: list[str] | None = None,
    appointment_id: int | None = None,
    subject: str | None = None,
    html_template: str | None = None,
):
    """
    Centralized multichannel notification dispatcher.

    Args:
        recipient: Either a dict with keys 'email', 'phone', 'name',
                   or a Django User/Client object with those attributes.
        notif_type: One of NotificationLog.NotifType values or a custom string.
        context: Template context dict (barbershop_name, start_time, etc.).
        channels: List of channels to use. Defaults to ['email'].
                  Supported: 'email', 'sms'.
        appointment_id: Optional appointment PK for logging.
        subject: Email subject override. Auto-generated if None.
        html_template: Template path override for email body.

    The function queues the actual sending via django_q (async_task) so that
    no HTTP thread is ever blocked by email/SMS I/O.
    """
    if context is None:
        context = {}
    if channels is None:
        channels = ["email"]

    if isinstance(recipient, dict):
        email = recipient.get("email", "")
        phone = recipient.get("phone", "")
        name = recipient.get("name", "")
    else:
        email = getattr(recipient, "email", "")
        phone = getattr(recipient, "phone", "")
        name = str(recipient) if not hasattr(recipient, "name") else recipient.name

    context.setdefault("recipient_name", name)

    domain = getattr(settings, "SITE_URL", "http://127.0.0.1:8000")
    context.setdefault("site_url", domain)

    subject_map = {
        "reminder_24h": f"Recordatorio: tu cita mañana en {context.get('barbershop_name', 'BarberSync')}",
        "reminder_1h": f"Tu cita en {context.get('barbershop_name', 'BarberSync')} es en 1 hora",
        "barber_reminder": f"Cita en 1 hora: {context.get('client_name', context.get('recipient_name', ''))}",
        "cancellation": f"Cita cancelada en {context.get('barbershop_name', 'BarberSync')}",
        "confirmation": f"Cita confirmada en {context.get('barbershop_name', 'BarberSync')}",
        "reschedule_client": f"Cita reprogramada en {context.get('barbershop_name', 'BarberSync')}",
        "reschedule_barber": f"Agenda modificada: cita reprogramada en {context.get('barbershop_name', 'BarberSync')}",
        "phone_otp": f"Tu código de verificación {context.get('barbershop_name', 'BarberSync')}: {context.get('otp_code', '')}",
        "email_verification": f"Tu código de verificación {context.get('barbershop_name', 'BarberSync')}: {context.get('otp_code', '')}",
    }
    final_subject = subject or subject_map.get(notif_type, "Notificación – BarberSync")

    default_template = f"notifications/{notif_type}.html"
    template_path = html_template or default_template

    try:
        html_body = render_to_string(template_path, context)
    except Exception:
        html_body = (
            f"Hola {name},\n\n"
            f"Te informamos sobre tu cita en {context.get('barbershop_name', 'BarberSync')} "
            f"el {context.get('start_time', '')}.\n\n"
            f"– BarberSync"
        )

    sms_message = _build_sms_message(context, notif_type)

    try:
        from django_q.tasks import async_task

        async_task(
            "apps.notifications.notifications._dispatch_notification_task",
            email,
            phone,
            name,
            notif_type,
            final_subject,
            html_body,
            sms_message,
            channels,
            appointment_id,
        )
    except ImportError:
        logger.warning("django_q not available, sending notification synchronously")
        _dispatch_notification_task(
            email,
            phone,
            name,
            notif_type,
            final_subject,
            html_body,
            sms_message,
            channels,
            appointment_id,
        )


def send_appointment_reminders(appointment_id: int):
    """
    Convenience wrapper: queue 24h, 1h (client) and 1h (barber) reminders
    for a newly-created or rescheduled appointment via django_q schedule().
    """
    from datetime import timedelta

    try:
        from django_q.tasks import schedule
        from django_q.models import Schedule

        from apps.scheduling.models import Appointment

        appointment = Appointment.objects.select_related(
            "client", "barber__membership__user"
        ).get(pk=appointment_id)
        start = appointment.start_time

        reminder_24h = start - timedelta(hours=24)
        if reminder_24h > timezone.now():
            schedule(
                "apps.notifications.notifications._send_reminder_task",
                appointment_id,
                "reminder_24h",
                "client",
                name=f"reminder_24h_apt_{appointment_id}",
                schedule_type=Schedule.ONCE,
                next_run=reminder_24h,
            )

        reminder_1h = start - timedelta(hours=1)
        if reminder_1h > timezone.now():
            schedule(
                "apps.notifications.notifications._send_reminder_task",
                appointment_id,
                "reminder_1h",
                "client",
                name=f"reminder_1h_apt_{appointment_id}",
                schedule_type=Schedule.ONCE,
                next_run=reminder_1h,
            )

        if reminder_1h > timezone.now():
            schedule(
                "apps.notifications.notifications._send_reminder_task",
                appointment_id,
                "barber_reminder",
                "barber",
                name=f"barber_reminder_apt_{appointment_id}",
                schedule_type=Schedule.ONCE,
                next_run=reminder_1h,
            )

    except Exception:
        logger.exception(
            "Error scheduling reminders for appointment %s", appointment_id
        )


def _send_reminder_task(appointment_id: int, notif_type: str, recipient_type: str):
    """
    Task executed by django_q worker for scheduled reminders.
    Uses send_notification() so all channels/logging are centralized.
    """
    from apps.scheduling.models import Appointment

    try:
        appointment = Appointment.objects.select_related(
            "client", "barber__membership__user", "barbershop"
        ).get(pk=appointment_id)
    except Appointment.DoesNotExist:
        logger.warning("Appointment %s not found for reminder", appointment_id)
        return

    if appointment.status in ("cancelled", "no_show"):
        return

    if not appointment.client:
        return

    service_names = ", ".join(
        appointment.services.values_list("service__name", flat=True)
    )

    context = {
        "appointment": appointment,
        "recipient_name": "",
        "service_names": service_names,
        "barbershop_name": appointment.barbershop.name,
        "barber_name": str(appointment.barber),
        "start_time": appointment.start_time,
        "client_name": appointment.client.name,
    }

    channels = ["email"]

    if recipient_type == "client":
        context["client_name"] = appointment.client.name
        recipient = {
            "email": appointment.client.email,
            "phone": appointment.client.phone,
            "name": appointment.client.name,
        }
        if appointment.client.phone:
            channels.append("sms")

        email = appointment.client.email
        name = appointment.client.name
        if notif_type == "reminder_24h":
            appointment.reminder_24h_sent = True
        elif notif_type == "reminder_1h":
            appointment.reminder_1h_sent = True
        appointment.save(update_fields=["reminder_24h_sent", "reminder_1h_sent"])

    else:
        recipient = {
            "email": appointment.barber.user.email,
            "phone": getattr(appointment.barber, "phone", "") or "",
            "name": str(appointment.barber),
        }
        if recipient["phone"]:
            channels.append("sms")

    send_notification(
        recipient=recipient,
        notif_type=notif_type,
        context=context,
        channels=channels,
        appointment_id=appointment_id,
    )
