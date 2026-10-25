from django.urls import path

from . import views

app_name = "careers"

urlpatterns = [
    path("", views.index, name="index"),

    # Offres (pages publiques)
    path("offres/", views.offres, name="offres"),
    path("offres/<int:pk>/", views.offre_detail, name="offre_detail"),
    path("offres/<int:pk>/postuler/", views.postuler, name="postuler"),
    path("offres/<int:pk>/signaler/", views.signaler_offre, name="signaler_offre"),
    path("entreprises/inscription/", views.inscription_recruteur, name="inscription_recruteur"),

    # Espace apprenant
    path("tableau-de-bord/", views.tableau_apprenant, name="tableau_apprenant"),
    path("profil/", views.profil_carriere, name="profil"),
    path("profil/cv/", views.deposer_cv, name="deposer_cv"),
    path("profil/suggestions/", views.ajouter_suggestions, name="ajouter_suggestions"),
    path("candidatures/", views.mes_candidatures, name="mes_candidatures"),
    path("candidatures/<int:pk>/", views.candidature_detail, name="candidature_detail"),
    path("candidatures/<int:pk>/retirer/", views.retirer_candidature, name="retirer_candidature"),

    # CV (téléchargement protégé)
    path("cv/profil/<int:pk>/", views.cv_profil, name="cv_profil"),
    path("cv/candidature/<int:pk>/", views.cv_candidature, name="cv_candidature"),

    # Espace recruteur
    path("recruteur/", views.tableau_recruteur, name="tableau_recruteur"),
    path("recruteur/offres/", views.mes_offres, name="mes_offres"),
    path("recruteur/offres/nouvelle/", views.offre_creer, name="offre_creer"),
    path("recruteur/offres/<int:pk>/modifier/", views.offre_modifier, name="offre_modifier"),
    path("recruteur/offres/<int:pk>/dupliquer/", views.offre_dupliquer, name="offre_dupliquer"),
    path("recruteur/offres/<int:pk>/publier/", views.offre_publier, name="offre_publier"),
    path("recruteur/offres/<int:pk>/fermer/", views.offre_fermer, name="offre_fermer"),
    path("recruteur/offres/<int:pk>/candidats/", views.kanban, name="kanban"),
    path("recruteur/candidatures/<int:pk>/", views.fiche_candidat, name="fiche_candidat"),
    path("recruteur/candidatures/<int:pk>/statut/", views.changer_statut, name="changer_statut"),
    path("recruteur/candidatures/<int:pk>/entretien/", views.planifier_entretien, name="planifier_entretien"),

    # Administration
    path("administration/entreprises/", views.admin_entreprises, name="admin_entreprises"),
    path("administration/entreprises/<int:pk>/valider/", views.admin_valider_entreprise,
         name="admin_valider_entreprise"),
    path("administration/entreprises/<int:pk>/refuser/", views.admin_refuser_entreprise,
         name="admin_refuser_entreprise"),
    path("administration/signalements/", views.admin_signalements, name="admin_signalements"),
    path("administration/signalements/<int:pk>/traiter/", views.admin_traiter_signalement,
         name="admin_traiter_signalement"),
    path("administration/offres/<int:pk>/suspendre/", views.admin_suspendre_offre, name="admin_suspendre_offre"),
    path("administration/competences/", views.admin_competences, name="admin_competences"),
    path("administration/competences/<int:pk>/", views.admin_competence_modifier, name="admin_competence_modifier"),
    path("administration/statistiques/", views.admin_statistiques, name="admin_statistiques"),
]
