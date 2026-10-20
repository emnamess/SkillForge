from django.core import mail
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .decorators import role_required
from .models import User

MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email,
                                    password=MDP, role=role, **extra)


class UserModelTests(TestCase):
    def test_initiales_et_roles(self):
        u = creer("yasmine@test.tn", first_name="Yasmine", last_name="Ben Ali")
        self.assertEqual(u.initiales, "YB")
        self.assertTrue(u.est_apprenant)
        self.assertFalse(u.est_administrateur)

    def test_superuser_devient_administrateur(self):
        admin = User.objects.create_superuser("admin", "admin@test.tn", MDP)
        self.assertEqual(admin.role, User.Role.ADMINISTRATEUR)

    def test_generer_username_unique(self):
        creer("karim@test.tn")
        self.assertEqual(User.generer_username("karim@autre.tn"), "karim2")

    def test_email_normalise_en_minuscules(self):
        u = creer("Sarra.K@Test.TN")
        self.assertEqual(u.email, "sarra.k@test.tn")


class InscriptionTests(TestCase):
    url = reverse("accounts:inscription")

    def donnees(self, **extra):
        data = {"first_name": "Amine", "last_name": "M", "email": "amine@test.tn",
                "role": "apprenant", "password1": MDP, "password2": MDP}
        data.update(extra)
        return data

    def test_inscription_apprenant_connecte_directement(self):
        r = self.client.post(self.url, self.donnees())
        self.assertRedirects(r, reverse("accounts:dashboard"))
        u = User.objects.get(email="amine@test.tn")
        self.assertTrue(u.est_valide)
        self.assertEqual(int(self.client.session["_auth_user_id"]), u.pk)

    def test_inscription_formateur_en_attente(self):
        self.client.post(self.url, self.donnees(role="formateur", specialite="Data"))
        u = User.objects.get(email="amine@test.tn")
        self.assertTrue(u.en_attente_validation)

    def test_formateur_sans_specialite_refuse(self):
        r = self.client.post(self.url, self.donnees(role="formateur"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_impossible_de_s_inscrire_administrateur(self):
        r = self.client.post(self.url, self.donnees(role="administrateur"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_email_deja_utilise(self):
        creer("amine@test.tn")
        r = self.client.post(self.url, self.donnees(email="AMINE@test.tn"))
        self.assertContains(r, "existe déjà")


class ConnexionTests(TestCase):
    def setUp(self):
        self.user = creer("omar@test.tn")

    def test_connexion_par_email(self):
        r = self.client.post(reverse("accounts:login"), {"username": "OMAR@test.tn", "password": MDP})
        self.assertRedirects(r, reverse("accounts:dashboard"))

    def test_connexion_par_username(self):
        r = self.client.post(reverse("accounts:login"), {"username": "omar", "password": MDP})
        self.assertRedirects(r, reverse("accounts:dashboard"))

    def test_mauvais_mot_de_passe(self):
        r = self.client.post(reverse("accounts:login"), {"username": "omar@test.tn", "password": "faux"})
        self.assertContains(r, "Identifiants incorrects")

    def test_compte_desactive_refuse(self):
        self.user.is_active = False
        self.user.save()
        r = self.client.post(reverse("accounts:login"), {"username": "omar@test.tn", "password": MDP})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_reinitialisation_envoie_un_email(self):
        self.client.post(reverse("accounts:password_reset"), {"email": "omar@test.tn"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/comptes/mot-de-passe/reinitialiser/", mail.outbox[0].body)


class ProfilTests(TestCase):
    def test_modifier_profil(self):
        u = creer("leila@test.tn")
        self.client.force_login(u)
        r = self.client.post(reverse("accounts:profil"),
                             {"first_name": "Leïla", "last_name": "T", "email": "leila@test.tn", "bio": "Data"})
        self.assertRedirects(r, reverse("accounts:profil"))
        u.refresh_from_db()
        self.assertEqual(u.first_name, "Leïla")

    def test_apprenant_ne_peut_pas_changer_son_role(self):
        u = creer("leila@test.tn")
        self.client.force_login(u)
        self.client.post(reverse("accounts:profil"),
                         {"first_name": "L", "last_name": "T", "email": "leila@test.tn", "role": "administrateur"})
        u.refresh_from_db()
        self.assertTrue(u.est_apprenant)


class GestionUtilisateursTests(TestCase):
    def setUp(self):
        self.admin = creer("admin@test.tn", role=User.Role.ADMINISTRATEUR)
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR, est_valide=False)
        self.apprenant = creer("yasmine@test.tn")

    def test_liste_reservee_aux_admins(self):
        self.client.force_login(self.apprenant)
        self.assertEqual(self.client.get(reverse("accounts:utilisateurs")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:utilisateurs")).status_code, 200)

    def test_filtre_formateurs_en_attente(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("accounts:utilisateurs"), {"statut": "attente"})
        self.assertEqual(list(r.context["page"]), [self.formateur])

    def test_valider_formateur(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:valider_formateur", args=[self.formateur.pk]))
        self.formateur.refresh_from_db()
        self.assertTrue(self.formateur.est_valide)

    def test_desactiver_puis_reactiver(self):
        self.client.force_login(self.admin)
        url = reverse("accounts:basculer_actif", args=[self.apprenant.pk])
        self.client.post(url)
        self.apprenant.refresh_from_db()
        self.assertFalse(self.apprenant.is_active)
        self.client.post(url)
        self.apprenant.refresh_from_db()
        self.assertTrue(self.apprenant.is_active)

    def test_admin_ne_peut_pas_se_desactiver(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:basculer_actif", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_changer_role(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:utilisateur_detail", args=[self.apprenant.pk]),
                         {"role": "formateur", "est_valide": "on", "is_active": "on"})
        self.apprenant.refresh_from_db()
        self.assertTrue(self.apprenant.est_formateur)

    def test_admin_ne_peut_pas_se_retirer_ses_droits(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:utilisateur_detail", args=[self.admin.pk]),
                         {"role": "apprenant", "est_valide": "on", "is_active": "on"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.est_administrateur)


class RoleRequiredTests(TestCase):
    def setUp(self):
        self.vue = role_required(User.Role.FORMATEUR)(lambda request: HttpResponse("ok"))
        self.factory = RequestFactory()

    def appeler(self, user):
        request = self.factory.get("/")
        request.user = user
        return self.vue(request)

    def test_formateur_valide_autorise(self):
        u = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.assertEqual(self.appeler(u).status_code, 200)

    def test_formateur_non_valide_refuse(self):
        u = creer("karim@test.tn", role=User.Role.FORMATEUR, est_valide=False)
        with self.assertRaises(PermissionDenied):
            self.appeler(u)

    def test_apprenant_refuse(self):
        with self.assertRaises(PermissionDenied):
            self.appeler(creer("yasmine@test.tn"))

    def test_administrateur_toujours_autorise(self):
        u = creer("admin@test.tn", role=User.Role.ADMINISTRATEUR)
        self.assertEqual(self.appeler(u).status_code, 200)
