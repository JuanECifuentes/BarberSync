"""
Async tasks for accounts – invitation emails and email verification.

Refactored to use the centralized notification engine.
"""

from django.conf import settings
from django.urls import reverse

from apps.notifications.notifications import send_notification
from .models import OrganizationInvitation, EmailVerificationToken


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


def send_verification_email_task(user_id):
    """
    Generates a cryptographic one-time token and sends the verification email.
    Called via django_q async_task.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return "User does not exist"

    if user.email_verification:
        return "Email already verified"

    token_obj = EmailVerificationToken.generate_for_user(user)

    domain = getattr(settings, "SITE_URL", "http://127.0.0.1:8000")
    confirm_path = reverse("accounts:confirm_email", kwargs={"token": token_obj.token})
    confirm_url = f"{domain}{confirm_path}"

    context = {
        "recipient_name": user.get_full_name() or user.email,
        "confirm_url": confirm_url,
    }

    send_notification(
        recipient={
            "email": user.email,
            "phone": "",
            "name": user.get_full_name() or user.email,
        },
        notif_type="email_verification",
        context=context,
        channels=["email"],
        subject="Verifica tu correo en BarberSync",
        html_template="notifications/email_verification.html",
    )

    return "Verification email dispatched"
