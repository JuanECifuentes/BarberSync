from django.dispatch import receiver
from allauth.account.signals import user_signed_up, user_logged_in


@receiver(user_signed_up)
def handle_signup(request, user, **kwargs):
    sociallogin = kwargs.get("sociallogin")
    if sociallogin:
        user.email_verification = True
        user.save(update_fields=["email_verification"])
        return

    try:
        from django_q.tasks import async_task

        async_task(
            "apps.accounts.tasks.send_verification_email_task",
            user.pk,
        )
    except ImportError:
        from .tasks import send_verification_email_task

        send_verification_email_task(user.pk)


@receiver(user_logged_in)
def process_invitation_on_login(request, user, **kwargs):
    pass
