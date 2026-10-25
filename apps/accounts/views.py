from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import admin_required
from .forms import FiltreUtilisateursForm, GestionUtilisateurForm, InscriptionForm, ProfilForm
from .models import User


def home(request):
    """Page d'accueil publique : vitrine de chaque module avec des chiffres réels."""
    from apps.careers.views import offres_ouvertes
    from apps.certificates.models import Certificat
    from apps.courses.models import Cours

    cours_publies = Cours.objects.filter(est_publie=True)
    offres = offres_ouvertes()
    return render(request, "home.html", {
        "chiffres": {
            "cours": cours_publies.count(),
            "apprenants": User.objects.filter(role=User.Role.APPRENANT, is_active=True).count(),
            "certificats": Certificat.objects.filter(statut=Certificat.Statut.VALIDE).count(),
            "offres": offres.count(),
        },
        "cours_populaires": cours_publies.select_related("formateur").annotate(
            nb_inscrits=Count("inscriptions", distinct=True), nb_modules=Count("modules", distinct=True),
        ).order_by("-nb_inscrits", "titre")[:6],
        "formateurs": User.objects.filter(role=User.Role.FORMATEUR, est_valide=True, is_active=True).annotate(
            nb_cours=Count("cours_crees", filter=Q(cours_crees__est_publie=True), distinct=True),
        ).order_by("-nb_cours")[:3],
        "offres_recentes": offres.order_by("-date_publication")[:3],
    })


def inscription(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    form = InscriptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        if user.en_attente_validation:
            messages.info(request, "Votre compte formateur est créé. Un administrateur doit le valider "
                                   "avant que vous puissiez publier des cours.")
        else:
            messages.success(request, f"Bienvenue sur SkillForge, {user.first_name} !")
        return redirect("accounts:dashboard")

    return render(request, "accounts/inscription.html", {"form": form})


@login_required
def dashboard(request):
    return render(request, "accounts/dashboard.html")


@login_required
def profil(request):
    form = ProfilForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votre profil a été mis à jour.")
        return redirect("accounts:profil")
    return render(request, "accounts/profil.html", {"form": form})


# ---------- Gestion des utilisateurs (administrateur) ----------

@admin_required
def utilisateurs(request):
    filtres = FiltreUtilisateursForm(request.GET or None)
    qs = User.objects.all()

    if filtres.is_valid():
        q = filtres.cleaned_data["q"]
        role = filtres.cleaned_data["role"]
        statut = filtres.cleaned_data["statut"]
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q)
                           | Q(email__icontains=q) | Q(username__icontains=q))
        if role:
            qs = qs.filter(role=role)
        if statut == "actif":
            qs = qs.filter(is_active=True)
        elif statut == "inactif":
            qs = qs.filter(is_active=False)
        elif statut == "attente":
            qs = qs.filter(role=User.Role.FORMATEUR, est_valide=False)

    stats = User.objects.aggregate(
        total=Count("id"),
        apprenants=Count("id", filter=Q(role=User.Role.APPRENANT)),
        formateurs=Count("id", filter=Q(role=User.Role.FORMATEUR)),
        en_attente=Count("id", filter=Q(role=User.Role.FORMATEUR, est_valide=False)),
    )

    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "accounts/utilisateurs.html", {
        "filtres": filtres,
        "page": page,
        "stats": stats,
        "params": params.urlencode(),
    })


@admin_required
def utilisateur_detail(request, pk):
    cible = get_object_or_404(User, pk=pk)
    form = GestionUtilisateurForm(request.POST or None, instance=cible)

    if request.method == "POST" and form.is_valid():
        if cible == request.user and (not form.cleaned_data["is_active"]
                                      or form.cleaned_data["role"] != User.Role.ADMINISTRATEUR):
            messages.error(request, "Vous ne pouvez pas retirer vos propres droits d'administrateur.")
        else:
            form.save()
            messages.success(request, f"Le compte de {cible} a été mis à jour.")
            return redirect("accounts:utilisateurs")

    return render(request, "accounts/utilisateur_detail.html", {"cible": cible, "form": form})


@require_POST
@admin_required
def valider_formateur(request, pk):
    cible = get_object_or_404(User, pk=pk, role=User.Role.FORMATEUR)
    cible.est_valide = True
    cible.save(update_fields=["est_valide"])
    messages.success(request, f"{cible} est maintenant formateur validé.")
    return redirect(request.POST.get("next") or "accounts:utilisateurs")


@require_POST
@admin_required
def basculer_actif(request, pk):
    cible = get_object_or_404(User, pk=pk)
    if cible == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
    else:
        cible.is_active = not cible.is_active
        cible.save(update_fields=["is_active"])
        etat = "réactivé" if cible.is_active else "désactivé"
        messages.success(request, f"Le compte de {cible} a été {etat}.")
    return redirect(request.POST.get("next") or "accounts:utilisateurs")
