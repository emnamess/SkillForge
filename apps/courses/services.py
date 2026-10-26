from django.db.models import Avg

from .models import Inscription, Module, ProgressionModule


def recalculer_progression(inscription):
    """Calcule à partir des leçons publiées ; conserve le mode historique sinon."""
    from .models import Lesson, LessonProgress

    cours_lecons = Lesson.objects.filter(module__cours_id=inscription.cours_id)
    lecons = cours_lecons.filter(est_publiee=True)
    nombre_lecons = lecons.count()
    if nombre_lecons:
        terminees = LessonProgress.objects.filter(
            inscription=inscription, lesson__in=lecons, etat=LessonProgress.Etat.TERMINEE,
        ).count()
        progression = (terminees * 100) // nombre_lecons
    elif not cours_lecons.exists():
        nombre_modules = Module.objects.filter(cours_id=inscription.cours_id).count()
        if nombre_modules:
            modules_termines = ProgressionModule.objects.filter(
                inscription=inscription,
                module__cours_id=inscription.cours_id,
            ).count()
            progression = (modules_termines * 100) // nombre_modules
        else:
            progression = 0
    else:
        # Un cours structuré mais sans leçon publiée n'est pas terminé.
        progression = 0

    if inscription.progression != progression:
        inscription.progression = progression
        inscription.save(update_fields=["progression"])
    return inscription


def recalculer_progressions_cours(cours):
    """Met à jour les inscriptions après un changement de structure du cours."""
    for inscription in Inscription.objects.filter(cours=cours).select_related("cours", "apprenant"):
        recalculer_progression(inscription)


def score_moyen_quiz(inscription):
    """Moyenne des pourcentages des tentatives terminées sur les quiz associés au cours."""
    from apps.quizzes.models import Tentative

    return Tentative.objects.filter(
        apprenant=inscription.apprenant,
        quiz__cours=inscription.cours,
        terminee=True,
        pourcentage__isnull=False,
    ).aggregate(moyenne=Avg("pourcentage"))["moyenne"]


def delivrer_certificat_si_eligible(inscription):
    """Délivre via le service existant si progression complète et score de quiz disponible."""
    if inscription.progression < 100:
        return None
    score = score_moyen_quiz(inscription)
    if score is None:
        # Le service certificats autorise un score absent ; ici le contrat SkillForge
        # prévoit un score moyen aux quiz, on attend donc au moins une tentative corrigée.
        return None

    from apps.certificates.services import delivrer_si_eligible

    return delivrer_si_eligible(
        inscription.apprenant,
        inscription.cours.titre,
        progression=inscription.progression,
        score=int(round(score)),
        formateur=inscription.cours.formateur,
    )
