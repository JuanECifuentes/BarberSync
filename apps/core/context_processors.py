"""
Template context processors for BarberSync.
Makes tenant info and user role available in every template.
"""

from apps.accounts.models import Barbershop


def tenant_context(request):
    ctx = {
        "current_organization": getattr(request, "organization", None),
        "current_barbershop": getattr(request, "barbershop", None),
    }
    membership = getattr(request.user, "membership", None) if hasattr(request, "user") and request.user.is_authenticated else None
    if membership:
        ctx["user_role"] = membership.role
        ctx["is_owner"] = membership.role == "owner"
        ctx["is_admin"] = membership.role in ("owner", "admin")
        ctx["is_barber"] = membership.role == "barber"

        # All active barbershops for booking link popover
        org = getattr(request, "organization", None)
        if org and membership.role in ("owner", "admin"):
            ctx["all_barbershops"] = Barbershop.objects.filter(
                organization=org, is_active=True
            )
    return ctx
