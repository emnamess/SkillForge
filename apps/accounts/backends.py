from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Permet de se connecter avec l'adresse e-mail ou le nom d'utilisateur."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        champ = "email__iexact" if "@" in username else "username__iexact"
        try:
            user = User.objects.get(**{champ: username})
        except User.DoesNotExist:
            # Exécute le hachage pour ne pas révéler l'existence du compte par le temps de réponse
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
