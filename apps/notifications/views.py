from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import admin_required
from apps.accounts.models import User

from . import services
from .forms import AnnonceForm, MessageForm, ModifierMessageForm, NouvelleConversationForm
from .models import Annonce, Conversation, Message, Signalement
from .moderation import ia_disponible
from .realtime import est_en_ligne, message_en_dict
from .services import (MessageBloque, envoyer_message, marquer_toutes_lues, messages_non_lus,
                       obtenir_conversation, peut_ecrire_a, rechercher_messages)
from .services import traiter_signalement as appliquer_decision_moderateur


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
            dernier_fichier=Subquery(dernier.values("nom_fichier")[:1]),
            nb_non_lus=Count("messages", filter=Q(messages__lu=False) & ~Q(messages__expediteur=user),
                             distinct=True),
        )
        .filter(dernier_message__isnull=False)
        .prefetch_related(Prefetch("participants", queryset=User.objects.exclude(pk=user.pk),
                                   to_attr="autres"))
    )


def est_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@login_required
def messagerie(request, pk=None):
    conversations = conversations_de(request.user)
    conversation = None
    form = MessageForm()

    if pk is not None:
        conversation = get_object_or_404(Conversation.objects.pour(request.user), pk=pk)
        interlocuteur = conversation.interlocuteur(request.user)

        if request.method == "POST":
            form = MessageForm(request.POST, request.FILES)
            erreur = None
            if form.is_valid():
                try:
                    message = envoyer_message(conversation, request.user, form.cleaned_data["contenu"],
                                              form.cleaned_data["fichier"])
                except MessageBloque as e:
                    erreur = (f"Message bloqué par la modération : {e.resultat.raison} "
                              f"(détecté par : {e.resultat.libelle_source})")
                except ValidationError as e:
                    erreur = e.messages[0]
                else:
                    if est_ajax(request):
                        return JsonResponse({"ok": True, "message": message_en_dict(message)})
                    return redirect(conversation)
            else:
                erreur = next(iter(form.errors.values()))[0]

            if est_ajax(request):
                return JsonResponse({"ok": False, "erreur": erreur}, status=400)
            messages.error(request, erreur)

        conversation.marquer_lue(request.user)
        conversation.interlocuteur_courant = interlocuteur
        conversation.interlocuteur_en_ligne = interlocuteur and est_en_ligne(interlocuteur.pk)

    return render(request, "notifications/messagerie.html", {
        "conversations": conversations,
        "conversation": conversation,
        "messages_conversation": conversation.messages.select_related("expediteur") if conversation else [],
        "form": form,
        "extensions_acceptees": ",".join(f".{e}" for e in settings.PIECE_JOINTE_EXTENSIONS),
        "taille_max": settings.PIECE_JOINTE_TAILLE_MAX,
    })


@login_required
def piece_jointe(request, pk):
    """Sert une pièce jointe, uniquement aux participants de la conversation."""
    message = get_object_or_404(Message.objects.filter(conversation__participants=request.user)
                                .exclude(fichier=""), pk=pk)
    # Images et PDF s'affichent dans le navigateur ; le reste est téléchargé
    en_ligne = message.est_image or message.extension == "pdf"
    if request.GET.get("telecharger"):
        en_ligne = False
    try:
        fichier = message.fichier.open("rb")
    except FileNotFoundError:
        raise Http404("Fichier introuvable.")
    return FileResponse(fichier, as_attachment=not en_ligne, filename=message.nom_fichier)


@login_required
def recherche(request):
    terme = request.GET.get("q", "").strip()
    resultats = rechercher_messages(request.user, terme) if len(terme) >= 2 else []
    return render(request, "notifications/recherche.html", {
        "terme": terme,
        "resultats": resultats,
        "conversations": conversations_de(request.user),
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
            try:
                envoyer_message(conversation, request.user, form.cleaned_data["contenu"])
            except MessageBloque as e:
                form.add_error("contenu", f"Message bloqué par la modération : {e.resultat.raison} "
                                          f"(détecté par : {e.resultat.libelle_source})")
            else:
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
    return JsonResponse({"messages": [
        {**message_en_dict(m), "moi": m.expediteur_id == request.user.pk} for m in nouveaux
    ]})


# ---------- Modération (administrateur) ----------

@admin_required
def moderation(request):
    filtre = request.GET.get("filtre", "a-traiter")
    qs = Signalement.objects.select_related("auteur", "message", "traite_par", "conversation")
    if filtre == "a-traiter":
        qs = qs.filter(traite=False)
    elif filtre == "traites":
        qs = qs.filter(traite=True)

    stats = Signalement.objects.aggregate(
        a_traiter=Count("id", filter=Q(traite=False)),
        bloques=Count("id", filter=Q(decision=Signalement.Decision.BLOQUE)),
        signales=Count("id", filter=Q(decision=Signalement.Decision.SIGNALE)),
        par_ia=Count("id", filter=Q(source=Signalement.Source.GEMINI)),
    )
    # Nombre de signalements par auteur, pour repérer les récidivistes
    recidives = dict(Signalement.objects.values_list("auteur").annotate(n=Count("id")))
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    for s in page:
        s.nb_signalements_auteur = recidives.get(s.auteur_id, 0)

    return render(request, "notifications/moderation.html", {
        "page": page,
        "filtre": filtre,
        "stats": stats,
        "ia_active": ia_disponible(),
    })


@require_POST
@admin_required
def traiter_signalement(request, pk):
    signalement = get_object_or_404(Signalement.objects.select_related("auteur", "conversation", "message"), pk=pk)
    try:
        messages.success(request, appliquer_decision_moderateur(signalement, request.user, request.POST.get("action")))
    except (PermissionDenied, ValidationError) as e:
        messages.error(request, f"Action impossible : {e.messages[0] if isinstance(e, ValidationError) else e}")
    return rediriger_vers_suivant(request, "notifications:moderation")


# ---------- Messages : modifier et supprimer les siens ----------

@login_required
def message_modifier(request, pk):
    message = get_object_or_404(Message.objects.select_related("conversation"), pk=pk, expediteur=request.user)
    form = ModifierMessageForm(request.POST or None, initial={"contenu": message.contenu})
    if request.method == "POST" and form.is_valid():
        try:
            services.modifier_message(message, request.user, form.cleaned_data["contenu"])
        except MessageBloque as e:
            form.add_error("contenu", f"Modification refusée par la modération : {e.resultat.raison} "
                                      f"(détecté par : {e.resultat.libelle_source})")
        except ValidationError as e:
            form.add_error("contenu", e.messages[0])
        else:
            messages.success(request, "Message modifié.")
            return redirect(f"{message.conversation.get_absolute_url()}#message-{message.pk}")
    return render(request, "notifications/message_modifier.html", {"message": message, "form": form})


@require_POST
@login_required
def message_supprimer(request, pk):
    message = get_object_or_404(Message.objects.select_related("conversation"), pk=pk, expediteur=request.user)
    conversation = message.conversation
    services.supprimer_message(message, request.user)
    if est_ajax(request):
        return JsonResponse({"ok": True})
    messages.success(request, "Message supprimé.")
    return redirect(conversation)


# ---------- Annonces (CRUD) ----------

@login_required
def annonces(request):
    """Liste : tout pour l'administrateur (avec gestion), seulement les siennes pour les autres."""
    qs = Annonce.objects.select_related("auteur")
    if not request.user.est_administrateur:
        qs = qs.filter(public__in=[Annonce.Public.TOUS, request.user.role])
    page = Paginator(qs, 15).get_page(request.GET.get("page"))
    if request.user.est_administrateur:
        for annonce in page:
            stats = annonce.notifications().aggregate(envoyees=Count("id"), lues=Count("id", filter=Q(lue=True)))
            annonce.nb_envoyees, annonce.nb_lues = stats["envoyees"], stats["lues"]
    return render(request, "notifications/annonces.html", {"page": page})


@login_required
def annonce_detail(request, pk):
    annonce = get_object_or_404(Annonce.objects.select_related("auteur"), pk=pk)
    if not annonce.concerne(request.user):
        raise Http404
    annonce.notifications().filter(destinataire=request.user, lue=False).update(lue=True)
    return render(request, "notifications/annonce_detail.html", {"annonce": annonce})


@admin_required
def annonce_creer(request):
    form = AnnonceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        annonce = form.save(commit=False)
        annonce.auteur = request.user
        annonce.save()
        n = services.publier_annonce(annonce)
        messages.success(request, f"Annonce publiée auprès de {n} personne{'s' if n > 1 else ''}.")
        return redirect("notifications:annonces")
    return render(request, "notifications/annonce_form.html", {"form": form})


@admin_required
def annonce_modifier(request, pk):
    annonce = get_object_or_404(Annonce, pk=pk)
    form = AnnonceForm(request.POST or None, instance=annonce)
    if request.method == "POST" and form.is_valid():
        annonce = form.save()
        n = services.mettre_a_jour_annonce(annonce)
        messages.success(request, f"Annonce modifiée ({n} destinataire{'s' if n > 1 else ''}).")
        return redirect("notifications:annonces")
    return render(request, "notifications/annonce_form.html", {"form": form, "annonce": annonce})


@admin_required
def annonce_supprimer(request, pk):
    annonce = get_object_or_404(Annonce, pk=pk)
    if request.method == "POST":
        titre = annonce.titre
        services.supprimer_annonce(annonce)
        messages.success(request, f"Annonce « {titre} » supprimée.")
        return redirect("notifications:annonces")
    return render(request, "notifications/annonce_supprimer.html", {
        "annonce": annonce, "nb_notifications": annonce.notifications().count(),
    })
