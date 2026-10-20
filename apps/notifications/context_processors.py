from .services import messages_non_lus


def notifications(request):
    """Compteurs de la cloche et de la messagerie, disponibles dans tous les templates."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    contexte = {
        "nb_notifications_non_lues": user.notifications.filter(lue=False).count(),
        "dernieres_notifications": user.notifications.all()[:5],
        "nb_messages_non_lus": messages_non_lus(user),
    }
    if user.est_administrateur:
        from .models import Signalement

        contexte["nb_signalements_a_traiter"] = Signalement.objects.filter(traite=False).count()
    return contexte
