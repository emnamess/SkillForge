from django import forms

from .services import destinataires_possibles


class MessageForm(forms.Form):
    contenu = forms.CharField(
        label="Message",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 1, "placeholder": "Écrire un message..."}),
    )

    def clean_contenu(self):
        contenu = self.cleaned_data["contenu"].strip()
        if not contenu:
            raise forms.ValidationError("Le message est vide.")
        return contenu


class NouvelleConversationForm(MessageForm):
    destinataire = forms.ModelChoiceField(label="Destinataire", queryset=None,
                                          empty_label="Choisir un destinataire")

    field_order = ["destinataire", "contenu"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destinataire"].queryset = destinataires_possibles(user)
        self.fields["destinataire"].label_from_instance = (
            lambda u: f"{u} · {u.get_role_display()}" + (f" ({u.specialite})" if u.specialite else "")
        )
        self.fields["contenu"].widget.attrs["rows"] = 4
