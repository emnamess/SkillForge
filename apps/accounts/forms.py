from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class InscriptionForm(UserCreationForm):
    ROLES_INSCRIPTION = [
        (User.Role.APPRENANT, "Apprenant — je veux suivre des cours"),
        (User.Role.FORMATEUR, "Formateur — je veux créer des cours"),
    ]

    role = forms.ChoiceField(label="Je m'inscris en tant que", choices=ROLES_INSCRIPTION,
                             widget=forms.RadioSelect, initial=User.Role.APPRENANT)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role", "specialite")
        labels = {"first_name": "Prénom", "last_name": "Nom"}
        help_texts = {"specialite": "Pour les formateurs : votre domaine d'expertise."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cette adresse e-mail.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") == User.Role.FORMATEUR and not cleaned.get("specialite"):
            self.add_error("specialite", "Indiquez votre spécialité pour devenir formateur.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = User.generer_username(user.email)
        user.est_valide = user.role != User.Role.FORMATEUR
        if commit:
            user.save()
        return user


class ConnexionForm(AuthenticationForm):
    username = forms.CharField(label="E-mail ou nom d'utilisateur",
                               widget=forms.TextInput(attrs={"autofocus": True}))

    error_messages = {
        "invalid_login": "Identifiants incorrects. Vérifiez votre e-mail et votre mot de passe.",
        "inactive": "Ce compte a été désactivé. Contactez un administrateur.",
    }


class ProfilForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "bio", "specialite")
        labels = {"first_name": "Prénom", "last_name": "Nom"}
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.est_formateur:
            del self.fields["specialite"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email


class GestionUtilisateurForm(forms.ModelForm):
    """Formulaire de l'administrateur pour modifier le rôle et le statut d'un compte."""

    class Meta:
        model = User
        fields = ("role", "est_valide", "is_active")
        labels = {"is_active": "Compte actif"}


class FiltreUtilisateursForm(forms.Form):
    STATUTS = [
        ("", "Tous les statuts"),
        ("actif", "Actifs"),
        ("inactif", "Désactivés"),
        ("attente", "Formateurs en attente"),
    ]

    q = forms.CharField(required=False, label="Recherche",
                        widget=forms.TextInput(attrs={"placeholder": "Nom, e-mail..."}))
    role = forms.ChoiceField(required=False, label="Rôle",
                             choices=[("", "Tous les rôles")] + User.Role.choices)
    statut = forms.ChoiceField(required=False, label="Statut", choices=STATUTS)
