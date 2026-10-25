"""Réponses extractives, bornées au texte de la leçon et filtrées contre le bruit."""
import re


REFUS_CONTENU = (
    "Je ne peux pas répondre de façon fiable : le texte de cette leçon est trop court, "
    "répétitif ou semble incohérent. Ajoutez une explication claire dans la leçon, puis réessayez."
)
REFUS_PERTINENCE = "Je ne trouve pas cette information dans le texte de la leçon. Reformulez la question avec les notions abordées dans le cours."
STOP_WORDS = {
    "alors", "avec", "dans", "des", "donc", "elle", "elles", "est", "être", "faire", "fait", "ici", "leur", "leurs",
    "mais", "même", "nous", "pour", "quoi", "sans", "sera", "sont", "sur", "tout", "tous", "une", "uns", "vous",
    "cette", "cela", "ceci", "comment", "pourquoi", "quels", "quelle", "quelles", "quand", "quel", "plus", "moins",
    "the", "this", "that", "with", "from", "what", "when", "where", "which", "how", "does", "have", "will", "your",
}
WORD_RE = re.compile(r"[a-zà-öø-ÿ]{2,}", re.IGNORECASE)
VOWELS = set("aeiouyàâäéèêëîïôöùûüÿœ")


def build_context(lesson):
    """Sépare métadonnées, texte pédagogique et code pour ne pas les confondre."""
    description = lesson.description.strip()
    narrative = [lesson.contenu.strip()] if lesson.contenu and lesson.contenu.strip() else []
    narrative.extend(lesson.blocs.filter(type="text").values_list("texte", flat=True))
    code = list(lesson.blocs.filter(type="code").values_list("texte", flat=True))
    sections = [f"TITRE:\n{lesson.titre.strip()}"]
    if description:
        sections.append(f"DESCRIPTION:\n{description}")
    if narrative:
        sections.append("CONTENU:\n" + "\n".join(text.strip() for text in narrative if text and text.strip()))
    if code:
        sections.append("CODE:\n" + "\n".join(code))
    return "\n\n".join(sections)[:12000]


def _sections(context):
    result = {"TITRE": "", "DESCRIPTION": "", "CONTENU": "", "CODE": ""}
    matches = list(re.finditer(r"(?m)^(TITRE|DESCRIPTION|CONTENU|CODE):\s*$", context))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(context)
        result[match.group(1)] = context[match.end():end].strip()
    # Compatibilité des anciens contextes qui ne contenaient aucun marqueur.
    if not matches:
        result["CONTENU"] = context.strip()
    return result


def _quality_ok(text):
    words = [word.lower() for word in WORD_RE.findall(text)]
    if len(words) < 8:
        return False
    unique_ratio = len(set(words)) / len(words)
    if unique_ratio < 0.45:
        return False
    letters = "".join(words)
    vowel_ratio = sum(char in VOWELS for char in letters) / max(1, len(letters))
    if not 0.22 <= vowel_ratio <= 0.62:
        return False
    if sum(any(char in VOWELS for char in word) for word in words) / len(words) < 0.65:
        return False
    if re.search(r"(.)\1{3,}", text, re.IGNORECASE):
        return False
    if re.search(r"[^aeiouyàâäéèêëîïôöùûüÿœ\W\d_]{7,}", text, re.IGNORECASE):
        return False
    return True


def context_is_reliable(context):
    """Check the lesson's teaching text before sending it to an AI provider."""
    sections = _sections(context)
    source = "\n".join(part for part in (sections["DESCRIPTION"], sections["CONTENU"]) if part)
    return _quality_ok(source)


def _sentences(text):
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]


def explain(intent, question, context):
    sections = _sections(context)
    source = "\n".join(part for part in (sections["DESCRIPTION"], sections["CONTENU"]) if part)
    if not _quality_ok(source):
        return REFUS_CONTENU

    sentences = _sentences(source)
    if not sentences:
        return REFUS_CONTENU
    if intent == "resume":
        return "Résumé basé sur la leçon :\n" + " ".join(sentences[:5])
    if intent == "quiz":
        statement = sentences[0]
        return (
            "Mini-quiz basé sur la leçon — Vrai ou faux ?\n"
            f"{statement[:300]}\n\n"
            "Réfléchissez à votre réponse, puis comparez-la au passage correspondant. Le quiz reprend le cours sans vérifier cette affirmation indépendamment."
        )
    if intent == "example":
        if sections["CODE"].strip():
            return "Exemple de code issu de la leçon :\n" + sections["CODE"][:1200]
        return "Exemple tiré du contenu de la leçon : " + sentences[0]
    if intent == "simple":
        return "En termes simples, la leçon indique : " + sentences[0]
    if intent == "definition":
        return "Définition tirée du contenu de cette leçon : " + sentences[0]
    if intent == "steps":
        outline = "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(sentences[:4], 1))
        return "Points à suivre d'après la leçon :\n" + outline

    question_words = {word.lower() for word in WORD_RE.findall(question)} - STOP_WORDS
    content_words = {word.lower() for word in WORD_RE.findall(source)}
    overlap = question_words & content_words
    if not overlap:
        return REFUS_PERTINENCE
    ranked = sorted(
        sentences,
        key=lambda sentence: len({word.lower() for word in WORD_RE.findall(sentence)} & overlap),
        reverse=True,
    )
    best_overlap = {word.lower() for word in WORD_RE.findall(ranked[0])} & overlap
    if not best_overlap:
        return REFUS_PERTINENCE
    return "Passage de la leçon correspondant le mieux à votre question : " + " ".join(ranked[:2])
