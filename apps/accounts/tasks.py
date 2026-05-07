from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import OrganizationInvitation


def send_invitation_email_task(invitation_id):
    """
    Sends the invitation email to the user.
    Called via django_q.
    """
    try:
        invitation = OrganizationInvitation.objects.select_related('organization').get(id=invitation_id)
    except OrganizationInvitation.DoesNotExist:
        return "Invitation does not exist"

    if not invitation.is_valid:
        return "Invitation is invalid or expired"

    # Construct the accept URL (assuming current site is correctly configured or using a specific setting)
    # We will need the site domain, normally retrieved via Site model or a settings variable
    domain = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000') # default fallback
    
    # We will create the AcceptInvitationView mapping to 'accounts:accept_invitation'
    accept_path = reverse('accounts:accept_invitation', kwargs={'token': str(invitation.token)})
    accept_url = f"{domain}{accept_path}"

    subject = f"Invitación a unirte a {invitation.organization.name} en BarberSync"
    message = (
        f"Hola,\n\n"
        f"Has sido invitado a unirte a la organización '{invitation.organization.name}' "
        f"con el rol de {invitation.get_role_display()}.\n\n"
        f"Por favor, haz clic en el siguiente enlace para aceptar la invitación y registrarte:\n\n"
        f"{accept_url}\n\n"
        f"Este enlace expira el {invitation.expires_at.strftime('%d/%m/%Y a las %H:%M')}.\n\n"
        f"Si no esperabas esta invitación, puedes ignorar este correo.\n\n"
        f"Saludos,\nEl equipo de BarberSync."
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email],
        fail_silently=False,
    )
    return "Email sent successfully"
