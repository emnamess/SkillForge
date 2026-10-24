"""Statistiques de la plateforme (administrateur) et d'un formateur, sur une période au choix."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from django.utils.formats import date_format

from .models import Certificat
from .progression import CHAMPS, inscriptions_pour

NB_MOIS = 6
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


@dataclass(frozen=True)
class Periode:
    code: str
    libelle: str          # « 30 derniers jours »
    nb: int               # nombre de jours ou de mois affichés dans les graphiques
    pas: str              # "jour" ou "mois"

    def debut(self):
        """Premier jour inclus dans la période."""
        aujourd_hui = timezone.localdate()
        if self.pas == "jour":
            return aujourd_hui - timedelta(days=self.nb - 1)
        return debut_mois(aujourd_hui, -(self.nb - 1))


PERIODES = {
    "30j": Periode("30j", "30 derniers jours", 30, "jour"),
    "6m": Periode("6m", "6 derniers mois", 6, "mois"),
    "12m": Periode("12m", "12 derniers mois", 12, "mois"),
}
PERIODE_PAR_DEFAUT = "6m"


def periode_depuis(code):
    """Période demandée dans l'URL (?periode=30j) ; valeur inconnue -> période par défaut."""
    return PERIODES.get(code, PERIODES[PERIODE_PAR_DEFAUT])


def debut_mois(d, decalage=0):
    """Premier jour du mois de `d`, décalé de `decalage` mois (négatif = dans le passé)."""
    total = d.year * 12 + d.month - 1 + decalage
    return date(total // 12, total % 12 + 1, 1)


def _en_date(valeur):
    return valeur.date() if hasattr(valeur, "date") else valeur


def serie(qs, champ_date, periode):
    """Compte les objets par jour ou par mois sur la période (jours et mois vides inclus)."""
    debut = periode.debut()
    tronque = TruncDate(champ_date) if periode.pas == "jour" else TruncMonth(champ_date)
    comptes = {
        _en_date(ligne["moment"]): ligne["n"]
        for ligne in qs.filter(**{f"{champ_date}__date__gte": debut})
        .annotate(moment=tronque).values("moment").annotate(n=Count("id"))
    }
    points = []
    for i in range(periode.nb):
        if periode.pas == "jour":
            jour = debut + timedelta(days=i)
            # Une étiquette tous les 5 jours (et le dernier jour) pour garder l'axe lisible
            etiquette = f"{jour.day} {MOIS_COURTS[jour.month - 1]}" if (periode.nb - 1 - i) % 5 == 0 else ""
            points.append({"moment": jour, "label": etiquette, "titre": date_format(jour, "j F Y"),
                           "valeur": comptes.get(jour, 0)})
        else:
            mois = debut_mois(debut, i)
            points.append({"moment": mois, "label": MOIS_COURTS[mois.month - 1], "titre": date_format(mois, "F Y"),
                           "valeur": comptes.get(mois, 0)})
    maximum = max((p["valeur"] for p in points), default=0)
    for p in points:
        p["hauteur"] = round(100 * p["valeur"] / maximum) if maximum else 0
    return points


def serie_mensuelle(qs, champ_date, nb_mois=NB_MOIS):
    """Raccourci : série mensuelle sur les `nb_mois` derniers mois."""
    return serie(qs, champ_date, Periode("", "", nb_mois, "mois"))


def classement(qs, champ, limite=5):
    lignes = list(qs.values(champ).annotate(n=Count("id")).order_by("-n", champ)[:limite])
    maximum = lignes[0]["n"] if lignes else 0
    return [{"nom": l[champ] or "—", "valeur": l["n"], "largeur": round(100 * l["n"] / maximum) if maximum else 0}
            for l in lignes]


def resume_certificats(qs, periode=None):
    """Indicateurs des certificats. `total` compte tous les certificats valides ; les indicateurs
    `periode_*` ne comptent que ceux délivrés (ou révoqués) pendant la période."""
    debut_du_mois = debut_mois(timezone.localdate())
    valides = qs.filter(statut=Certificat.Statut.VALIDE)
    agregat = valides.aggregate(
        total=Count("id"),
        ce_mois=Count("id", filter=Q(date_delivrance__date__gte=debut_du_mois)),
        apprenants=Count("apprenant", distinct=True),
        score_moyen=Avg("score"),
    )
    agregat["revoques"] = qs.filter(statut=Certificat.Statut.REVOQUE).count()
    agregat["score_moyen"] = round(agregat["score_moyen"]) if agregat["score_moyen"] is not None else None

    if periode is not None:
        debut = periode.debut()
        dans_periode = valides.filter(date_delivrance__date__gte=debut).aggregate(
            n=Count("id"), apprenants=Count("apprenant", distinct=True), score=Avg("score"))
        agregat["periode_delivres"] = dans_periode["n"]
        agregat["periode_apprenants"] = dans_periode["apprenants"]
        agregat["periode_score"] = round(dans_periode["score"]) if dans_periode["score"] is not None else None
        agregat["periode_revoques"] = qs.filter(statut=Certificat.Statut.REVOQUE,
                                                date_revocation__date__gte=debut).count()
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


def statistiques_plateforme(periode=None):
    periode = periode or periode_depuis(None)
    User = get_user_model()
    debut = periode.debut()
    il_y_a_30_jours = timezone.now() - timedelta(days=30)
    certificats = Certificat.objects.all()
    valides_periode = certificats.filter(statut=Certificat.Statut.VALIDE, date_delivrance__date__gte=debut)

    utilisateurs = User.objects.aggregate(
        total=Count("id", filter=Q(is_active=True)),
        apprenants=Count("id", filter=Q(role=User.Role.APPRENANT, is_active=True)),
        formateurs=Count("id", filter=Q(role=User.Role.FORMATEUR, est_valide=True, is_active=True)),
        en_attente=Count("id", filter=Q(role=User.Role.FORMATEUR, est_valide=False, is_active=True)),
        nouveaux=Count("id", filter=Q(date_joined__date__gte=debut)),
        actifs=Count("id", filter=Q(last_login__gte=il_y_a_30_jours)),
    )

    return {
        "periode": periode,
        "periodes": PERIODES.values(),
        "utilisateurs": utilisateurs,
        "certificats": resume_certificats(certificats, periode),
        "progression": None,  # rempli par la vue (dépend de l'utilisateur)
        "serie_certificats": serie(certificats.filter(statut=Certificat.Statut.VALIDE), "date_delivrance", periode),
        "serie_inscriptions": serie(User.objects.all(), "date_joined", periode),
        "top_cours": classement(valides_periode, "titre_cours"),
        "top_formateurs": classement(valides_periode.exclude(nom_formateur=""), "nom_formateur"),
        "messages_periode": messages_recents(debut),
    }


def statistiques_formateur(formateur, periode=None):
    periode = periode or periode_depuis(None)
    certificats = Certificat.objects.filter(Q(formateur=formateur) | Q(delivre_par=formateur))
    valides = certificats.filter(statut=Certificat.Statut.VALIDE)
    return {
        "periode": periode,
        "periodes": PERIODES.values(),
        "certificats": resume_certificats(certificats, periode),
        "serie_certificats": serie(valides, "date_delivrance", periode),
        "top_cours": classement(valides.filter(date_delivrance__date__gte=periode.debut()), "titre_cours"),
    }


def messages_recents(depuis):
    """Activité de la messagerie (module notifications) depuis une date, 0 si le modèle n'est pas disponible."""
    try:
        from apps.notifications.models import Message
    except ImportError:
        return 0
    return Message.objects.filter(date_envoi__date__gte=depuis).count()
