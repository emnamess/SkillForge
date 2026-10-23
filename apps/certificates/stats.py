"""Statistiques de la plateforme (administrateur) et d'un formateur."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.formats import date_format

from .models import Certificat
from .progression import CHAMPS, inscriptions_pour

NB_MOIS = 6
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def debut_mois(d, decalage=0):
    """Premier jour du mois de `d`, décalé de `decalage` mois (négatif = dans le passé)."""
    total = d.year * 12 + d.month - 1 + decalage
    return date(total // 12, total % 12 + 1, 1)


def serie_mensuelle(qs, champ_date, nb_mois=NB_MOIS):
    """Compte les objets par mois sur les `nb_mois` derniers mois (mois vides inclus)."""
    aujourd_hui = timezone.localdate()
    premier = debut_mois(aujourd_hui, -(nb_mois - 1))
    comptes = {
        (ligne["mois"].date() if hasattr(ligne["mois"], "date") else ligne["mois"]): ligne["n"]
        for ligne in qs.filter(**{f"{champ_date}__date__gte": premier})
        .annotate(mois=TruncMonth(champ_date)).values("mois").annotate(n=Count("id"))
    }
    serie = []
    for i in range(nb_mois):
        mois = debut_mois(premier, i)
        serie.append({"mois": mois, "label": MOIS_COURTS[mois.month - 1], "titre": date_format(mois, "F Y"),
                      "valeur": comptes.get(mois, 0)})
    maximum = max((p["valeur"] for p in serie), default=0)
    for p in serie:
        p["hauteur"] = round(100 * p["valeur"] / maximum) if maximum else 0
    return serie


def classement(qs, champ, limite=5):
    lignes = list(qs.values(champ).annotate(n=Count("id")).order_by("-n", champ)[:limite])
    maximum = lignes[0]["n"] if lignes else 0
    return [{"nom": l[champ] or "—", "valeur": l["n"], "largeur": round(100 * l["n"] / maximum) if maximum else 0}
            for l in lignes]


def resume_certificats(qs):
    debut = debut_mois(timezone.localdate())
    valides = qs.filter(statut=Certificat.Statut.VALIDE)
    agregat = valides.aggregate(
        total=Count("id"),
        ce_mois=Count("id", filter=Q(date_delivrance__date__gte=debut)),
        apprenants=Count("apprenant", distinct=True),
        score_moyen=Avg("score"),
    )
    agregat["revoques"] = qs.filter(statut=Certificat.Statut.REVOQUE).count()
    agregat["score_moyen"] = round(agregat["score_moyen"]) if agregat["score_moyen"] is not None else None
    return agregat


def resume_progression(user):
    """Indicateurs tirés des inscriptions (None tant que le module cours n'est pas disponible)."""
    qs = inscriptions_pour(user)
    if qs is None:
        return None
    champ = CHAMPS["progression"]
    agregat = qs.aggregate(total=Count("id"), moyenne=Avg(champ),
                           termines=Count("id", filter=Q(**{f"{champ}__gte": 100})))
    agregat["moyenne"] = round(agregat["moyenne"] or 0)
    agregat["taux_reussite"] = round(100 * agregat["termines"] / agregat["total"]) if agregat["total"] else 0
    return agregat


def statistiques_plateforme():
    User = get_user_model()
    il_y_a_30_jours = timezone.now() - timedelta(days=30)
    certificats = Certificat.objects.all()

    utilisateurs = User.objects.aggregate(
        total=Count("id", filter=Q(is_active=True)),
        apprenants=Count("id", filter=Q(role=User.Role.APPRENANT, is_active=True)),
        formateurs=Count("id", filter=Q(role=User.Role.FORMATEUR, est_valide=True, is_active=True)),
        en_attente=Count("id", filter=Q(role=User.Role.FORMATEUR, est_valide=False, is_active=True)),
        nouveaux=Count("id", filter=Q(date_joined__gte=il_y_a_30_jours)),
        actifs=Count("id", filter=Q(last_login__gte=il_y_a_30_jours)),
    )

    return {
        "utilisateurs": utilisateurs,
        "certificats": resume_certificats(certificats),
        "progression": None,  # rempli par la vue (dépend de l'utilisateur)
        "serie_certificats": serie_mensuelle(certificats.filter(statut=Certificat.Statut.VALIDE),
                                             "date_delivrance"),
        "serie_inscriptions": serie_mensuelle(User.objects.all(), "date_joined"),
        "top_cours": classement(certificats.filter(statut=Certificat.Statut.VALIDE), "titre_cours"),
        "top_formateurs": classement(certificats.filter(statut=Certificat.Statut.VALIDE)
                                     .exclude(nom_formateur=""), "nom_formateur"),
        "messages_30j": messages_recents(il_y_a_30_jours),
    }


def statistiques_formateur(formateur):
    certificats = Certificat.objects.filter(Q(formateur=formateur) | Q(delivre_par=formateur))
    return {
        "certificats": resume_certificats(certificats),
        "serie_certificats": serie_mensuelle(certificats.filter(statut=Certificat.Statut.VALIDE),
                                             "date_delivrance"),
        "top_cours": classement(certificats.filter(statut=Certificat.Statut.VALIDE), "titre_cours"),
    }


def messages_recents(depuis):
    """Activité de la messagerie (module notifications), 0 si le modèle n'est pas disponible."""
    try:
        from apps.notifications.models import Message
    except ImportError:
        return 0
    return Message.objects.filter(date_envoi__gte=depuis).count()
