from abc import ABC, abstractmethod

from django.conf import settings


class BaseBillingProvider(ABC):
    @abstractmethod
    def create_customer(self, user, organization) -> str:
        raise NotImplementedError

    @abstractmethod
    def create_checkout_session(
        self, user, plan_price, success_url, cancel_url
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def cancel_subscription(self, subscription) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate_webhook_signature(self, request) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch_checkout_session(self, session_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_event_type(self, payload: dict) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_event_id(self, payload: dict) -> str:
        raise NotImplementedError


class StripeProvider(BaseBillingProvider):
    def __init__(self):
        import stripe

        self.stripe = stripe
        self.stripe.api_key = settings.STRIPE_SECRET_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    def create_customer(self, user, organization) -> str:
        metadata = {"user_id": user.pk}
        if organization:
            metadata["organization_id"] = organization.pk

        customer = self.stripe.Customer.create(
            email=user.email,
            name=organization.name if organization else f"Usuario: {user.get_full_name() or user.email}",
            metadata=metadata,
        )
        return customer.id

    def create_checkout_session(
        self, user, plan_price, success_url, cancel_url
    ) -> dict:
        membership = user.memberships.filter(is_active=True).first()
        organization = membership.organization if membership else None
        customer_id = self._ensure_customer(user, organization)

        print(f"PROBANDO PLAN {plan_price.provider_price_id}")
        print(f"PROBANDO CUSTOMER {customer_id}")
        print(f"PROBANDO SUCCESS URL {success_url}")
        print(f"PROBANDO CANCEL URL {cancel_url}")
        print("PROBANDO METADATA ")
        print("plan_code: ", plan_price.plan.code)
        print("organization_id: ", organization.pk if organization else "")
        print("user_id: ", user.pk)

        session = self.stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": plan_price.provider_price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "plan_code": plan_price.plan.code,
                "organization_id": organization.pk if organization else "",
                "user_id": user.pk,
            },
        )
        return {"session_id": session.id, "checkout_url": session.url}

    def cancel_subscription(self, subscription) -> bool:
        if not subscription.provider_subscription_id:
            return False
        self.stripe.Subscription.modify(
            subscription.provider_subscription_id,
            cancel_at_period_end=True,
        )
        return True

    def validate_webhook_signature(self, request) -> bool:
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            self.stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            return True
        except (self.stripe.error.SignatureVerificationError, ValueError):
            return False

    def fetch_checkout_session(self, session_id: str) -> dict:
        session = self.stripe.checkout.Session.retrieve(session_id)
        return {
            "session_id": session.id,
            "status": session.status,
            "customer": session.customer,
            "subscription": session.subscription,
            "metadata": session.metadata,
        }

    def get_event_type(self, payload: dict) -> str:
        return payload.get("type", "")

    def get_event_id(self, payload: dict) -> str:
        return payload.get("id", "")

    def _ensure_customer(self, user, organization):
        from apps.billing.models import Subscription

        if organization:
            existing = (
                Subscription.objects.filter(
                    organization=organization, provider_customer_id__startswith="cus_"
                )
                .order_by("-created_at")
                .values_list("provider_customer_id", flat=True)
                .first()
            )
        else:
            existing = (
                Subscription.objects.filter(
                    user=user, provider_customer_id__startswith="cus_"
                )
                .order_by("-created_at")
                .values_list("provider_customer_id", flat=True)
                .first()
            )
        if existing:
            return existing
        return self.create_customer(user, organization)


class BillingProviderFactory:
    _registry = {}

    @classmethod
    def get_provider(cls, provider: str) -> BaseBillingProvider:
        if provider in cls._registry:
            return cls._registry[provider]()

        if provider == "stripe":
            provider_instance = StripeProvider()
            cls._registry[provider] = lambda: provider_instance
            return provider_instance

        raise ValueError(f"Proveedor de facturación desconocido: {provider}")

    @classmethod
    def register_provider(cls, name: str, provider_cls: type):
        cls._registry[name] = provider_cls
