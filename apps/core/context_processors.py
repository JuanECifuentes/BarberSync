"""
Template context processors for BarberSync.
Makes tenant info and user role available in every template.
"""


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
    return ctx
