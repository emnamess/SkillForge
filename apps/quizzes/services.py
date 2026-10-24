"""Correction IA des réponses libres via Google Gemini.

    from apps.quizzes.services import corriger_reponse_libre, corriger_tentative

    # Corriger une seule réponse texte libre
    corriger_reponse_libre(reponse)

    # Corriger toute une tentative (QCM + texte libre)
    corriger_tentative(tentative)
"""

import functools
import json
import logging
import os
import re

from django.conf import settings
from django.utils import timezone

from .models import Question, Reponse

logger = logging.getLogger(__name__)

CONSIGNES_CORRECTION = """\
Tu es un correcteur pédagogique sur SkillForge, une plateforme e-learning.
Tu corriges la réponse libre d'un apprenant à une question de quiz.

Tu reçois :
- L'énoncé de la question
- La consigne de correction (réponse attendue ou critères)
- La réponse de l'apprenant
- Le nombre de points maximum

Tu dois :
1. Attribuer une note entre 0 et le maximum de points (valeurs décimales possibles, ex: 1.5/3)
2. Donner un feedback constructif et bienveillant en français, en 2-3 phrases maximum
3. Expliquer pourquoi la note est attribuée

Sois juste mais encourageant. Valorise les bonnes idées même dans une réponse partielle.
"""


class CorrectionIA:
    """Résultat structuré d'une correction IA."""
    def __init__(self, points_obtenus, feedback, source="gemini"):
        self.points_obtenus = points_obtenus
        self.feedback = feedback
        self.source = source


def obtenir_cle_gemini():
    """Récupère la clé Gemini depuis les paramètres ou recharge le .env si nécessaire."""
    cle = (getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")).strip()
    if not cle:
        from dotenv import load_dotenv
        load_dotenv(settings.BASE_DIR / ".env", override=True)
        cle = os.getenv("GEMINI_API_KEY", "").strip()
    return cle


def _client_gemini():
    """Client Gemini partagé (réutilise la connexion HTTP)."""
    cle = obtenir_cle_gemini()
    return _client_pour(cle, getattr(settings, "MODERATION_TIMEOUT", 15))


@functools.lru_cache(maxsize=1)
def _client_pour(cle_api, timeout):
    from google import genai
    from google.genai import types

    return genai.Client(api_key=cle_api, http_options=types.HttpOptions(timeout=timeout * 1000))


def ia_disponible():
    """Vérifie si l'IA est disponible pour la correction."""
    return bool(obtenir_cle_gemini())


def _corriger_par_gemini(question, reponse_texte, points_max):
    """Envoie la réponse à Gemini pour correction. Tente des modèles de secours si besoin."""
    from google.genai import types
    from pydantic import BaseModel, Field

    class ResultatCorrection(BaseModel):
        points: float = Field(description="Note attribuée entre 0 et le maximum.", ge=0)
        feedback: str = Field(description="Feedback constructif en français, 2-3 phrases.")

    prompt = (
        f"Question ({points_max} point{'s' if points_max > 1 else ''}) :\n"
        f"{question.enonce}\n\n"
    )
    if question.consigne_ia:
        prompt += f"Consigne de correction :\n{question.consigne_ia}\n\n"
    prompt += f"Réponse de l'apprenant :\n{reponse_texte}\n"

    securite = [
        types.SafetySetting(category=categorie, threshold=types.HarmBlockThreshold.BLOCK_NONE)
        for categorie in (
            types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        )
    ]

    # Modèles à tester dans l'ordre de priorité
    modeles_a_tester = [getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")]
    for repli in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        if repli not in modeles_a_tester:
            modeles_a_tester.append(repli)

    reponse = None
    derniere_erreur = None

    for modele in modeles_a_tester:
        try:
            reponse = _client_gemini().models.generate_content(
                model=modele,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CONSIGNES_CORRECTION,
                    response_mime_type="application/json",
                    response_schema=ResultatCorrection,
                    temperature=0.2,
                    safety_settings=securite,
                ),
            )
            if reponse:
                break
        except Exception as err:
            derniere_erreur = err
            logger.warning("Échec Gemini avec le modèle %s : %s", modele, err)
            continue

    if not reponse:
        raise derniere_erreur or RuntimeError("Aucun modèle Gemini n'a pu répondre.")

    resultat = reponse.parsed
    if not isinstance(resultat, ResultatCorrection):
        resultat = ResultatCorrection.model_validate(json.loads(reponse.text))

    # S'assurer que la note ne dépasse pas le max
    points = min(max(0, resultat.points), points_max)
    return CorrectionIA(points, resultat.feedback.strip(), "gemini")


def _corriger_sans_ia(question, reponse_texte, points_max):
    """Correction de secours quand Gemini n'est pas configuré ou indisponible."""
    texte = reponse_texte.strip().lower()
    if not texte:
        return CorrectionIA(0, "Aucune réponse fournie.", "regles")

    # Vérification par mots-clés de base si consigne_ia est présente
    consigne = (question.consigne_ia or "").lower()
    enonce = (question.enonce or "").lower()

    # Détecter si les mots clés de la réponse se retrouvent dans la consigne ou la question
    mots_cles = [m for m in re.findall(r"\b\w{3,}\b", consigne) if m not in {"les", "des", "une", "pour", "dans", "avec", "doit", "doivent"}]
    correspondances = [m for m in mots_cles if m in texte] if mots_cles else []

    if correspondances or (texte in consigne or consigne in texte and len(texte) > 2):
        points = float(points_max)
        feedback = (
            f"✅ Bonne réponse ! Mots-clés attendus identifiés ({', '.join(correspondances) or texte}). "
            "Note : activez GEMINI_API_KEY dans votre fichier .env pour bénéficier de retours pédagogiques plus détaillés."
        )
    else:
        points = round(float(points_max) * 0.5, 2) if len(texte) > 10 else 0
        feedback = (
            "⏳ Réponse enregistrée. Pour une évaluation IA détaillée avec feedback personnalisé, "
            "ajoutez votre clé gratuite GEMINI_API_KEY dans le fichier .env (depuis aistudio.google.com/apikey)."
        )

    return CorrectionIA(points, feedback, "regles")


def corriger_reponse_libre(reponse):
    """Corrige une réponse de type texte libre via l'IA ou le moteur de secours."""
    if reponse.question.type != Question.Type.TEXTE_LIBRE:
        return

    points_max = reponse.question.points
    texte = reponse.texte_libre.strip()

    if not texte:
        reponse.est_correcte = False
        reponse.points_obtenus = 0
        reponse.feedback_ia = "Aucune réponse fournie."
        reponse.corrigee = True
        reponse.save(update_fields=["est_correcte", "points_obtenus", "feedback_ia", "corrigee"])
        return

    try:
        if ia_disponible():
            correction = _corriger_par_gemini(reponse.question, texte, points_max)
        else:
            correction = _corriger_sans_ia(reponse.question, texte, points_max)
    except Exception as e:
        logger.warning("Correction IA échouée pour réponse %s : %s", reponse.pk, e)
        correction = _corriger_sans_ia(reponse.question, texte, points_max)

    reponse.points_obtenus = correction.points_obtenus
    reponse.feedback_ia = correction.feedback
    reponse.est_correcte = float(correction.points_obtenus) >= (float(points_max) * 0.5)
    reponse.corrigee = True
    reponse.save(update_fields=["points_obtenus", "feedback_ia", "est_correcte", "corrigee"])


def corriger_tentative(tentative):
    """Corrige toutes les réponses d'une tentative et calcule le score.

    1. Les QCM et Vrai/Faux sont corrigés immédiatement
    2. Les réponses libres sont envoyées à Gemini
    3. Le score final est calculé
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import notifier

    reponses = tentative.reponses.select_related("question", "choix_selectionne").all()

    for reponse in reponses:
        if reponse.corrigee:
            continue

        if reponse.question.type in (Question.Type.QCM, Question.Type.VRAI_FAUX):
            reponse.corriger_qcm()
        elif reponse.question.type == Question.Type.TEXTE_LIBRE:
            corriger_reponse_libre(reponse)

    tentative.terminee = True
    tentative.date_fin = timezone.now()
    tentative.save(update_fields=["terminee", "date_fin"])
    tentative.calculer_score()

    # Notifier l'apprenant
    note = f"{tentative.score}/{tentative.score_total}"
    statut = "réussi ✅" if tentative.reussie else "non réussi ❌"
    notifier(
        tentative.apprenant,
        f"Quiz corrigé · {tentative.quiz.titre}",
        f"Vous avez obtenu {note} ({tentative.pourcentage}%) — {statut}.",
        type=Notification.Type.QUIZ,
        lien=tentative.get_absolute_url(),
    )

    return tentative


def recorriger_tentative(tentative):
    """Force une réévaluation des réponses libres de la tentative par l'IA."""
    for reponse in tentative.reponses.filter(question__type=Question.Type.TEXTE_LIBRE):
        reponse.corrigee = False
        corriger_reponse_libre(reponse)
    tentative.calculer_score()
    return tentative


def generer_questions_par_ia(quiz, theme, niveau="Intermédiaire", nombre=3):
    """Génère automatiquement un lot de questions adaptées au quiz grâce à Gemini."""
    from typing import List
    from google.genai import types
    from pydantic import BaseModel, Field
    from .models import Choix, Question

    class ChoixGenere(BaseModel):
        texte: str
        est_correct: bool

    class QuestionGeneree(BaseModel):
        type: str = Field(description="'qcm', 'vrai_faux' ou 'texte_libre'")
        enonce: str
        points: int = Field(default=1, ge=1, le=5)
        explication: str = Field(description="Explication pédagogique brève")
        consigne_ia: str = Field(default="", description="Pour texte_libre uniquement : points clés attendus")
        choix: List[ChoixGenere] = Field(default_factory=list, description="Pour QCM (3-4 options, 1 seule correcte) ou vrai_faux (2 options)")

    class LotQuestions(BaseModel):
        questions: List[QuestionGeneree]

    consigne = f"""\
Tu es un concepteur pédagogique expert sur SkillForge.
Génère {nombre} questions de quiz sur le thème : « {theme} » (Niveau : {niveau}).
Varie les types : principalement du QCM pertinent, et au moins une question de type 'texte_libre'.
Pour chaque question QCM : fournis 3 à 4 options avec EXACTEMENT UNE seule bonne réponse (est_correct=True).
Pour chaque question vrai_faux : fournis 2 options (Vrai et Faux).
Pour chaque question texte_libre : fournis une consigne_ia claire précisant les concepts indispensables attendus.
Rédige en français soigné et professionnel.
"""

    modeles = [getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"), "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    reponse = None
    derniere_erreur = None

    for m in modeles:
        try:
            reponse = _client_gemini().models.generate_content(
                model=m,
                contents=f"Génère {nombre} questions de quiz sur le sujet : {theme}",
                config=types.GenerateContentConfig(
                    system_instruction=consigne,
                    response_mime_type="application/json",
                    response_schema=LotQuestions,
                    temperature=0.3,
                ),
            )
            if reponse:
                break
        except Exception as e:
            derniere_erreur = e
            continue

    if not reponse:
        logger.warning("Échec de la génération Gemini (%s). Utilisation du moteur de questions de secours.", derniere_erreur)
        return _generer_questions_secours(quiz, theme, niveau, nombre)

    try:
        lot = reponse.parsed
        if not isinstance(lot, LotQuestions):
            lot = LotQuestions.model_validate(json.loads(reponse.text))
    except Exception as e:
        logger.warning("Erreur de parsing de la réponse Gemini : %s. Bascule de secours.", e)
        return _generer_questions_secours(quiz, theme, niveau, nombre)

    ordre_debut = quiz.questions.count() + 1
    questions_creees = []

    for idx, q_data in enumerate(lot.questions):
        type_clean = q_data.type if q_data.type in (Question.Type.QCM, Question.Type.VRAI_FAUX, Question.Type.TEXTE_LIBRE) else Question.Type.QCM
        q = Question.objects.create(
            quiz=quiz,
            type=type_clean,
            enonce=q_data.enonce,
            points=q_data.points,
            ordre=ordre_debut + idx,
            explication=q_data.explication,
            consigne_ia=q_data.consigne_ia if type_clean == Question.Type.TEXTE_LIBRE else "",
        )
        if type_clean in (Question.Type.QCM, Question.Type.VRAI_FAUX) and q_data.choix:
            for c_idx, c in enumerate(q_data.choix):
                Choix.objects.create(
                    question=q,
                    texte=c.texte,
                    est_correct=c.est_correct,
                    ordre=c_idx + 1,
                )
        questions_creees.append(q)

    return questions_creees, "gemini"


def _generer_questions_secours(quiz, theme, niveau, nombre=3):
    """Génération de secours locale pour que le formateur ne soit jamais bloqué."""
    from .models import Choix, Question
    ordre_debut = quiz.questions.count() + 1
    theme_propre = (theme or quiz.titre).capitalize().strip()

    questions_modeles = [
        {
            "type": Question.Type.QCM,
            "enonce": f"Concernant « {theme_propre} », quelle est la bonne pratique essentielle ?",
            "points": 1,
            "explication": f"Une conception rigoureuse et le respect des normes garantissent la qualité dans {theme_propre}.",
            "choix": [
                (f"Appliquer une structuration claire et respecter les standards recommandés", True),
                (f"Ignorer les contraintes de sécurité et d'intégrité", False),
                (f"Dupliquer systématiquement les composants sans factorisation", False),
                (f"Ne jamais documenter les choix techniques", False),
            ]
        },
        {
            "type": Question.Type.VRAI_FAUX,
            "enonce": f"Dans « {theme_propre} », l'optimisation des performances et la clarté du code sont prioritaires dès la conception.",
            "points": 1,
            "explication": "Vrai, une bonne conception initiale évite les goulots d'étranglement futurs.",
            "choix": [
                ("Vrai", True),
                ("Faux", False),
            ]
        },
        {
            "type": Question.Type.TEXTE_LIBRE,
            "enonce": f"Expliquez en 2 ou 3 phrases l'intérêt principal et le principe de fonctionnement de « {theme_propre} ».",
            "points": 2,
            "explication": f"Synthèse claire des objectifs et de la mise en pratique de {theme_propre}.",
            "consigne_ia": f"L'apprenant doit définir {theme_propre} et mentionner son rôle ou ses bénéfices clés.",
            "choix": []
        },
        {
            "type": Question.Type.QCM,
            "enonce": f"Quel problème courant cherche-t-on principalement à éviter lors de la mise en œuvre de « {theme_propre} » ?",
            "points": 1,
            "explication": "La gestion des anomalies et la cohérence des flux sont cruciales.",
            "choix": [
                ("Les incohérences et les pertes de performance", True),
                ("L'amélioration de la lisibilité", False),
                ("L'accélération des temps de réponse", False),
                ("La standardisation des protocoles", False),
            ]
        },
        {
            "type": Question.Type.VRAI_FAUX,
            "enonce": f"Une mauvaise configuration dans « {theme_propre} » peut entraîner des failles ou des lenteurs applicatives.",
            "points": 1,
            "explication": "Vrai, tout composant mal paramétré peut dégrader l'application.",
            "choix": [
                ("Vrai", True),
                ("Faux", False),
            ]
        },
    ]

    creees = []
    for idx, item in enumerate(questions_modeles[:nombre]):
        q = Question.objects.create(
            quiz=quiz,
            type=item["type"],
            enonce=item["enonce"],
            points=item["points"],
            ordre=ordre_debut + idx,
            explication=item["explication"],
            consigne_ia=item.get("consigne_ia", ""),
        )
        for c_idx, (texte_c, est_c) in enumerate(item["choix"]):
            Choix.objects.create(question=q, texte=texte_c, est_correct=est_c, ordre=c_idx + 1)
        creees.append(q)

    return creees, "secours"
