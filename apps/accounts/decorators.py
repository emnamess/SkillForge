"""Contrôle d'accès par rôle, réutilisable par tous les modules.

Exemples :

    @role_required(User.Role.FORMATEUR)
    def creer_cours(request): ...

    class CreerQuizView(RoleRequiredMixin, CreateView):
        roles = [User.Role.FORMATEUR]
"""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def a_le_role(user, roles):
    """Vrai si l'utilisateur a l'un des rôles demandés (un formateur doit être validé)."""
    if not user.is_authenticated:
        return False
    if user.est_administrateur:
        return True
    if user.en_attente_validation:
        return False
    return user.role in roles


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not a_le_role(request.user, roles):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


admin_required = role_required()  # seuls les administrateurs passent


class RoleRequiredMixin(LoginRequiredMixin):
    roles = []

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not a_le_role(request.user, self.roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
