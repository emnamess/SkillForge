from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from . import services
from .models import (Candidature, Competence, CompetenceApprenant, CompetenceRequise, HistoriqueCandidature, Offre,
                     ProfilCarriere, ProfilEntreprise, SignalementOffre)


@admin.register(Competence)
class CompetenceAdmin(admin.ModelAdmin):
    list_display = ("nom", "categorie", "alias")
    list_filter = ("categorie",)
    search_fields = ("nom", "alias")
    prepopulated_fields = {"slug": ("nom",)}


@admin.register(ProfilEntreprise)
class ProfilEntrepriseAdmin(admin.ModelAdmin):
    list_display = ("nom", "utilisateur", "secteur", "ville", "statut", "date_creation")
    list_filter = ("statut", "secteur")
    search_fields = ("nom", "utilisateur__email", "matricule_fiscal")
    raw_id_fields = ("utilisateur",)
    readonly_fields = ("date_creation", "date_decision")
    actions = ("valider",)

    @admin.action(description="Valider les entreprises sélectionnées")
    def valider(self, request, queryset):
        # Objet par objet via le service (pas de update()) : les notifications partent
        n = 0
        for entreprise in queryset.exclude(statut=ProfilEntreprise.Statut.VALIDEE):
            services.valider_entreprise(entreprise)
            n += 1
        self.message_user(request, f"{n} entreprise(s) validée(s).", messages.SUCCESS)


class CompetenceRequiseInline(admin.TabularInline):
    model = CompetenceRequise
    extra = 0
    autocomplete_fields = ("competence",)


@admin.register(Offre)
class OffreAdmin(admin.ModelAdmin):
    list_display = ("titre", "entreprise", "type_contrat", "mode_travail", "ville", "statut", "date_limite",
                    "date_publication")
    list_filter = ("statut", "type_contrat", "mode_travail")
    search_fields = ("titre", "description", "entreprise__nom", "ville")
    list_select_related = ("entreprise",)
    inlines = [CompetenceRequiseInline]
    actions = ("suspendre",)

    @admin.action(description="Suspendre les offres sélectionnées")
    def suspendre(self, request, queryset):
        n = 0
        for offre in queryset.exclude(statut=Offre.Statut.SUSPENDUE):
            services.suspendre_offre(offre)
            n += 1
        self.message_user(request, f"{n} offre(s) suspendue(s).", messages.SUCCESS)


class CompetenceApprenantInline(admin.TabularInline):
    model = CompetenceApprenant
    extra = 0
    autocomplete_fields = ("competence",)


@admin.register(ProfilCarriere)
class ProfilCarriereAdmin(admin.ModelAdmin):
    list_display = ("apprenant", "titre", "ville", "date_maj")
    search_fields = ("apprenant__email", "apprenant__first_name", "apprenant__last_name", "titre")
    raw_id_fields = ("apprenant",)
    exclude = ("cv",)  # fichier privé : téléchargement via l'Espace Carrière uniquement
    inlines = [CompetenceApprenantInline]


class HistoriqueInline(admin.TabularInline):
    model = HistoriqueCandidature
    extra = 0
    readonly_fields = ("ancien_statut", "nouveau_statut", "auteur", "commentaire", "date")
    can_delete = False


@admin.register(Candidature)
class CandidatureAdmin(admin.ModelAdmin):
    list_display = ("apprenant", "offre", "statut", "score_au_depot", "date_creation", "date_entretien")
    list_filter = ("statut", "offre__type_contrat")
    search_fields = ("apprenant__email", "apprenant__last_name", "offre__titre", "offre__entreprise__nom")
    list_select_related = ("apprenant", "offre")
    raw_id_fields = ("apprenant", "offre")
    # Le statut ne change que via le service (transitions contrôlées et historisées)
    readonly_fields = ("statut", "score_au_depot", "date_creation", "date_maj", "date_premiere_reponse")
    exclude = ("cv_depose",)
    inlines = [HistoriqueInline]


@admin.register(HistoriqueCandidature)
class HistoriqueCandidatureAdmin(admin.ModelAdmin):
    list_display = ("candidature", "ancien_statut", "nouveau_statut", "auteur", "date")
    list_filter = ("nouveau_statut",)
    search_fields = ("candidature__apprenant__email", "candidature__offre__titre")
    raw_id_fields = ("candidature", "auteur")


@admin.register(SignalementOffre)
class SignalementOffreAdmin(admin.ModelAdmin):
    list_display = ("offre", "auteur", "motif", "traite", "decision", "date_creation")
    list_filter = ("motif", "traite", "decision")
    search_fields = ("offre__titre", "details", "auteur__email")
    raw_id_fields = ("offre", "auteur", "traite_par")
    readonly_fields = ("traite", "decision", "traite_par", "date_traitement")
    actions = ("suspendre_offres", "classer")

    def _traiter(self, request, queryset, decision):
        n = 0
        for signalement in queryset.filter(traite=False).select_related("offre"):
            try:
                services.traiter_signalement(signalement, request.user, decision)
                n += 1
            except ValidationError:
                pass
        self.message_user(request, f"{n} signalement(s) traité(s).", messages.SUCCESS)

    @admin.action(description="Suspendre les offres signalées")
    def suspendre_offres(self, request, queryset):
        self._traiter(request, queryset, SignalementOffre.Decision.SUSPENDUE)

    @admin.action(description="Classer sans suite")
    def classer(self, request, queryset):
        self._traiter(request, queryset, SignalementOffre.Decision.CLASSEE)
