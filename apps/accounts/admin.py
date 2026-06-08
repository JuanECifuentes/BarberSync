from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    BarberProfile,
    Barbershop,
    Membership,
    Organization,
    User,
    SmsVerificationRequest,
    EmailLinkVerification,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "is_active")
    prepopulated_fields = {"slug": ("name",)}


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Barbershop)
class BarbershopAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "phone", "is_active")
    list_filter = ("organization",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "barbershop", "role", "is_active")
    list_filter = ("role", "organization")


@admin.register(BarberProfile)
class BarberProfileAdmin(admin.ModelAdmin):
    list_display = ("__str__", "phone", "buffer_minutes", "is_active")


@admin.register(SmsVerificationRequest)
class SmsVerificationRequestAdmin(admin.ModelAdmin):
    list_display = ("phone", "country_code", "purpose", "created_at", "attempts")
    list_filter = ("purpose",)
    readonly_fields = ("otp_hash",)
    search_fields = ("phone", "country_code")


@admin.register(EmailLinkVerification)
class EmailLinkVerificationAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "created_at", "attempts")
    list_filter = ("user",)
    readonly_fields = ("otp_hash",)
