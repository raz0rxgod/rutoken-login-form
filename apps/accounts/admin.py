from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import TokenCertificate, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "full_name", "role", "is_account_active", "is_staff")
    list_filter = ("role", "is_account_active")
    search_fields = ("username", "full_name", "email")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Данные для входа по Рутокену", {"fields": ("role", "full_name", "is_account_active")}),
    )


@admin.register(TokenCertificate)
class TokenCertificateAdmin(admin.ModelAdmin):
    list_display = ("subject_dn", "user", "serial_number", "valid_to", "is_revoked")
    list_filter = ("is_revoked",)
    search_fields = ("subject_dn", "serial_number", "thumbprint", "user__username")
    readonly_fields = ("created_at",)
    actions = ["revoke_selected"]

    @admin.action(description="Отозвать выбранные сертификаты")
    def revoke_selected(self, request, queryset):
        for cert in queryset:
            cert.revoke(reason=f"Отозвано администратором {request.user}")
