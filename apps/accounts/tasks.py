"""
Async tasks for accounts – invitation emails.

Refactored to use the centralized notification engine.
"""

from django.conf import settings
from django.urls import reverse

from apps.notifications.notifications import send_notification
from .models import OrganizationInvitation


def send_invitation_email_task(invitation_id):
    """
    Sends the invitation email via the centralized notification engine.
    Called via django_q async_task.
    """
    try:
        invitation = OrganizationInvitation.objects.select_related("organization").get(
            id=invitation_id
        )
    except OrganizationInvitation.DoesNotExist:
        return "Invitation does not exist"

    if not invitation.is_valid:
        return "Invitation is invalid or expired"

    domain = getattr(settings, "SITE_URL", "http://127.0.0.1:8000")
    accept_path = reverse(
        "accounts:accept_invitation", kwargs={"token": str(invitation.token)}
    )
    accept_url = f"{domain}{accept_path}"

    context = {
        "recipient_name": invitation.email,
        "organization_name": invitation.organization.name,
        "accept_url": accept_url,
        "expires_at": invitation.expires_at.strftime("%d/%m/%Y a las %H:%M"),
        "role_display": invitation.get_role_display(),
    }

    send_notification(
        recipient={"email": invitation.email, "phone": "", "name": invitation.email},
        notif_type="confirmation",
        context=context,
        channels=["email"],
        subject=f"Invitación a unirte a {invitation.organization.name} en BarberSync",
        html_template="notifications/invitation.html",
    )

    return "Notification dispatched"
