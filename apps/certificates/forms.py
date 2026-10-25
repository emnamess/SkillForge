from django import forms
from django.contrib.auth import get_user_model

from .models import Certificat

User = get_user_model()


class DelivrerCertificatForm(forms.Form):
    apprenant = forms.ModelChoiceField(
        label="Apprenant", empty_label="Choisir un apprenant",
        queryset=User.objects.filter(role=User.Role.APPRENANT, is_active=True).order_by("first_name", "last_name"),
    )
    titre_cours = forms.CharField(label="Cours", max_length=200,
                                  widget=forms.TextInput(attrs={"placeholder": "Ex. Modélisation UML"}))
    formateur = forms.ModelChoiceField(
        label="Formateur du cours", required=False, empty_label="Aucun",
        queryset=User.objects.filter(role=User.Role.FORMATEUR, est_valide=True, is_active=True)
        .order_by("first_name", "last_name"),
    )
    score = forms.IntegerField(label="Score final (%)", required=False, min_value=0, max_value=100,
                               help_text="Moyenne des quiz du cours, sur 100.")
    duree_heures = forms.IntegerField(label="Durée (heures)", required=False, min_value=1, max_value=1000)
    competences = forms.CharField(
        label="Compétences validées", required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Diagramme de classes\nHéritage et polymorphisme"}),
        help_text="Une compétence par ligne.",
    )

    def __init__(self, *args, delivre_par=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.delivre_par = delivre_par
        # Un formateur délivre pour ses propres cours : le champ formateur n'a pas de sens pour lui
        if delivre_par is not None and not delivre_par.est_administrateur:
            del self.fields["formateur"]

    def clean_titre_cours(self):
        return " ".join(self.cleaned_data["titre_cours"].split())

    def clean(self):
        donnees = super().clean()
        apprenant, titre = donnees.get("apprenant"), donnees.get("titre_cours")
        if apprenant and titre and Certificat.doublon_valide(apprenant, titre):
            raise forms.ValidationError(f"{apprenant} possède déjà un certificat valide pour « {titre} ».")
        return donnees

    def formateur_choisi(self):
        if "formateur" in self.fields:
            return self.cleaned_data.get("formateur")
        return self.delivre_par


class ModifierCertificatForm(forms.ModelForm):
    """Correction d'un certificat valide (faute dans le titre, score mal saisi, compétences)."""

    class Meta:
        model = Certificat
        fields = ["titre_cours", "formateur", "score", "duree_heures", "competences"]
        widgets = {"competences": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, modifie_par=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["formateur"].queryset = User.objects.filter(role=User.Role.FORMATEUR, est_valide=True,
                                                                is_active=True).order_by("first_name")
        self.fields["formateur"].empty_label = "Aucun"
        self.fields["duree_heures"].widget.attrs.update(min=1, max=1000)
        # Seul l'administrateur peut réattribuer le certificat à un autre formateur
        if modifie_par is not None and not modifie_par.est_administrateur:
            del self.fields["formateur"]

    def clean_titre_cours(self):
        titre = " ".join(self.cleaned_data["titre_cours"].split())
        if Certificat.doublon_valide(self.instance.apprenant, titre, exclure=self.instance):
            raise forms.ValidationError("Cet apprenant possède déjà un autre certificat valide pour ce cours.")
        return titre

    def save(self, commit=True):
        certificat = super().save(commit=False)
        if "formateur" in self.changed_data:
            certificat.nom_formateur = str(certificat.formateur) if certificat.formateur else ""
        if commit:
            certificat.save()
        return certificat


class RevocationForm(forms.Form):
    motif = forms.CharField(label="Motif de la révocation", max_length=500,
                            widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Ex. fraude constatée au quiz final"}))


class VerificationForm(forms.Form):
    code = forms.CharField(label="Code de vérification", max_length=20,
                           widget=forms.TextInput(attrs={"placeholder": "SF-XXXX-XXXX", "autocomplete": "off"}))

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper().replace(" ", "")
        if not code.startswith("SF-") and len(code) == 8:
            code = f"SF-{code[:4]}-{code[4:]}"
        return code


class FiltreCertificatsForm(forms.Form):
    q = forms.CharField(required=False, label="Recherche",
                        widget=forms.TextInput(attrs={"placeholder": "Apprenant, cours, code..."}))
    statut = forms.ChoiceField(required=False, label="Statut",
                               choices=[("", "Tous les statuts")] + Certificat.Statut.choices)
