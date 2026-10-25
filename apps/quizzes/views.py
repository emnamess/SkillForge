"""Vues du module Quiz et correction IA.

Formateur : créer, modifier, supprimer des quiz, gérer les questions, voir les résultats.
Apprenant : parcourir les quiz publiés, passer un quiz, consulter ses tentatives.
"""

import csv
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .forms import ChoixFormSet, QuestionForm, QuizForm
from .models import Choix, Question, Quiz, Reponse, Tentative
from .services import corriger_tentative


# ──────────────────────────────────────────────
# Pages communes
# ──────────────────────────────────────────────

@login_required
def index(request):
    """Page principale : liste des quiz selon le rôle."""
    if request.user.est_administrateur:
        quiz_list = Quiz.objects.annotate(
            nb_questions=Count("questions", distinct=True),
            nb_tentatives=Count("tentatives", filter=Q(tentatives__terminee=True), distinct=True),
        )
        template = "quizzes/index_formateur.html"
    elif request.user.est_formateur:
        quiz_list = Quiz.objects.filter(formateur=request.user).annotate(
            nb_questions=Count("questions", distinct=True),
            nb_tentatives=Count("tentatives", filter=Q(tentatives__terminee=True), distinct=True),
        )
        template = "quizzes/index_formateur.html"
    else:
        quiz_list = Quiz.objects.filter(est_publie=True).annotate(
            nb_questions=Count("questions", distinct=True),
        ).filter(
            Q(cours__isnull=True) | Q(cours__inscriptions__apprenant=request.user)
        ).distinct()
        template = "quizzes/index_apprenant.html"

    return render(request, template, {"quiz_list": quiz_list})


def _get_quiz_formateur_ou_admin(request, pk):
    """Récupère un quiz si l'utilisateur est administrateur ou formateur propriétaire."""
    if request.user.est_administrateur:
        return get_object_or_404(Quiz, pk=pk)
    return get_object_or_404(Quiz, pk=pk, formateur=request.user)


# ──────────────────────────────────────────────
# Formateur — CRUD Quiz
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR)
def quiz_creer(request):
    if request.method == "POST":
        form = QuizForm(request.POST, formateur=request.user)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.formateur = request.user
            quiz.save()
            messages.success(request, f"Quiz « {quiz.titre} » créé. Ajoutez maintenant des questions.")
            return redirect("quizzes:questions_gerer", pk=quiz.pk)
    else:
        form = QuizForm(
            initial={"cours": request.GET.get("cours")},
            formateur=request.user,
        )
    return render(request, "quizzes/quiz_form.html", {"form": form, "creation": True})


@login_required
def quiz_detail(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if request.user.est_apprenant and quiz.cours_id and not quiz.cours.inscriptions.filter(
        apprenant=request.user
    ).exists():
        raise Http404
    # Un quiz non publié n'est visible que par son formateur
    if not quiz.est_publie and quiz.formateur != request.user and not request.user.est_administrateur:
        raise Http404

    questions = quiz.questions.prefetch_related("choix").all()

    # Tentatives de l'apprenant sur ce quiz
    tentatives = []
    if request.user.est_apprenant:
        tentatives = Tentative.objects.filter(quiz=quiz, apprenant=request.user, terminee=True)

    context = {
        "quiz": quiz,
        "questions": questions,
        "tentatives": tentatives,
    }
    return render(request, "quizzes/quiz_detail.html", context)


@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def quiz_modifier(request, pk):
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    if request.method == "POST":
        form = QuizForm(request.POST, instance=quiz, formateur=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Quiz mis à jour.")
            return redirect("quizzes:quiz_detail", pk=quiz.pk)
    else:
        form = QuizForm(instance=quiz, formateur=request.user)
    return render(request, "quizzes/quiz_form.html", {"form": form, "quiz": quiz, "creation": False})


@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def quiz_supprimer(request, pk):
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    if request.method == "POST":
        titre = quiz.titre
        quiz.delete()
        messages.success(request, f"Quiz « {titre} » supprimé.")
        return redirect("quizzes:index")
    return render(request, "quizzes/quiz_confirm_delete.html", {"quiz": quiz})


# ──────────────────────────────────────────────
# Formateur / Admin — Gestion des questions
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def questions_gerer(request, pk):
    """Page de gestion des questions d'un quiz (ajout, modification, suppression)."""
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    questions = quiz.questions.prefetch_related("choix").all()
    return render(request, "quizzes/questions_gerer.html", {"quiz": quiz, "questions": questions})


@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def question_ajouter(request, pk):
    """Ajouter une question à un quiz."""
    quiz = _get_quiz_formateur_ou_admin(request, pk)

    if request.method == "POST":
        form = QuestionForm(request.POST)
        formset = ChoixFormSet(request.POST, prefix="choix")

        if form.is_valid():
            question = form.save(commit=False)
            question.quiz = quiz
            if not question.ordre:
                question.ordre = quiz.questions.count() + 1
            question.save()

            if question.type in (Question.Type.QCM, Question.Type.VRAI_FAUX):
                formset = ChoixFormSet(request.POST, prefix="choix", instance=question)
                if formset.is_valid():
                    formset.save()
                else:
                    question.delete()
                    messages.error(request, "Erreur dans les choix de réponse.")
                    return render(request, "quizzes/question_form.html", {
                        "form": form, "formset": formset, "quiz": quiz, "creation": True,
                    })

            messages.success(request, "Question ajoutée.")
            return redirect("quizzes:questions_gerer", pk=quiz.pk)
    else:
        form = QuestionForm(initial={"ordre": quiz.questions.count() + 1})
        formset = ChoixFormSet(prefix="choix")

    return render(request, "quizzes/question_form.html", {
        "form": form, "formset": formset, "quiz": quiz, "creation": True,
    })


@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def question_modifier(request, pk, question_pk):
    """Modifier une question existante."""
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    question = get_object_or_404(Question, pk=question_pk, quiz=quiz)

    if request.method == "POST":
        form = QuestionForm(request.POST, instance=question)
        formset = ChoixFormSet(request.POST, prefix="choix", instance=question)

        if form.is_valid():
            question = form.save()
            if question.type in (Question.Type.QCM, Question.Type.VRAI_FAUX):
                if formset.is_valid():
                    formset.save()
                else:
                    messages.error(request, "Erreur dans les choix de réponse.")
                    return render(request, "quizzes/question_form.html", {
                        "form": form, "formset": formset, "quiz": quiz,
                        "question": question, "creation": False,
                    })
            else:
                question.choix.all().delete()

            messages.success(request, "Question mise à jour.")
            return redirect("quizzes:questions_gerer", pk=quiz.pk)
    else:
        form = QuestionForm(instance=question)
        formset = ChoixFormSet(prefix="choix", instance=question)

    return render(request, "quizzes/question_form.html", {
        "form": form, "formset": formset, "quiz": quiz,
        "question": question, "creation": False,
    })


@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def question_supprimer(request, pk, question_pk):
    """Supprimer une question."""
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    question = get_object_or_404(Question, pk=question_pk, quiz=quiz)

    if request.method == "POST":
        question.delete()
        messages.success(request, "Question supprimée.")
        return redirect("quizzes:questions_gerer", pk=quiz.pk)

    return render(request, "quizzes/question_confirm_delete.html", {
        "quiz": quiz, "question": question,
    })


# ──────────────────────────────────────────────
# Formateur / Admin — Résultats
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def quiz_resultats(request, pk):
    """Résultats d'un quiz : liste des tentatives, statistiques."""
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    tentatives = Tentative.objects.filter(quiz=quiz, terminee=True).select_related("apprenant")

    stats = tentatives.aggregate(
        moyenne=Avg("pourcentage"),
        nb_tentatives=Count("pk"),
        nb_reussies=Count("pk", filter=Q(reussie=True)),
    )
    stats["taux_reussite"] = (
        round(stats["nb_reussies"] / stats["nb_tentatives"] * 100)
        if stats["nb_tentatives"] > 0
        else 0
    )

    return render(request, "quizzes/quiz_resultats.html", {
        "quiz": quiz,
        "tentatives": tentatives,
        "stats": stats,
    })


# ──────────────────────────────────────────────
# Passer un quiz (Apprenant, ou Formateur/Admin en test)
# ──────────────────────────────────────────────

@login_required
def passer_quiz(request, pk):
    """Page où l'apprenant (ou l'administrateur/formateur) répond aux questions du quiz."""
    # Les administrateurs et formateurs peuvent tester leur propre quiz même non publié
    if request.user.est_administrateur or (request.user.est_formateur and Quiz.objects.filter(pk=pk, formateur=request.user).exists()):
        quiz = get_object_or_404(Quiz, pk=pk)
    else:
        quiz = get_object_or_404(Quiz, pk=pk, est_publie=True)

    if request.user.est_apprenant and quiz.cours_id and not quiz.cours.inscriptions.filter(
        apprenant=request.user
    ).exists():
        raise Http404

    questions = quiz.questions.prefetch_related("choix").all()

    if not questions.exists():
        messages.warning(request, "Ce quiz ne contient aucune question pour le moment.")
        return redirect("quizzes:quiz_detail", pk=quiz.pk)

    if request.method == "POST":
        # Créer la tentative
        tentative = Tentative.objects.create(quiz=quiz, apprenant=request.user)

        for question in questions:
            reponse = Reponse(tentative=tentative, question=question)

            if question.type in (Question.Type.QCM, Question.Type.VRAI_FAUX):
                choix_id = request.POST.get(f"question_{question.pk}")
                if choix_id:
                    try:
                        choix = Choix.objects.get(pk=choix_id, question=question)
                        reponse.choix_selectionne = choix
                    except Choix.DoesNotExist:
                        pass
            elif question.type == Question.Type.TEXTE_LIBRE:
                reponse.texte_libre = request.POST.get(f"question_{question.pk}", "")

            reponse.save()

        # Corriger la tentative (QCM + IA)
        corriger_tentative(tentative)

        if request.user.est_apprenant and quiz.cours_id:
            from apps.courses.models import Inscription
            from apps.courses.services import delivrer_certificat_si_eligible

            inscription = Inscription.objects.filter(
                apprenant=request.user, cours_id=quiz.cours_id
            ).select_related("apprenant", "cours").first()
            if inscription:
                certificat = delivrer_certificat_si_eligible(inscription)
                if certificat:
                    messages.success(request, "Votre certificat de cours est maintenant disponible.")

        messages.success(request, "Quiz terminé ! Voici vos résultats.")
        return redirect("quizzes:tentative_detail", pk=tentative.pk)

    questions_affichage = list(questions)
    if quiz.melanger_questions:
        random.shuffle(questions_affichage)

    return render(request, "quizzes/passer_quiz.html", {"quiz": quiz, "questions": questions_affichage})


# ──────────────────────────────────────────────
# Apprenant / Formateur — Détail d'une tentative
# ──────────────────────────────────────────────

@login_required
def tentative_detail(request, pk):
    """Détail d'une tentative avec les réponses et corrections."""
    tentative = get_object_or_404(
        Tentative.objects.select_related("quiz", "apprenant"),
        pk=pk,
    )

    # Seul l'apprenant ou le formateur du quiz peut voir la tentative
    if (
        tentative.apprenant != request.user
        and tentative.quiz.formateur != request.user
        and not request.user.est_administrateur
    ):
        raise Http404

    reponses = tentative.reponses.select_related(
        "question", "choix_selectionne"
    ).prefetch_related("question__choix").all()

    return render(request, "quizzes/tentative_detail.html", {
        "tentative": tentative,
        "reponses": reponses,
    })


@role_required(User.Role.APPRENANT)
def mes_tentatives(request):
    """Historique des tentatives de l'apprenant."""
    tentatives = Tentative.objects.filter(
        apprenant=request.user, terminee=True
    ).select_related("quiz")

    return render(request, "quizzes/mes_tentatives.html", {"tentatives": tentatives})


@role_required(User.Role.FORMATEUR, User.Role.ADMINISTRATEUR)
def quiz_generer_ia(request, pk):
    """Génération assistée par IA de nouvelles questions pour un quiz."""
    quiz = _get_quiz_formateur_ou_admin(request, pk)
    if request.method == "POST":
        theme = request.POST.get("theme", "").strip() or quiz.titre
        niveau = request.POST.get("niveau", "Intermédiaire")
        nb = min(max(int(request.POST.get("nombre", 3)), 1), 5)
        try:
            from .services import generer_questions_par_ia
            creees, source = generer_questions_par_ia(quiz, theme, niveau=niveau, nombre=nb)
            if source == "gemini":
                messages.success(request, f"✨ {len(creees)} questions générées avec succès par Google Gemini !")
            else:
                messages.success(request, f"✨ {len(creees)} questions générées pour le thème « {theme} » !")
            return redirect("quizzes:questions_gerer", pk=quiz.pk)
        except Exception as e:
            messages.error(request, f"Échec de la génération : {e}")

    return render(request, "quizzes/quiz_generer_ia.html", {"quiz": quiz})


@login_required
def tentative_recorriger(request, pk):
    """Permet de forcer la réévaluation par l'IA des réponses libres d'une tentative."""
    tentative = get_object_or_404(Tentative, pk=pk)
    if (
        tentative.apprenant != request.user
        and tentative.quiz.formateur != request.user
        and not request.user.est_administrateur
    ):
        raise Http404

    from .services import recorriger_tentative
    recorriger_tentative(tentative)
    messages.success(request, "✨ Les réponses libres ont été recorrigées par l'IA !")
    return redirect("quizzes:tentative_detail", pk=tentative.pk)


# ──────────────────────────────────────────────
# Formateur — Export CSV
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR)
def quiz_export_csv(request, pk):
    """Exporte les résultats d'un quiz au format CSV compatible Excel."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
    tentatives = Tentative.objects.filter(quiz=quiz, terminee=True).select_related("apprenant").order_by("-date_debut")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="resultats_quiz_{quiz.pk}_{timezone.now():%Y%m%d}.csv"'

    response.write("\ufeff")  # BOM UTF-8 pour Excel
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Nom", "Prénom", "Nom d'utilisateur", "Email", "Date", "Score", "Total", "Pourcentage", "Statut"])

    for t in tentatives:
        writer.writerow([
            t.apprenant.last_name or "—",
            t.apprenant.first_name or "—",
            t.apprenant.username,
            t.apprenant.email,
            t.date_debut.strftime("%d/%m/%Y %H:%M"),
            f"{t.score}",
            f"{t.score_total}",
            f"{t.pourcentage}%",
            "Réussi" if t.reussie else "Non réussi",
        ])

    return response


# ──────────────────────────────────────────────
# Admin — Supervision globale des Quiz
# ──────────────────────────────────────────────

@role_required(User.Role.ADMINISTRATEUR)
def supervision_admin(request):
    """Tableau de bord de supervision globale des Quiz pour l'administrateur."""
    quizzes = Quiz.objects.select_related("formateur").annotate(
        nb_q=Count("questions", distinct=True),
        nb_t=Count("tentatives", filter=Q(tentatives__terminee=True), distinct=True),
        moyenne=Avg("tentatives__pourcentage", filter=Q(tentatives__terminee=True)),
    ).order_by("-date_creation")

    stats = {
        "nb_quiz": Quiz.objects.count(),
        "nb_publies": Quiz.objects.filter(est_publie=True).count(),
        "nb_questions": Question.objects.count(),
        "nb_qcm": Question.objects.filter(type=Question.Type.QCM).count(),
        "nb_texte_libre": Question.objects.filter(type=Question.Type.TEXTE_LIBRE).count(),
        "nb_tentatives": Tentative.objects.filter(terminee=True).count(),
        "nb_corrections_ia": Reponse.objects.filter(question__type=Question.Type.TEXTE_LIBRE, corrigee=True).count(),
        "taux_reussite_global": Tentative.objects.filter(terminee=True).aggregate(t=Avg("pourcentage"))["t"] or 0,
    }

    top_quiz = quizzes.order_by("-nb_t")[:5]
    dernieres_tentatives = Tentative.objects.filter(terminee=True).select_related(
        "quiz", "apprenant"
    ).order_by("-date_debut")[:10]

    return render(request, "quizzes/supervision_admin.html", {
        "quizzes": quizzes,
        "stats": stats,
        "top_quiz": top_quiz,
        "dernieres_tentatives": dernieres_tentatives,
    })


@role_required(User.Role.ADMINISTRATEUR, User.Role.FORMATEUR)
def quiz_toggle_publication(request, pk):
    """Bascule rapide entre Publié et Brouillon (modération en 1 clic)."""
    if request.user.est_administrateur:
        quiz = get_object_or_404(Quiz, pk=pk)
    else:
        quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)

    quiz.est_publie = not quiz.est_publie
    quiz.save(update_fields=["est_publie"])
    etat = "publié ✅" if quiz.est_publie else "dépublié (brouillon) ⏸️"
    messages.success(request, f"Le quiz « {quiz.titre} » est désormais {etat}.")

    next_url = request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect("quizzes:index")


# ──────────────────────────────────────────────
# Apprenant — Révision des erreurs & Attestation
# ──────────────────────────────────────────────

@role_required(User.Role.APPRENANT)
def mes_erreurs(request):
    """Espace d'entraînement ciblé : récapitulatif des erreurs pour progresser."""
    reponses_ratees = (
        Reponse.objects.filter(
            tentative__apprenant=request.user,
            tentative__terminee=True,
            corrigee=True,
        )
        .filter(Q(est_correcte=False) | Q(points_obtenus__lt=F("question__points")))
        .select_related("question", "question__quiz", "choix_selectionne")
        .prefetch_related("question__choix")
        .order_by("-tentative__date_debut")
    )

    return render(request, "quizzes/mes_erreurs.html", {
        "reponses_ratees": reponses_ratees,
    })


@login_required
def attestation_reussite(request, pk):
    """Attestation de réussite imprimable pour toute tentative validée."""
    tentative = get_object_or_404(
        Tentative.objects.select_related("quiz", "quiz__formateur", "apprenant"),
        pk=pk,
        terminee=True,
    )
    if not tentative.reussie:
        messages.warning(request, "L'attestation n'est accessible que pour un quiz réussi.")
        return redirect("quizzes:tentative_detail", pk=tentative.pk)

    if (
        tentative.apprenant != request.user
        and not request.user.est_administrateur
        and tentative.quiz.formateur != request.user
    ):
        raise Http404

    return render(request, "quizzes/attestation.html", {
        "tentative": tentative,
    })
