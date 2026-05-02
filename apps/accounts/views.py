from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from django.contrib import messages

from .models import Barbershop, Membership
from .forms import ProfileForm


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
