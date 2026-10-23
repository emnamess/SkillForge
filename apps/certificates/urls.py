from django.urls import path

from . import views

app_name = "certificates"

urlpatterns = [
    path("", views.index, name="index"),
    path("delivrer/", views.delivrer, name="delivrer"),
    path("statistiques/", views.statistiques, name="statistiques"),
    path("export.csv", views.export_csv, name="export_csv"),
    path("verifier/", views.verifier, name="verifier"),
    path("verifier/<str:code>/", views.verifier_code, name="verifier_code"),
    path("<str:code>/", views.detail, name="detail"),
    path("<str:code>/modifier/", views.modifier, name="modifier"),
    path("<str:code>/supprimer/", views.supprimer, name="supprimer"),
    path("<str:code>/revoquer/", views.revoquer, name="revoquer"),
]
