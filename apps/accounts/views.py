from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView

from .models import Barbershop, Membership


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"


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
