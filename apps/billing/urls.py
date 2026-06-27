from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("success/", views.BillingSuccessView.as_view(), name="success"),
    path("cancel/", views.BillingCancelView.as_view(), name="cancel"),
    path(
        "subscription-status/",
        views.SubscriptionStatusCheckView.as_view(),
        name="subscription_status",
    ),
    path("plans/", views.PlanPricingView.as_view(), name="plans"),
    path("webhook/stripe/", views.StripeWebhookView.as_view(), name="webhook_stripe"),
    path("webhook/wompi/", views.WompiWebhookView.as_view(), name="webhook_wompi"),
]
