from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .forms import CoursForm, ModuleForm
from .models import Cours, Inscription, Module, ProgressionModule
from .services import (
    delivrer_certificat_si_eligible,
    recalculer_progression,
    recalculer_progressions_cours,
)


def cours_visibles_par(user):
    cours = Cours.objects.select_related("formateur")
    if user.est_administrateur:
        return cours
    if user.est_formateur:
        return cours.filter(Q(est_publie=True) | Q(formateur=user))
    # Un cours dépublié n'accepte plus de nouvelles inscriptions, mais reste accessible
    # aux apprenants déjà inscrits afin qu'ils puissent poursuivre leur parcours.
    return cours.filter(Q(est_publie=True) | Q(inscriptions__apprenant=user)).distinct()


def _peut_gerer_cours(user, cours):
    return user.est_administrateur or (
        user.est_formateur and not user.en_attente_validation and cours.formateur_id == user.pk
    )


def _cours_a_gerer(user, pk):
    if user.est_administrateur:
        return get_object_or_404(Cours, pk=pk)
    if user.est_formateur and not user.en_attente_validation:
        return get_object_or_404(Cours, pk=pk, formateur=user)
    raise PermissionDenied


def _module_a_gerer(user, pk):
    if user.est_administrateur:
        return get_object_or_404(Module.objects.select_related("cours", "cours__formateur"), pk=pk)
    if user.est_formateur and not user.en_attente_validation:
        return get_object_or_404(
            Module.objects.select_related("cours", "cours__formateur"),
            pk=pk,
            cours__formateur=user,
        )
    raise PermissionDenied


@login_required
def index(request):
    page = Paginator(cours_visibles_par(request.user), 9).get_page(request.GET.get("page"))
    cours_inscrits = set()
    if request.user.est_apprenant:
        cours_inscrits = set(
            Inscription.objects.filter(
                apprenant=request.user,
                cours_id__in=[cours.pk for cours in page.object_list],
            ).values_list("cours_id", flat=True)
        )
    peut_creer = request.user.est_administrateur or (
        request.user.est_formateur and not request.user.en_attente_validation
    )
    return render(request, "courses/index.html", {
        "page": page,
        "cours_inscrits": cours_inscrits,
        "est_apprenant": request.user.est_apprenant,
        "peut_creer": peut_creer,
    })


@login_required
def detail(request, pk):
    cours = get_object_or_404(
        cours_visibles_par(request.user).prefetch_related("modules"),
        pk=pk,
    )
    inscription = None
    progression_modules = set()
    if request.user.est_apprenant:
        inscription = Inscription.objects.filter(apprenant=request.user, cours=cours).first()
        if inscription:
            progression_modules = set(
                inscription.modules_termines.values_list("module_id", flat=True)
            )

    quiz_list = []
    if request.user.est_administrateur or _peut_gerer_cours(request.user, cours):
        quiz_list = cours.quiz.select_related("formateur").all()
    elif inscription:
        quiz_list = cours.quiz.filter(est_publie=True).select_related("formateur")

    return render(request, "courses/detail.html", {
        "cours": cours,
        "est_apprenant": request.user.est_apprenant,
        "est_inscrit": inscription is not None,
        "inscription": inscription,
        "progression_modules": progression_modules,
        "peut_gerer": _peut_gerer_cours(request.user, cours),
        "quiz_list": quiz_list,
    })


@login_required
@role_required(User.Role.FORMATEUR)
def cours_creer(request):
    admin = request.user.est_administrateur
    form = CoursForm(request.POST or None, administrateur=admin)
    if request.method == "POST" and form.is_valid():
        cours = form.save(commit=False)
        cours.formateur = form.cleaned_data["formateur"] if admin else request.user
        cours.save()
        messages.success(request, f"Le cours « {cours.titre} » a été créé.")
        return redirect("courses:detail", pk=cours.pk)
    return render(request, "courses/cours_form.html", {"form": form, "creation": True})


@login_required
@role_required(User.Role.FORMATEUR)
def cours_modifier(request, pk):
    cours = _cours_a_gerer(request.user, pk)
    form = CoursForm(request.POST or None, instance=cours, administrateur=request.user.est_administrateur)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Le cours « {cours.titre} » a été mis à jour.")
        return redirect("courses:detail", pk=cours.pk)
    return render(request, "courses/cours_form.html", {"form": form, "cours": cours, "creation": False})


@login_required
@role_required(User.Role.FORMATEUR)
@require_POST
def cours_publication(request, pk):
    cours = _cours_a_gerer(request.user, pk)
    cours.est_publie = not cours.est_publie
    cours.save(update_fields=["est_publie", "date_modification"])
    etat = "publié" if cours.est_publie else "dépublié"
    messages.success(request, f"Le cours « {cours.titre} » a été {etat}.")
    return redirect("courses:detail", pk=cours.pk)


@login_required
@role_required(User.Role.FORMATEUR)
@require_http_methods(["GET", "POST"])
def cours_supprimer(request, pk):
    cours = _cours_a_gerer(request.user, pk)
    if request.method == "POST":
        titre = cours.titre
        cours.delete()
        messages.warning(
            request,
            f"Le cours « {titre} » et ses modules, inscriptions et suivis ont été supprimés. "
            "Les quiz associés sont conservés sans cours ; les certificats conservent leur copie du titre.",
        )
        return redirect("courses:index")
    return render(request, "courses/cours_confirm_delete.html", {"cours": cours})


@login_required
@role_required(User.Role.FORMATEUR)
def module_creer(request, cours_pk):
    cours = _cours_a_gerer(request.user, cours_pk)
    form = ModuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        module = form.save(commit=False)
        module.cours = cours
        module.save()
        recalculer_progressions_cours(cours)
        messages.success(request, f"Le module « {module.titre} » a été ajouté.")
        return redirect("courses:detail", pk=cours.pk)
    return render(request, "courses/module_form.html", {"form": form, "cours": cours, "creation": True})


@login_required
@role_required(User.Role.FORMATEUR)
def module_modifier(request, pk):
    module = _module_a_gerer(request.user, pk)
    form = ModuleForm(request.POST or None, instance=module)
    if request.method == "POST" and form.is_valid():
        contenu_modifie = bool({"titre", "description", "contenu"} & set(form.changed_data))
        with transaction.atomic():
            if contenu_modifie:
                ProgressionModule.objects.filter(module=module).delete()
            form.save()
            if contenu_modifie:
                recalculer_progressions_cours(module.cours)
        if contenu_modifie:
            messages.warning(
                request,
                "Le contenu pédagogique a changé : les validations de ce module ont été réinitialisées "
                "et les progressions recalculées.",
            )
        else:
            messages.success(request, f"Le module « {module.titre} » a été mis à jour.")
        return redirect("courses:detail", pk=module.cours_id)
    return render(request, "courses/module_form.html", {
        "form": form, "cours": module.cours, "module": module, "creation": False,
    })


@login_required
@role_required(User.Role.FORMATEUR)
@require_http_methods(["GET", "POST"])
def module_supprimer(request, pk):
    module = _module_a_gerer(request.user, pk)
    cours = module.cours
    if request.method == "POST":
        titre = module.titre
        module.delete()
        recalculer_progressions_cours(cours)
        messages.success(request, f"Le module « {titre} » a été supprimé et les progressions recalculées.")
        return redirect("courses:detail", pk=cours.pk)
    return render(request, "courses/module_confirm_delete.html", {"module": module})


@login_required
@require_POST
def inscrire(request, pk):
    if not request.user.est_apprenant:
        raise PermissionDenied

    cours = get_object_or_404(Cours, pk=pk)
    if not cours.est_publie:
        messages.error(request, "Ce cours n’est pas disponible à l’inscription.")
        return redirect("courses:index")

    _, creee = Inscription.objects.get_or_create(apprenant=request.user, cours=cours)
    if creee:
        messages.success(request, f"Vous êtes inscrit au cours « {cours.titre} ».")
    else:
        messages.info(request, f"Vous êtes déjà inscrit au cours « {cours.titre} ».")
    return redirect("courses:detail", pk=cours.pk)


@login_required
@require_POST
def module_terminer(request, pk):
    if not request.user.est_apprenant:
        raise PermissionDenied

    module = get_object_or_404(Module.objects.select_related("cours"), pk=pk)
    inscription = get_object_or_404(
        Inscription.objects.select_related("cours", "apprenant"),
        apprenant=request.user,
        cours=module.cours,
    )
    with transaction.atomic():
        ProgressionModule.objects.get_or_create(inscription=inscription, module=module)
        recalculer_progression(inscription)
    certificat = delivrer_certificat_si_eligible(inscription)
    if certificat:
        messages.success(request, "Module terminé. Votre progression est à 100 % et votre certificat est disponible.")
    else:
        messages.success(request, f"Module « {module.titre} » marqué comme terminé.")
    return redirect("courses:detail", pk=module.cours_id)


@login_required
def mes_cours(request):
    if not request.user.est_apprenant:
        raise PermissionDenied
    inscriptions = Inscription.objects.filter(apprenant=request.user).select_related(
        "cours", "cours__formateur"
    )
    return render(request, "courses/mes_cours.html", {"inscriptions": inscriptions})
