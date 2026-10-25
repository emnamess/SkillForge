from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import inlineformset_factory
from django.utils import timezone

from apps.accounts.models import User

from . import services
from .models import (Candidature, Competence, CompetenceApprenant, CompetenceRequise, Offre, ProfilCarriere,
                     ProfilEntreprise, SignalementOffre, TypeContrat)


# ---------- Recruteurs ----------

class InscriptionRecruteurForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Prénom", "last_name": "Nom", "email": "E-mail professionnel"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cette adresse e-mail.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = User.generer_username(user.email)
        user.role = User.Role.RECRUTEUR
        if commit:
            user.save()
        return user


class ProfilEntrepriseForm(forms.ModelForm):
    class Meta:
        model = ProfilEntreprise
        fields = ("nom", "secteur", "ville", "site_web", "matricule_fiscal", "description", "logo")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        help_texts = {"logo": "PNG, JPG ou WebP, 2 Mo maximum.",
                      "matricule_fiscal": "Facultatif : il accélère la validation."}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "size") and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Le logo dépasse 2 Mo.")
        return logo


class RefusEntrepriseForm(forms.Form):
    motif = forms.CharField(label="Motif du refus", widget=forms.Textarea(attrs={"rows": 2}))


# ---------- Offres ----------

class OffreForm(forms.ModelForm):
    class Meta:
        model = Offre
        fields = ("titre", "type_contrat", "mode_travail", "ville", "remuneration", "date_limite", "description")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 8}),
            "date_limite": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {"remuneration": "Facultatif. Ex. : 800 DT / mois", "date_limite": "Facultative."}

    def clean_date_limite(self):
        date = self.cleaned_data.get("date_limite")
        if date and date < timezone.localdate() and "date_limite" in self.changed_data:
            raise forms.ValidationError("La date limite ne peut pas être dans le passé.")
        return date


CompetenceRequiseFormSet = inlineformset_factory(
    Offre, CompetenceRequise, fields=("competence", "niveau_requis", "obligatoire"),
    extra=3, can_delete=True,
)


class FiltreOffresForm(forms.Form):
    TRIS = [("compatibilite", "Meilleure compatibilité"), ("date", "Plus récentes")]

    q = forms.CharField(required=False, label="Recherche",
                        widget=forms.TextInput(attrs={"placeholder": "Poste, entreprise..."}))
    type_contrat = forms.ChoiceField(required=False, label="Contrat",
                                     choices=[("", "Tous les contrats")] + TypeContrat.choices)
    mode_travail = forms.ChoiceField(required=False, label="Mode",
                                     choices=[("", "Tous les modes")] + Offre.ModeTravail.choices)
    ville = forms.CharField(required=False, label="Ville", widget=forms.TextInput(attrs={"placeholder": "Ville"}))
    competence = forms.ModelChoiceField(required=False, label="Compétence", queryset=Competence.objects.all(),
                                        empty_label="Toutes les compétences")
    tri = forms.ChoiceField(required=False, label="Tri", choices=TRIS)

    def filtrer(self, qs):
        if not self.is_valid():
            return qs
        d = self.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(titre__icontains=d["q"]) | Q(entreprise__nom__icontains=d["q"]))
        if d["type_contrat"]:
            qs = qs.filter(type_contrat=d["type_contrat"])
        if d["mode_travail"]:
            qs = qs.filter(mode_travail=d["mode_travail"])
        if d["ville"]:
            qs = qs.filter(ville__icontains=d["ville"])
        if d["competence"]:
            qs = qs.filter(competences_requises__competence=d["competence"])
        return qs.distinct()


# ---------- Profil carrière ----------

class ProfilCarriereForm(forms.ModelForm):
    types_contrat_recherches = forms.MultipleChoiceField(
        label="Types de contrat recherchés", required=False, choices=TypeContrat.choices,
        widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = ProfilCarriere
        fields = ("titre", "ville", "disponibilite", "types_contrat_recherches", "presentation",
                  "lien_github", "lien_linkedin", "lien_portfolio")
        labels = {"titre": "Titre du profil"}
        widgets = {"presentation": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["types_contrat_recherches"] = self.instance.liste_types_contrat()

    def clean_types_contrat_recherches(self):
        return ",".join(self.cleaned_data["types_contrat_recherches"])


CompetenceApprenantFormSet = inlineformset_factory(
    ProfilCarriere, CompetenceApprenant, fields=("competence", "niveau"), extra=3, can_delete=True,
)


class CVForm(forms.Form):
    cv = forms.FileField(label="CV (PDF, 5 Mo maximum)",
                         widget=forms.ClearableFileInput(attrs={"accept": ".pdf,application/pdf"}))

    def clean_cv(self):
        fichier = self.cleaned_data["cv"]
        services.valider_cv(fichier)
        return fichier


class SuggestionsForm(forms.Form):
    competences = forms.ModelMultipleChoiceField(queryset=Competence.objects.all(), required=False,
                                                 widget=forms.CheckboxSelectMultiple)


# ---------- Candidatures ----------

class CandidatureForm(forms.ModelForm):
    class Meta:
        model = Candidature
        fields = ("lettre_motivation",)
        widgets = {"lettre_motivation": forms.Textarea(
            attrs={"rows": 5, "placeholder": "Facultatif : pourquoi cette offre vous intéresse..."})}


class ChangerStatutForm(forms.Form):
    statut = forms.ChoiceField(label="Changer le statut", choices=Candidature.Statut.choices)
    commentaire = forms.CharField(label="Message au candidat", required=False,
                                  widget=forms.Textarea(attrs={"rows": 2}))


class EntretienForm(forms.Form):
    date_entretien = forms.DateTimeField(
        label="Date et heure", input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    lieu_ou_lien_entretien = forms.CharField(label="Lieu ou lien de visioconférence", max_length=255)
    commentaire = forms.CharField(label="Message au candidat", required=False,
                                  widget=forms.Textarea(attrs={"rows": 2}))

    def clean_date_entretien(self):
        date = self.cleaned_data["date_entretien"]
        if date <= timezone.now():
            raise ValidationError("La date de l'entretien doit être dans le futur.")
        return date


class SignalementOffreForm(forms.ModelForm):
    class Meta:
        model = SignalementOffre
        fields = ("motif", "details")
        widgets = {"details": forms.Textarea(attrs={"rows": 3, "placeholder": "Ce qui vous semble suspect..."})}


# ---------- Référentiel (administrateur) ----------

class CompetenceForm(forms.ModelForm):
    class Meta:
        model = Competence
        fields = ("nom", "categorie", "alias")
        widgets = {"alias": forms.Textarea(attrs={"rows": 2})}
