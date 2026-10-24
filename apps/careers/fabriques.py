"""Fabriques d'objets pour les tests de l'Espace Carrière (et un générateur de PDF minimal)."""

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User

from .models import Competence, CompetenceApprenant, CompetenceRequise, Offre, ProfilCarriere, ProfilEntreprise

MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize(), **extra)


def creer_recruteur(email, statut=ProfilEntreprise.Statut.VALIDEE, nom=None):
    user = creer(email, role=User.Role.RECRUTEUR)
    ProfilEntreprise.objects.create(utilisateur=user, nom=nom or f"Entreprise {user.first_name}",
                                    secteur="Informatique", ville="Tunis", statut=statut)
    return user


def creer_admin(email="admin@test.tn"):
    return User.objects.create_superuser(User.generer_username(email), email, MDP)


def competence(nom, alias=""):
    return Competence.objects.get_or_create(nom=nom, defaults={"alias": alias})[0]


def creer_offre(recruteur, titre="Data analyst", statut=Offre.Statut.PUBLIEE, exigences=(), **extra):
    """`exigences` : [(Competence, niveau_requis, obligatoire), ...]"""
    extra.setdefault("type_contrat", "stage_pfe")
    extra.setdefault("ville", "Tunis")
    offre = Offre.objects.create(entreprise=recruteur.profil_entreprise, titre=titre, description="Description",
                                 statut=statut, **extra)
    for c, niveau, obligatoire in exigences:
        CompetenceRequise.objects.create(offre=offre, competence=c, niveau_requis=niveau, obligatoire=obligatoire)
    return offre


def donner_competences(apprenant, niveaux):
    """`niveaux` : {Competence: niveau}"""
    profil, _ = ProfilCarriere.objects.get_or_create(apprenant=apprenant)
    for c, niveau in niveaux.items():
        CompetenceApprenant.objects.update_or_create(profil=profil, competence=c, defaults={"niveau": niveau})
    return profil


def pdf_octets(texte=""):
    """PDF valide d'une page, avec le texte donné (ASCII) écrit en Helvetica, ou vide."""
    flux = f"BT /F1 12 Tf 72 720 Td ({texte}) Tj ET".encode() if texte else b""
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(flux) + flux + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    contenu = b"%PDF-1.4\n"
    positions = []
    for i, objet in enumerate(objets, start=1):
        positions.append(len(contenu))
        contenu += b"%d 0 obj\n" % i + objet + b"\nendobj\n"
    debut_xref = len(contenu)
    contenu += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objets) + 1)
    contenu += b"".join(b"%010d 00000 n \n" % p for p in positions)
    contenu += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objets) + 1, debut_xref)
    return contenu


def fichier_pdf(texte="", nom="cv.pdf"):
    return SimpleUploadedFile(nom, pdf_octets(texte), content_type="application/pdf")
