import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import admin_required, role_required
from apps.accounts.models import User

from . import progression, services, stats
from .forms import (DelivrerCertificatForm, FiltreCertificatsForm, ModifierCertificatForm, RevocationForm,
                    VerificationForm)
from .models import Certificat


def certificats_visibles(user):
    qs = Certificat.objects.select_related("apprenant", "formateur")
    if user.est_administrateur:
        return qs
    if user.est_formateur:
        return qs.filter(Q(formateur=user) | Q(delivre_par=user))
    return qs.filter(apprenant=user)


@login_required
def index(request):
    """Apprenant : ses certificats. Formateur et administrateur : progression et certificats délivrés."""
    user = request.user
    if user.est_apprenant:
        return render(request, "certificates/mes_certificats.html", {
            "certificats": certificats_visibles(user),
            "progression": progression.lignes_progression(user),
            "score_minimum": services.score_minimum(),
        })

    filtres = FiltreCertificatsForm(request.GET or None)
    qs = certificats_visibles(user)
    if filtres.is_valid():
        q, statut = filtres.cleaned_data["q"], filtres.cleaned_data["statut"]
        if q:
            qs = qs.filter(Q(titre_cours__icontains=q) | Q(code_verification__icontains=q)
                           | Q(apprenant__first_name__icontains=q) | Q(apprenant__last_name__icontains=q)
                           | Q(apprenant__email__icontains=q))
        if statut:
            qs = qs.filter(statut=statut)

    params = request.GET.copy()
    params.pop("page", None)
    resume = (stats.statistiques_plateforme()["certificats"] if user.est_administrateur
              else stats.statistiques_formateur(user)["certificats"])

    return render(request, "certificates/suivi.html", {
        "filtres": filtres,
        "page": Paginator(qs, 15).get_page(request.GET.get("page")),
        "params": params.urlencode(),
        "resume": resume,
        "progression": progression.lignes_progression(user, limite=8),
        "progression_resume": stats.resume_progression(user),
    })


@login_required
def detail(request, code):
    certificat = get_object_or_404(Certificat.objects.select_related("apprenant", "formateur"),
                                   code_verification=code)
    if not certificat.peut_etre_consulte_par(request.user):
        raise PermissionDenied
    return render(request, "certificates/detail.html", {
        "certificat": certificat,
        "url_verification": request.build_absolute_uri(certificat.get_verification_url()),
        "form_revocation": RevocationForm() if request.user.est_administrateur else None,
        "peut_modifier": certificat.est_valide and certificat.peut_etre_modifie_par(request.user),
    })


@role_required(User.Role.FORMATEUR)
def delivrer(request):
    initial = {"apprenant": request.GET.get("apprenant"), "titre_cours": request.GET.get("cours", "")}
    form = DelivrerCertificatForm(request.POST or None, initial=initial, delivre_par=request.user)
    if request.method == "POST" and form.is_valid():
        donnees = form.cleaned_data
        try:
            certificat = services.delivrer_certificat(
                donnees["apprenant"], donnees["titre_cours"], formateur=form.formateur_choisi(),
                score=donnees["score"], duree_heures=donnees["duree_heures"],
                competences=donnees["competences"], delivre_par=request.user,
            )
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f"Certificat délivré à {certificat.apprenant}. Il a été prévenu par notification.")
            return redirect(certificat)
    return render(request, "certificates/delivrer.html", {"form": form})


@role_required(User.Role.FORMATEUR)
def modifier(request, code):
    """Corriger un certificat valide : administrateur, ou formateur qui l'a délivré / dont c'est le cours."""
    certificat = get_object_or_404(Certificat.objects.select_related("apprenant"), code_verification=code)
    if not certificat.peut_etre_modifie_par(request.user):
        raise PermissionDenied
    if not certificat.est_valide:
        messages.error(request, "Un certificat révoqué ne peut plus être modifié.")
        return redirect(certificat)

    form = ModifierCertificatForm(request.POST or None, instance=certificat, modifie_par=request.user)
    if request.method == "POST" and form.is_valid():
        if form.has_changed():
            form.save()
            services.notifier_modification(certificat)
            messages.success(request, "Le certificat a été mis à jour. L'apprenant a été prévenu.")
        return redirect(certificat)
    return render(request, "certificates/modifier.html", {"form": form, "certificat": certificat})


@admin_required
def supprimer(request, code):
    """Suppression définitive (erreur de délivrance). Pour une fraude, préférer la révocation qui garde une trace."""
    certificat = get_object_or_404(Certificat.objects.select_related("apprenant"), code_verification=code)
    if request.method == "POST":
        description = str(certificat)
        certificat.delete()
        messages.success(request, f"Certificat supprimé : {description}.")
        return redirect("certificates:index")
    return render(request, "certificates/supprimer.html", {"certificat": certificat})


@require_POST
@admin_required
def revoquer(request, code):
    certificat = get_object_or_404(Certificat, code_verification=code)
    form = RevocationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indiquez le motif de la révocation.")
        return redirect(certificat)
    try:
        services.revoquer_certificat(certificat, request.user, form.cleaned_data["motif"])
    except ValidationError as e:
        messages.error(request, e.messages[0])
    else:
        messages.success(request, "Le certificat a été révoqué. L'apprenant a été prévenu.")
    return redirect(certificat)


def verifier(request):
    """Page publique : un recruteur saisit le code imprimé sur le certificat."""
    form = VerificationForm(request.GET or None)
    if form.is_valid():
        return redirect("certificates:verifier_code", code=form.cleaned_data["code"])
    return render(request, "certificates/verifier.html", {"form": form})


def verifier_code(request, code):
    certificat = (Certificat.objects.select_related("apprenant")
                  .filter(code_verification=code.strip().upper()).first())
    return render(request, "certificates/verifier.html", {
        "form": VerificationForm(initial={"code": code}),
        "code": code,
        "certificat": certificat,
        "recherche": True,
    })


@role_required(User.Role.FORMATEUR)
def statistiques(request):
    user = request.user
    if user.est_administrateur:
        contexte = stats.statistiques_plateforme()
    else:
        contexte = stats.statistiques_formateur(user)
    contexte["progression"] = stats.resume_progression(user)
    return render(request, "certificates/statistiques.html", contexte)


@admin_required
def export_csv(request):
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    nom = f"certificats-skillforge-{timezone.localdate():%Y-%m-%d}.csv"
    reponse["Content-Disposition"] = f'attachment; filename="{nom}"'
    reponse.write("﻿")  # BOM : Excel ouvre correctement les accents
    ecrivain = csv.writer(reponse, delimiter=";")
    ecrivain.writerow(["Code", "Apprenant", "E-mail", "Cours", "Formateur", "Score", "Heures",
                       "Délivré le", "Statut", "Motif de révocation"])
    for c in Certificat.objects.select_related("apprenant").order_by("-date_delivrance"):
        ecrivain.writerow([
            c.code_verification, str(c.apprenant), c.apprenant.email, c.titre_cours, c.nom_formateur,
            "" if c.score is None else c.score, c.duree_heures or "",
            timezone.localtime(c.date_delivrance).strftime("%d/%m/%Y"), c.get_statut_display(), c.motif_revocation,
        ])
    return reponse
