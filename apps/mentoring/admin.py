from django.contrib import admin

from .models import Disponibilite, SeanceMentorat


@admin.register(Disponibilite)
class DisponibiliteAdmin(admin.ModelAdmin):
    list_display = ("formateur", "debut", "fin", "duree_seance", "active")
    list_filter = ("active", "duree_seance")
    search_fields = ("formateur__username", "formateur__email")


@admin.register(SeanceMentorat)
class SeanceMentoratAdmin(admin.ModelAdmin):
    list_display = ("sujet", "formateur", "apprenant", "debut", "statut")
    list_filter = ("statut",)
    search_fields = ("sujet", "formateur__username", "apprenant__username")
    readonly_fields = ("date_creation", "date_modification")
