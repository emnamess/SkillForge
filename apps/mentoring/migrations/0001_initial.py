# Generated for the mentoring app.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Disponibilite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("debut", models.DateTimeField(verbose_name="début")),
                ("fin", models.DateTimeField(verbose_name="fin")),
                ("duree_seance", models.PositiveSmallIntegerField(choices=[(30, "30 minutes"), (45, "45 minutes"), (60, "1 heure"), (90, "1 h 30")], default=60, verbose_name="durée d’une séance (minutes)")),
                ("active", models.BooleanField(default=True, verbose_name="active")),
                ("date_creation", models.DateTimeField(auto_now_add=True, verbose_name="créée le")),
                ("formateur", models.ForeignKey(limit_choices_to={"role": "formateur"}, on_delete=django.db.models.deletion.CASCADE, related_name="disponibilites_mentorat", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "disponibilité de mentorat", "verbose_name_plural": "disponibilités de mentorat", "ordering": ["debut"]},
        ),
        migrations.CreateModel(
            name="SeanceMentorat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("debut", models.DateTimeField(verbose_name="début")),
                ("fin", models.DateTimeField(verbose_name="fin")),
                ("sujet", models.CharField(max_length=160, verbose_name="sujet")),
                ("description", models.TextField(blank=True, verbose_name="description")),
                ("lien_visio", models.URLField(blank=True, verbose_name="lien de visioconférence")),
                ("statut", models.CharField(choices=[("en_attente", "En attente de confirmation"), ("confirmee", "Confirmée"), ("annulee", "Annulée"), ("terminee", "Terminée")], default="en_attente", max_length=12, verbose_name="statut")),
                ("date_creation", models.DateTimeField(auto_now_add=True, verbose_name="demandée le")),
                ("date_modification", models.DateTimeField(auto_now=True, verbose_name="modifiée le")),
                ("apprenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="seances_mentorat_apprenant", to=settings.AUTH_USER_MODEL, verbose_name="apprenant")),
                ("disponibilite", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="seances", to="mentoring.disponibilite", verbose_name="créneau")),
                ("formateur", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="seances_mentorat_formateur", to=settings.AUTH_USER_MODEL, verbose_name="formateur")),
            ],
            options={"verbose_name": "séance de mentorat", "verbose_name_plural": "séances de mentorat", "ordering": ["debut"]},
        ),
        migrations.AddConstraint(
            model_name="disponibilite",
            constraint=models.CheckConstraint(condition=models.Q(fin__gt=models.F("debut")), name="mentoring_disponibilite_intervalle_valide"),
        ),
        migrations.AddConstraint(
            model_name="disponibilite",
            constraint=models.CheckConstraint(condition=models.Q(duree_seance__in=(30, 45, 60, 90)), name="mentoring_disponibilite_duree_valide"),
        ),
        migrations.AddConstraint(
            model_name="seancementorat",
            constraint=models.CheckConstraint(condition=models.Q(fin__gt=models.F("debut")), name="mentoring_seance_intervalle_valide"),
        ),
        migrations.AddConstraint(
            model_name="seancementorat",
            constraint=models.UniqueConstraint(condition=models.Q(statut__in=("en_attente", "confirmee")), fields=("disponibilite", "debut"), name="mentoring_seance_creneau_unique_actif"),
        ),
        migrations.AddIndex(
            model_name="seancementorat",
            index=models.Index(fields=["formateur", "debut", "fin"], name="mentoring_s_formate_b59c47_idx"),
        ),
        migrations.AddIndex(
            model_name="seancementorat",
            index=models.Index(fields=["apprenant", "debut"], name="mentoring_s_apprena_439c32_idx"),
        ),
    ]
