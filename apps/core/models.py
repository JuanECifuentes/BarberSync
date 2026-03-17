"""
Core abstract models for BarberSync.

Every tenant-scoped model inherits from TenantModel which enforces
barbershop-level data isolation. AuditModel adds automatic audit logging.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


# ─────────────────────────────────────────────────────────
# Audit Log (standalone table, replaces the old Auditoria)
# ─────────────────────────────────────────────────────────
class AuditLog(models.Model):
    """Immutable audit trail for any model change."""

    event = models.CharField(max_length=80)
    table_name = models.CharField(max_length=120)
    object_id = models.BigIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "core_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["table_name", "object_id"]),
        ]

    def __str__(self):
        return f"{self.event} on {self.table_name}#{self.object_id}"


# ─────────────────────────────────────────────────────────
# Abstract base: timestamps + audit
# ─────────────────────────────────────────────────────────
class AuditModel(models.Model):
    """
    Abstract model that adds created/updated timestamps and
    automatic audit logging on save.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_obj = None
        if not is_new:
            try:
                old_obj = self.__class__.objects.get(pk=self.pk)
            except self.__class__.DoesNotExist:
                pass

        super().save(*args, **kwargs)
        self._write_audit(old_obj, is_new)

    def _write_audit(self, old_obj, is_new):
        event = (
            f"{self._meta.label}.created"
            if is_new
            else f"{self._meta.label}.updated"
        )
        description = ""

        if not is_new and old_obj is not None:
            changes = {"before": {}, "after": {}}
            skip = {"updated_at", "updated_by"}
            for field in self._meta.fields:
                if field.name in skip:
                    continue
                old_val = getattr(old_obj, field.attname, None)
                new_val = getattr(self, field.attname, None)
                if old_val != new_val:
                    changes["before"][field.name] = str(old_val)
                    changes["after"][field.name] = str(new_val)
            if not changes["after"]:
                return  # nothing changed
            description = str(changes)
        else:
            description = f"Created {self._meta.label} id={self.pk}"

        AuditLog.objects.create(
            event=event,
            table_name=self._meta.db_table,
            object_id=self.pk,
            description=description,
            user=self.updated_by,
        )


# ─────────────────────────────────────────────────────────
# Abstract base: tenant-scoped model (Barbershop isolation)
# ─────────────────────────────────────────────────────────
class TenantModel(AuditModel):
    """
    Abstract model that ties every row to a Barbershop.
    Uses TenantManager to auto-filter queries by the current tenant.
    """

    barbershop = models.ForeignKey(
        "accounts.Barbershop",
        on_delete=models.CASCADE,
        related_name="%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True


# ─────────────────────────────────────────────────────────
# Abstract base: organization-scoped model
# ─────────────────────────────────────────────────────────
class OrganizationModel(AuditModel):
    """
    Abstract model scoped at the Organization level
    (e.g., shared CRM clients).
    """

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True
