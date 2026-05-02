"""
Views for the Configuración module.
Handles Organization settings and Barbershop (sucursal) CRUD with soft delete.
"""

import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from apps.core.mixins import RoleRequiredMixin
from .models import Barbershop, Organization, Membership, OrganizationInvitation
from django.utils import timezone


class ConfiguracionIndexView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "configuracion/index.html"
    allowed_roles = ["owner", "admin"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization
        ctx["organization"] = org
        ctx["sucursales"] = Barbershop.objects.filter(
            organization=org, is_active=True
        ).order_by("name")
        ctx["sucursales_inactivas"] = Barbershop.objects.filter(
            organization=org, is_active=False
        ).order_by("name")
        
        ctx["memberships"] = Membership.objects.filter(
            organization=org, is_active=True
        ).select_related("user").prefetch_related("sucursales").order_by("-role", "user__email")
        
        ctx["invitations"] = OrganizationInvitation.objects.filter(
            organization=org, is_active=True, is_used=False, expires_at__gt=timezone.now()
        ).prefetch_related("sucursales").order_by("-created_at")
        
        return ctx


class OrganizacionUpdateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner"]

    def post(self, request):
        org = request.organization
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "El nombre es requerido"}, status=400)

        org.name = name
        if "slug" in data and data["slug"].strip():
            new_slug = data["slug"].strip().lower()
            if Organization.objects.filter(slug=new_slug).exclude(pk=org.pk).exists():
                return JsonResponse({"error": "Ese slug ya está en uso"}, status=400)
            org.slug = new_slug
        org.save()
        return JsonResponse({"ok": True, "name": org.name, "slug": org.slug})


class OrganizacionLogoAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner"]

    def post(self, request):
        org = request.organization
        logo = request.FILES.get("logo")
        if not logo:
            return JsonResponse({"error": "No se envió un archivo"}, status=400)
        org.logo = logo
        org.save(update_fields=["logo"])
        return JsonResponse({"ok": True, "logo_url": org.logo.url})


class SucursalCreateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request):
        org = request.organization
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "El nombre es requerido"}, status=400)

        from django.utils.text import slugify
        slug = slugify(name)
        base_slug = slug
        counter = 1
        while Barbershop.objects.filter(organization=org, slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        barbershop = Barbershop.objects.create(
            organization=org,
            name=name,
            slug=slug,
            address=data.get("address", ""),
            phone=data.get("phone", ""),
            open_hour=int(data.get("open_hour", 8)),
            close_hour=int(data.get("close_hour", 20)),
        )
        return JsonResponse({
            "ok": True,
            "id": barbershop.pk,
            "name": barbershop.name,
            "slug": barbershop.slug,
        })


class SucursalUpdateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barbershop = Barbershop.objects.get(pk=pk, organization=org, is_active=True)
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal no encontrada"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "El nombre es requerido"}, status=400)

        barbershop.name = name
        barbershop.address = data.get("address", barbershop.address)
        barbershop.phone = data.get("phone", barbershop.phone)
        barbershop.open_hour = int(data.get("open_hour", barbershop.open_hour))
        barbershop.close_hour = int(data.get("close_hour", barbershop.close_hour))
        barbershop.save()
        return JsonResponse({"ok": True})


class SucursalDeactivateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    """Soft delete: sets is_active=False instead of deleting."""
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barbershop = Barbershop.objects.get(pk=pk, organization=org, is_active=True)
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal no encontrada"}, status=404)

        barbershop.is_active = False
        barbershop.save(update_fields=["is_active"])
        return JsonResponse({"ok": True})


class SucursalReactivateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    """Re-activate a soft-deleted barbershop."""
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            barbershop = Barbershop.objects.get(pk=pk, organization=org, is_active=False)
        except Barbershop.DoesNotExist:
            return JsonResponse({"error": "Sucursal no encontrada"}, status=404)

        barbershop.is_active = True
        barbershop.save(update_fields=["is_active"])
        return JsonResponse({"ok": True})


# ─────────────────────────────────────────────
# Invitations APIs
# ─────────────────────────────────────────────

class SendInvitationAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request):
        org = request.organization
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        email = data.get("email", "").strip().lower()
        role = data.get("role", "").strip()
        sucursales_ids = data.get("sucursales", [])

        if not email or not role:
            return JsonResponse({"error": "El email y el rol son obligatorios"}, status=400)

        valid_roles = [r[0] for r in Membership.Role.choices]
        if role not in valid_roles:
            return JsonResponse({"error": "Rol inválido"}, status=400)

        # Check if already has an active invitation
        if OrganizationInvitation.objects.filter(
            email=email, organization=org, is_active=True, is_used=False, expires_at__gt=timezone.now()
        ).exists():
            return JsonResponse({"error": "Ya existe una invitación activa para este correo"}, status=400)

        # Check if user is already a member
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if user and Membership.objects.filter(user=user, organization=org, is_active=True).exists():
            return JsonResponse({"error": "Este usuario ya es miembro de la organización"}, status=400)

        # Create invitation
        invitation = OrganizationInvitation.objects.create(
            email=email,
            organization=org,
            role=role,
        )

        if sucursales_ids:
            # Validate branches belong to organization
            sucursales = Barbershop.objects.filter(id__in=sucursales_ids, organization=org)
            invitation.sucursales.set(sucursales)

        # Enqueue email task
        try:
            from django_q.tasks import async_task
            async_task("apps.accounts.tasks.send_invitation_email_task", invitation.id)
        except ImportError:
            # fallback if django_q is not available during dev
            from apps.accounts.tasks import send_invitation_email_task
            send_invitation_email_task(invitation.id)

        return JsonResponse({"ok": True, "id": invitation.id})


class CancelInvitationAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            invitation = OrganizationInvitation.objects.get(pk=pk, organization=org, is_active=True)
            invitation.is_active = False
            invitation.save(update_fields=["is_active"])
            return JsonResponse({"ok": True})
        except OrganizationInvitation.DoesNotExist:
            return JsonResponse({"error": "Invitación no encontrada"}, status=404)


class ResendInvitationAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            old_invitation = OrganizationInvitation.objects.get(pk=pk, organization=org)
        except OrganizationInvitation.DoesNotExist:
            return JsonResponse({"error": "Invitación no encontrada"}, status=404)

        # Cancel old
        old_invitation.is_active = False
        old_invitation.save(update_fields=["is_active"])

        # Create new
        from .models import get_default_expiration
        new_invitation = OrganizationInvitation.objects.create(
            email=old_invitation.email,
            organization=org,
            role=old_invitation.role,
            expires_at=get_default_expiration()
        )
        new_invitation.sucursales.set(old_invitation.sucursales.all())

        # Enqueue email task
        try:
            from django_q.tasks import async_task
            async_task("apps.accounts.tasks.send_invitation_email_task", new_invitation.id)
        except ImportError:
            from apps.accounts.tasks import send_invitation_email_task
            send_invitation_email_task(new_invitation.id)

        return JsonResponse({"ok": True})


# ─────────────────────────────────────────────
# Users & Memberships APIs
# ─────────────────────────────────────────────

class UpdateMembershipAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            membership = Membership.objects.get(pk=pk, organization=org, is_active=True)
        except Membership.DoesNotExist:
            return JsonResponse({"error": "Miembro no encontrado"}, status=404)

        # Don't allow modifying owner unless it's the same user? Or just restrict owner role changes.
        if membership.role == Membership.Role.OWNER and membership.user != request.user:
            return JsonResponse({"error": "No puedes modificar al propietario"}, status=403)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        role = data.get("role", membership.role)
        sucursales_ids = data.get("sucursales", [])

        if role not in [r[0] for r in Membership.Role.choices]:
            return JsonResponse({"error": "Rol inválido"}, status=400)

        # If they are modifying the role of an owner to something else, protect it if it's the last owner
        if membership.role == Membership.Role.OWNER and role != Membership.Role.OWNER:
            owner_count = Membership.objects.filter(organization=org, role=Membership.Role.OWNER, is_active=True).count()
            if owner_count <= 1:
                return JsonResponse({"error": "Debe haber al menos un propietario en la organización"}, status=400)

        membership.role = role
        membership.save(update_fields=["role"])

        # Update branches
        sucursales = Barbershop.objects.filter(id__in=sucursales_ids, organization=org)
        membership.sucursales.set(sucursales)

        # If barber, update BarberProfile
        if role == Membership.Role.BARBER:
            from .models import BarberProfile
            profile, _ = BarberProfile.objects.get_or_create(membership=membership)
            profile.sucursales.set(sucursales)

        return JsonResponse({"ok": True})


class DeactivateMembershipAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        try:
            membership = Membership.objects.get(pk=pk, organization=org, is_active=True)
        except Membership.DoesNotExist:
            return JsonResponse({"error": "Miembro no encontrado"}, status=404)

        if membership.role == Membership.Role.OWNER:
            owner_count = Membership.objects.filter(organization=org, role=Membership.Role.OWNER, is_active=True).count()
            if owner_count <= 1:
                return JsonResponse({"error": "No puedes eliminar al único propietario de la organización"}, status=400)

        membership.is_active = False
        membership.save(update_fields=["is_active"])

        # If user is logged in, clear cache
        if hasattr(membership.user, "_membership_cache"):
            del membership.user._membership_cache

        return JsonResponse({"ok": True})

