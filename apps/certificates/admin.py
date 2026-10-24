from django.contrib import admin

from .models import Certificat


@admin.register(Certificat)
class CertificatAdmin(admin.ModelAdmin):
    list_display = ("code_verification", "apprenant", "titre_cours", "nom_formateur", "score",
                    "date_delivrance", "statut")
    list_filter = ("statut", "date_delivrance")
    search_fields = ("code_verification", "titre_cours", "apprenant__email", "apprenant__first_name",
                     "apprenant__last_name", "nom_formateur")
    readonly_fields = ("code_verification", "date_revocation", "revoque_par")
    autocomplete_fields = ("apprenant", "formateur", "delivre_par")
    date_hierarchy = "date_delivrance"
    fieldsets = (
        (None, {"fields": ("code_verification", "apprenant", "titre_cours", "formateur", "nom_formateur")}),
        ("Résultats", {"fields": ("score", "duree_heures", "competences")}),
        ("Délivrance", {"fields": ("date_delivrance", "delivre_par", "statut", "motif_revocation",
                                   "date_revocation", "revoque_par")}),
    )
