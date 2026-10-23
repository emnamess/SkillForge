import re

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.notifications.models import Notification

from . import progression, services, stats
from .models import Certificat

MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize(), **extra)


class Base(TestCase):
    def setUp(self):
        self.yasmine = creer("yasmine@test.tn")
        self.amine = creer("amine@test.tn")
        self.karim = creer("karim@test.tn", User.Role.FORMATEUR)
        self.leila = creer("leila@test.tn", User.Role.FORMATEUR)
        self.sami = creer("sami@test.tn", User.Role.FORMATEUR, est_valide=False)
        self.admin = creer("admin@test.tn", User.Role.ADMINISTRATEUR)

    def certificat(self, apprenant=None, cours="Modélisation UML", formateur=None, **kwargs):
        return services.delivrer_certificat(apprenant or self.yasmine, cours, formateur=formateur or self.karim,
                                            delivre_par=formateur or self.karim, **kwargs)


class CertificatModelTests(Base):
    def test_code_verification_genere_et_unique(self):
        a = self.certificat()
        b = self.certificat(cours="SQL avancé")
        self.assertRegex(a.code_verification, r"^SF-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertNotEqual(a.code_verification, b.code_verification)

    def test_nom_formateur_recopie(self):
        c = self.certificat()
        self.assertEqual(c.nom_formateur, str(self.karim))

    def test_mention_selon_score(self):
        self.assertEqual(self.certificat(score=95).mention, "Excellent")
        self.assertEqual(self.certificat(cours="B", score=82).mention, "Très bien")
        self.assertEqual(self.certificat(cours="C", score=60).mention, "Validé")
        self.assertEqual(self.certificat(cours="D").mention, "")

    def test_liste_competences(self):
        c = self.certificat(competences="- Héritage\n\n• Associations \n")
        self.assertEqual(c.liste_competences, ["Héritage", "Associations"])


class ServicesTests(Base):
    def test_delivrer_notifie_l_apprenant(self):
        with self.captureOnCommitCallbacks(execute=True):
            c = self.certificat()
        n = Notification.objects.get(destinataire=self.yasmine, type=Notification.Type.CERTIFICAT)
        self.assertEqual(n.titre, "Certificat obtenu")
        self.assertEqual(n.lien, c.get_absolute_url())

    def test_un_seul_certificat_valide_par_cours(self):
        self.certificat()
        with self.assertRaises(ValidationError):
            self.certificat(cours="modélisation uml")

    def test_nouveau_certificat_possible_apres_revocation(self):
        c = self.certificat()
        services.revoquer_certificat(c, self.admin, "Erreur de saisie")
        self.assertTrue(self.certificat().est_valide)

    def test_seul_un_apprenant_recoit_un_certificat(self):
        with self.assertRaises(ValidationError):
            services.delivrer_certificat(self.karim, "UML")

    def test_eligibilite(self):
        self.assertFalse(services.est_eligible(99, 100))
        self.assertTrue(services.est_eligible(100))
        self.assertTrue(services.est_eligible(100, 70))
        self.assertFalse(services.est_eligible(100, 69))
        with override_settings(CERTIFICAT_SCORE_MINIMUM=50):
            self.assertTrue(services.est_eligible(100, 55))

    def test_delivrer_si_eligible(self):
        self.assertIsNone(services.delivrer_si_eligible(self.yasmine, "UML", progression=80, score=90))
        c = services.delivrer_si_eligible(self.yasmine, "UML", progression=100, score=90)
        self.assertIsNotNone(c)
        # Appel répété (ex. à chaque mise à jour de la progression) : pas de doublon
        self.assertIsNone(services.delivrer_si_eligible(self.yasmine, "UML", progression=100, score=90))
        self.assertEqual(Certificat.objects.count(), 1)

    def test_revocation_exige_un_motif(self):
        c = self.certificat()
        with self.assertRaises(ValidationError):
            services.revoquer_certificat(c, self.admin, "  ")
        with self.captureOnCommitCallbacks(execute=True):
            services.revoquer_certificat(c, self.admin, "Fraude")
        c.refresh_from_db()
        self.assertEqual(c.statut, Certificat.Statut.REVOQUE)
        self.assertEqual(c.revoque_par, self.admin)
        self.assertTrue(Notification.objects.filter(destinataire=self.yasmine, titre="Certificat révoqué").exists())


class AccesTests(Base):
    def test_index_selon_le_role(self):
        self.client.force_login(self.yasmine)
        self.assertTemplateUsed(self.client.get(reverse("certificates:index")), "certificates/mes_certificats.html")
        self.client.force_login(self.karim)
        self.assertTemplateUsed(self.client.get(reverse("certificates:index")), "certificates/suivi.html")

    def test_apprenant_ne_voit_que_ses_certificats(self):
        a = self.certificat()
        b = self.certificat(apprenant=self.amine)
        self.client.force_login(self.yasmine)
        r = self.client.get(reverse("certificates:index"))
        self.assertContains(r, a.code_verification)
        self.assertNotContains(r, b.code_verification)
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.get(a.get_absolute_url()).status_code, 200)

    def test_formateur_voit_les_certificats_de_ses_cours(self):
        a = self.certificat()
        b = self.certificat(cours="SQL", formateur=self.leila)
        self.client.force_login(self.karim)
        r = self.client.get(reverse("certificates:index"))
        self.assertContains(r, a.code_verification)
        self.assertNotContains(r, b.code_verification)
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code, 403)

    def test_admin_voit_tout(self):
        b = self.certificat(cours="SQL", formateur=self.leila)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("certificates:index")), b.code_verification)
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code, 200)

    def test_detail_exige_connexion(self):
        c = self.certificat()
        self.assertEqual(self.client.get(c.get_absolute_url()).status_code, 302)


class DelivrerViewTests(Base):
    url = reverse("certificates:delivrer")

    def donnees(self, **extra):
        return {"apprenant": self.yasmine.pk, "titre_cours": "  Modélisation   UML ", "score": 88,
                "duree_heures": 24, "competences": "Héritage\nAssociations", **extra}

    def test_formateur_delivre(self):
        self.client.force_login(self.karim)
        r = self.client.post(self.url, self.donnees())
        c = Certificat.objects.get()
        self.assertRedirects(r, c.get_absolute_url())
        self.assertEqual(c.titre_cours, "Modélisation UML")
        self.assertEqual(c.formateur, self.karim)
        self.assertEqual(c.delivre_par, self.karim)

    def test_formateur_ne_choisit_pas_le_formateur(self):
        self.client.force_login(self.karim)
        self.client.post(self.url, self.donnees(formateur=self.leila.pk))
        self.assertEqual(Certificat.objects.get().formateur, self.karim)

    def test_admin_choisit_le_formateur(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, self.donnees(formateur=self.leila.pk))
        c = Certificat.objects.get()
        self.assertEqual((c.formateur, c.delivre_par), (self.leila, self.admin))

    def test_doublon_refuse_avec_message(self):
        self.certificat()
        self.client.force_login(self.karim)
        r = self.client.post(self.url, self.donnees())
        self.assertContains(r, "possède déjà un certificat valide")
        self.assertEqual(Certificat.objects.count(), 1)

    def test_score_hors_limites(self):
        self.client.force_login(self.karim)
        r = self.client.post(self.url, self.donnees(score=120))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Certificat.objects.exists())

    def test_apprenant_et_formateur_non_valide_refuses(self):
        for user in (self.yasmine, self.sami):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, self.donnees()).status_code, 403)
        self.assertFalse(Certificat.objects.exists())


class RevoquerViewTests(Base):
    def test_seul_l_admin_revoque(self):
        c = self.certificat()
        url = reverse("certificates:revoquer", args=[c.code_verification])
        self.client.force_login(self.karim)
        self.assertEqual(self.client.post(url, {"motif": "x"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(url, {"motif": "Fraude au quiz"}), c.get_absolute_url())
        c.refresh_from_db()
        self.assertFalse(c.est_valide)

    def test_get_refuse(self):
        c = self.certificat()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("certificates:revoquer", args=[c.code_verification])).status_code, 405)


class VerificationTests(Base):
    def test_page_publique_certificat_valide(self):
        c = self.certificat(score=90)
        r = self.client.get(c.get_verification_url())
        self.assertContains(r, "Certificat authentique")
        self.assertContains(r, "Modélisation UML")

    def test_saisie_normalisee(self):
        c = self.certificat()
        brut = c.code_verification.replace("SF-", "").replace("-", "").lower()
        r = self.client.get(reverse("certificates:verifier"), {"code": brut})
        self.assertRedirects(r, c.get_verification_url())

    def test_code_inconnu(self):
        self.assertContains(self.client.get(reverse("certificates:verifier_code", args=["SF-AAAA-BBBB"])),
                            "Code inconnu")

    def test_certificat_revoque(self):
        c = self.certificat()
        services.revoquer_certificat(c, self.admin, "Fraude")
        r = self.client.get(c.get_verification_url())
        self.assertContains(r, "Certificat révoqué")
        self.assertNotContains(r, "Fraude")  # le motif reste interne


class StatistiquesTests(Base):
    def test_acces(self):
        url = reverse("certificates:statistiques")
        self.client.force_login(self.yasmine)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.karim)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "Formateurs en attente")

    def test_chiffres_plateforme(self):
        self.certificat(score=80)
        self.certificat(apprenant=self.amine, score=90)
        c = self.certificat(cours="SQL", formateur=self.leila, score=50)
        services.revoquer_certificat(c, self.admin, "Erreur")
        s = stats.statistiques_plateforme()
        self.assertEqual(s["certificats"]["total"], 2)
        self.assertEqual(s["certificats"]["revoques"], 1)
        self.assertEqual(s["certificats"]["score_moyen"], 85)
        self.assertEqual(s["certificats"]["apprenants"], 2)
        self.assertEqual(s["utilisateurs"]["en_attente"], 1)
        self.assertEqual(s["top_cours"][0], {"nom": "Modélisation UML", "valeur": 2, "largeur": 100})
        self.assertEqual(len(s["serie_certificats"]), stats.NB_MOIS)
        self.assertEqual(s["serie_certificats"][-1]["valeur"], 2)

    def test_formateur_ne_voit_que_ses_chiffres(self):
        self.certificat()
        self.certificat(cours="SQL", formateur=self.leila)
        self.assertEqual(stats.statistiques_formateur(self.karim)["certificats"]["total"], 1)

    def test_debut_mois(self):
        from datetime import date
        self.assertEqual(stats.debut_mois(date(2026, 1, 15), -1), date(2025, 12, 1))
        self.assertEqual(stats.debut_mois(date(2026, 11, 3), 2), date(2027, 1, 1))

    def test_export_csv_admin(self):
        c = self.certificat()
        url = reverse("certificates:export_csv")
        self.client.force_login(self.karim)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(url)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        contenu = r.content.decode("utf-8-sig")
        self.assertIn(c.code_verification, contenu)
        self.assertTrue(re.match(r"^Code;Apprenant", contenu))


class ProgressionTests(Base):
    def test_sans_module_cours_les_pages_restent_utilisables(self):
        if progression.inscriptions_disponibles():
            self.skipTest("Le module cours fournit déjà les inscriptions.")
        self.assertIsNone(progression.lignes_progression(self.karim))
        self.client.force_login(self.karim)
        self.assertContains(self.client.get(reverse("certificates:index")), "Bientôt")


class ModifierViewTests(Base):
    def url(self, c):
        return reverse("certificates:modifier", args=[c.code_verification])

    def donnees(self, **extra):
        return {"titre_cours": "Modélisation UML avancée", "score": 91, "duree_heures": 30,
                "competences": "Héritage", **extra}

    def test_formateur_corrige_son_certificat(self):
        c = self.certificat(score=80)
        self.client.force_login(self.karim)
        self.assertEqual(self.client.get(self.url(c)).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url(c), self.donnees())
        self.assertRedirects(r, c.get_absolute_url())
        code = c.code_verification
        c.refresh_from_db()
        self.assertEqual((c.titre_cours, c.score, c.duree_heures), ("Modélisation UML avancée", 91, 30))
        self.assertEqual(c.code_verification, code)  # le code imprimé ne change jamais
        self.assertTrue(Notification.objects.filter(destinataire=self.yasmine, titre="Certificat mis à jour").exists())

    def test_acces_refuse_aux_autres(self):
        c = self.certificat()
        for user in (self.yasmine, self.leila, self.sami):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url(c)).status_code, 403)
            self.assertEqual(self.client.post(self.url(c), self.donnees()).status_code, 403)
        c.refresh_from_db()
        self.assertEqual(c.titre_cours, "Modélisation UML")

    def test_admin_reattribue_le_formateur(self):
        c = self.certificat()
        self.client.force_login(self.admin)
        self.client.post(self.url(c), self.donnees(formateur=self.leila.pk))
        c.refresh_from_db()
        self.assertEqual((c.formateur, c.nom_formateur), (self.leila, str(self.leila)))

    def test_formateur_ne_peut_pas_reattribuer(self):
        c = self.certificat()
        self.client.force_login(self.karim)
        self.client.post(self.url(c), self.donnees(formateur=self.leila.pk))
        c.refresh_from_db()
        self.assertEqual(c.formateur, self.karim)

    def test_titre_en_doublon_refuse(self):
        self.certificat(cours="SQL avancé")
        c = self.certificat()
        self.client.force_login(self.karim)
        r = self.client.post(self.url(c), self.donnees(titre_cours="sql AVANCÉ"))
        self.assertContains(r, "déjà un autre certificat valide")

    def test_validation_du_score(self):
        c = self.certificat(score=80)
        self.client.force_login(self.karim)
        r = self.client.post(self.url(c), self.donnees(score=150))
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.score, 80)

    def test_certificat_revoque_non_modifiable(self):
        c = self.certificat()
        services.revoquer_certificat(c, self.admin, "Fraude")
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(self.url(c), self.donnees()), c.get_absolute_url())
        c.refresh_from_db()
        self.assertEqual(c.titre_cours, "Modélisation UML")


class SupprimerViewTests(Base):
    def test_admin_supprime_apres_confirmation(self):
        c = self.certificat()
        url = reverse("certificates:supprimer", args=[c.code_verification])
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "Supprimer définitivement")
        self.assertTrue(Certificat.objects.exists())  # un GET ne supprime rien
        self.assertRedirects(self.client.post(url), reverse("certificates:index"))
        self.assertFalse(Certificat.objects.exists())
        self.assertContains(self.client.get(c.get_verification_url()), "Code inconnu")

    def test_formateur_et_apprenant_refuses(self):
        c = self.certificat()
        url = reverse("certificates:supprimer", args=[c.code_verification])
        for user in (self.karim, self.yasmine):
            self.client.force_login(user)
            self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Certificat.objects.exists())


class SecuriteEtErreursTests(Base):
    def test_post_sans_jeton_csrf_refuse(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.karim)
        r = client.post(reverse("certificates:delivrer"), {"apprenant": self.yasmine.pk, "titre_cours": "UML"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Certificat.objects.exists())

    def test_page_404_personnalisee(self):
        self.client.force_login(self.yasmine)
        r = self.client.get(reverse("certificates:detail", args=["SF-ZZZZ-ZZZZ"]))
        self.assertEqual(r.status_code, 404)
        self.assertTemplateUsed(r, "404.html")
        self.assertContains(r, "Page introuvable", status_code=404)

    def test_page_500_se_rend_sans_contexte(self):
        from django.template.loader import render_to_string
        self.assertIn("Un problème est survenu", render_to_string("500.html"))


class FiltresTests(Base):
    def test_recherche_et_statut(self):
        a = self.certificat()
        b = self.certificat(apprenant=self.amine, cours="SQL avancé")
        services.revoquer_certificat(b, self.admin, "Erreur")
        self.client.force_login(self.admin)
        url = reverse("certificates:index")
        r = self.client.get(url, {"q": "amine"})
        self.assertContains(r, b.code_verification)
        self.assertNotContains(r, a.code_verification)
        r = self.client.get(url, {"statut": Certificat.Statut.VALIDE})
        self.assertContains(r, a.code_verification)
        self.assertNotContains(r, b.code_verification)
        self.assertContains(self.client.get(url, {"q": "introuvable"}), "Aucun certificat ne correspond")
