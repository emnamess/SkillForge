from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.index, name="index"),
    path("mes-cours/", views.mes_cours, name="mes_cours"),
    path("creer/", views.cours_creer, name="cours_creer"),
    path("<int:pk>/modifier/", views.cours_modifier, name="cours_modifier"),
    path("<int:pk>/publication/", views.cours_publication, name="cours_publication"),
    path("<int:pk>/supprimer/", views.cours_supprimer, name="cours_supprimer"),
    path("<int:cours_pk>/modules/ajouter/", views.module_creer, name="module_creer"),
    path("modules/<int:pk>/modifier/", views.module_modifier, name="module_modifier"),
    path("modules/<int:pk>/supprimer/", views.module_supprimer, name="module_supprimer"),
    path("modules/<int:pk>/terminer/", views.module_terminer, name="module_terminer"),
    path("<int:pk>/inscription/", views.inscrire, name="inscrire"),
    path("<int:pk>/", views.detail, name="detail"),
]
