"""Vues du module Quiz et correction IA.

Formateur : créer, modifier, supprimer des quiz, gérer les questions, voir les résultats.
Apprenant : parcourir les quiz publiés, passer un quiz, consulter ses tentatives.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q
from django.http import Http404
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
    if request.user.est_formateur or request.user.est_administrateur:
        quiz_list = Quiz.objects.filter(formateur=request.user).annotate(
            nb_questions=Count("questions"),
            nb_tentatives=Count("tentatives", filter=Q(tentatives__terminee=True)),
        )
        template = "quizzes/index_formateur.html"
    else:
        quiz_list = Quiz.objects.filter(est_publie=True).annotate(
            nb_questions=Count("questions"),
        )
        template = "quizzes/index_apprenant.html"

    return render(request, template, {"quiz_list": quiz_list})


# ──────────────────────────────────────────────
# Formateur — CRUD Quiz
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR)
def quiz_creer(request):
    if request.method == "POST":
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.formateur = request.user
            quiz.save()
            messages.success(request, f"Quiz « {quiz.titre} » créé. Ajoutez maintenant des questions.")
            return redirect("quizzes:questions_gerer", pk=quiz.pk)
    else:
        form = QuizForm()
    return render(request, "quizzes/quiz_form.html", {"form": form, "creation": True})


@login_required
def quiz_detail(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
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


@role_required(User.Role.FORMATEUR)
def quiz_modifier(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
    if request.method == "POST":
        form = QuizForm(request.POST, instance=quiz)
        if form.is_valid():
            form.save()
            messages.success(request, "Quiz mis à jour.")
            return redirect("quizzes:quiz_detail", pk=quiz.pk)
    else:
        form = QuizForm(instance=quiz)
    return render(request, "quizzes/quiz_form.html", {"form": form, "quiz": quiz, "creation": False})


@role_required(User.Role.FORMATEUR)
def quiz_supprimer(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
    if request.method == "POST":
        titre = quiz.titre
        quiz.delete()
        messages.success(request, f"Quiz « {titre} » supprimé.")
        return redirect("quizzes:index")
    return render(request, "quizzes/quiz_confirm_delete.html", {"quiz": quiz})


# ──────────────────────────────────────────────
# Formateur — Gestion des questions
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR)
def questions_gerer(request, pk):
    """Page de gestion des questions d'un quiz (ajout, modification, suppression)."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
    questions = quiz.questions.prefetch_related("choix").all()
    return render(request, "quizzes/questions_gerer.html", {"quiz": quiz, "questions": questions})


@role_required(User.Role.FORMATEUR)
def question_ajouter(request, pk):
    """Ajouter une question à un quiz."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)

    if request.method == "POST":
        form = QuestionForm(request.POST)
        formset = ChoixFormSet(request.POST, prefix="choix")

        if form.is_valid():
            question = form.save(commit=False)
            question.quiz = quiz
            if not question.ordre:
                question.ordre = quiz.questions.count() + 1
            question.save()

            # Les choix ne sont pertinents que pour QCM et Vrai/Faux
            if question.type in (Question.Type.QCM, Question.Type.VRAI_FAUX):
                formset = ChoixFormSet(request.POST, prefix="choix", instance=question)
                if formset.is_valid():
                    formset.save()
                else:
                    # Si les choix sont invalides, supprimer la question créée
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


@role_required(User.Role.FORMATEUR)
def question_modifier(request, pk, question_pk):
    """Modifier une question existante."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
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
                # Supprimer les choix si on change le type vers texte libre
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


@role_required(User.Role.FORMATEUR)
def question_supprimer(request, pk, question_pk):
    """Supprimer une question."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
    question = get_object_or_404(Question, pk=question_pk, quiz=quiz)

    if request.method == "POST":
        question.delete()
        messages.success(request, "Question supprimée.")
        return redirect("quizzes:questions_gerer", pk=quiz.pk)

    return render(request, "quizzes/question_confirm_delete.html", {
        "quiz": quiz, "question": question,
    })


# ──────────────────────────────────────────────
# Formateur — Résultats
# ──────────────────────────────────────────────

@role_required(User.Role.FORMATEUR)
def quiz_resultats(request, pk):
    """Résultats d'un quiz : liste des tentatives, statistiques."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
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
# Apprenant — Passer un quiz
# ──────────────────────────────────────────────

@role_required(User.Role.APPRENANT)
def passer_quiz(request, pk):
    """Page où l'apprenant répond aux questions du quiz."""
    quiz = get_object_or_404(Quiz, pk=pk, est_publie=True)
    questions = quiz.questions.prefetch_related("choix").all()

    if not questions.exists():
        messages.warning(request, "Ce quiz ne contient aucune question.")
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

        messages.success(request, "Quiz terminé ! Voici vos résultats.")
        return redirect("quizzes:tentative_detail", pk=tentative.pk)

    return render(request, "quizzes/passer_quiz.html", {"quiz": quiz, "questions": questions})


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


@role_required(User.Role.FORMATEUR)
def quiz_generer_ia(request, pk):
    """Génération assistée par IA de nouvelles questions pour un quiz."""
    quiz = get_object_or_404(Quiz, pk=pk, formateur=request.user)
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
