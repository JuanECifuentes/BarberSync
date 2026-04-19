"""
Client CRM – centralized at the Organization level.

A client who books at any barbershop within the organization
is stored once and accessible across all branches.
"""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import AuditModel, OrganizationModel

phone_validator = RegexValidator(
    regex=r"^\+?\d{7,15}$",
    message="El teléfono debe contener entre 7 y 15 dígitos.",
)


class Client(OrganizationModel):
    """
    A barbershop client. Shared across the organization (CRM centralizado).
    May be linked to a User if they authenticated via Google.
    Supports soft delete via is_active flag.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client_profile",
        help_text="Vinculado si el cliente se autenticó con Google.",
    )
    name = models.CharField("nombre", max_length=150)
    email = models.EmailField("correo", blank=True)
    phone = models.CharField(
        "teléfono", max_length=20, blank=True, validators=[phone_validator],
    )
    notes = models.TextField("notas internas", blank=True)
    source = models.CharField(
        "origen",
        max_length=30,
        default="booking",
        help_text="Cómo llegó: booking, manual, import, etc.",
    )
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        db_table = "clients_client"
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(email__gt="") & models.Q(is_active=True),
                name="unique_client_email_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "phone"],
                condition=models.Q(phone__gt="") & models.Q(is_active=True),
                name="unique_client_phone_per_org",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Auto-associate with User if email matches an existing platform user
        if not self.user_id and self.email:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                matching_user = User.objects.get(email__iexact=self.email)
                # Only link if this user isn't already linked to another client
                if not Client.objects.filter(user=matching_user).exclude(pk=self.pk).exists():
                    self.user = matching_user
            except User.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    @property
    def total_appointments(self):
        return self.appointments.count()

    @property
    def completed_appointments(self):
        return self.appointments.filter(status="completed").count()


class FichaClinica(AuditModel):
    """
    Ficha clínica/estética del cliente.
    Almacena historia clínica, recomendaciones y notas médicas/estéticas.
    """

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="fichas_clinicas",
    )
    historia_clinica = models.TextField(
        "historia clínica",
        blank=True,
        help_text="Historial médico/estético relevante del cliente.",
    )
    recomendaciones = models.TextField(
        "recomendaciones",
        blank=True,
        help_text="Recomendaciones de cuidado o tratamiento.",
    )
    notas_medicas = models.TextField(
        "notas médicas/estéticas",
        blank=True,
        help_text="Notas adicionales de carácter médico o estético.",
    )
    datos_extra = models.JSONField(
        "datos adicionales",
        default=dict,
        blank=True,
        help_text="Campos flexibles en formato JSON.",
    )

    class Meta:
        db_table = "clients_ficha_clinica"
        verbose_name = "ficha clínica"
        verbose_name_plural = "fichas clínicas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Ficha clínica – {self.client.name} ({self.created_at:%d/%m/%Y})"
