from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils import timezone
from django.shortcuts import render

from .models import Barbershop, Membership, OrganizationInvitation
from .forms import ProfileForm, OrganizationOnboardingForm, BarbershopOnboardingForm
from django.db import transaction

class OnboardingView(LoginRequiredMixin, View):
    template_name = "accounts/onboarding.html"

    def get(self, request):
        # Redirect if user already has an active membership with an organization
        membership = request.user.memberships.filter(is_active=True).first()
        if membership and membership.organization:
            return redirect("root")
            
        org_form = OrganizationOnboardingForm()
        shop_form = BarbershopOnboardingForm()
        return render(request, self.template_name, {
            "org_form": org_form,
            "shop_form": shop_form,
            "is_booking_page": True,
        })

    def post(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        if membership and membership.organization:
            return redirect("root")

        org_form = OrganizationOnboardingForm(request.POST)
        shop_form = BarbershopOnboardingForm(request.POST)

        if org_form.is_valid() and shop_form.is_valid():
            with transaction.atomic():
                org = org_form.save(commit=False)
                org.owner = request.user
                org.save()

                shop = shop_form.save(commit=False)
                shop.organization = org
                shop.save()

                if not membership:
                    membership = Membership.objects.create(
                        user=request.user,
                        organization=org,
                        role=Membership.Role.OWNER,
                        is_active=True
                    )
                else:
                    membership.organization = org
                    membership.save(update_fields=["organization"])

                # Update orphaned subscriptions and invoices
                from apps.billing.models import Subscription, Invoice
                Subscription.objects.filter(user=request.user, organization__isnull=True).update(organization=org)
                Invoice.objects.filter(user=request.user, organization__isnull=True).update(organization=org)
                
                if hasattr(request.user, "_membership_cache"):
                    del request.user._membership_cache

                messages.success(request, "¡Organización creada exitosamente! Bienvenido a BarberSync.")
                return redirect("root")

        return render(request, self.template_name, {
            "org_form": org_form,
            "shop_form": shop_form,
            "is_booking_page": True,
        })

class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Check if Google is linked and get the account info
        context['google_account'] = self.request.user.socialaccount_set.filter(provider='google').first()
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
        if membership is None or membership.organization_id != barbershop.organization_id:
            return JsonResponse({"error": "Sin permisos"}, status=403)

        # Deactivate old, activate new
        Membership.objects.filter(user=request.user, is_active=True).update(is_active=False)
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

        print('user_exists',user_exists)
        try:
            print('email request.user',request.user.is_authenticated, request.user.email.lower())
        except Exception as e:
            print('email request.user',e)
        print('email invitation',invitation.email.lower())
        context = {
            "invitation": invitation,
            "user_exists": user_exists,
            "email_match": request.user.is_authenticated and request.user.email.lower() == invitation.email.lower()
        }

        print('context',context)
        
        # Guardar token en sesión para que los signals funcionen si el usuario inicia sesión o se registra vía AllAuth
        request.session["invitation_token"] = str(token)
        
        return render(request, "accounts/accept_invitation.html", context)

    def post(self, request, token):
        invitation = get_object_or_404(OrganizationInvitation, token=token)

        if not invitation.is_valid:
            return JsonResponse({"error": "La invitación ya no es válida o expiró."}, status=400)

        action = request.POST.get("action")

        if action == "accept_logged_in":
            if not request.user.is_authenticated:
                return JsonResponse({"error": "No estás autenticado."}, status=401)
            if request.user.email.lower() != invitation.email.lower():
                return JsonResponse({"error": "El correo no coincide."}, status=403)
            
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
                return JsonResponse({"error": "La contraseña debe tener al menos 6 caracteres."}, status=400)

            from django.contrib.auth import get_user_model
            User = get_user_model()
            if User.objects.filter(email__iexact=invitation.email).exists():
                return JsonResponse({"error": "Este correo ya está registrado. Por favor inicia sesión."}, status=400)

            user = User.objects.create_user(
                username=invitation.email,  # o generar un username
                email=invitation.email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )

            # Auto login
            from django.contrib.auth import login
            # Allauth requiere backend especificado
            from django.contrib.auth.backends import ModelBackend
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            self.process_invitation(user, invitation)
            if "invitation_token" in request.session:
                del request.session["invitation_token"]

            return JsonResponse({"ok": True})

        return JsonResponse({"error": "Acción no válida."}, status=400)

    @staticmethod
    def process_invitation(user, invitation):
        if not invitation.is_valid:
            return

        # Check if membership already exists
        membership, created = Membership.objects.get_or_create(
            user=user,
            organization=invitation.organization,
            defaults={"role": invitation.role, "is_active": True}
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

