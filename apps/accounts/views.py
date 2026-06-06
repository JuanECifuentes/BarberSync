import json

from django.conf import settings
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
    """

    def get(self, request, token):
        user = EmailVerificationToken.consume_token(token)
        if user is None:
            return render(
                request,
                "accounts/email_verification_result.html",
                {
                    "success": False,
                    "is_booking_page": True,
                },
            )

        user.email_verification = True
        user.save(update_fields=["email_verification"])

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

        if not org_name:
            return JsonResponse(
                {"error": "El nombre de la organización es obligatorio."}, status=400
            )
        if not shop_name:
            return JsonResponse(
                {"error": "El nombre de la sucursal es obligatorio."}, status=400
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
                    shop.save(
                        update_fields=[
                            "name",
                            "slug",
                            "maps_location",
                            "maps_instructions",
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
        # Check if Google is linked and get the account info
        context["google_account"] = self.request.user.socialaccount_set.filter(
            provider="google"
        ).first()
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
