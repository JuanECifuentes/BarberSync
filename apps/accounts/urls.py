from django.urls import path
from django.views.generic import TemplateView

from . import views

app_name = "accounts"

urlpatterns = [
    path("onboarding/", views.OnboardingView.as_view(), name="onboarding"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path(
        "switch-barbershop/<int:pk>/",
        views.SwitchBarbershopView.as_view(),
        name="switch_barbershop",
    ),
    path(
        "invite/<uuid:token>/",
        views.AcceptInvitationView.as_view(),
        name="accept_invitation",
    ),
    path(
        "confirm-email/<str:token>/",
        views.ConfirmEmailView.as_view(),
        name="confirm_email",
    ),
    path(
        "resend-verification/",
        views.ResendVerificationEmailView.as_view(),
        name="resend_verification",
    ),
    path(
        "onboarding/api/step1/",
        views.OnboardingStep1API.as_view(),
        name="onboarding_step1_api",
    ),
    path(
        "onboarding/api/step2/",
        views.OnboardingStep2API.as_view(),
        name="onboarding_step2_api",
    ),
    path(
        "onboarding/api/services/",
        views.OnboardingServicesAPI.as_view(),
        name="onboarding_services_api",
    ),
    # Phone OTP authentication
    path(
        "otp/send/",
        views.SendOTPView.as_view(),
        name="send_otp",
    ),
    path(
        "otp/verify/",
        views.VerifyOTPView.as_view(),
        name="verify_otp",
    ),
    path(
        "otp/resend/",
        views.ResendOTPView.as_view(),
        name="resend_otp",
    ),
    path(
        "phone-check/",
        views.CheckPhoneView.as_view(),
        name="check_phone",
    ),
    path(
        "country-code/",
        views.CountryCodeAPI.as_view(),
        name="country_code",
    ),
    path(
        "capture-name/",
        views.CaptureNameView.as_view(),
        name="capture_name",
    ),
    # Email linking (for phone-only accounts)
    path(
        "email-otp/send/",
        views.SendEmailOTPView.as_view(),
        name="send_email_otp",
    ),
    path(
        "email-otp/verify/",
        views.VerifyEmailOTPView.as_view(),
        name="verify_email_otp",
    ),
    path(
        "phone-login/",
        TemplateView.as_view(template_name="accounts/phone_login.html"),
        name="phone_login",
    ),
    path(
        "google/unlink/",
        views.UnlinkGoogleView.as_view(),
        name="unlink_google",
    ),
]
