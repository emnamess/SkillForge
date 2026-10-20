from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import ConnexionForm

app_name = "accounts"

urlpatterns = [
    # Authentification
    path("inscription/", views.inscription, name="inscription"),
    path("connexion/", auth_views.LoginView.as_view(
        template_name="accounts/login.html",
        authentication_form=ConnexionForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),

    # Mot de passe
    path("mot-de-passe/modifier/", auth_views.PasswordChangeView.as_view(
        template_name="accounts/password_change.html",
        success_url=reverse_lazy("accounts:password_change_done"),
    ), name="password_change"),
    path("mot-de-passe/modifie/", auth_views.PasswordChangeDoneView.as_view(
        template_name="accounts/password_change_done.html",
    ), name="password_change_done"),
    path("mot-de-passe/oublie/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset.html",
        email_template_name="accounts/emails/password_reset_email.txt",
        subject_template_name="accounts/emails/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
    ), name="password_reset"),
    path("mot-de-passe/envoye/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html",
    ), name="password_reset_done"),
    path("mot-de-passe/reinitialiser/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/password_reset_confirm.html",
        success_url=reverse_lazy("accounts:password_reset_complete"),
    ), name="password_reset_confirm"),
    path("mot-de-passe/reinitialise/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html",
    ), name="password_reset_complete"),

    # Espace personnel
    path("tableau-de-bord/", views.dashboard, name="dashboard"),
    path("profil/", views.profil, name="profil"),

    # Gestion des utilisateurs (administrateur)
    path("utilisateurs/", views.utilisateurs, name="utilisateurs"),
    path("utilisateurs/<int:pk>/", views.utilisateur_detail, name="utilisateur_detail"),
    path("utilisateurs/<int:pk>/valider/", views.valider_formateur, name="valider_formateur"),
    path("utilisateurs/<int:pk>/activer/", views.basculer_actif, name="basculer_actif"),
]
