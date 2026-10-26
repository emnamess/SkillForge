from django.contrib import admin
from django import forms

from .models import Cours, Inscription, Lesson, LessonContent, LessonProgress, Module, ProgressionModule


@admin.register(Cours)
class CoursAdmin(admin.ModelAdmin):
    list_display = ("titre", "formateur", "categorie", "niveau", "est_publie", "date_creation")
    list_filter = ("est_publie", "niveau", "categorie", "date_creation")
    search_fields = (
        "titre",
        "description",
        "formateur__username",
        "formateur__email",
        "formateur__first_name",
        "formateur__last_name",
    )
    list_select_related = ("formateur",)
    date_hierarchy = "date_creation"


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("titre", "cours", "ordre")
    list_filter = ("cours",)
    search_fields = ("titre", "description", "contenu", "cours__titre")
    list_select_related = ("cours",)


@admin.register(Inscription)
class InscriptionAdmin(admin.ModelAdmin):
    list_display = ("apprenant", "cours", "progression", "date_inscription")
    list_filter = ("cours", "progression", "date_inscription")
    search_fields = (
        "apprenant__username",
        "apprenant__email",
        "apprenant__first_name",
        "apprenant__last_name",
        "cours__titre",
    )
    list_select_related = ("apprenant", "cours")
    date_hierarchy = "date_inscription"


@admin.register(ProgressionModule)
class ProgressionModuleAdmin(admin.ModelAdmin):
    list_display = ("module", "inscription", "date_terminaison")
    list_filter = ("module__cours", "date_terminaison")
    search_fields = (
        "module__titre",
        "module__cours__titre",
        "inscription__apprenant__username",
        "inscription__apprenant__email",
    )
    list_select_related = ("module", "module__cours", "inscription", "inscription__apprenant")
    readonly_fields = ("inscription", "module", "date_terminaison")
    date_hierarchy = "date_terminaison"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


class LessonContentInlineForm(forms.ModelForm):
    class Meta:
        model = LessonContent
        fields = "__all__"
        widgets = {"fichier": forms.FileInput}


class LessonContentInline(admin.StackedInline):
    model = LessonContent
    form = LessonContentInlineForm
    extra = 0


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("titre", "module", "ordre", "est_publiee")
    list_filter = ("est_publiee", "module__cours")
    search_fields = ("titre", "description", "module__titre", "module__cours__titre")
    inlines = [LessonContentInline]


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("lesson", "inscription", "date_terminaison")
    list_select_related = ("lesson", "inscription", "inscription__apprenant")
    readonly_fields = ("lesson", "inscription", "date_terminaison")
