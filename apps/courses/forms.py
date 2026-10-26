from django import forms
from django.contrib.auth import get_user_model

from .models import Cours, Lesson, LessonContent, Module

User = get_user_model()


class CoursForm(forms.ModelForm):
    formateur = forms.ModelChoiceField(
        label="Formateur responsable",
        queryset=User.objects.none(),
        empty_label="Choisir un formateur",
    )

    class Meta:
        model = Cours
        fields = ("titre", "description", "objectifs", "categorie", "niveau", "duree_estimee", "image_couverture", "ordre", "est_publie", "formateur")
        widgets = {
            "titre": forms.TextInput(attrs={"placeholder": "Ex. Introduction à Python"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, administrateur=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["formateur"].queryset = User.objects.filter(
            role=User.Role.FORMATEUR,
            est_valide=True,
            is_active=True,
        ).order_by("first_name", "last_name", "username")
        if not administrateur or self.instance.pk:
            self.fields.pop("formateur")


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ("titre", "description", "contenu", "ordre")
        widgets = {
            "titre": forms.TextInput(attrs={"placeholder": "Ex. Variables et types"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "contenu": forms.Textarea(attrs={"rows": 12}),
            "ordre": forms.NumberInput(attrs={"min": 0}),
        }

    def __init__(self, *args, cours=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cours = cours or getattr(self.instance, "cours", None)

    def clean_ordre(self):
        ordre = self.cleaned_data["ordre"]
        if self.cours and Module.objects.filter(cours=self.cours, ordre=ordre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce numéro d'ordre est déjà utilisé dans ce cours.")
        return ordre


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ("titre", "description", "contenu", "ordre", "duree_estimee", "est_publiee")
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "contenu": forms.Textarea(attrs={"rows": 10})}

    def clean_ordre(self):
        ordre = self.cleaned_data["ordre"]
        if self.instance.module_id and Lesson.objects.filter(module=self.instance.module, ordre=ordre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce numéro d'ordre est déjà utilisé dans ce chapitre.")
        return ordre


class LessonContentForm(forms.ModelForm):
    fichier = forms.FileField(label="Fichier pédagogique", required=False, widget=forms.FileInput)

    class Meta:
        model = LessonContent
        fields = ("type", "titre", "texte", "url", "fichier", "texte_alternatif", "legende", "ordre")
        widgets = {"texte": forms.Textarea(attrs={"rows": 8})}

    def clean_ordre(self):
        ordre = self.cleaned_data["ordre"]
        if self.instance.lesson_id and LessonContent.objects.filter(lesson=self.instance.lesson, ordre=ordre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ce numéro d'ordre est déjà utilisé dans cette leçon.")
        return ordre
