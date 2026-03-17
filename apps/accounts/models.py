"""
Accounts models – multi-tenant hierarchy.

Organization  (top-level tenant)
  └── Barbershop  (branch / sucursal)
        └── Membership  (links User ↔ Barbershop with a role)

User extends AbstractUser and acts as a single identity across the platform.
"""

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

phone_validator = RegexValidator(
    regex=r"^\+?\d{7,15}$",
    message="El teléfono debe contener entre 7 y 15 dígitos, opcionalmente con + al inicio.",
)


# ─────────────────────────────────────────────
# Custom User
# ─────────────────────────────────────────────
class User(AbstractUser):
    """
    Custom user.  Uses email as the primary login field.
    Username is kept for admin compat but is auto-generated.
    """

    email = models.EmailField("correo electrónico", unique=True)
    phone = models.CharField(
        "teléfono", max_length=20, blank=True, validators=[phone_validator]
    )
    avatar = models.ImageField(upload_to="avatars/", blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "accounts_user"
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def membership(self):
        """Return the user's active membership (cached on instance)."""
        if not hasattr(self, "_membership_cache"):
            self._membership_cache = (
                self.memberships.select_related("organization", "barbershop")
                .filter(is_active=True)
                .first()
            )
        return self._membership_cache


# ─────────────────────────────────────────────
# Organization (top-level tenant)
# ─────────────────────────────────────────────
class Organization(models.Model):
    name = models.CharField("nombre", max_length=120)
    slug = models.SlugField(unique=True, help_text="Identificador URL-friendly.")
    logo = models.ImageField(upload_to="org_logos/", blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_organization"
        verbose_name = "organización"
        verbose_name_plural = "organizaciones"

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────
# Barbershop (branch / sucursal)
# ─────────────────────────────────────────────
class Barbershop(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="barbershops",
    )
    name = models.CharField("nombre", max_length=120)
    slug = models.SlugField(
        help_text="Se usa para el link público de reservas.",
    )
    booking_uid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="ID público para el link de reservas.",
    )
    address = models.TextField("dirección", blank=True)
    phone = models.CharField(
        "teléfono", max_length=20, blank=True, validators=[phone_validator]
    )
    timezone = models.CharField(
        max_length=50, default="America/Bogota",
        help_text="Zona horaria de la sucursal.",
    )
    open_hour = models.PositiveSmallIntegerField(
        "hora de apertura", default=8
    )
    close_hour = models.PositiveSmallIntegerField(
        "hora de cierre", default=20
    )
    closed_days = models.JSONField(
        "días cerrados",
        default=list,
        blank=True,
        help_text='Lista de días de la semana cerrados (0=lunes, 6=domingo). Ej: [6]',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_barbershop"
        verbose_name = "barbería"
        verbose_name_plural = "barberías"
        unique_together = [("organization", "slug")]

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def get_booking_url(self):
        return f"/book/{self.booking_uid}/"


# ─────────────────────────────────────────────
# Membership (User ↔ Barbershop + role)
# ─────────────────────────────────────────────
class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Propietario"
        ADMIN = "admin", "Administrador"
        BARBER = "barber", "Barbero"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    barbershop = models.ForeignKey(
        Barbershop,
        on_delete=models.CASCADE,
        related_name="memberships",
        null=True,
        blank=True,
        help_text="Null = acceso a todas las sucursales de la organización.",
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_membership"
        verbose_name = "membresía"
        verbose_name_plural = "membresías"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization", "barbershop"],
                name="unique_membership",
            ),
        ]

    def __str__(self):
        shop = self.barbershop or "Todas"
        return f"{self.user} – {self.role} @ {shop}"


# ─────────────────────────────────────────────
# Barber Profile (extends membership for barbers)
# ─────────────────────────────────────────────
class BarberProfile(models.Model):
    """
    Extra info for users with the 'barber' role.
    Linked to their Membership + Barbershop.
    """

    membership = models.OneToOneField(
        Membership,
        on_delete=models.CASCADE,
        related_name="barber_profile",
        limit_choices_to={"role": "barber"},
    )
    display_name = models.CharField("nombre artístico", max_length=100, blank=True)
    phone = models.CharField(
        "teléfono", max_length=20, blank=True, validators=[phone_validator]
    )
    bio = models.TextField("biografía", blank=True)
    photo = models.ImageField(upload_to="barber_photos/", blank=True)
    instagram = models.URLField(blank=True)

    # Time management
    buffer_minutes = models.PositiveSmallIntegerField(
        "descanso entre servicios (min)", default=0,
        help_text="Minutos de buffer entre citas.",
    )
    lunch_start = models.TimeField(
        "inicio almuerzo", null=True, blank=True,
        help_text="Dejar vacío si no tiene horario fijo de almuerzo.",
    )
    lunch_end = models.TimeField(
        "fin almuerzo", null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_barber_profile"
        verbose_name = "perfil de barbero"
        verbose_name_plural = "perfiles de barbero"

    def __str__(self):
        return self.display_name or str(self.membership.user)

    @property
    def barbershop(self):
        return self.membership.barbershop

    @property
    def user(self):
        return self.membership.user
