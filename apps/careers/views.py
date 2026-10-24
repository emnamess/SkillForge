from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.decorators import admin_required

from . import services
from .decorators import apprenant_required, recruteur_required
from .forms import (CandidatureForm, ChangerStatutForm, CompetenceApprenantFormSet, CompetenceForm,
                    CompetenceRequiseFormSet, CVForm, EntretienForm, FiltreOffresForm, InscriptionRecruteurForm,
                    OffreForm, ProfilCarriereForm, ProfilEntrepriseForm, RefusEntrepriseForm, SignalementOffreForm,
                    SuggestionsForm)
from .models import (Candidature, Competence, HistoriqueCandidature, Offre, ProfilCarriere, ProfilEntreprise,
                     SignalementOffre)

CLE_SUGGESTIONS = "careers_suggestions"


def rediriger_vers_suivant(request, defaut, *args):
    """Redirige vers ?next s'il pointe vers SkillForge, sinon vers la page par défaut."""
    suivant = request.POST.get("next")
    if suivant and url_has_allowed_host_and_scheme(suivant, {request.get_host()}):
        return redirect(suivant)
    return redirect(defaut, *args)


def est_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def paginer(request, objets, par_page=12):
    page = Paginator(objets, par_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def premiere_erreur(e):
    return e.messages[0] if isinstance(e, ValidationError) else str(e)


def offres_ouvertes():
    return Offre.objects.ouvertes().select_related("entreprise").prefetch_related("competences_requises__competence")


def index(request):
    """Point d'entrée « Carrière » : chaque rôle arrive sur son tableau de bord."""
    user = request.user
    if user.is_authenticated:
        if user.est_administrateur:
            return redirect("careers:admin_statistiques")
        if user.est_recruteur:
            return redirect("careers:tableau_recruteur")
        if user.est_apprenant:
            return redirect("careers:tableau_apprenant")
    return redirect("careers:offres")


# ---------- Offres (pages publiques) ----------

def offres(request):
    filtres = FiltreOffresForm(request.GET or None)
    qs = filtres.filtrer(offres_ouvertes())
    tri = filtres.cleaned_data.get("tri") if filtres.is_valid() else ""
    apprenant = request.user if request.user.is_authenticated and request.user.est_apprenant else None

    if apprenant:
        liste = services.scores_offres(apprenant, qs)
        if tri != "date":
            liste = services.trier_par_score(liste)
    else:
        liste = qs

    page, params = paginer(request, liste)
    return render(request, "careers/offres.html", {
        "page": page, "params": params, "filtres": filtres, "avec_score": apprenant is not None,
    })


def offre_detail(request, pk):
    offre = get_object_or_404(Offre.objects.select_related("entreprise").prefetch_related(
        "competences_requises__competence"), pk=pk)
    user = request.user
    proprietaire = user.is_authenticated and offre.entreprise.utilisateur_id == user.pk
    candidature = (Candidature.objects.filter(offre=offre, apprenant=user).first()
                   if user.is_authenticated and user.est_apprenant else None)

    # Une offre non publiée n'est visible que par son recruteur, l'administrateur et ses candidats
    if not offre.est_ouverte and not (proprietaire or candidature or
                                      (user.is_authenticated and user.est_administrateur)):
        raise Http404("Offre introuvable.")

    contexte = {"offre": offre, "proprietaire": proprietaire, "candidature": candidature}
    if user.is_authenticated and user.est_apprenant:
        niveaux = services.niveaux_de(user)
        contexte.update({
            "compatibilite": services.score_offre(offre, user, niveaux),
            "ecarts": services.ecart_competences(offre, user, niveaux),
            "raison_refus": services.raison_refus_candidature(offre, user),
            "form": CandidatureForm(),
            "form_signalement": SignalementOffreForm(),
            "profil_a_un_cv": ProfilCarriere.objects.filter(apprenant=user).exclude(cv="").exists(),
        })
    return render(request, "careers/offre_detail.html", contexte)


@require_POST
@apprenant_required
def postuler(request, pk):
    offre = get_object_or_404(Offre.objects.select_related("entreprise__utilisateur"), pk=pk)
    form = CandidatureForm(request.POST)
    if form.is_valid():
        try:
            services.postuler(offre, request.user, form.cleaned_data["lettre_motivation"])
        except ValidationError as e:
            messages.error(request, premiere_erreur(e))
        else:
            messages.success(request, f"Candidature envoyée à {offre.entreprise}. Suivez-la dans « Mes candidatures ».")
            return redirect("careers:mes_candidatures")
    return redirect(offre)


@require_POST
@apprenant_required
def signaler_offre(request, pk):
    offre = get_object_or_404(Offre.objects.ouvertes(), pk=pk)
    form = SignalementOffreForm(request.POST)
    if form.is_valid():
        try:
            services.signaler_offre(offre, request.user, form.cleaned_data["motif"], form.cleaned_data["details"])
        except ValidationError as e:
            messages.error(request, premiere_erreur(e))
        else:
            messages.success(request, "Merci : l'offre a été signalée à la modération.")
    else:
        messages.error(request, "Choisissez un motif de signalement.")
    return redirect(offre)


# ---------- Inscription des recruteurs ----------

def inscription_recruteur(request):
    if request.user.is_authenticated:
        return redirect("careers:index")

    form = InscriptionRecruteurForm(request.POST or None)
    form_entreprise = ProfilEntrepriseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid() and form_entreprise.is_valid():
        user = services.inscrire_recruteur(form, form_entreprise)
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        messages.info(request, "Votre compte recruteur est créé. Un administrateur doit valider votre entreprise "
                               "avant que vous puissiez publier des offres.")
        return redirect("careers:tableau_recruteur")

    return render(request, "careers/inscription_recruteur.html", {"form": form, "form_entreprise": form_entreprise})


# ---------- Espace apprenant ----------

@apprenant_required
def tableau_apprenant(request):
    user = request.user
    profil = ProfilCarriere.objects.filter(apprenant=user).annotate(nb_competences=Count("competences")).first()
    deja_postule = user.candidatures.values_list("offre_id", flat=True)
    offres_pour_toi = services.trier_par_score(
        services.scores_offres(user, offres_ouvertes().exclude(pk__in=deja_postule)[:60]))[:6]
    return render(request, "careers/apprenant/tableau.html", {
        "profil": profil,
        "completude": services.completude_profil(profil, profil.nb_competences if profil else 0),
        "offres_pour_toi": offres_pour_toi,
        "prioritaires": services.competences_prioritaires(user),
        "candidatures": user.candidatures.select_related("offre__entreprise")[:5],
    })


@apprenant_required
def profil_carriere(request):
    profil = services.obtenir_profil(request.user)
    form = ProfilCarriereForm(request.POST or None, instance=profil)
    formset = CompetenceApprenantFormSet(request.POST or None, instance=profil, prefix="competences",
                                         queryset=profil.competences.select_related("competence"))
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Votre profil carrière a été mis à jour.")
            return redirect("careers:profil")
        messages.error(request, "Corrigez les erreurs signalées dans le formulaire.")

    ids = request.session.get(CLE_SUGGESTIONS)
    suggestions = Competence.objects.filter(pk__in=ids) if ids else None
    return render(request, "careers/apprenant/profil.html", {
        "profil": profil,
        "form": form,
        "formset": formset,
        "form_cv": CVForm(),
        "suggestions": suggestions,
        "cv_analyse": ids is not None,
        "completude": services.completude_profil(profil),
    })


@require_POST
@apprenant_required
def deposer_cv(request):
    profil = services.obtenir_profil(request.user)
    form = CVForm(request.POST, request.FILES)
    if form.is_valid():
        suggestions = services.enregistrer_cv(profil, form.cleaned_data["cv"])
        request.session[CLE_SUGGESTIONS] = [c.pk for c in suggestions]
        if suggestions:
            messages.success(request, f"CV enregistré. {len(suggestions)} compétence(s) repérée(s) : "
                                      "cochez celles à ajouter à votre profil.")
        else:
            messages.success(request, "CV enregistré. Aucune suggestion de compétence trouvée dans ce document.")
    else:
        messages.error(request, form.errors["cv"][0])
    return redirect("careers:profil")


@require_POST
@apprenant_required
def ajouter_suggestions(request):
    profil = services.obtenir_profil(request.user)
    form = SuggestionsForm(request.POST)
    proposees = request.session.pop(CLE_SUGGESTIONS, None) or []
    if form.is_valid():
        ids = [c.pk for c in form.cleaned_data["competences"] if c.pk in proposees]
        n = services.ajouter_competences(profil, ids)
        if n:
            messages.success(request, f"{n} compétence(s) ajoutée(s) au niveau « Notions » : ajustez vos niveaux.")
    return redirect("careers:profil")


@apprenant_required
def mes_candidatures(request):
    qs = request.user.candidatures.select_related("offre__entreprise").prefetch_related(
        Prefetch("historique", queryset=HistoriqueCandidature.objects.select_related("auteur")))
    page, params = paginer(request, qs, 10)
    return render(request, "careers/apprenant/candidatures.html", {"page": page, "params": params})


@apprenant_required
def candidature_detail(request, pk):
    candidature = get_object_or_404(request.user.candidatures.select_related("offre__entreprise"), pk=pk)
    return render(request, "careers/apprenant/candidature_detail.html", {
        "candidature": candidature,
        "historique": candidature.historique.select_related("auteur"),
    })


@require_POST
@apprenant_required
def retirer_candidature(request, pk):
    candidature = get_object_or_404(request.user.candidatures.select_related("offre__entreprise"), pk=pk)
    try:
        services.retirer_candidature(candidature, request.user)
    except ValidationError as e:
        messages.error(request, premiere_erreur(e))
    else:
        messages.success(request, f"Votre candidature à « {candidature.offre.titre} » est retirée.")
    return rediriger_vers_suivant(request, "careers:mes_candidatures")


# ---------- Téléchargement protégé des CV ----------

def servir_pdf(champ, nom):
    try:
        fichier = champ.open("rb")
    except FileNotFoundError:
        raise Http404("Fichier introuvable.")
    return FileResponse(fichier, as_attachment=False, filename=nom, content_type="application/pdf")


@login_required
def cv_profil(request, pk):
    """CV actuel : son propriétaire et l'administrateur uniquement."""
    qs = ProfilCarriere.objects.exclude(cv="").select_related("apprenant")
    if not request.user.est_administrateur:
        qs = qs.filter(apprenant=request.user)
    profil = get_object_or_404(qs, pk=pk)
    return servir_pdf(profil.cv, f"CV {profil.apprenant}.pdf")


@login_required
def cv_candidature(request, pk):
    """CV déposé : le candidat, le recruteur de l'offre et l'administrateur uniquement."""
    qs = Candidature.objects.exclude(cv_depose="").select_related("apprenant")
    if not request.user.est_administrateur:
        qs = qs.filter(Q(apprenant=request.user) | Q(offre__entreprise__utilisateur=request.user))
    candidature = get_object_or_404(qs, pk=pk)
    return servir_pdf(candidature.cv_depose, f"CV {candidature.apprenant}.pdf")


# ---------- Espace recruteur ----------

@recruteur_required
def tableau_recruteur(request):
    return render(request, "careers/recruteur/tableau.html", services.tableau_recruteur(request.user))


@recruteur_required
def mes_offres(request):
    filtre = request.GET.get("statut", "")
    qs = Offre.objects.de(request.user).annotate(
        nb_candidatures=Count("candidatures"),
        nb_nouvelles=Count("candidatures", filter=Q(candidatures__statut=Candidature.Statut.ENVOYEE)),
    ).order_by("-date_creation")
    if filtre in Offre.Statut.values:
        qs = qs.filter(statut=filtre)
    page, params = paginer(request, qs, 15)
    return render(request, "careers/recruteur/offres.html", {
        "page": page, "params": params, "filtre": filtre, "statuts": Offre.Statut.choices,
    })


def _editer_offre(request, offre):
    nouvelle = offre.pk is None
    form = OffreForm(request.POST or None, instance=offre)
    formset = CompetenceRequiseFormSet(request.POST or None, instance=offre, prefix="competences")
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            offre = form.save(commit=False)
            offre.entreprise = request.entreprise
            offre.save()
            formset.instance = offre
            formset.save()
            if "publier" in request.POST:
                try:
                    services.publier_offre(offre)
                    messages.success(request, f"L'offre « {offre.titre} » est publiée.")
                except ValidationError as e:
                    messages.error(request, f"Offre enregistrée mais non publiée : {premiere_erreur(e)}")
            else:
                messages.success(request, f"L'offre « {offre.titre} » est enregistrée.")
            return redirect("careers:mes_offres")
        messages.error(request, "Corrigez les erreurs signalées dans le formulaire.")
    return render(request, "careers/recruteur/offre_form.html", {"form": form, "formset": formset,
                                                                  "offre": None if nouvelle else offre})


@recruteur_required
def offre_creer(request):
    return _editer_offre(request, Offre(entreprise=request.entreprise))


@recruteur_required
def offre_modifier(request, pk):
    return _editer_offre(request, get_object_or_404(Offre.objects.de(request.user), pk=pk))


@require_POST
@recruteur_required
def offre_dupliquer(request, pk):
    copie = services.dupliquer_offre(get_object_or_404(Offre.objects.de(request.user), pk=pk))
    messages.success(request, "Offre dupliquée en brouillon : ajustez-la puis publiez-la.")
    return redirect("careers:offre_modifier", copie.pk)


@require_POST
@recruteur_required
def offre_publier(request, pk):
    offre = get_object_or_404(Offre.objects.de(request.user).select_related("entreprise"), pk=pk)
    try:
        services.publier_offre(offre)
        messages.success(request, f"L'offre « {offre.titre} » est publiée.")
    except ValidationError as e:
        messages.error(request, premiere_erreur(e))
    return rediriger_vers_suivant(request, "careers:mes_offres")


@require_POST
@recruteur_required
def offre_fermer(request, pk):
    offre = get_object_or_404(Offre.objects.de(request.user), pk=pk)
    try:
        services.fermer_offre(offre)
        messages.success(request, f"L'offre « {offre.titre} » est fermée aux candidatures.")
    except ValidationError as e:
        messages.error(request, premiere_erreur(e))
    return rediriger_vers_suivant(request, "careers:mes_offres")


@recruteur_required
def kanban(request, pk):
    offre = get_object_or_404(Offre.objects.de(request.user), pk=pk)
    colonnes = services.colonnes_kanban(offre)
    for _, cartes in colonnes:
        for c in cartes:
            c.statuts_possibles = services.statuts_possibles(c, request.user)
    return render(request, "careers/recruteur/kanban.html", {"offre": offre, "colonnes": colonnes})


def candidatures_du_recruteur(user):
    return Candidature.objects.filter(offre__entreprise__utilisateur=user).select_related(
        "apprenant", "offre__entreprise")


@recruteur_required
def fiche_candidat(request, pk):
    candidature = get_object_or_404(candidatures_du_recruteur(request.user), pk=pk)
    profil = (ProfilCarriere.objects.filter(apprenant=candidature.apprenant)
              .prefetch_related("competences__competence").first())
    niveaux = services.niveaux_de(candidature.apprenant)
    return render(request, "careers/recruteur/fiche_candidat.html", {
        "candidature": candidature,
        "profil": profil,
        "compatibilite": services.score_offre(candidature.offre, candidature.apprenant, niveaux),
        "ecarts": services.ecart_competences(candidature.offre, candidature.apprenant, niveaux),
        "historique": candidature.historique.select_related("auteur"),
        "statuts_possibles": services.statuts_possibles(candidature, request.user),
        "form_entretien": EntretienForm(initial={
            "date_entretien": candidature.date_entretien,
            "lieu_ou_lien_entretien": candidature.lieu_ou_lien_entretien,
        }),
    })


@require_POST
@recruteur_required
def changer_statut(request, pk):
    """Formulaire classique (sans JavaScript) ou glisser-déposer du Kanban (fetch, réponse JSON)."""
    candidature = get_object_or_404(candidatures_du_recruteur(request.user), pk=pk)
    form = ChangerStatutForm(request.POST)
    erreur = None
    if not form.is_valid():
        erreur = "Statut inconnu."
    else:
        nouveau = form.cleaned_data["statut"]
        options = {}
        if nouveau == Candidature.Statut.ENTRETIEN and request.POST.get("date_entretien"):
            form_entretien = EntretienForm(request.POST)
            if form_entretien.is_valid():
                options = {"date_entretien": form_entretien.cleaned_data["date_entretien"],
                           "lieu": form_entretien.cleaned_data["lieu_ou_lien_entretien"]}
        try:
            services.changer_statut(candidature, request.user, nouveau,
                                    commentaire=form.cleaned_data["commentaire"], **options)
        except (ValidationError, PermissionDenied) as e:
            erreur = premiere_erreur(e)
            if nouveau == Candidature.Statut.ENTRETIEN and not options:
                erreur += " Planifiez-le depuis la fiche du candidat."

    if est_ajax(request):
        if erreur:
            return JsonResponse({"ok": False, "erreur": erreur, "statut": candidature.statut}, status=400)
        return JsonResponse({
            "ok": True,
            "statut": candidature.statut,
            "libelle": candidature.get_statut_display(),
            "statuts_possibles": [{"valeur": s.value, "libelle": s.label}
                                  for s in services.statuts_possibles(candidature, request.user)],
        })
    if erreur:
        messages.error(request, erreur)
    else:
        messages.success(request, f"{candidature.apprenant} : candidature « {candidature.get_statut_display()} ».")
    return rediriger_vers_suivant(request, "careers:kanban", candidature.offre_id)


@require_POST
@recruteur_required
def planifier_entretien(request, pk):
    candidature = get_object_or_404(candidatures_du_recruteur(request.user), pk=pk)
    form = EntretienForm(request.POST)
    if form.is_valid():
        try:
            services.planifier_entretien(candidature, request.user, form.cleaned_data["date_entretien"],
                                         form.cleaned_data["lieu_ou_lien_entretien"], form.cleaned_data["commentaire"])
        except ValidationError as e:
            messages.error(request, premiere_erreur(e))
        else:
            messages.success(request, f"Entretien planifié avec {candidature.apprenant}.")
    else:
        messages.error(request, next(iter(form.errors.values()))[0])
    return redirect("careers:fiche_candidat", candidature.pk)


# ---------- Administration ----------

@admin_required
def admin_entreprises(request):
    filtre = request.GET.get("statut", ProfilEntreprise.Statut.EN_ATTENTE)
    qs = ProfilEntreprise.objects.select_related("utilisateur").annotate(nb_offres=Count("offres"))
    if filtre in ProfilEntreprise.Statut.values:
        qs = qs.filter(statut=filtre)
    page, params = paginer(request, qs.order_by("-date_creation"), 15)
    return render(request, "careers/admin/entreprises.html", {
        "page": page, "params": params, "filtre": filtre, "statuts": ProfilEntreprise.Statut.choices,
        "form_refus": RefusEntrepriseForm(),
    })


@require_POST
@admin_required
def admin_valider_entreprise(request, pk):
    entreprise = get_object_or_404(ProfilEntreprise.objects.select_related("utilisateur"), pk=pk)
    try:
        services.valider_entreprise(entreprise)
        messages.success(request, f"{entreprise} est validée : elle peut publier des offres.")
    except ValidationError as e:
        messages.error(request, premiere_erreur(e))
    return rediriger_vers_suivant(request, "careers:admin_entreprises")


@require_POST
@admin_required
def admin_refuser_entreprise(request, pk):
    entreprise = get_object_or_404(ProfilEntreprise.objects.select_related("utilisateur"), pk=pk)
    try:
        services.refuser_entreprise(entreprise, request.POST.get("motif"))
        messages.success(request, f"{entreprise} est refusée.")
    except ValidationError as e:
        messages.error(request, premiere_erreur(e))
    return rediriger_vers_suivant(request, "careers:admin_entreprises")


@admin_required
def admin_signalements(request):
    filtre = request.GET.get("filtre", "a-traiter")
    qs = SignalementOffre.objects.select_related("offre__entreprise", "auteur", "traite_par")
    if filtre == "a-traiter":
        qs = qs.filter(traite=False)
    elif filtre == "traites":
        qs = qs.filter(traite=True)
    page, params = paginer(request, qs, 15)
    return render(request, "careers/admin/signalements.html", {"page": page, "params": params, "filtre": filtre})


@require_POST
@admin_required
def admin_traiter_signalement(request, pk):
    signalement = get_object_or_404(SignalementOffre.objects.select_related("offre"), pk=pk)
    try:
        messages.success(request, services.traiter_signalement(signalement, request.user,
                                                               request.POST.get("decision")))
    except ValidationError as e:
        messages.error(request, premiere_erreur(e))
    return rediriger_vers_suivant(request, "careers:admin_signalements")


@require_POST
@admin_required
def admin_suspendre_offre(request, pk):
    offre = get_object_or_404(Offre, pk=pk)
    services.suspendre_offre(offre)
    messages.success(request, f"L'offre « {offre.titre} » est suspendue.")
    return rediriger_vers_suivant(request, "careers:admin_signalements")


@admin_required
def admin_competences(request):
    form = CompetenceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        competence = form.save()
        messages.success(request, f"Compétence « {competence} » ajoutée au référentiel.")
        return redirect("careers:admin_competences")

    q = request.GET.get("q", "").strip()
    qs = Competence.objects.annotate(nb_offres=Count("exigences", distinct=True),
                                     nb_apprenants=Count("maitrises", distinct=True))
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(alias__icontains=q))
    page, params = paginer(request, qs, 30)
    return render(request, "careers/admin/competences.html", {"page": page, "params": params, "form": form, "q": q})


@admin_required
def admin_competence_modifier(request, pk):
    competence = get_object_or_404(Competence, pk=pk)
    form = CompetenceForm(request.POST or None, instance=competence)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Compétence « {competence} » mise à jour.")
        return redirect("careers:admin_competences")
    return render(request, "careers/admin/competence_form.html", {"form": form, "competence": competence})


@admin_required
def admin_statistiques(request):
    stats = services.statistiques()
    stats["delai_moyen_texte"] = services.formater_duree(stats["delai_moyen"])
    maximum = max((t["nb_offres"] for t in stats["top_competences"]), default=0)
    for t in stats["top_competences"]:
        t["pourcentage"] = round(100 * t["nb_offres"] / maximum) if maximum else 0
    return render(request, "careers/admin/statistiques.html", stats)
