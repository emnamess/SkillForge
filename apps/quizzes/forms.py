"""Formulaires du module Quiz."""

from django import forms
from django.forms import inlineformset_factory

from apps.courses.models import Cours

from .models import Choix, Question, Quiz


class QuizForm(forms.ModelForm):
    def __init__(self, *args, formateur=None, **kwargs):
        super().__init__(*args, **kwargs)
        if formateur is None:
            self.fields["cours"].queryset = Cours.objects.none()
        elif formateur.est_administrateur:
            self.fields["cours"].queryset = Cours.objects.all().order_by("titre")
        else:
            cours_autorises = Cours.objects.filter(formateur=formateur)
            if self.instance.pk and self.instance.cours_id:
                cours_autorises = cours_autorises | Cours.objects.filter(pk=self.instance.cours_id)
            self.fields["cours"].queryset = cours_autorises.order_by("titre")

    class Meta:
        model = Quiz
        fields = ["titre", "description", "cours", "seuil_reussite", "duree_minutes", "est_publie", "melanger_questions"]
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
