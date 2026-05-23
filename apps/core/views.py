import json

from django.views.generic import TemplateView
from django.conf import settings

from apps.billing.models import Plan, PlanPrice


class LandingPageView(TemplateView):
    template_name = "landing.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            org = None
            membership = self.request.user.memberships.filter(is_active=True).first()
            if membership:
                org = membership.organization
            country_code = getattr(org, "country_code", "") if org else ""
        else:
            country_code = ""

        country_config = settings.BILLING_COUNTRY_PROVIDER_MAP.get(
            country_code.upper(), {}
        )
        allowed_providers = country_config.get(
            "allowed", [settings.BILLING_DEFAULT_PROVIDER]
        )
        default_provider = country_config.get(
            "default", settings.BILLING_DEFAULT_PROVIDER
        )
        ctx["billing_allowed_providers"] = allowed_providers
        ctx["billing_default_provider"] = default_provider
        ctx["billing_country_code"] = country_code.upper()

        plan_prices = {}
        for plan in Plan.objects.filter(is_active=True):
            prices = {}
            for price in PlanPrice.objects.filter(
                plan=plan, is_current=True
            ).select_related("plan"):
                prices[price.provider] = {
                    "amount_minor": price.amount_minor,
                    "currency": price.currency,
                }
            plan_prices[plan.code] = prices
        ctx["plan_prices"] = json.dumps(plan_prices)

        return ctx
