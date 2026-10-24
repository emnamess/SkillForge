from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .fabriques import competence, creer, creer_admin, creer_offre, creer_recruteur
from .management.commands.seed_competences import COMPETENCES
from .models import Competence, CompetenceRequise, Offre, ProfilEntreprise


class RoleRecruteurTests(TestCase):
    def setUp(self):
        self.recruteur = creer("rh@entreprise.tn", role=User.Role.RECRUTEUR)

    def test_proprietes_du_role(self):
        self.assertTrue(self.recruteur.est_recruteur)
        self.assertFalse(self.recruteur.est_apprenant)
        # La validation des formateurs (est_valide) ne concerne pas les recruteurs
        self.assertFalse(self.recruteur.en_attente_validation)

    def test_role_required_accepte_le_recruteur_et_refuse_les_autres(self):
        vue = role_required(User.Role.RECRUTEUR)(lambda request: HttpResponse("ok"))
        requete = RequestFactory().get("/")
        requete.user = self.recruteur
        self.assertEqual(vue(requete).status_code, 200)
        requete.user = creer("yasmine@test.tn")
        with self.assertRaises(PermissionDenied):
            vue(requete)
        requete.user = AnonymousUser()
        self.assertEqual(vue(requete).status_code, 302)


class ModelesTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")

    def test_slug_et_alias_de_competence(self):
        c = Competence.objects.create(nom="Power BI", alias="powerbi, dax , ")
        self.assertEqual(c.slug, "power-bi")
        self.assertEqual(c.liste_alias(), ["powerbi", "dax"])

    def test_offres_ouvertes(self):
        ouverte = creer_offre(self.recruteur, "Ouverte", date_limite=timezone.localdate())
        creer_offre(self.recruteur, "Expirée", date_limite=timezone.localdate() - timedelta(days=1))
        creer_offre(self.recruteur, "Brouillon", statut=Offre.Statut.BROUILLON)
        creer_offre(self.recruteur, "Suspendue", statut=Offre.Statut.SUSPENDUE)
        attente = creer_recruteur("rh@attente.tn", statut=ProfilEntreprise.Statut.EN_ATTENTE)
        creer_offre(attente, "Entreprise non validée")
        self.assertQuerySetEqual(Offre.objects.ouvertes(), [ouverte])

    def test_offre_expiree_affichee_fermee(self):
        offre = creer_offre(self.recruteur, date_limite=timezone.localdate() - timedelta(days=1))
        self.assertEqual(offre.statut, Offre.Statut.PUBLIEE)
        self.assertEqual(offre.statut_effectif, Offre.Statut.FERMEE)
        self.assertFalse(offre.est_ouverte)

    def test_competence_requise_unique_par_offre(self):
        sql = competence("SQL")
        offre = creer_offre(self.recruteur, exigences=[(sql, 2, True)])
        with self.assertRaises(IntegrityError):
            CompetenceRequise.objects.create(offre=offre, competence=sql, niveau_requis=3)


class SeedCompetencesTests(TestCase):
    def test_commande_idempotente(self):
        call_command("seed_competences", stdout=StringIO())
        call_command("seed_competences", stdout=StringIO())
        self.assertEqual(Competence.objects.count(), len(COMPETENCES))
        self.assertGreaterEqual(len(COMPETENCES), 40)
        self.assertIn("powerbi", Competence.objects.get(nom="Power BI").liste_alias())


class BackOfficeTests(TestCase):
    def setUp(self):
        self.admin = creer_admin()
        self.client.force_login(self.admin)

    def test_pages_du_back_office(self):
        recruteur = creer_recruteur("rh@data.tn")
        creer_offre(recruteur, exigences=[(competence("SQL"), 2, True)])
        for modele in ("competence", "profilentreprise", "offre", "profilcarriere", "candidature",
                       "historiquecandidature", "signalementoffre"):
            r = self.client.get(reverse(f"admin:careers_{modele}_changelist"))
            self.assertEqual(r.status_code, 200, modele)

    @mock.patch("apps.careers.integrations.notifier")
    def test_validation_groupee_passe_par_le_service(self, notifier):
        a = creer_recruteur("rh@a.tn", statut=ProfilEntreprise.Statut.EN_ATTENTE)
        b = creer_recruteur("rh@b.tn", statut=ProfilEntreprise.Statut.EN_ATTENTE)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("admin:careers_profilentreprise_changelist"), {
                "action": "valider",
                "_selected_action": [a.profil_entreprise.pk, b.profil_entreprise.pk],
            })
        self.assertEqual(ProfilEntreprise.objects.filter(statut=ProfilEntreprise.Statut.VALIDEE).count(), 2)
        # Une notification par entreprise : chaque objet est passé par le service (pas de update())
        self.assertEqual(notifier.call_count, 2)
