from django.dispatch import receiver
from allauth.account.signals import user_signed_up, user_logged_in

@receiver(user_signed_up)
def process_invitation_on_signup(request, user, **kwargs):
    token = request.session.get("invitation_token")
    if token:
        from apps.accounts.models import OrganizationInvitation
        from apps.accounts.views import AcceptInvitationView
        try:
            invitation = OrganizationInvitation.objects.get(token=token, is_used=False)
            if invitation.is_valid and invitation.email.lower() == user.email.lower():
                AcceptInvitationView.process_invitation(user, invitation)
                del request.session["invitation_token"]
        except OrganizationInvitation.DoesNotExist:
            pass

@receiver(user_logged_in)
def process_invitation_on_login(request, user, **kwargs):
    token = request.session.get("invitation_token")
    if token:
        from apps.accounts.models import OrganizationInvitation
        from apps.accounts.views import AcceptInvitationView
        try:
            invitation = OrganizationInvitation.objects.get(token=token, is_used=False)
            if invitation.is_valid and invitation.email.lower() == user.email.lower():
                AcceptInvitationView.process_invitation(user, invitation)
                del request.session["invitation_token"]
        except OrganizationInvitation.DoesNotExist:
            pass
