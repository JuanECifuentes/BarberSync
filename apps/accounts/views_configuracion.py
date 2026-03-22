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
from .models import Barbershop, Organization


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
