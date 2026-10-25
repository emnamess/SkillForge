from django import forms
from django.contrib.auth import get_user_model

from .models import Cours, Module

User = get_user_model()


class CoursForm(forms.ModelForm):
    formateur = forms.ModelChoiceField(
        label="Formateur responsable",
        queryset=User.objects.none(),
        empty_label="Choisir un formateur",
    )

    class Meta:
        model = Cours
        fields = ("titre", "description", "est_publie", "formateur")
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
