from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import localtime
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User

from .forms import MessageForm, NouvelleConversationForm
from .models import Conversation, Message
from .services import (envoyer_message, marquer_toutes_lues, messages_non_lus, obtenir_conversation,
                       peut_ecrire_a)


def rediriger_vers_suivant(request, defaut):
    """Redirige vers ?next s'il pointe vers SkillForge, sinon vers la page par défaut."""
    suivant = request.POST.get("next")
    if suivant and url_has_allowed_host_and_scheme(suivant, {request.get_host()}):
        return redirect(suivant)
    return redirect(defaut)


# ---------- Notifications ----------

@login_required
def index(request):
    filtre = request.GET.get("filtre", "toutes")
    qs = request.user.notifications.all()
    if filtre == "non-lues":
        qs = qs.filter(lue=False)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "notifications/index.html", {"page": page, "filtre": filtre})


@login_required
def ouvrir(request, pk):
    """Marque la notification comme lue puis redirige vers son lien."""
    notification = get_object_or_404(request.user.notifications, pk=pk)
    if not notification.lue:
        notification.lue = True
        notification.save(update_fields=["lue"])
    if notification.lien and url_has_allowed_host_and_scheme(notification.lien, {request.get_host()}):
        return redirect(notification.lien)
    return redirect("notifications:index")


@require_POST
@login_required
def tout_marquer_lu(request):
    n = marquer_toutes_lues(request.user)
    if n:
        messages.success(request, f"{n} notification(s) marquée(s) comme lue(s).")
    return rediriger_vers_suivant(request, "notifications:index")


@require_POST
@login_required
def supprimer(request, pk):
    get_object_or_404(request.user.notifications, pk=pk).delete()
    return rediriger_vers_suivant(request, "notifications:index")


@require_GET
@login_required
def api_compteurs(request):
    return JsonResponse({
        "notifications": request.user.notifications.filter(lue=False).count(),
        "messages": messages_non_lus(request.user),
    })


# ---------- Messagerie ----------

def conversations_de(user):
    dernier = Message.objects.filter(conversation=OuterRef("pk")).order_by("-date_envoi")
    return (
        Conversation.objects.pour(user)
        .annotate(
            dernier_message=Subquery(dernier.values("contenu")[:1]),
            dernier_expediteur=Subquery(dernier.values("expediteur")[:1]),
            nb_non_lus=Count("messages", filter=Q(messages__lu=False) & ~Q(messages__expediteur=user),
                             distinct=True),
        )
        .filter(dernier_message__isnull=False)
        .prefetch_related(Prefetch("participants", queryset=User.objects.exclude(pk=user.pk),
                                   to_attr="autres"))
    )


@login_required
def messagerie(request, pk=None):
    conversations = conversations_de(request.user)
    conversation = None
    form = MessageForm()

    if pk is not None:
        conversation = get_object_or_404(Conversation.objects.pour(request.user), pk=pk)
        interlocuteur = conversation.interlocuteur(request.user)

        if request.method == "POST":
            form = MessageForm(request.POST)
            if form.is_valid():
                envoyer_message(conversation, request.user, form.cleaned_data["contenu"])
                return redirect(conversation)

        conversation.marquer_lue(request.user)
        conversation.interlocuteur_courant = interlocuteur

    return render(request, "notifications/messagerie.html", {
        "conversations": conversations,
        "conversation": conversation,
        "messages_conversation": conversation.messages.select_related("expediteur") if conversation else [],
        "form": form,
    })


@login_required
def nouvelle_conversation(request):
    """Démarre une conversation. Accepte ?a=<id utilisateur> pour présélectionner le destinataire."""
    initial = {}
    if request.GET.get("a", "").isdigit():
        initial["destinataire"] = request.GET["a"]

    form = NouvelleConversationForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        destinataire = form.cleaned_data["destinataire"]
        if not peut_ecrire_a(request.user, destinataire):
            messages.error(request, "Vous ne pouvez pas écrire à cet utilisateur.")
        else:
            conversation = obtenir_conversation(request.user, destinataire)
            envoyer_message(conversation, request.user, form.cleaned_data["contenu"])
            return redirect(conversation)

    return render(request, "notifications/nouvelle_conversation.html", {
        "form": form,
        "conversations": conversations_de(request.user),
    })


@require_GET
@login_required
def api_messages(request, pk):
    """Messages postérieurs à ?apres=<id>, pour actualiser la conversation sans recharger."""
    conversation = get_object_or_404(Conversation.objects.pour(request.user), pk=pk)
    apres = request.GET.get("apres", "0")
    nouveaux = conversation.messages.filter(pk__gt=int(apres) if apres.isdigit() else 0).select_related(
        "expediteur")
    conversation.marquer_lue(request.user)
    return JsonResponse({"messages": [{
        "id": m.pk,
        "contenu": m.contenu,
        "auteur": "Vous" if m.expediteur_id == request.user.pk else str(m.expediteur),
        "initiales": m.expediteur.initiales,
        "moi": m.expediteur_id == request.user.pk,
        "heure": date_format(localtime(m.date_envoi), "H:i"),
    } for m in nouveaux]})
