"""
Client CRM – centralized at the Organization level.

A client who books at any barbershop within the organization
is stored once and accessible across all branches.
"""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import OrganizationModel

phone_validator = RegexValidator(
    regex=r"^\+?\d{7,15}$",
    message="El teléfono debe contener entre 7 y 15 dígitos.",
)


class Client(OrganizationModel):
    """
    A barbershop client. Shared across the organization (CRM centralizado).
    May be linked to a User if they authenticated via Google.
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

    class Meta:
        db_table = "clients_client"
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(email__gt=""),
                name="unique_client_email_per_org",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def total_appointments(self):
        return self.appointments.count()

    @property
    def completed_appointments(self):
        return self.appointments.filter(status="completed").count()
