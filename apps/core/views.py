import json

from django.views.generic import TemplateView
from django.conf import settings

from apps.billing.models import Plan, PlanPrice


from apps.core.utils import resolve_country_code


class LandingPageView(TemplateView):
    template_name = "landing.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = None
        if self.request.user.is_authenticated:
            membership = self.request.user.memberships.filter(is_active=True).first()
            if membership:
                org = membership.organization
        
        country_code = resolve_country_code(self.request)
        print(f"country_code resolved: {country_code}")


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

        has_sub = False
        if self.request.user.is_authenticated and org:
            has_sub = org.has_active_subscription
        ctx["has_active_subscription"] = has_sub

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
