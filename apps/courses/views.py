from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import FileResponse, JsonResponse
import json
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .forms import CoursForm, LessonContentForm, LessonForm, ModuleForm
from .models import Cours, Inscription, Lesson, LessonContent, LessonProgress, Module, ProgressionModule
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
    catalogue = cours_visibles_par(request.user)
    categories = catalogue.exclude(categorie="").values_list("categorie", flat=True).distinct().order_by("categorie")
    query = request.GET.get("q", "").strip()
    niveau = request.GET.get("niveau", "")
    categorie = request.GET.get("categorie", "")
    if query:
        catalogue = catalogue.filter(Q(titre__icontains=query) | Q(description__icontains=query) |
                                     Q(formateur__first_name__icontains=query) | Q(formateur__last_name__icontains=query))
    if niveau in dict(Cours._meta.get_field("niveau").choices):
        catalogue = catalogue.filter(niveau=niveau)
    if categorie:
        catalogue = catalogue.filter(categorie=categorie)
    catalogue = catalogue.annotate(
        nombre_chapitres=Count("modules", distinct=True),
        nombre_lecons=Count("modules__lecons", filter=Q(modules__lecons__est_publiee=True), distinct=True),
    ).order_by("ordre", "titre")
    page = Paginator(catalogue, 9).get_page(request.GET.get("page"))
    cours_inscrits = set()
    progressions = {}
    if request.user.est_apprenant:
        inscriptions = Inscription.objects.filter(
                apprenant=request.user,
                cours_id__in=[cours.pk for cours in page.object_list],
            ).values_list("cours_id", "progression", "derniere_lecon_id")
        cours_inscrits = {cours_id for cours_id, _, _ in inscriptions}
        progressions = {cours_id: progression for cours_id, progression, _ in inscriptions}
        derniere_lecons = {cours_id: lecon_id for cours_id, _, lecon_id in inscriptions}
        reprises_ids = {lecon_id for _, _, lecon_id in inscriptions if lecon_id}
        reprises = {lecon.pk: lecon for lecon in Lesson.objects.filter(pk__in=reprises_ids, est_publiee=True)}
    for cours in page.object_list:
        cours.progression_etudiant = progressions.get(cours.pk, 0)
        cours.reprise_lecon = reprises.get(derniere_lecons.get(cours.pk)) if request.user.est_apprenant else None
    peut_creer = request.user.est_administrateur or (
        request.user.est_formateur and not request.user.en_attente_validation
    )
    return render(request, "courses/index.html", {
        "page": page,
        "cours_inscrits": cours_inscrits,
        "est_apprenant": request.user.est_apprenant,
        "peut_creer": peut_creer,
        "progressions": progressions,
        "q": query,
        "niveau_filtre": niveau,
        "categorie_filtre": categorie,
        "categories": categories,
        "niveaux": Cours._meta.get_field("niveau").choices,
    })


@login_required
def detail(request, pk):
    cours = get_object_or_404(
        cours_visibles_par(request.user).prefetch_related("modules__lecons"),
        pk=pk,
    )
    premiere_lecon = None
    for module in cours.modules.all():
        module.lecons_publiees = [lecon for lecon in module.lecons.all() if lecon.est_publiee]
        module.a_lecons_publiees = bool(module.lecons_publiees)
        if premiere_lecon is None and module.lecons_publiees:
            premiere_lecon = module.lecons_publiees[0]
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
        "lecon_reprise": (inscription.derniere_lecon if inscription and inscription.derniere_lecon_id and inscription.derniere_lecon.est_publiee else premiere_lecon),
        "premiere_lecon": premiere_lecon,
        "peut_gerer": _peut_gerer_cours(request.user, cours),
        "quiz_list": quiz_list,
    })


@login_required
@role_required(User.Role.FORMATEUR)
def cours_creer(request):
    admin = request.user.est_administrateur
    form = CoursForm(request.POST or None, request.FILES or None, administrateur=admin)
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
    form = CoursForm(request.POST or None, request.FILES or None, instance=cours, administrateur=request.user.est_administrateur)
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
    form = ModuleForm(request.POST or None, cours=cours)
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
    form = ModuleForm(request.POST or None, instance=module, cours=module.cours)
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


@login_required
@role_required(User.Role.FORMATEUR)
def lecon_creer(request, module_pk):
    module = _module_a_gerer(request.user, module_pk)
    form = LessonForm(request.POST or None, instance=Lesson(module=module))
    if request.method == "POST" and form.is_valid():
        lecon = form.save(commit=False)
        lecon.module = module
        lecon.save()
        return redirect("courses:lecon_modifier", pk=lecon.pk)
    return render(request, "courses/lecon_form.html", {"form": form, "module": module})


@login_required
@role_required(User.Role.FORMATEUR)
def lecon_modifier(request, pk):
    lecon = get_object_or_404(Lesson.objects.select_related("module", "module__cours"), pk=pk)
    if not _peut_gerer_cours(request.user, lecon.module.cours):
        raise PermissionDenied
    form = LessonForm(request.POST or None, instance=lecon)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("courses:lecon_modifier", pk=lecon.pk)
    return render(request, "courses/lecon_form.html", {"form": form, "lecon": lecon, "module": lecon.module})


@login_required
@role_required(User.Role.FORMATEUR)
def bloc_ajouter(request, lecon_pk):
    lecon = get_object_or_404(Lesson.objects.select_related("module", "module__cours"), pk=lecon_pk)
    if not _peut_gerer_cours(request.user, lecon.module.cours):
        raise PermissionDenied
    form = LessonContentForm(request.POST or None, request.FILES or None, instance=LessonContent(lesson=lecon))
    if request.method == "POST" and form.is_valid():
        bloc = form.save(commit=False)
        bloc.save()
        return redirect("courses:lecon_modifier", pk=lecon.pk)
    return render(request, "courses/bloc_form.html", {"form": form, "lecon": lecon})


@login_required
@role_required(User.Role.FORMATEUR)
def bloc_modifier(request, pk):
    bloc = get_object_or_404(LessonContent.objects.select_related("lesson__module__cours"), pk=pk)
    if not _peut_gerer_cours(request.user, bloc.lesson.module.cours):
        raise PermissionDenied
    form = LessonContentForm(request.POST or None, request.FILES or None, instance=bloc)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("courses:lecon_modifier", pk=bloc.lesson_id)
    return render(request, "courses/bloc_form.html", {"form": form, "lecon": bloc.lesson, "bloc": bloc})


@login_required
@role_required(User.Role.FORMATEUR)
@require_POST
def bloc_supprimer(request, pk):
    bloc = get_object_or_404(LessonContent.objects.select_related("lesson__module__cours"), pk=pk)
    if not _peut_gerer_cours(request.user, bloc.lesson.module.cours):
        raise PermissionDenied
    lecon_id = bloc.lesson_id
    bloc.delete()
    messages.success(request, "Le bloc de contenu a été supprimé.")
    return redirect("courses:lecon_modifier", pk=lecon_id)


@login_required
@role_required(User.Role.FORMATEUR)
@require_POST
def lecon_supprimer(request, pk):
    lecon = get_object_or_404(Lesson.objects.select_related("module__cours"), pk=pk)
    if not _peut_gerer_cours(request.user, lecon.module.cours):
        raise PermissionDenied
    cours_id = lecon.module.cours_id
    lecon.delete()
    messages.success(request, "La leçon et ses blocs ont été supprimés.")
    return redirect("courses:detail", pk=cours_id)


@login_required
def lecon_lire(request, pk):
    lecon = get_object_or_404(
        Lesson.objects.select_related("module", "module__cours").prefetch_related("blocs"), pk=pk
    )
    cours = lecon.module.cours
    if request.user.est_apprenant:
        inscription = get_object_or_404(Inscription, apprenant=request.user, cours=cours)
        if not cours.est_publie or not lecon.est_publiee:
            raise PermissionDenied
        progression_lecon, _ = LessonProgress.objects.get_or_create(inscription=inscription, lesson=lecon)
        progression_lecon.save(update_fields=["derniere_consultation"])
        inscription.derniere_lecon = lecon
        inscription.save(update_fields=["derniere_lecon"])
        recalculer_progression(inscription)
    elif not (request.user.est_administrateur or _peut_gerer_cours(request.user, cours)):
        raise PermissionDenied
    else:
        inscription = None
    lecon_qs = Lesson.objects.filter(module__cours=cours).select_related("module").prefetch_related("blocs").order_by("module__ordre", "ordre", "pk")
    if request.user.est_apprenant:
        lecon_qs = lecon_qs.filter(est_publiee=True)
    lecons = list(lecon_qs)
    chapitres = list(Module.objects.filter(cours=cours).prefetch_related(
        Prefetch("lecons", queryset=lecon_qs.order_by("ordre", "pk")),
    ))
    courante = next((i for i, item in enumerate(lecons) if item.pk == lecon.pk), 0)
    terminees = set(inscription.lecons_terminees.filter(etat=LessonProgress.Etat.TERMINEE).values_list("lesson_id", flat=True)) if inscription else set()
    return render(request, "courses/lecon_lire.html", {
        "lecon": lecon, "cours": cours, "lecons": lecons, "chapitres": chapitres,
        "precedente": lecons[courante - 1] if courante else None,
        "suivante": lecons[courante + 1] if courante + 1 < len(lecons) else None, "position": courante + 1,
        "terminees": terminees, "inscription": inscription,
    })


@login_required
def ressource_lecon(request, pk):
    bloc = get_object_or_404(LessonContent.objects.select_related("lesson__module__cours"), pk=pk)
    cours = bloc.lesson.module.cours
    if request.user.est_apprenant:
        if not bloc.lesson.est_publiee or not Inscription.objects.filter(apprenant=request.user, cours=cours).exists():
            raise PermissionDenied
    elif not (request.user.est_administrateur or _peut_gerer_cours(request.user, cours)):
        raise PermissionDenied
    if not bloc.fichier:
        raise PermissionDenied
    extension = bloc.fichier.name.rsplit(".", 1)[-1].lower()
    content_types = {
        "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "mp4": "video/mp4", "webm": "video/webm",
        "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    inline = extension in {"pdf", "png", "jpg", "jpeg", "webp", "mp4", "webm"}
    response = FileResponse(
        bloc.fichier.open("rb"), as_attachment=not inline,
        filename=bloc.fichier.name.rsplit("/", 1)[-1],
        content_type=content_types.get(extension, "application/octet-stream"),
    )
    response["X-Content-Type-Options"] = "nosniff"
    # Le navigateur PDF est intégré dans une iframe du même site.
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def assistant_lecon(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Corps JSON invalide."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Un objet JSON est attendu."}, status=400)
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        return JsonResponse({"error": "La question doit contenir de 1 à 500 caractères."}, status=400)
    try:
        lecon = Lesson.objects.select_related("module__cours").get(pk=payload.get("lesson_id"))
    except (Lesson.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "Leçon introuvable."}, status=404)
    cours = lecon.module.cours
    if request.user.est_apprenant:
        if not cours.est_publie or not lecon.est_publiee or not Inscription.objects.filter(apprenant=request.user, cours=cours).exists():
            raise PermissionDenied
    elif not (request.user.est_administrateur or _peut_gerer_cours(request.user, cours)):
        raise PermissionDenied
    key = f"lesson-ai:{request.user.pk}"
    count = cache.get(key, 0)
    if count >= 20:
        return JsonResponse({"error": "Limite atteinte : réessayez dans une minute."}, status=429)
    cache.set(key, count + 1, timeout=60)
    from apps.courses.ai_assistant.explainer import build_context, context_is_reliable, explain, REFUS_CONTENU
    from apps.courses.ai_assistant.gemini_service import answer_from_lesson
    from apps.courses.ai_assistant.predict import predict_intent
    context = build_context(lecon)
    if not context_is_reliable(context):
        return JsonResponse({"answer": REFUS_CONTENU,
                             "notice": "Contenu de leçon inexploitable."})
    answer, fallback_reason = answer_from_lesson(question.strip(), context)
    if answer:
        return JsonResponse({"answer": answer,
                             "notice": "Réponse fondée uniquement sur le texte disponible de cette leçon."})
    try:
        intent = predict_intent(question.strip())
    except FileNotFoundError as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except Exception:
        return JsonResponse({"error": "Le modèle de l'assistant est momentanément indisponible."}, status=503)
    if fallback_reason == "missing_key":
        notice = "Service de réponse IA non configuré ; réponse de secours utilisée."
    elif fallback_reason in {"ResourceExhausted", "TooManyRequests", "RateLimitError"}:
        notice = "Limite du service de réponse atteinte ; réponse de secours utilisée."
    elif fallback_reason in {"APIKeyError", "PermissionDenied", "ClientError"}:
        notice = "Service de réponse temporairement indisponible ; réponse de secours utilisée."
    elif fallback_reason in {"APIConnectionError", "TimeoutError", "ConnectError"}:
        notice = "Connexion au service de réponse impossible ; réponse de secours utilisée."
    else:
        notice = "Une réponse de secours a été utilisée."
    return JsonResponse({"answer": explain(intent, question.strip(), context), "intent": intent,
                         "notice": notice})


@login_required
@require_POST
def lecon_terminer(request, pk):
    if not request.user.est_apprenant:
        raise PermissionDenied
    lecon = get_object_or_404(Lesson.objects.select_related("module__cours"), pk=pk, est_publiee=True)
    inscription = get_object_or_404(Inscription, apprenant=request.user, cours=lecon.module.cours)
    progression, _ = LessonProgress.objects.get_or_create(inscription=inscription, lesson=lecon)
    if progression.etat != LessonProgress.Etat.TERMINEE:
        progression.etat = LessonProgress.Etat.TERMINEE
        progression.date_terminaison = timezone.now()
        progression.save(update_fields=["etat", "date_terminaison", "derniere_consultation"])
    recalculer_progression(inscription)
    delivrer_certificat_si_eligible(inscription)
    messages.success(request, f"Leçon « {lecon.titre} » marquée comme terminée.")
    return redirect("courses:lecon_lire", pk=pk)
