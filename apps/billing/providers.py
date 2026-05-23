import hashlib
import hmac
import uuid
from abc import ABC, abstractmethod

import requests
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
            name=(
                organization.name
                if organization
                else f"Usuario: {user.get_full_name() or user.email}"
            ),
            metadata=metadata,
        )
        return customer.id

    def create_checkout_session(
        self, user, plan_price, success_url, cancel_url
    ) -> dict:
        membership = user.memberships.filter(is_active=True).first()
        organization = membership.organization if membership else None
        customer_id = self._ensure_customer(user, organization)

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
                "provider": "stripe",
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


class WompiProvider(BaseBillingProvider):
    """
    Wompi (Multipay) integration for Colombia (COP).

    Wompi uses an integrity hash (SHA-256) combining the checkout payload
    fields with the merchant's event secret key to prevent tampering.
    Amounts are stored in minor units (centavos for COP) and sent directly
    as amount_in_cents to the Wompi checkout.

    The Merchant Web Checkout URL is always https://checkout.wompi.co/checkout/
    regardless of sandbox/production mode. The public key (pub_test_ vs pub_prod_)
    determines the environment.
    """

    API_URL_SANDBOX = "https://sandbox.wompi.co/v1"
    API_URL_PRODUCTION = "https://production.wompi.co/v1"
    CHECKOUT_URL = "https://checkout.wompi.co/p/"

    def __init__(self):
        self.public_key = settings.WOMPI_PUBLIC_KEY
        self.private_key = settings.WOMPI_PRIVATE_KEY
        self.event_secret = settings.WOMPI_EVENT_SECRET
        self.integrity_secret = settings.WOMPI_INTEGRITY_SECRET
        self.is_sandbox = settings.WOMPI_SANDBOX
        self.api_url = (
            self.API_URL_SANDBOX if self.is_sandbox else self.API_URL_PRODUCTION
        )

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.private_key}",
            "Content-Type": "application/json",
        }

    def create_customer(self, user, organization) -> str:
        return f"wompi_cust_{organization.pk if organization else user.pk}"

    def create_checkout_session(
        self, user, plan_price, success_url, cancel_url
    ) -> dict:
        import time

        membership = user.memberships.filter(is_active=True).first()
        organization = membership.organization if membership else None

        reference = (
            f"bs_{plan_price.plan.code}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        )
        amount_in_cents = plan_price.amount_minor
        currency = plan_price.currency

        integrity_signature = self._generate_integrity_signature(
            reference=reference,
            amount_in_cents=amount_in_cents,
            currency=currency,
        )

        checkout_url = (
            f"{self.CHECKOUT_URL}"
            f"?public-key={self.public_key}"
            f"&currency={currency}"
            f"&amount-in-cents={amount_in_cents}"
            f"&reference={reference}"
            f"&signature:integrity={integrity_signature}"
            f"&redirect-url={success_url}"
        )

        return {
            "session_id": reference,
            "checkout_url": checkout_url,
            "reference": reference,
            "amount_in_cents": amount_in_cents,
            "currency": currency,
            "metadata": {
                "plan_code": plan_price.plan.code,
                "organization_id": organization.pk if organization else "",
                "user_id": user.pk,
                "provider": "wompi",
                "wompi_reference": reference,
            },
        }

    def cancel_subscription(self, subscription) -> bool:
        return True

    def validate_webhook_signature(self, request) -> bool:
        import json

        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return False

        sig_data = payload.get("signature", {})
        properties = sig_data.get("properties", [])
        received_sig = sig_data.get("checksum", "")
        timestamp = payload.get("timestamp")

        if not properties or not received_sig or timestamp is None:
            return False

        # Gather property values dynamically from payload data
        concat_str = ""
        data_obj = payload.get("data", {})
        for prop in properties:
            keys = prop.split(".")
            val = data_obj
            for key in keys:
                if isinstance(val, dict):
                    val = val.get(key)
                else:
                    val = None
                    break
            if val is not None:
                concat_str += str(val)

        # Append timestamp and the event secret
        concat_str += str(timestamp)
        concat_str += self.event_secret

        expected_sig = hashlib.sha256(concat_str.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected_sig, received_sig)

    def fetch_checkout_session(self, session_id: str) -> dict:
        try:
            response = requests.get(
                f"{self.api_url}/transactions/{session_id}",
                headers=self._headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            return {
                "session_id": data.get("id"),
                "status": data.get("status"),
                "reference": data.get("reference"),
                "amount_in_cents": data.get("amount_in_cents"),
                "currency": data.get("currency"),
                "metadata": data.get("metadata", {}),
            }
        except requests.RequestException:
            return {}

    def get_event_type(self, payload: dict) -> str:
        return payload.get("event", "")

    def get_event_id(self, payload: dict) -> str:
        return payload.get("event_id") or str(
            payload.get("data", {}).get("transaction", {}).get("id", "")
        )

    def _generate_integrity_signature(self, reference, amount_in_cents, currency):
        raw = f"{reference}{amount_in_cents}{currency}{self.integrity_secret}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BillingProviderFactory:
    _registry = {}
    _instances = {}

    PROVIDER_BY_COUNTRY = {
        "CO": "wompi",
    }
    DEFAULT_PROVIDER = "stripe"

    @classmethod
    def get_default_provider_for_country(cls, country_code: str) -> str:
        return cls.PROVIDER_BY_COUNTRY.get(country_code.upper(), cls.DEFAULT_PROVIDER)

    @classmethod
    def get_allowed_providers_for_country(cls, country_code: str) -> list:
        country = country_code.upper()
        if country == "CO":
            return ["wompi", "stripe"]
        return ["stripe"]

    @classmethod
    def get_provider(cls, provider: str) -> BaseBillingProvider:
        if provider in cls._instances:
            return cls._instances[provider]

        if provider == "stripe":
            instance = StripeProvider()
        elif provider == "wompi":
            instance = WompiProvider()
        else:
            raise ValueError(f"Proveedor de facturación desconocido: {provider}")

        cls._instances[provider] = instance
        return instance

    @classmethod
    def register_provider(cls, name: str, provider_cls: type):
        cls._registry[name] = provider_cls
