from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from apps.accounts.models import User

from .forms import DemandeSeanceForm, DisponibiliteForm, LienVisioForm, PlanifierSeanceForm
from .models import Disponibilite, SeanceMentorat
from .services import CreneauIndisponible, changer_statut, creneaux_disponibles, peut_gerer_seance, reserver_seance


@login_required
def index(request):
    user = request.user
    peut_gerer = user.est_administrateur or (user.est_formateur and not user.en_attente_validation)
    peut_publier = user.est_formateur and not user.en_attente_validation and user.is_active
    formateurs = User.objects.none()
    formateur_selectionne = None
    if user.est_administrateur:
        seances = SeanceMentorat.objects.all()
        disponibilites = Disponibilite.objects.filter(active=True)
    elif user.est_formateur:
        seances = SeanceMentorat.objects.filter(formateur=user)
        disponibilites = Disponibilite.objects.filter(formateur=user, active=True)
    elif user.est_apprenant:
        maintenant = timezone.now()
        formateurs = User.objects.filter(
            role=User.Role.FORMATEUR, is_active=True, est_valide=True,
            disponibilites_mentorat__active=True, disponibilites_mentorat__fin__gt=maintenant,
        ).distinct().order_by("first_name", "last_name", "username")
        try:
            formateur_id = int(request.GET.get("formateur", ""))
        except (TypeError, ValueError):
            formateur_id = None
        if formateur_id:
            formateur_selectionne = formateurs.filter(pk=formateur_id).first()
        seances = SeanceMentorat.objects.filter(apprenant=user)
        disponibilites = Disponibilite.objects.none()
        if formateur_selectionne:
            disponibilites = Disponibilite.objects.filter(
                formateur=formateur_selectionne, active=True, debut__gt=maintenant,
            )
            seances = seances.filter(formateur=formateur_selectionne)
    else:
        raise PermissionDenied
    seances = seances.select_related("apprenant", "formateur", "disponibilite")
    disponibilites = disponibilites.select_related("formateur")
    return render(request, "mentoring/index.html", {
        "seances": seances,
        "disponibilites": disponibilites,
        "peut_gerer": peut_gerer,
        "peut_publier": peut_publier,
        "formateurs": formateurs,
        "formateur_selectionne": formateur_selectionne,
    })


@login_required
def calendrier_evenements(request):
    debut = parse_datetime(request.GET.get("start", ""))
    fin = parse_datetime(request.GET.get("end", ""))
    if not debut or not fin:
        return JsonResponse({"error": "Paramètres start et end requis."}, status=400)
    if timezone.is_naive(debut):
        debut = timezone.make_aware(debut, timezone.get_current_timezone())
    if timezone.is_naive(fin):
        fin = timezone.make_aware(fin, timezone.get_current_timezone())
    if fin <= debut or (fin - debut).days > 62:
        return JsonResponse({"error": "Période de calendrier invalide."}, status=400)

    user = request.user
    if user.est_administrateur:
        disponibilites = Disponibilite.objects.filter(active=True)
        seances = SeanceMentorat.objects.all()
    elif user.est_formateur:
        disponibilites = Disponibilite.objects.filter(formateur=user, active=True)
        seances = SeanceMentorat.objects.filter(formateur=user)
    elif user.est_apprenant:
        try:
            formateur_id = int(request.GET.get("formateur", ""))
        except (TypeError, ValueError):
            formateur_id = None
        formateur = User.objects.filter(
            pk=formateur_id, role=User.Role.FORMATEUR, is_active=True, est_valide=True,
        ).first() if formateur_id else None
        if not formateur:
            return JsonResponse({"error": "Choisissez un formateur valide pour afficher son calendrier."}, status=400)
        disponibilites = Disponibilite.objects.filter(
            formateur=formateur, active=True, debut__gt=timezone.now(),
        )
        seances = SeanceMentorat.objects.filter(apprenant=user, formateur=formateur)
    else:
        raise PermissionDenied

    events = []
    for slot in disponibilites.filter(debut__lt=fin, fin__gt=debut).select_related("formateur"):
        events.append({
            "id": f"availability-{slot.pk}", "type": "availability",
            "title": f"Libre · {slot.formateur.get_full_name() or slot.formateur.username}",
            "start": timezone.localtime(slot.debut).isoformat(),
            "end": timezone.localtime(slot.fin).isoformat(),
            "availability_id": slot.pk, "duration": slot.duree_seance,
            "trainer": slot.formateur.get_full_name() or slot.formateur.username,
            "has_sessions": slot.seances.exists(),
            "url": reverse("mentoring:disponibilite_modifier", args=[slot.pk])
            if user.pk == slot.formateur_id else (
                reverse("mentoring:reserver", args=[slot.pk]) if user.est_apprenant else ""
            ),
            "plan_url": reverse("mentoring:planifier", args=[slot.pk])
            if user.pk == slot.formateur_id else "",
            "delete_url": reverse("mentoring:disponibilite_supprimer", args=[slot.pk])
            if user.pk == slot.formateur_id else "",
        })
    for session in seances.filter(debut__lt=fin, fin__gt=debut).select_related("formateur", "apprenant"):
        events.append({
            "id": f"session-{session.pk}", "type": "session",
            "title": session.sujet,
            "start": timezone.localtime(session.debut).isoformat(),
            "end": timezone.localtime(session.fin).isoformat(),
            "status": session.statut, "status_label": session.get_statut_display(),
            "trainer": session.formateur.get_full_name() or session.formateur.username,
            "learner": session.apprenant.get_full_name() or session.apprenant.username,
            "url": session.get_absolute_url(),
        })
    return JsonResponse({"events": events})


@login_required
def disponibilite_creer(request):
    if not (request.user.is_active and request.user.est_formateur and not request.user.en_attente_validation):
        raise PermissionDenied
    form = DisponibiliteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        disponibilite = form.save(commit=False)
        disponibilite.formateur = request.user
        try:
            disponibilite.full_clean()
            disponibilite.save()
        except (ValidationError, IntegrityError) as exc:
            erreurs = exc.message_dict if isinstance(exc, ValidationError) and hasattr(exc, "message_dict") else {"__all__": ["Cette disponibilité chevauche une autre plage ou contient des données invalides."]}
            for champ, liste in erreurs.items():
                for erreur in liste:
                    form.add_error(champ if champ in form.fields else None, erreur)
        else:
            messages.success(request, "Votre disponibilité a été publiée.")
            return redirect("mentoring:index")
    return render(request, "mentoring/disponibilite_form.html", {"form": form})


@login_required
def disponibilite_modifier(request, pk):
    disponibilite = get_object_or_404(Disponibilite, pk=pk)
    if not (request.user.is_active and request.user.est_formateur and not request.user.en_attente_validation
            and disponibilite.formateur_id == request.user.pk):
        raise PermissionDenied
    form = DisponibiliteForm(request.POST or None, instance=disponibilite)
    if request.method == "POST" and form.is_valid():
        modifiee = form.save(commit=False)
        try:
            modifiee.full_clean()
            seances_actives = disponibilite.seances.filter(
                statut__in=(SeanceMentorat.Statut.EN_ATTENTE, SeanceMentorat.Statut.CONFIRMEE),
            )
            if modifiee.duree_seance != disponibilite.duree_seance and seances_actives.exists():
                form.add_error("duree_seance", "La durée ne peut pas changer tant que des séances sont réservées.")
            for seance in seances_actives:
                if seance.debut < modifiee.debut or seance.fin > modifiee.fin:
                    form.add_error(None, "La nouvelle période doit continuer à contenir toutes les séances actives.")
                    break
            if form.errors:
                return render(request, "mentoring/disponibilite_form.html", {
                    "form": form, "edition": True, "disponibilite": disponibilite,
                })
            modifiee.save()
        except (ValidationError, IntegrityError) as exc:
            erreurs = exc.message_dict if isinstance(exc, ValidationError) and hasattr(exc, "message_dict") else {"__all__": ["La disponibilité n’a pas pu être mise à jour."]}
            for champ, liste in erreurs.items():
                for erreur in liste:
                    form.add_error(champ if champ in form.fields else None, erreur)
        else:
            messages.success(request, "La disponibilité a été mise à jour.")
            return redirect("mentoring:index")
    return render(request, "mentoring/disponibilite_form.html", {
        "form": form, "edition": True, "disponibilite": disponibilite,
    })


@login_required
@require_POST
def disponibilite_supprimer(request, pk):
    disponibilite = get_object_or_404(Disponibilite, pk=pk)
    if not (request.user.is_active and request.user.est_formateur and not request.user.en_attente_validation
            and disponibilite.formateur_id == request.user.pk):
        raise PermissionDenied
    if disponibilite.seances.exists():
        messages.error(request, "Cette disponibilité est liée à des séances. Fermez-la plutôt que de la supprimer.")
    else:
        disponibilite.delete()
        messages.success(request, "La disponibilité a été supprimée.")
    return redirect("mentoring:index")


@login_required
@require_POST
def disponibilite_desactiver(request, pk):
    disponibilite = get_object_or_404(Disponibilite, pk=pk)
    if not (request.user.est_administrateur or (request.user.est_formateur and not request.user.en_attente_validation and disponibilite.formateur_id == request.user.pk)):
        raise PermissionDenied
    if disponibilite.seances.filter(statut__in=(SeanceMentorat.Statut.EN_ATTENTE, SeanceMentorat.Statut.CONFIRMEE)).exists():
        messages.error(request, "Cette disponibilité contient des réservations actives. Annulez-les avant de la fermer.")
    else:
        disponibilite.active = False
        disponibilite.save(update_fields=["active"])
        messages.success(request, "La disponibilité a été fermée.")
    return redirect("mentoring:index")


@login_required
def reserver(request, pk):
    if not request.user.est_apprenant:
        raise PermissionDenied
    disponibilite = get_object_or_404(Disponibilite.objects.select_related("formateur"), pk=pk, active=True)
    creneaux = creneaux_disponibles(disponibilite)
    form = DemandeSeanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        debut_txt = request.POST.get("debut", "")
        debut = next((item for item in creneaux if item.isoformat() == debut_txt), None)
        if debut is None:
            form.add_error(None, "Ce créneau n’est plus disponible. Choisissez-en un autre.")
        else:
            try:
                seance = reserver_seance(disponibilite.pk, request.user, debut, form.cleaned_data["sujet"], form.cleaned_data["description"])
            except CreneauIndisponible as exc:
                form.add_error(None, str(exc))
            except ValidationError as exc:
                for erreur in exc.messages:
                    form.add_error(None, erreur)
            else:
                messages.success(request, "Votre demande de séance a été envoyée au formateur.")
                return redirect(seance.get_absolute_url())
    return render(request, "mentoring/reserver.html", {"form": form, "disponibilite": disponibilite, "creneaux": creneaux})


@login_required
def planifier(request, pk):
    disponibilite = get_object_or_404(Disponibilite, pk=pk, active=True)
    if not (request.user.is_active and request.user.est_formateur and not request.user.en_attente_validation
            and disponibilite.formateur_id == request.user.pk):
        raise PermissionDenied
    form = PlanifierSeanceForm(request.POST or None, disponibilite=disponibilite)
    if request.method == "POST" and form.is_valid():
        try:
            seance = reserver_seance(
                disponibilite.pk, form.cleaned_data["apprenant"], form.cleaned_data["debut"],
                form.cleaned_data["sujet"], form.cleaned_data["description"], demandeur=request.user,
            )
        except CreneauIndisponible as exc:
            form.add_error(None, str(exc))
        except ValidationError as exc:
            for erreur in exc.messages:
                form.add_error(None, erreur)
        else:
            messages.success(request, "La séance a été planifiée et confirmée.")
            return redirect(seance.get_absolute_url())
    return render(request, "mentoring/planifier.html", {"form": form, "disponibilite": disponibilite})


@login_required
def seance_detail(request, pk):
    seance = get_object_or_404(SeanceMentorat.objects.select_related("formateur", "apprenant", "disponibilite"), pk=pk)
    if not (request.user.est_administrateur or request.user.pk in (seance.formateur_id, seance.apprenant_id)):
        raise PermissionDenied
    peut_confirmer = request.user.est_administrateur or (request.user.est_formateur and not request.user.en_attente_validation and request.user.pk == seance.formateur_id)
    peut_annuler = peut_confirmer or request.user.pk == seance.apprenant_id
    lien_form = LienVisioForm(request.POST or None, instance=seance)
    if request.method == "POST" and request.POST.get("action") == "lien":
        if not peut_confirmer:
            raise PermissionDenied
        if lien_form.is_valid():
            lien_form.save()
            messages.success(request, "Le lien de visioconférence a été enregistré.")
            return redirect(seance.get_absolute_url())
    return render(request, "mentoring/seance_detail.html", {
        "seance": seance, "peut_confirmer": peut_confirmer,
        "peut_annuler": peut_annuler, "lien_form": lien_form,
    })


@login_required
@require_POST
def seance_action(request, pk, action):
    seance = get_object_or_404(SeanceMentorat.objects.select_related("formateur", "apprenant"), pk=pk)
    statut_cible = {"confirmer": SeanceMentorat.Statut.CONFIRMEE, "annuler": SeanceMentorat.Statut.ANNULEE,
                    "terminer": SeanceMentorat.Statut.TERMINEE}.get(action)
    if statut_cible is None:
        raise PermissionDenied
    if action == "confirmer" and not (request.user.est_administrateur or (request.user.est_formateur and not request.user.en_attente_validation and request.user.pk == seance.formateur_id)):
        raise PermissionDenied
    if action == "terminer" and not (request.user.est_administrateur or (request.user.est_formateur and not request.user.en_attente_validation and request.user.pk == seance.formateur_id)):
        raise PermissionDenied
    if action == "annuler" and not (request.user.est_administrateur or request.user.pk in (seance.formateur_id, seance.apprenant_id)):
        raise PermissionDenied
    try:
        changer_statut(seance, statut_cible, par=request.user)
    except ValidationError as exc:
        for erreur in exc.messages:
            messages.error(request, erreur)
    else:
        messages.success(request, f"La séance est maintenant : {seance.get_statut_display().lower()}.")
    return redirect(seance.get_absolute_url())
