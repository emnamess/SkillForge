from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Disponibilite, SeanceMentorat
from .services import creneaux_disponibles

User = get_user_model()


class DisponibiliteForm(forms.ModelForm):
    class Meta:
        model = Disponibilite
        fields = ("debut", "fin", "duree_seance")
        widgets = {
            "debut": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "fin": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("debut", "fin"):
            self.fields[field].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean(self):
        cleaned = super().clean()
        debut, fin = cleaned.get("debut"), cleaned.get("fin")
        duree = cleaned.get("duree_seance")
        if debut and debut <= timezone.now():
            self.add_error("debut", "Choisissez une date future.")
        if debut and fin and fin <= debut:
            self.add_error("fin", "La fin doit être après le début.")
        if debut and fin and duree and fin - debut < timedelta(minutes=duree):
            self.add_error("fin", "La plage doit durer au moins une séance.")
        return cleaned


class DemandeSeanceForm(forms.Form):
    sujet = forms.CharField(label="Sujet", max_length=160)
    description = forms.CharField(label="Précisions", required=False, widget=forms.Textarea(attrs={"rows": 4}))


class LienVisioForm(forms.ModelForm):
    class Meta:
        model = SeanceMentorat
        fields = ("lien_visio",)


class PlanifierSeanceForm(forms.Form):
    apprenant = forms.ModelChoiceField(
        label="Apprenant",
        queryset=User.objects.none(),
        empty_label="Choisir un apprenant",
    )
    debut = forms.ChoiceField(label="Heure de début")
    sujet = forms.CharField(label="Sujet", max_length=160)
    description = forms.CharField(label="Précisions", required=False, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, disponibilite, **kwargs):
        super().__init__(*args, **kwargs)
        self.disponibilite = disponibilite
        self.fields["apprenant"].queryset = User.objects.filter(
            role=User.Role.APPRENANT, is_active=True,
        ).order_by("first_name", "last_name", "username")
        self.creneaux = creneaux_disponibles(disponibilite)
        self.fields["debut"].choices = [
            (creneau.isoformat(), timezone.localtime(creneau).strftime("%A %d/%m à %H:%M"))
            for creneau in self.creneaux
        ]

    def clean_debut(self):
        valeur = self.cleaned_data["debut"]
        for creneau in self.creneaux:
            if valeur == creneau.isoformat():
                return creneau
        raise forms.ValidationError("Ce créneau n’est plus disponible.")

