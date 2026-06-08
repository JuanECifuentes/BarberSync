import hashlib
import json

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views import View
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils import timezone
from django.shortcuts import render
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import (
    Barbershop,
    Membership,
    Organization,
    OrganizationInvitation,
    EmailVerificationToken,
    SmsVerificationRequest,
    EmailLinkVerification,
)
from .forms import ProfileForm, OrganizationOnboardingForm, BarbershopOnboardingForm


def _generate_unique_slug(model_class, name, exclude_pk=None, **filter_kwargs):
    base_slug = slugify(name)
    if not base_slug:
        base_slug = "item"
    slug = base_slug
    counter = 1
    while True:
        qs = model_class.objects.filter(slug=slug, **filter_kwargs)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


class ConfirmEmailView(View):
    """
    Consumes a one-time cryptographic token to verify the user's email.
    Completely session-agnostic: works regardless of whether the clicking
    user is logged in, logged in as a different user, or anonymous.
    """

    def get(self, request, token):
        from django.core import signing as django_signing

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        token_obj = (
            EmailVerificationToken.objects.filter(
                token_hash=token_hash,
                is_consumed=False,
            )
            .select_related("user")
            .first()
        )

        if token_obj is None:
            return render(
                request,
                "accounts/email_verification_result.html",
                {
                    "success": False,
                    "is_booking_page": True,
                },
            )

        try:
            django_signing.loads(
                token, salt="barbersync-email-verification", max_age=86400
            )
        except django_signing.SignatureExpired:
            return render(
                request,
                "accounts/email_verification_result.html",
                {
                    "success": False,
                    "is_booking_page": True,
                },
            )
        except django_signing.BadSignature:
            return render(
                request,
                "accounts/email_verification_result.html",
                {
                    "success": False,
                    "is_booking_page": True,
                },
            )

        token_obj.is_consumed = True
        token_obj.consumed_at = timezone.now()
        token_obj.save(update_fields=["is_consumed", "consumed_at"])

        target_user = token_obj.user
        target_user.email_verification = True
        target_user.save(update_fields=["email_verification"])

        return render(
            request,
            "accounts/email_verification_result.html",
            {
                "success": True,
                "is_booking_page": True,
            },
        )


class ResendVerificationEmailView(LoginRequiredMixin, View):
    """
    Re-dispatches the verification email for the authenticated user.
    """

    def post(self, request):
        if request.user.email_verification:
            return JsonResponse({"error": "Tu correo ya está verificado."}, status=400)

        try:
            from django_q.tasks import async_task

            async_task(
                "apps.accounts.tasks.send_verification_email_task",
                request.user.pk,
            )
        except ImportError:
            from .tasks import send_verification_email_task

            send_verification_email_task(request.user.pk)

        return JsonResponse(
            {"ok": True, "message": "Correo de verificación reenviado."}
        )


class OnboardingView(LoginRequiredMixin, View):
    template_name = "accounts/onboarding.html"

    def _get_onboarding_state(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        org = membership.organization if membership else None
        shop = None
        has_services = False
        current_step = 1

        if org:
            shop = org.barbershops.filter(is_active=True).first()
            from apps.scheduling.models import Service

            has_services = Service.objects.filter(barbershop__organization=org).exists()

            if has_services:
                return None, None, None, None, None

            if org.onboarding_step >= Organization.OnboardingStep.STEP_2:
                current_step = 2
            else:
                current_step = 1

        return membership, org, shop, has_services, current_step

    def get(self, request):
        membership, org, shop, has_services, current_step = self._get_onboarding_state(
            request
        )

        if membership and org and has_services:
            if org.has_active_subscription:
                return redirect("/app/schedule/")
            return redirect("/?expired=true#planes")

        org_form = OrganizationOnboardingForm(
            prefix="org",
            initial={"name": org.name} if org else None,
        )
        shop_form = BarbershopOnboardingForm(
            prefix="shop",
            initial={
                "name": shop.name,
                "maps_location": shop.maps_location or "",
                "maps_instructions": shop.maps_instructions or "",
                "hora_apertura": shop.hora_apertura or "08:00",
                "hora_cierre": shop.hora_cierre or "20:00",
            }
            if shop
            else None,
        )

        google_maps_api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")

        return render(
            request,
            self.template_name,
            {
                "org_form": org_form,
                "shop_form": shop_form,
                "current_step": current_step,
                "org": org,
                "shop": shop,
                "google_maps_api_key": google_maps_api_key,
                "is_booking_page": True,
            },
        )


class OnboardingStep1API(LoginRequiredMixin, View):
    """
    Saves Step 1: Organization + First Branch.
    Creates or updates existing records. Sets onboarding_step = 2.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        org_name = (data.get("org_name") or "").strip()
        shop_name = (data.get("shop_name") or "").strip()
        maps_location = (data.get("maps_location") or "").strip()
        maps_instructions = (data.get("maps_instructions") or "").strip()
        open_time = (data.get("open_time") or "").strip()
        close_time = (data.get("close_time") or "").strip()

        if not org_name:
            return JsonResponse(
                {"error": "El nombre de la organización es obligatorio."}, status=400
            )
        if not shop_name:
            return JsonResponse(
                {"error": "El nombre de la sucursal es obligatorio."}, status=400
            )
        if not open_time or not close_time:
            return JsonResponse(
                {"error": "El horario de apertura y cierre son obligatorios."},
                status=400,
            )

        from datetime import datetime as dt

        try:
            open_h = dt.strptime(open_time, "%H:%M").hour
            close_h = dt.strptime(close_time, "%H:%M").hour
        except ValueError:
            return JsonResponse(
                {"error": "Formato de hora inválido. Use HH:MM."}, status=400
            )

        if open_time >= close_time:
            return JsonResponse(
                {"error": "La hora de cierre debe ser posterior a la de apertura."},
                status=400,
            )

        membership = request.user.memberships.filter(is_active=True).first()

        with transaction.atomic():
            if membership and membership.organization:
                org = membership.organization
                if org.owner_id != request.user.pk:
                    return JsonResponse({"error": "Sin permisos."}, status=403)
                org.name = org_name
                org.slug = _generate_unique_slug(
                    Organization, org_name, exclude_pk=org.pk
                )
                org.onboarding_step = Organization.OnboardingStep.STEP_2
                org.save(update_fields=["name", "slug", "onboarding_step"])

                shop = org.barbershops.filter(is_active=True).first()
                if shop:
                    shop.name = shop_name
                    shop.slug = _generate_unique_slug(
                        Barbershop, shop_name, exclude_pk=shop.pk, organization=org
                    )
                    shop.maps_location = maps_location
                    shop.maps_instructions = maps_instructions
                    shop.hora_apertura = open_time
                    shop.hora_cierre = close_time
                    shop.open_hour = open_h
                    shop.close_hour = close_h
                    shop.save(
                        update_fields=[
                            "name",
                            "slug",
                            "maps_location",
                            "maps_instructions",
                            "hora_apertura",
                            "hora_cierre",
                            "open_hour",
                            "close_hour",
                        ]
                    )
                else:
                    shop = Barbershop.objects.create(
                        organization=org,
                        name=shop_name,
                        slug=_generate_unique_slug(
                            Barbershop, shop_name, organization=org
                        ),
                        maps_location=maps_location,
                        maps_instructions=maps_instructions,
                        hora_apertura=open_time,
                        hora_cierre=close_time,
                        open_hour=open_h,
                        close_hour=close_h,
                    )
            else:
                org = Organization.objects.create(
                    name=org_name,
                    slug=_generate_unique_slug(Organization, org_name),
                    owner=request.user,
                    onboarding_step=Organization.OnboardingStep.STEP_2,
                )

                shop = Barbershop.objects.create(
                    organization=org,
                    name=shop_name,
                    slug=_generate_unique_slug(Barbershop, shop_name, organization=org),
                    maps_location=maps_location,
                    maps_instructions=maps_instructions,
                    hora_apertura=open_time,
                    hora_cierre=close_time,
                    open_hour=open_h,
                    close_hour=close_h,
                )

                if not membership:
                    Membership.objects.create(
                        user=request.user,
                        organization=org,
                        role=Membership.Role.OWNER,
                        is_active=True,
                    )
                else:
                    membership.organization = org
                    membership.save(update_fields=["organization"])

                from apps.billing.models import Subscription, Invoice

                Subscription.objects.filter(
                    user=request.user, organization__isnull=True
                ).update(organization=org)
                Invoice.objects.filter(
                    user=request.user, organization__isnull=True
                ).update(organization=org)
                Subscription.objects.filter(
                    organization__isnull=True,
                    user__isnull=True,
                ).update(organization=org, user=request.user)

            if hasattr(request.user, "_membership_cache"):
                del request.user._membership_cache

        return JsonResponse(
            {
                "ok": True,
                "org_id": org.pk,
                "shop_id": shop.pk,
                "org_name": org.name,
                "shop_name": shop.name,
            }
        )


class OnboardingStep2API(LoginRequiredMixin, View):
    """
    Saves Step 2: Service catalog.
    Creates categories and services in bulk. Sets onboarding_step = COMPLETED.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        services_data = data.get("services", [])
        if not services_data:
            return JsonResponse(
                {"error": "Debes seleccionar al menos 1 servicio."}, status=400
            )

        membership = request.user.memberships.filter(is_active=True).first()
        if not membership or not membership.organization:
            return JsonResponse({"error": "Sin organización."}, status=403)

        org = membership.organization
        if org.owner_id != request.user.pk:
            return JsonResponse({"error": "Sin permisos."}, status=403)

        shop = org.barbershops.filter(is_active=True).first()
        if not shop:
            return JsonResponse({"error": "Sin sucursal."}, status=400)

        from apps.scheduling.models import CategoriaServicio, Service

        with transaction.atomic():
            category_cache = {}
            created_services = []

            for svc in services_data:
                cat_name = (svc.get("category") or "General").strip()
                svc_name = (svc.get("name") or "").strip()
                duration = int(svc.get("duration", 30))
                price = float(svc.get("price", 0))

                if not svc_name:
                    continue
                if duration < 5:
                    duration = 5

                if cat_name not in category_cache:
                    cat, _ = CategoriaServicio.objects.get_or_create(
                        barbershop=shop,
                        name=cat_name,
                        defaults={"is_active": True},
                    )
                    category_cache[cat_name] = cat

                category = category_cache[cat_name]

                service = Service.objects.create(
                    barbershop=shop,
                    category=category,
                    name=svc_name,
                    duration_minutes=duration,
                    price=price,
                    is_active=True,
                )
                created_services.append(service.pk)

            org.onboarding_step = Organization.OnboardingStep.COMPLETED
            org.save(update_fields=["onboarding_step"])

        return JsonResponse(
            {
                "ok": True,
                "services_created": len(created_services),
                "redirect": "/app/schedule/",
            }
        )


class OnboardingServicesAPI(LoginRequiredMixin, View):
    """
    Returns existing services for the organization (for step 2 resume).
    """

    def get(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        if not membership or not membership.organization:
            return JsonResponse({"error": "Sin organización."}, status=403)

        org = membership.organization
        from apps.scheduling.models import Service, CategoriaServicio

        shop = org.barbershops.filter(is_active=True).first()
        if not shop:
            return JsonResponse({"services": []})

        services = Service.objects.filter(barbershop=shop).select_related("category")
        result = []
        for svc in services:
            result.append(
                {
                    "id": svc.pk,
                    "name": svc.name,
                    "category": svc.category.name if svc.category else "General",
                    "duration": svc.duration_minutes,
                    "price": str(svc.price),
                }
            )

        return JsonResponse({"services": result})


class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["google_account"] = self.request.user.socialaccount_set.filter(
            provider="google"
        ).first()
        context["has_linked_email"] = bool(
            self.request.user.email and self.request.user.email_verification
        )
        context["has_google"] = self.request.user.socialaccount_set.filter(
            provider="google"
        ).exists()
        context["can_edit_email"] = (
            not context["has_linked_email"] and not context["has_google"]
        )
        context["phone_display"] = (
            f"+{self.request.user.country_code}{self.request.user.phone}"
            if self.request.user.phone
            else ""
        )
        context["is_phone_verified"] = self.request.user.phone_verification
        return context

    def form_valid(self, form):
        messages.success(self.request, "Tu perfil ha sido actualizado correctamente.")
        return super().form_valid(form)


class SwitchBarbershopView(LoginRequiredMixin, View):
    """
    Allows an owner/admin to switch the active barbershop
    they are managing within the same organization.
    """

    def post(self, request, pk):
        barbershop = get_object_or_404(Barbershop, pk=pk, is_active=True)
        membership = request.user.membership
        if (
            membership is None
            or membership.organization_id != barbershop.organization_id
        ):
            return JsonResponse({"error": "Sin permisos"}, status=403)

        # Deactivate old, activate new
        Membership.objects.filter(user=request.user, is_active=True).update(
            is_active=False
        )
        new_membership, _ = Membership.objects.get_or_create(
            user=request.user,
            organization=barbershop.organization,
            barbershop=barbershop,
            defaults={"role": membership.role},
        )
        new_membership.is_active = True
        new_membership.save(update_fields=["is_active"])

        # Clear cached membership
        if hasattr(request.user, "_membership_cache"):
            del request.user._membership_cache

        return redirect("scheduling:calendar")


class AcceptInvitationView(View):
    """
    Handles when a user clicks the invitation link.
    """

    def get(self, request, token):
        invitation = get_object_or_404(OrganizationInvitation, token=token)

        if not invitation.is_valid:
            return render(request, "accounts/invitation_invalid.html")

        # Check if user with this email exists
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_exists = User.objects.filter(email__iexact=invitation.email).exists()

        current_active_org_name = ""
        has_blocking_subscription = False
        if request.user.is_authenticated:
            active_membership = (
                request.user.memberships.filter(is_active=True)
                .exclude(organization=invitation.organization)
                .first()
            )
            if active_membership and active_membership.organization:
                current_active_org_name = active_membership.organization.name
                if (
                    active_membership.role == "owner"
                    and active_membership.organization.has_active_subscription
                ):
                    has_blocking_subscription = True

        context = {
            "invitation": invitation,
            "user_exists": user_exists,
            "email_match": request.user.is_authenticated
            and request.user.email.lower() == invitation.email.lower(),
            "current_active_org_name": current_active_org_name,
            "has_blocking_subscription": has_blocking_subscription,
        }

        # Guardar token en sesión para que los signals funcionen si el usuario inicia sesión o se registra vía AllAuth
        request.session["invitation_token"] = str(token)

        return render(request, "accounts/accept_invitation.html", context)

    def post(self, request, token):
        invitation = get_object_or_404(OrganizationInvitation, token=token)

        if not invitation.is_valid:
            return JsonResponse(
                {"error": "La invitación ya no es válida o expiró."}, status=400
            )

        action = request.POST.get("action")

        if action == "accept_logged_in":
            if not request.user.is_authenticated:
                return JsonResponse({"error": "No estás autenticado."}, status=401)
            if request.user.email.lower() != invitation.email.lower():
                return JsonResponse({"error": "El correo no coincide."}, status=403)

            active_membership = (
                request.user.memberships.filter(is_active=True)
                .exclude(organization=invitation.organization)
                .first()
            )
            if active_membership and active_membership.organization:
                if (
                    active_membership.role == "owner"
                    and active_membership.organization.has_active_subscription
                ):
                    return JsonResponse(
                        {
                            "error": "No se pudo completar la operación debido a que cuentas con una suscripción activa como propietario. Debes cancelarla primero antes de aceptar la invitación."
                        },
                        status=400,
                    )

            self.process_invitation(request.user, invitation)
            if "invitation_token" in request.session:
                del request.session["invitation_token"]
            return JsonResponse({"ok": True})

        elif action == "register":
            if request.user.is_authenticated:
                return JsonResponse({"error": "Ya estás autenticado."}, status=400)

            password = request.POST.get("password")
            first_name = request.POST.get("first_name", "")
            last_name = request.POST.get("last_name", "")

            if not password or len(password) < 6:
                return JsonResponse(
                    {"error": "La contraseña debe tener al menos 6 caracteres."},
                    status=400,
                )

            from django.contrib.auth import get_user_model

            User = get_user_model()
            if User.objects.filter(email__iexact=invitation.email).exists():
                return JsonResponse(
                    {
                        "error": "Este correo ya está registrado. Por favor inicia sesión."
                    },
                    status=400,
                )

            user = User.objects.create_user(
                username=invitation.email,  # o generar un username
                email=invitation.email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )

            # Auto login
            from django.contrib.auth import login

            # Allauth requiere backend especificado
            from django.contrib.auth.backends import ModelBackend

            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

            self.process_invitation(user, invitation)
            if "invitation_token" in request.session:
                del request.session["invitation_token"]

            return JsonResponse({"ok": True})

        return JsonResponse({"error": "Acción no válida."}, status=400)

    @staticmethod
    def process_invitation(user, invitation):
        if not invitation.is_valid:
            return

        # Deactivate all active memberships in other organizations
        user.memberships.filter(is_active=True).exclude(
            organization=invitation.organization
        ).update(is_active=False)

        # Check if membership already exists
        membership, created = Membership.objects.get_or_create(
            user=user,
            organization=invitation.organization,
            defaults={"role": invitation.role, "is_active": True},
        )
        if not created:
            membership.role = invitation.role
            membership.is_active = True
            membership.save(update_fields=["role", "is_active"])

        # Update branches
        if invitation.sucursales.exists():
            membership.sucursales.set(invitation.sucursales.all())

        invitation.is_used = True
        invitation.save(update_fields=["is_used"])

        # If barber, ensure BarberProfile exists
        if invitation.role == Membership.Role.BARBER:
            from .models import BarberProfile

            profile, _ = BarberProfile.objects.get_or_create(membership=membership)
            if invitation.sucursales.exists():
                profile.sucursales.set(invitation.sucursales.all())


# ─────────────────────────────────────────────
# Phone OTP Authentication
# ─────────────────────────────────────────────


class SendOTPView(View):
    """
    Sends a 6-digit OTP code to the given phone number via SMS.
    Supports both login (existing user) and registration (new user).
    Rate-limited by SmsVerificationRequest.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        phone = (data.get("phone") or "").strip()
        country_code = (data.get("country_code") or "").strip()

        if not phone or not country_code:
            return JsonResponse(
                {"error": "Número de teléfono y código de país son obligatorios."},
                status=400,
            )

        phone = phone.replace(" ", "").replace("-", "").replace("+", "")
        country_code = country_code.replace("+", "")

        if not phone.isdigit() or len(phone) < 7 or len(phone) > 15:
            return JsonResponse(
                {
                    "error": "Número de teléfono inválido. Debe contener entre 7 y 15 dígitos."
                },
                status=400,
            )

        purpose = data.get("purpose", "login")
        if purpose not in ("login", "register"):
            purpose = "login"

        User = get_user_model()
        if purpose == "login":
            exists = User.objects.filter(
                country_code=country_code, phone=phone, phone_verification=True
            ).exists()
            if not exists:
                return JsonResponse(
                    {"error": "No existe una cuenta con este número de teléfono."},
                    status=404,
                )

        ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if not ip_address:
            ip_address = request.META.get("REMOTE_ADDR")

        otp_obj, otp_code_or_error = SmsVerificationRequest.create_otp(
            phone=phone,
            country_code=country_code,
            ip_address=ip_address,
            purpose=purpose,
        )

        if otp_obj is None:
            if otp_code_or_error == "rate_limit_hourly":
                return JsonResponse(
                    {
                        "error": "Has excedido el límite de solicitudes. Intenta nuevamente en una hora.",
                        "code": "rate_limit_hourly",
                    },
                    status=429,
                )
            elif otp_code_or_error == "cooldown_active":
                active = (
                    SmsVerificationRequest.objects.filter(
                        phone=phone,
                        country_code=country_code,
                        expires_at__gt=timezone.now(),
                    )
                    .order_by("-created_at")
                    .first()
                )
                remaining = 0
                if active and active.cooldown_until:
                    remaining = int(
                        (active.cooldown_until - timezone.now()).total_seconds()
                    )
                    remaining = max(remaining, 0)
                return JsonResponse(
                    {
                        "error": "Debes esperar antes de solicitar un nuevo código.",
                        "code": "cooldown_active",
                        "cooldown_remaining": remaining,
                    },
                    status=429,
                )

        full_phone = f"+{country_code}{phone}"
        try:
            from apps.notifications.notifications import send_notification

            send_notification(
                recipient={"email": "", "phone": full_phone, "name": phone},
                notif_type="phone_otp",
                context={
                    "recipient_name": phone,
                    "barbershop_name": "BarberSync",
                    "start_time": timezone.now(),
                    "otp_code": otp_code_or_error,
                },
                channels=["sms"],
                subject=f"Tu código de verificación BarberSync: {otp_code_or_error}",
                html_template="notifications/phone_otp.html",
            )
        except Exception:
            pass

        return JsonResponse(
            {
                "ok": True,
                "message": "Código de verificación enviado.",
                "cooldown_seconds": SmsVerificationRequest.COOLDOWN_SECONDS,
            }
        )


class VerifyOTPView(View):
    """
    Verifies the OTP code sent to a phone number.
    For login: authenticates an existing user.
    For registration: creates a new user account (deferred creation).
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        phone = (data.get("phone") or "").strip()
        country_code = (data.get("country_code") or "").strip()
        otp_code = (data.get("otp_code") or "").strip()
        purpose = data.get("purpose", "login")

        if not phone or not country_code or not otp_code:
            return JsonResponse(
                {"error": "Teléfono, código de país y OTP son obligatorios."},
                status=400,
            )

        phone = phone.replace(" ", "").replace("-", "").replace("+", "")
        country_code = country_code.replace("+", "")

        result, message = SmsVerificationRequest.verify_otp(
            phone, country_code, otp_code
        )

        if result is None:
            error_status = 400
            if message == "max_attempts":
                error_status = 429
            return JsonResponse(
                {
                    "error": {
                        "expired": "El código ha expirado. Solicita uno nuevo.",
                        "invalid": "Código incorrecto. Intenta de nuevo.",
                        "max_attempts": "Has excedido el número de intentos. Solicita un nuevo código.",
                    }.get(message, f"Error: {message}"),
                    "code": message,
                },
                status=error_status,
            )

        User = get_user_model()

        if purpose == "register":
            existing = User.objects.filter(
                country_code=country_code, phone=phone
            ).first()

            if existing:
                if existing.phone_verification:
                    purpose = "login"
                else:
                    existing.phone_verification = True
                    existing.save(update_fields=["phone_verification"])
                    login(
                        request,
                        existing,
                        backend="apps.accounts.auth_backends.PhoneOTPBackend",
                    )
                    needs_name = not existing.first_name.strip()
                    return JsonResponse(
                        {
                            "ok": True,
                            "purpose": "register",
                            "needs_name": needs_name,
                            "redirect": "/accounts/capture-name/"
                            if needs_name
                            else "/app/schedule/",
                        }
                    )

            username = f"phone_{country_code}{phone}_{User.objects.count() + 1}"
            user = User.objects.create_user(
                username=username,
                email=None,
                password=None,
                country_code=country_code,
                phone=phone,
                phone_verification=True,
            )
            user.set_unusable_password()
            user.save()

            login(request, user, backend="apps.accounts.auth_backends.PhoneOTPBackend")

            return JsonResponse(
                {
                    "ok": True,
                    "purpose": "register",
                    "needs_name": True,
                    "redirect": "/accounts/capture-name/",
                }
            )

        else:
            try:
                user = User.objects.get(
                    country_code=country_code, phone=phone, phone_verification=True
                )
            except User.DoesNotExist:
                return JsonResponse(
                    {"error": "No existe una cuenta con este número de teléfono."},
                    status=404,
                )

            login(request, user, backend="apps.accounts.auth_backends.PhoneOTPBackend")

            membership = user.memberships.filter(is_active=True).first()
            if membership and membership.organization:
                from apps.scheduling.models import Service

                has_services = Service.objects.filter(
                    barbershop__organization=membership.organization
                ).exists()
                if not has_services:
                    redirect_url = "/accounts/onboarding/"
                elif not membership.organization.has_active_subscription:
                    redirect_url = "/?expired=true#planes"
                else:
                    redirect_url = "/app/schedule/"
            else:
                redirect_url = "/accounts/onboarding/"

            needs_name = not user.first_name.strip()

            return JsonResponse(
                {
                    "ok": True,
                    "purpose": "login",
                    "needs_name": needs_name,
                    "redirect": redirect_url,
                }
            )


class ResendOTPView(View):
    """
    Resends an OTP code after cooldown validation.
    Backend-enforced cooldown prevents API abuse.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        phone = (data.get("phone") or "").strip()
        country_code = (data.get("country_code") or "").strip()

        if not phone or not country_code:
            return JsonResponse(
                {"error": "Número de teléfono y código de país son obligatorios."},
                status=400,
            )

        phone = phone.replace(" ", "").replace("-", "").replace("+", "")
        country_code = country_code.replace("+", "")

        allowed, remaining = SmsVerificationRequest.resend_allowed(phone, country_code)
        if not allowed:
            return JsonResponse(
                {
                    "error": "Debes esperar antes de solicitar un nuevo código.",
                    "code": "cooldown_active",
                    "cooldown_remaining": remaining,
                },
                status=429,
            )

        ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if not ip_address:
            ip_address = request.META.get("REMOTE_ADDR")

        purpose = data.get("purpose", "login")
        otp_obj, otp_code_or_error = SmsVerificationRequest.create_otp(
            phone=phone,
            country_code=country_code,
            ip_address=ip_address,
            purpose=purpose,
        )

        if otp_obj is None:
            if otp_code_or_error == "rate_limit_hourly":
                return JsonResponse(
                    {
                        "error": "Has excedido el límite de solicitudes. Intenta nuevamente en una hora.",
                        "code": "rate_limit_hourly",
                    },
                    status=429,
                )
            return JsonResponse(
                {"error": "No se pudo enviar el código.", "code": otp_code_or_error},
                status=400,
            )

        full_phone = f"+{country_code}{phone}"
        try:
            from apps.notifications.notifications import send_notification

            send_notification(
                recipient={"email": "", "phone": full_phone, "name": phone},
                notif_type="phone_otp",
                context={
                    "recipient_name": phone,
                    "barbershop_name": "BarberSync",
                    "start_time": timezone.now(),
                    "otp_code": otp_code_or_error,
                },
                channels=["sms"],
                subject=f"Tu código de verificación BarberSync: {otp_code_or_error}",
                html_template="notifications/phone_otp.html",
            )
        except Exception:
            pass

        return JsonResponse(
            {
                "ok": True,
                "message": "Nuevo código enviado.",
                "cooldown_seconds": SmsVerificationRequest.COOLDOWN_SECONDS,
            }
        )


class CountryCodeAPI(View):
    """
    Returns the detected country code based on the user's IP.
    Used by the frontend to auto-select the phone prefix.
    """

    def get(self, request):
        from apps.core.utils import resolve_country_code

        code = resolve_country_code(request)

        COUNTRY_PREFIXES = {
            "CO": "57",
            "US": "1",
            "MX": "52",
            "AR": "54",
            "CL": "56",
            "PE": "51",
            "EC": "593",
            "VE": "58",
            "BR": "55",
            "ES": "34",
            "PA": "507",
            "CR": "506",
            "DO": "1",
            "GT": "502",
            "SV": "503",
            "HN": "504",
            "NI": "505",
            "PY": "595",
            "UY": "598",
            "BO": "591",
        }

        phone_prefix = COUNTRY_PREFIXES.get(code, "57")
        country_name_map = {
            "CO": "Colombia",
            "US": "Estados Unidos",
            "MX": "México",
            "AR": "Argentina",
            "CL": "Chile",
            "PE": "Perú",
            "EC": "Ecuador",
            "VE": "Venezuela",
            "BR": "Brasil",
            "ES": "España",
        }
        country_name = country_name_map.get(code, code)

        return JsonResponse(
            {
                "country_code": code,
                "phone_prefix": phone_prefix,
                "country_name": country_name,
            }
        )


class CaptureNameView(LoginRequiredMixin, View):
    """
    Forces recently registered phone-only users to provide their name.
    """

    template_name = "accounts/capture_name.html"

    def get(self, request):
        if request.user.first_name.strip():
            return redirect("/app/schedule/")
        return render(request, self.template_name, {"is_booking_page": True})

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()

        if not first_name:
            return JsonResponse(
                {"error": "Tu nombre es obligatorio para continuar."},
                status=400,
            )

        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.save(update_fields=["first_name", "last_name"])

        membership = request.user.memberships.filter(is_active=True).first()
        if not membership or not membership.organization:
            return JsonResponse({"ok": True, "redirect": "/accounts/onboarding/"})

        org = membership.organization
        from apps.scheduling.models import Service

        has_services = Service.objects.filter(barbershop__organization=org).exists()
        if not has_services:
            return JsonResponse({"ok": True, "redirect": "/accounts/onboarding/"})

        if not org.has_active_subscription:
            return JsonResponse({"ok": True, "redirect": "/?expired=true#planes"})

        return JsonResponse({"ok": True, "redirect": "/app/schedule/"})


class CheckPhoneView(View):
    """
    Checks if a phone number is already registered.
    Used by the frontend to determine login vs register flow.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        phone = (data.get("phone") or "").strip()
        country_code = (data.get("country_code") or "").strip()

        if not phone or not country_code:
            return JsonResponse(
                {"error": "Número de teléfono y código de país son obligatorios."},
                status=400,
            )

        phone = phone.replace(" ", "").replace("-", "").replace("+", "")
        country_code = country_code.replace("+", "")

        User = get_user_model()
        exists = User.objects.filter(country_code=country_code, phone=phone).exists()

        return JsonResponse({"exists": exists})


class SendEmailOTPView(LoginRequiredMixin, View):
    """
    Sends a verification OTP to a new email address for phone-only users.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        email = (data.get("email") or "").strip()

        if not email:
            return JsonResponse(
                {"error": "El correo electrónico es obligatorio."},
                status=400,
            )

        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse(
                {"error": "Correo electrónico inválido."},
                status=400,
            )

        User = get_user_model()
        if (
            User.objects.filter(email__iexact=email)
            .exclude(pk=request.user.pk)
            .exists()
        ):
            return JsonResponse(
                {"error": "Este correo electrónico ya está en uso por otra cuenta."},
                status=409,
            )

        has_google = request.user.socialaccount_set.filter(provider="google").exists()
        if request.user.email and request.user.email_verification and has_google:
            return JsonResponse(
                {"error": "Tu correo ya está vinculado y verificado."},
                status=400,
            )

        otp_obj, otp_code_or_error = EmailLinkVerification.create_otp(
            user=request.user, email=email
        )

        if otp_obj is None:
            if otp_code_or_error == "rate_limit_hourly":
                return JsonResponse(
                    {
                        "error": "Has excedido el límite de solicitudes. Intenta en una hora.",
                        "code": "rate_limit_hourly",
                    },
                    status=429,
                )
            elif otp_code_or_error == "cooldown_active":
                return JsonResponse(
                    {
                        "error": "Debes esperar antes de solicitar un nuevo código.",
                        "code": "cooldown_active",
                    },
                    status=429,
                )

        try:
            from apps.notifications.notifications import send_notification

            send_notification(
                recipient={
                    "email": email,
                    "phone": "",
                    "name": request.user.get_full_name() or request.user.phone,
                },
                notif_type="email_verification",
                context={
                    "recipient_name": request.user.get_full_name()
                    or request.user.phone,
                    "confirm_url": "",
                    "otp_code": otp_code_or_error,
                },
                channels=["email"],
                subject=f"Tu código de verificación BarberSync: {otp_code_or_error}",
                html_template="notifications/email_link_otp.html",
            )
        except Exception:
            pass

        return JsonResponse(
            {
                "ok": True,
                "message": "Código de verificación enviado a tu correo.",
                "cooldown_seconds": EmailLinkVerification.COOLDOWN_SECONDS,
            }
        )


class VerifyEmailOTPView(LoginRequiredMixin, View):
    """
    Verifies the OTP for email linking and saves the email to the user account.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        otp_code = (data.get("otp_code") or "").strip()

        if not otp_code:
            return JsonResponse(
                {"error": "El código de verificación es obligatorio."},
                status=400,
            )

        result, message = EmailLinkVerification.verify_otp(request.user, otp_code)

        if result is None:
            error_status = 400
            if message == "max_attempts":
                error_status = 429
            error_messages = {
                "expired": "El código ha expirado. Solicita uno nuevo.",
                "invalid": "Código incorrecto. Intenta de nuevo.",
                "max_attempts": "Has excedido los intentos. Solicita un nuevo código.",
            }
            return JsonResponse(
                {
                    "error": error_messages.get(message, f"Error: {message}"),
                    "code": message,
                },
                status=error_status,
            )

        request.user.email = result
        request.user.email_verification = True
        request.user.save(update_fields=["email", "email_verification"])

        return JsonResponse(
            {
                "ok": True,
                "message": "Correo electrónico vinculado exitosamente.",
                "email": result,
            }
        )
