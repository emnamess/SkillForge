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


# ---------- Moteur de recommandation (IA) ----------

from django.core.cache import cache as cache_django  # noqa: E402

from . import recommandation  # noqa: E402
from .demo import CATALOGUE, creer_apprenants_simules  # noqa: E402


class RecommandationModeleTests(TestCase):
    """Tests du modèle seul, sur des données construites à la main (pas de base de données)."""

    def setUp(self):
        self.catalogue = {
            "uml": recommandation.Cours("uml", "UML", ["Diagramme de classes", "Héritage"]),
            "patterns": recommandation.Cours("patterns", "Design patterns", ["Héritage", "Patrons de conception"]),
            "sql": recommandation.Cours("sql", "SQL", ["Jointures", "Index"]),
            "bd": recommandation.Cours("bd", "Bases de données", ["Modèle relationnel", "Normalisation"]),
            "ml": recommandation.Cours("ml", "Machine learning", ["Classification", "Régression", "Python data"]),
        }
        # Les apprenants 1 à 4 enchaînent BD puis SQL ; 5 et 6 font UML puis Design patterns
        couples = [(u, c) for u in (1, 2, 3, 4) for c in ("bd", "sql")] + [(5, "uml"), (5, "patterns"),
                                                                           (6, "uml"), (6, "patterns"), (7, "bd")]
        self.modele = recommandation.ModeleRecommandation(self.catalogue, couples, alpha=0.5)

    def titres(self, *args, **kwargs):
        return [r.titre for r in self.modele.recommander(*args, **kwargs)]

    def test_collaboratif_apprend_les_parcours(self):
        self.assertEqual(self.modele.classement(["bd"], methode="collaboratif")[0][0], "sql")

    def test_contenu_utilise_les_competences_communes(self):
        self.assertEqual(self.modele.classement(["uml"], methode="contenu")[0][0], "patterns")

    def test_hybride_recommande_et_explique(self):
        recos = self.modele.recommander({"uml"})
        self.assertEqual(recos[0].titre, "Design patterns")
        self.assertEqual(recos[0].source, "hybride")
        self.assertTrue(any("Héritage" in r for r in recos[0].raisons))
        self.assertTrue(any("100 % des apprenants" in r for r in recos[0].raisons))
        self.assertEqual(recos[0].competences_nouvelles, ["Patrons de conception"])

    def test_n_exclut_jamais_un_cours_deja_obtenu(self):
        for deja in ({"bd"}, {"uml", "patterns"}, {"bd", "sql", "uml"}):
            self.assertFalse(set(self.titres(deja, k=5)) & {self.catalogue[c].titre for c in deja})

    def test_profil_seul_suffit(self):
        self.assertEqual(self.titres(set(), "Je veux apprendre le machine learning et la classification")[0],
                         "Machine learning")

    def test_demarrage_a_froid_sans_rien(self):
        recos = self.modele.recommander(set(), "")
        self.assertEqual(recos[0].source, "populaires")
        self.assertEqual(recos[0].titre, "Bases de données")  # le cours le plus obtenu

    def test_scores_bornes_et_k_respecte(self):
        recos = self.modele.recommander({"bd"}, k=2)
        self.assertEqual(len(recos), 2)
        self.assertTrue(all(0 <= r.score <= 1 for r in recos))

    def test_catalogue_vide(self):
        modele = recommandation.ModeleRecommandation({}, [])
        self.assertEqual(modele.recommander(set()), [])


class RecommandationIntegrationTests(Base):
    def setUp(self):
        super().setUp()
        cache_django.clear()
        comptes = {"karim": self.karim, "leila": self.leila}
        creer_apprenants_simules(comptes, nombre=24)

    def test_catalogue_construit_depuis_les_certificats(self):
        catalogue = recommandation.construire_catalogue(list(Certificat.objects.all()))
        self.assertTrue(set(catalogue) <= {Certificat.normaliser_titre(t) for t in CATALOGUE})
        sql = catalogue[Certificat.normaliser_titre("SQL avancé")]
        self.assertEqual(set(sql.competences), set(CATALOGUE["SQL avancé"]))

    def test_api_json(self):
        self.certificat(cours="Modélisation UML", competences=CATALOGUE["Modélisation UML"])
        self.client.force_login(self.yasmine)
        r = self.client.get(reverse("certificates:recommandations"))
        self.assertEqual(r.status_code, 200)
        donnees = r.json()
        self.assertEqual(len(donnees["recommandations"]), 3)
        self.assertEqual(donnees["source"], "hybride")
        self.assertNotIn("Modélisation UML", [x["titre"] for x in donnees["recommandations"]])
        self.assertIn("Design patterns", [x["titre"] for x in donnees["recommandations"]])
        self.assertIsInstance(donnees["duree_ms"], float)

    def test_api_exige_connexion(self):
        self.assertEqual(self.client.get(reverse("certificates:recommandations")).status_code, 302)

    def test_api_erreur_moteur_message_clair(self):
        from unittest import mock
        self.client.force_login(self.yasmine)
        # assertLogs capture le journal d'erreur attendu (et vérifie qu'il est bien écrit) au lieu de l'afficher
        with mock.patch.object(recommandation, "recommandations_pour", side_effect=RuntimeError("panne")), \
                self.assertLogs("apps.certificates.views", level="ERROR") as journal:
            r = self.client.get(reverse("certificates:recommandations"))
        self.assertIn("Échec du moteur de recommandation", journal.output[0])
        self.assertEqual(r.status_code, 503)
        self.assertIn("indisponibles", r.json()["erreur"])

    def test_modele_mis_en_cache_et_reentraine_si_donnees_changent(self):
        premier = recommandation.modele_courant()
        self.assertIs(recommandation.modele_courant(), premier)
        self.certificat(cours="Nouveau cours", competences=["Compétence inédite"])
        self.assertIsNot(recommandation.modele_courant(), premier)

    def test_evaluation_metriques_coherentes(self):
        res = recommandation.evaluer(repetitions=2)
        self.assertGreater(res["nb_apprenants_testes"], 5)
        methodes = {m["methode"]: m for m in res["methodes"]}
        self.assertEqual(set(methodes), {"populaires", "contenu", "collaboratif", "hybride"})
        for m in methodes.values():
            self.assertTrue(0 <= m["precision"] <= m["hit_rate"] <= 1)
            self.assertAlmostEqual(m["precision"], m["hit_rate"] / res["k"])
            self.assertTrue(0 <= m["ndcg"] <= m["hit_rate"])
        # Sur des parcours structurés, le modèle doit battre la référence naïve
        self.assertGreater(methodes["hybride"]["hit_rate"], methodes["populaires"]["hit_rate"])

    def test_evaluation_demarrage_a_froid(self):
        res = recommandation.evaluer_demarrage_a_froid()
        self.assertGreater(res["nb_apprenants_testes"], 0)
        self.assertEqual([m["methode"] for m in res["methodes"]], ["populaires", "hybride"])

    def test_page_performance_admin_seulement(self):
        url = reverse("certificates:performance_recommandations")
        for user in (self.yasmine, self.karim):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(url)
        self.assertContains(r, "HitRate@3")
        self.assertContains(r, "Hybride (modèle utilisé)")
        self.assertContains(r, "Nouvel apprenant")

    def test_page_mes_certificats_contient_la_zone_ia(self):
        self.client.force_login(self.yasmine)
        r = self.client.get(reverse("certificates:index"))
        self.assertContains(r, "Certifications recommandées pour vous")
        self.assertContains(r, reverse("certificates:recommandations"))


class RecommandationSansDonneesTests(Base):
    def test_page_performance_sans_donnees(self):
        cache_django.clear()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("certificates:performance_recommandations")),
                            "Pas assez de données")

    def test_api_sans_aucun_certificat(self):
        self.client.force_login(self.yasmine)
        self.assertEqual(self.client.get(reverse("certificates:recommandations")).json()["recommandations"], [])


# ---------- QR code, filtre de période, lien Statistiques du menu ----------

class QrCodeTests(Base):
    def test_qr_code_sur_le_certificat(self):
        c = self.certificat()
        self.client.force_login(self.yasmine)
        r = self.client.get(c.get_absolute_url())
        self.assertContains(r, 'class="certificat-qr-image"')
        self.assertContains(r, "QR code de vérification du certificat")
        self.assertContains(r, "Scannez pour vérifier")

    def test_qr_code_encode_la_page_de_verification(self):
        import segno
        from .views import qr_code_svg
        url = "http://testserver/certificats/verifier/SF-ABCD-EFGH/"
        svg = qr_code_svg(url)
        self.assertTrue(svg.startswith("<svg"))
        # Même contenu encodé que le QR code de référence pour cette URL
        self.assertIn(segno.make(url, error="m").svg_inline(scale=3, border=2, dark="#231f5c", light="#ffffff",
                                                            omitsize=True).split('d="')[1][:200], svg)


class FiltrePeriodeTests(Base):
    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from django.utils import timezone
        self.recent = self.certificat(cours="Récent", score=90)
        self.ancien = self.certificat(cours="Ancien", score=60)
        Certificat.objects.filter(pk=self.ancien.pk).update(date_delivrance=timezone.now() - timedelta(days=60))
        self.url = reverse("certificates:statistiques")

    def test_periode_change_les_chiffres(self):
        trente = stats.statistiques_plateforme(stats.periode_depuis("30j"))
        six = stats.statistiques_plateforme(stats.periode_depuis("6m"))
        self.assertEqual(trente["certificats"]["periode_delivres"], 1)
        self.assertEqual(trente["certificats"]["periode_score"], 90)
        self.assertEqual(six["certificats"]["periode_delivres"], 2)
        self.assertEqual(six["certificats"]["periode_score"], 75)
        # Le total des certificats valides ne dépend pas de la période
        self.assertEqual(trente["certificats"]["total"], six["certificats"]["total"])
        self.assertEqual([l["nom"] for l in trente["top_cours"]], ["Récent"])

    def test_series_selon_la_periode(self):
        self.assertEqual(len(stats.statistiques_plateforme(stats.periode_depuis("30j"))["serie_certificats"]), 30)
        self.assertEqual(len(stats.statistiques_plateforme(stats.periode_depuis("6m"))["serie_certificats"]), 6)
        self.assertEqual(len(stats.statistiques_plateforme(stats.periode_depuis("12m"))["serie_certificats"]), 12)
        serie = stats.statistiques_plateforme(stats.periode_depuis("30j"))["serie_certificats"]
        self.assertEqual(serie[-1]["valeur"], 1)  # le certificat récent, aujourd'hui
        self.assertEqual(sum(p["valeur"] for p in serie), 1)

    def test_page_et_periode_inconnue(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {"periode": "30j"})
        self.assertContains(r, 'aria-current="page">30 derniers jours')
        r = self.client.get(self.url, {"periode": "n_importe_quoi"})
        self.assertEqual(r.context["periode"].code, stats.PERIODE_PAR_DEFAUT)

    def test_formateur_filtre_aussi(self):
        self.client.force_login(self.karim)
        r = self.client.get(self.url, {"periode": "30j"})
        self.assertEqual(r.context["certificats"]["periode_delivres"], 1)


class LienMenuStatistiquesTests(Base):
    def test_visible_pour_admin_et_formateur_valide(self):
        lien = f'href="{reverse("certificates:statistiques")}"'
        for user, visible in ((self.admin, True), (self.karim, True), (self.yasmine, False), (self.sami, False)):
            self.client.force_login(user)
            r = self.client.get(reverse("accounts:dashboard"))
            (self.assertContains if visible else self.assertNotContains)(r, lien)
