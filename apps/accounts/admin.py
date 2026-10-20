from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class SkillForgeUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "est_valide", "is_active",
                    "date_joined")
    list_filter = ("role", "est_valide", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    actions = ("valider_formateurs", "activer", "desactiver")
    fieldsets = UserAdmin.fieldsets + (
        ("SkillForge", {"fields": ("role", "est_valide", "specialite", "bio")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("SkillForge", {"fields": ("email", "first_name", "last_name", "role")}),
    )

    @admin.action(description="Valider les formateurs sélectionnés")
    def valider_formateurs(self, request, queryset):
        n = queryset.filter(role=User.Role.FORMATEUR).update(est_valide=True)
        self.message_user(request, f"{n} formateur(s) validé(s).", messages.SUCCESS)

    @admin.action(description="Activer les comptes sélectionnés")
    def activer(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} compte(s) activé(s).", messages.SUCCESS)

    @admin.action(description="Désactiver les comptes sélectionnés")
    def desactiver(self, request, queryset):
        n = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, f"{n} compte(s) désactivé(s).", messages.SUCCESS)
