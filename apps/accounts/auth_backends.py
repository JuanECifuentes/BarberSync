"""
Custom authentication backends for BarberSync.

PhoneOTPBackend: authenticates users via country_code + phone
after OTP verification has been confirmed by the view layer.
"""

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class PhoneOTPBackend(BaseBackend):
    """
    Authenticates a user by country_code + phone combination.
    The OTP verification itself is handled by the view layer (SmsVerificationRequest.verify_otp).
    This backend is invoked AFTER the OTP has been validated, simply
    retrieving the matching User object to log them in.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        country_code = kwargs.get("country_code")
        phone = kwargs.get("phone")

        if not country_code or not phone:
            return None

        phone_clean = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
        country_code_clean = country_code.strip().replace("+", "")

        try:
            user = User.objects.get(
                country_code=country_code_clean,
                phone=phone_clean,
                phone_verification=True,
            )
            return user
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
