from django.urls import path

from . import views

app_name = "mentoring"

urlpatterns = [
    path("", views.index, name="index"),
    path("calendrier/evenements/", views.calendrier_evenements, name="calendrier_evenements"),
    path("disponibilites/creer/", views.disponibilite_creer, name="disponibilite_creer"),
    path("disponibilites/<int:pk>/modifier/", views.disponibilite_modifier, name="disponibilite_modifier"),
    path("disponibilites/<int:pk>/supprimer/", views.disponibilite_supprimer, name="disponibilite_supprimer"),
    path("disponibilites/<int:pk>/fermer/", views.disponibilite_desactiver, name="disponibilite_desactiver"),
    path("disponibilites/<int:pk>/reserver/", views.reserver, name="reserver"),
    path("disponibilites/<int:pk>/planifier/", views.planifier, name="planifier"),
    path("seances/<int:pk>/", views.seance_detail, name="seance_detail"),
    path("seances/<int:pk>/<str:action>/", views.seance_action, name="seance_action"),
]
