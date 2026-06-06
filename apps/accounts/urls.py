from django.urls import path

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
]
