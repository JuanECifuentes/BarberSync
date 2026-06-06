from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from allauth.core.exceptions import ImmediateHttpResponse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter for BarberSync social login handling.
    """

    def pre_social_login(self, request, sociallogin):
        """
        Called after a user successfully authenticates via a social provider,
        but before the login is processed.

        Handles the case where a user tries to sign in with Google using an email
        which already has a local password account. Instead of raising an error,
        we associate the social account and log the user in.
        """
        from allauth.account.models import EmailAddress
        from allauth.socialaccount.models import SocialAccount

        email = (
            sociallogin.email_addresses[0].email
            if sociallogin.email_addresses
            else None
        )
        if not email:
            return

        # Check if there's already an existing SocialAccount for this provider+uid
        try:
            existing_social = SocialAccount.objects.get(
                provider=sociallogin.account.provider,
                uid=sociallogin.account.uid,
            )
            # Already exists - let allauth handle it normally
            sociallogin.account = existing_social
            sociallogin.user = existing_social.user
            if not sociallogin.user.email_verification:
                sociallogin.user.email_verification = True
                sociallogin.user.save(update_fields=["email_verification"])
            return
        except SocialAccount.DoesNotExist:
            pass

        # Check if a local user with this email exists
        existing_email = EmailAddress.objects.filter(email__iexact=email).first()
        user = existing_email.user if (existing_email and existing_email.user) else None

        if not user:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.filter(email__iexact=email).first()

        # If the user is already authenticated and matches the found user,
        # they are just connecting their account, so we should allow it.
        if user and request.user.is_authenticated and request.user == user:
            if not user.email_verification:
                user.email_verification = True
                user.save(update_fields=["email_verification"])
            return

        if user:
            if user.has_usable_password():
                # User exists with this email and has a password
                # Do not auto-link. Show a conflict page.
                from django.shortcuts import render
                from allauth.core.exceptions import ImmediateHttpResponse

                response = render(
                    request,
                    "socialaccount/email_conflict.html",
                    {"email": email, "provider": sociallogin.account.provider},
                )
                raise ImmediateHttpResponse(response)
            else:
                # User exists but without a password (maybe another social account)
                # Connect the social account to the existing user
                sociallogin.user = user
                if not user.email_verification:
                    user.email_verification = True
                    user.save(update_fields=["email_verification"])

    def is_auto_signup_allowed(self, request, sociallogin):
        """
        Check if auto-signup is allowed.
        """
        return True

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None,
    ):
        """
        Handle authentication errors from social providers.

        When Google returns an error (e.g., invalid token, cancelled flow),
        we redirect to a styled error page instead of the generic allauth template.
        """
        from allauth.socialaccount.providers.base import AuthError

        if error == AuthError.CANCELLED:
            raise ImmediateHttpResponse(
                HttpResponseRedirect(reverse("socialaccount_login_cancelled"))
            )

        # For other errors, let allauth render its authentication_error template
        # Our custom template will be used since we created it in templates/socialaccount/
        pass
