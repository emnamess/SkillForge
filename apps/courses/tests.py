from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User

from .models import Cours, Inscription


def creer_utilisateur(role, username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.skillforge.tn",
        password="testpass123",
        role=role,
    )


class InscriptionCoursTests(TestCase):
    def setUp(self):
        self.apprenant = creer_utilisateur(User.Role.APPRENANT, "apprenant")
        self.autre_apprenant = creer_utilisateur(User.Role.APPRENANT, "autre")
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "formateur")
        self.administrateur = creer_utilisateur(User.Role.ADMINISTRATEUR, "admin")
        self.cours = Cours.objects.create(
            formateur=self.formateur,
            titre="Django",
            description="Créer des applications web.",
            est_publie=True,
        )
        self.autre_cours = Cours.objects.create(
            formateur=self.formateur,
            titre="Python",
            est_publie=True,
        )
        self.brouillon = Cours.objects.create(
            formateur=self.formateur,
            titre="Brouillon",
            est_publie=False,
        )
        self.url_inscription = reverse("courses:inscrire", args=[self.cours.pk])

    def test_apprenant_peut_s_inscrire_a_un_cours_publie(self):
        self.client.force_login(self.apprenant)

        reponse = self.client.post(self.url_inscription, follow=True)

        inscription = Inscription.objects.get(apprenant=self.apprenant, cours=self.cours)
        self.assertEqual(inscription.progression, 0)
        self.assertContains(reponse, "Vous êtes inscrit au cours")
        self.assertRedirects(reponse, reverse("courses:detail", args=[self.cours.pk]))

    def test_doublon_conserve_une_seule_inscription_et_affiche_un_message(self):
        self.client.force_login(self.apprenant)

        self.client.post(self.url_inscription)
        reponse = self.client.post(self.url_inscription, follow=True)

        self.assertEqual(Inscription.objects.filter(apprenant=self.apprenant, cours=self.cours).count(), 1)
        self.assertContains(reponse, "déjà inscrit")

    def test_formateur_ne_peut_pas_utiliser_l_action(self):
        self.client.force_login(self.formateur)

        reponse = self.client.post(self.url_inscription)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Inscription.objects.exists())

    def test_administrateur_garde_l_acces_aux_brouillons_mais_ne_s_inscrit_pas(self):
        self.client.force_login(self.administrateur)

        catalogue = self.client.get(reverse("courses:index"))
        detail = self.client.get(reverse("courses:detail", args=[self.brouillon.pk]))
        action = self.client.post(reverse("courses:inscrire", args=[self.cours.pk]))

        self.assertContains(catalogue, "Brouillon")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(action.status_code, 403)
        self.assertFalse(Inscription.objects.exists())

    def test_cours_non_publie_est_introuvable_pour_un_apprenant(self):
        self.client.force_login(self.apprenant)

        reponse = self.client.post(
            reverse("courses:inscrire", args=[self.brouillon.pk]), follow=True
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Ce cours n’est pas disponible à l’inscription.")
        self.assertNotContains(reponse, self.brouillon.titre)
        self.assertFalse(Inscription.objects.exists())

    def test_action_refuse_get(self):
        self.client.force_login(self.apprenant)

        reponse = self.client.get(self.url_inscription)

        self.assertEqual(reponse.status_code, 405)
        self.assertFalse(Inscription.objects.exists())

    def test_action_est_protegee_par_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.apprenant)

        reponse = client.post(self.url_inscription)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Inscription.objects.exists())

    def test_catalogue_affiche_le_bon_etat_d_inscription(self):
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)

        reponse = self.client.get(reverse("courses:index"))

        self.assertContains(reponse, "Déjà inscrit")
        self.assertContains(reponse, "S’inscrire")
        self.assertNotContains(reponse, "Brouillon")

    def test_detail_affiche_si_deja_inscrit(self):
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)

        reponse = self.client.get(reverse("courses:detail", args=[self.cours.pk]))

        self.assertContains(reponse, "Déjà inscrit")
        self.assertNotContains(reponse, "S’inscrire")

    def test_mes_cours_affiche_uniquement_les_inscriptions_de_l_apprenant(self):
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours, progression=35)
        Inscription.objects.create(apprenant=self.autre_apprenant, cours=self.autre_cours, progression=80)
        self.client.force_login(self.apprenant)

        reponse = self.client.get(reverse("courses:mes_cours"))

        self.assertContains(reponse, "Django")
        self.assertContains(reponse, "35 %")
        self.assertNotContains(reponse, "Python")

    def test_mes_cours_est_reserve_aux_apprenants(self):
        self.client.force_login(self.formateur)

        reponse = self.client.get(reverse("courses:mes_cours"))

        self.assertEqual(reponse.status_code, 403)

    def test_visiteur_non_connecte_est_redirige_vers_la_connexion(self):
        reponse = self.client.post(self.url_inscription)

        self.assertRedirects(
            reponse,
            f"{reverse('accounts:login')}?next={self.url_inscription}",
            fetch_redirect_response=False,
        )
        self.assertFalse(Inscription.objects.exists())
