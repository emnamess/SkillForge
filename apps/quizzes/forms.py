"""Formulaires du module Quiz."""

from django import forms
from django.forms import inlineformset_factory

from .models import Choix, Question, Quiz


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ["titre", "description", "seuil_reussite", "duree_minutes", "est_publie"]
        widgets = {
            "titre": forms.TextInput(attrs={"placeholder": "Ex : Les bases de SQL"}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "Description du quiz…"}),
            "seuil_reussite": forms.NumberInput(attrs={"min": 0, "max": 100, "step": 5}),
            "duree_minutes": forms.NumberInput(attrs={"min": 1, "placeholder": "Optionnel"}),
        }


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ["type", "enonce", "points", "ordre", "explication", "consigne_ia"]
        widgets = {
            "enonce": forms.Textarea(attrs={"rows": 3, "placeholder": "Écrivez votre question…"}),
            "explication": forms.Textarea(attrs={"rows": 2, "placeholder": "Explication affichée après correction (optionnel)"}),
            "consigne_ia": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "Réponse attendue ou critères de correction pour l'IA (uniquement pour texte libre)",
            }),
            "points": forms.NumberInput(attrs={"min": 1, "max": 100}),
            "ordre": forms.NumberInput(attrs={"min": 0}),
        }


class ChoixForm(forms.ModelForm):
    class Meta:
        model = Choix
        fields = ["texte", "est_correct", "ordre"]
        widgets = {
            "texte": forms.TextInput(attrs={"placeholder": "Texte du choix"}),
            "ordre": forms.NumberInput(attrs={"min": 0}),
        }


# Formset pour gérer les choix d'une question en inline
ChoixFormSet = inlineformset_factory(
    Question,
    Choix,
    form=ChoixForm,
    extra=4,
    can_delete=True,
    min_num=2,
    validate_min=True,
)


class ReponseTexteForm(forms.Form):
    """Formulaire pour une réponse texte libre."""
    texte = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Votre réponse…"}),
        required=False,
    )
