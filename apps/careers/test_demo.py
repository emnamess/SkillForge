import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from . import services
from .management.commands.seed_carriere_demo import DOMAINE, OFFRES
from .models import Candidature, Offre, ProfilEntreprise

DOSSIER_TEST = tempfile.mkdtemp()


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class CommandeDemoCarriereTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def lancer(self, *args):
        sortie = StringIO()
        call_command("seed_carriere_demo", "--force", *args, stdout=sortie)
        return sortie.getvalue()

    def test_cree_des_donnees_contrastees(self):
        sortie = self.lancer()
        self.assertIn(f"datavision@{DOMAINE}", sortie)
        self.assertIn("SkillForge2026!", sortie)
        self.assertEqual(ProfilEntreprise.objects.filter(statut=ProfilEntreprise.Statut.VALIDEE).count(), 2)
        self.assertEqual(ProfilEntreprise.objects.filter(statut=ProfilEntreprise.Statut.EN_ATTENTE).count(), 1)
        self.assertEqual(Offre.objects.ouvertes().count(), 6)

        reference = Offre.objects.get(titre=OFFRES[0][1])
        scores = [services.score_offre(reference, User.objects.get(username=f"carriere_{n}")).score
                  for n in ("ines", "walid", "rania")]
        self.assertEqual(scores, [93, 62, 31])

        # Toutes les colonnes du Kanban sont représentées
        self.assertEqual(set(Candidature.objects.values_list("statut", flat=True)), set(Candidature.Statut.values))

    def test_relancer_ne_cree_pas_de_doublons(self):
        self.lancer()
        self.assertIn("existent déjà", self.lancer())
        self.assertEqual(User.objects.filter(email__endswith=f"@{DOMAINE}").count(), 6)
        self.assertEqual(Offre.objects.count(), 6)
        self.lancer("--reinitialiser")
        self.assertEqual(Offre.objects.count(), 6)
        self.assertEqual(Candidature.objects.count(), 8)

    def test_toutes_les_pages_s_affichent_avec_les_donnees_de_demo(self):
        self.lancer()
        offre = Offre.objects.get(titre=OFFRES[0][1])
        candidature = offre.candidatures.get(apprenant__username="carriere_ines")
        competence = offre.competences_requises.first().competence
        pages = {
            None: [reverse("careers:offres"), offre.get_absolute_url(), reverse("careers:inscription_recruteur")],
            "carriere_ines": [reverse("careers:offres"), offre.get_absolute_url(), reverse("careers:tableau_apprenant"),
                              reverse("careers:profil"), reverse("careers:mes_candidatures"),
                              candidature.get_absolute_url(), reverse("accounts:dashboard")],
            "carriere_datavision": [reverse("careers:tableau_recruteur"), reverse("careers:mes_offres"),
                                    reverse("careers:offre_creer"), reverse("careers:offre_modifier", args=[offre.pk]),
                                    reverse("careers:kanban", args=[offre.pk]), offre.get_absolute_url(),
                                    reverse("careers:fiche_candidat", args=[candidature.pk]),
                                    reverse("accounts:dashboard")],
            "carriere_atlas": [reverse("careers:tableau_recruteur")],
            "admin": [reverse("careers:admin_statistiques"), reverse("careers:admin_entreprises"),
                      reverse("careers:admin_signalements"), reverse("careers:admin_competences"),
                      reverse("careers:admin_competence_modifier", args=[competence.pk]), offre.get_absolute_url()],
        }
        User.objects.create_superuser("admin", "admin@test.tn", "MotDePasse!2026")
        for username, urls in pages.items():
            if username:
                self.client.force_login(User.objects.get(username=username))
            else:
                self.client.logout()
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 200, f"{username} · {url}")

    @override_settings(DEBUG=False)
    def test_refusee_hors_developpement(self):
        with self.assertRaises(CommandError):
            call_command("seed_carriere_demo", stdout=StringIO())
