from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("onboarding/", views.OnboardingView.as_view(), name="onboarding"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("switch-barbershop/<int:pk>/", views.SwitchBarbershopView.as_view(), name="switch_barbershop"),
    path("invite/<uuid:token>/", views.AcceptInvitationView.as_view(), name="accept_invitation"),
]
