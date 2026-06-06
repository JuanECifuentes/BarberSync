"""
Accounts models – multi-tenant hierarchy.

Organization  (top-level tenant)
  └── Barbershop  (branch / sucursal)
        └── Membership  (links User ↔ Barbershop with a role)

User extends AbstractUser and acts as a single identity across the platform.
"""

import hashlib
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core import signing
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
    country_code = models.CharField(
        "código de país",
        max_length=5,
        help_text="Código de país para el número telefónico (ej. 57 para Colombia).",
    )
    phone_verification = models.BooleanField("teléfono verificado", default=False)
    email_verification = models.BooleanField("correo verificado", default=False)
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

    class OnboardingStep(models.IntegerChoices):
        NOT_STARTED = 0, "No iniciado"
        STEP_1 = 1, "Paso 1 – Organización y Sucursal"
        STEP_2 = 2, "Paso 2 – Catálogo de Servicios"
        COMPLETED = 3, "Completado"

    country_code = models.CharField(
        "país (ISO 3166-1 alpha-2)",
        max_length=2,
        default="CO",
        help_text="Código ISO del país. Determina la pasarela de pago por defecto.",
    )
    onboarding_step = models.PositiveSmallIntegerField(
        "paso de onboarding",
        choices=OnboardingStep.choices,
        default=OnboardingStep.NOT_STARTED,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_organization"
        verbose_name = "organización"
        verbose_name_plural = "organizaciones"

    def __str__(self):
        return self.name

    @property
    def has_active_subscription(self):
        if not hasattr(self, "_has_active_sub_cache"):
            self._has_active_sub_cache = self.subscriptions.filter(
                status__in=["trialing", "active", "past_due"]
            ).exists()
        return self._has_active_sub_cache


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
    maps_location = models.CharField(
        "ubicación (lat,lng)",
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Coordenadas del mapa en formato 'lat,lng'.",
    )
    maps_instructions = models.TextField(
        "indicaciones de llegada",
        blank=True,
        help_text="Indicaciones opcionales para llegar a la sucursal.",
    )
    timezone = models.CharField(
        max_length=50,
        default="America/Bogota",
        help_text="Zona horaria de la sucursal.",
    )
    open_hour = models.PositiveSmallIntegerField("hora de apertura", default=8)
    close_hour = models.PositiveSmallIntegerField("hora de cierre", default=20)
    hora_apertura = models.TimeField(
        "hora de apertura (TimeField)",
        null=True,
        blank=True,
        help_text="Hora exacta de apertura de la sucursal.",
    )
    hora_cierre = models.TimeField(
        "hora de cierre (TimeField)",
        null=True,
        blank=True,
        help_text="Hora exacta de cierre de la sucursal.",
    )
    closed_days = models.JSONField(
        "días cerrados",
        default=list,
        blank=True,
        help_text="Lista de días de la semana cerrados (0=lunes, 6=domingo). Ej: [6]",
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
        return f"/book/{self.slug}-{self.booking_uid}/"


# ─────────────────────────────────────────────
# Membership (User ↔ Barbershop + role)
# ─────────────────────────────────────────────
class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Propietario"
        ADMIN = "admin", "Administrador"
        BARBER = "barber", "Barbero"
        STAFF = "staff", "Personal Barberia"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
        null=True,
        blank=True,
    )
    barbershop = models.ForeignKey(
        Barbershop,
        on_delete=models.CASCADE,
        related_name="memberships",
        null=True,
        blank=True,
        help_text="Null = acceso a todas las sucursales de la organización.",
    )
    sucursales = models.ManyToManyField(
        Barbershop,
        related_name="memberships_assigned",
        blank=True,
        help_text="Sucursales adicionales asignadas (para selección múltiple).",
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

    # Multi-sucursal assignment
    sucursales = models.ManyToManyField(
        Barbershop,
        related_name="barberos",
        blank=True,
        verbose_name="sucursales asignadas",
        help_text="Sucursales donde trabaja este barbero.",
    )

    # Time management
    buffer_minutes = models.PositiveSmallIntegerField(
        "descanso entre servicios (min)",
        default=0,
        help_text="Minutos de buffer entre citas.",
    )
    lunch_start = models.TimeField(
        "inicio almuerzo",
        null=True,
        blank=True,
        help_text="Dejar vacío si no tiene horario fijo de almuerzo.",
    )
    lunch_end = models.TimeField(
        "fin almuerzo",
        null=True,
        blank=True,
    )
    intervalo_apertura_dias = models.PositiveSmallIntegerField(
        "ventana de apertura (días)",
        default=15,
        help_text="Días máximo en el futuro en los que un cliente puede agendar. Por defecto 15.",
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


# ─────────────────────────────────────────────
# Organization Invitation
# ─────────────────────────────────────────────
def get_default_expiration():
    return timezone.now() + timezone.timedelta(days=2)


class OrganizationInvitation(models.Model):
    email = models.EmailField("correo electrónico")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invitations"
    )
    sucursales = models.ManyToManyField(
        Barbershop, blank=True, related_name="invitations"
    )
    role = models.CharField(max_length=10, choices=Membership.Role.choices)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=get_default_expiration)
    is_used = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_organization_invitation"
        verbose_name = "invitación a organización"
        verbose_name_plural = "invitaciones a organización"

    def __str__(self):
        return f"Inv {self.email} -> {self.organization.name}"

    @property
    def is_valid(self):
        return self.is_active and not self.is_used and timezone.now() < self.expires_at


# ─────────────────────────────────────────────
# Email Verification Token (one-time crypto)
# ─────────────────────────────────────────────
class EmailVerificationToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verification_tokens",
    )
    token = models.CharField(max_length=255, unique=True, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    is_consumed = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_email_verification_token"
        verbose_name = "token de verificación de correo"
        verbose_name_plural = "tokens de verificación de correo"
        ordering = ["-created_at"]

    def __str__(self):
        status = "consumido" if self.is_consumed else "activo"
        return f"Token {self.user.email} ({status})"

    @classmethod
    def generate_for_user(cls, user):
        cls.objects.filter(user=user, is_consumed=False).update(
            is_consumed=True, consumed_at=timezone.now()
        )
        raw_token = signing.dumps(
            {"user_id": user.pk, "email": user.email},
            salt="barbersync-email-verification",
        )
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return cls.objects.create(
            user=user,
            token=raw_token,
            token_hash=token_hash,
        )

    @classmethod
    def consume_token(cls, raw_token):
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        try:
            obj = cls.objects.select_related("user").get(
                token_hash=token_hash,
                is_consumed=False,
            )
        except cls.DoesNotExist:
            return None
        try:
            signing.loads(
                raw_token, salt="barbersync-email-verification", max_age=86400
            )
        except signing.BadSignature:
            return None
        obj.is_consumed = True
        obj.consumed_at = timezone.now()
        obj.save(update_fields=["is_consumed", "consumed_at"])
        return obj.user
