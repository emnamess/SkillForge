"""Contrôle d'accès de l'Espace Carrière, construit sur role_required (apps.accounts)."""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .services import entreprise_de

apprenant_required = role_required(User.Role.APPRENANT)


def recruteur_required(view_func):
    """Recruteur dont l'entreprise est validée ; sinon page « Compte en attente de validation ».

    L'entreprise est disponible dans `request.entreprise`.
    """
    @role_required(User.Role.RECRUTEUR)
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        entreprise = entreprise_de(request.user)
        if entreprise is None:
            if not request.user.est_administrateur:
                raise PermissionDenied
            # Un administrateur passe role_required mais n'a pas d'entreprise
            messages.info(request, "L'espace recruteur est réservé aux comptes entreprise.")
            return redirect("careers:admin_entreprises")
        if not entreprise.est_validee:
            return render(request, "careers/recruteur/attente.html", {"entreprise": entreprise},
                          status=200 if request.method == "GET" else 403)
        request.entreprise = entreprise
        return view_func(request, *args, **kwargs)
    return wrapper
