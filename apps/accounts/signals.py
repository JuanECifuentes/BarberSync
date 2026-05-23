from django.dispatch import receiver
from allauth.account.signals import user_signed_up, user_logged_in

@receiver(user_signed_up)
def process_invitation_on_signup(request, user, **kwargs):
    pass

@receiver(user_logged_in)
def process_invitation_on_login(request, user, **kwargs):
    pass

