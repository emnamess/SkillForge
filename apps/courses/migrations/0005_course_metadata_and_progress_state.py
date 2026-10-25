import django.core.validators
import django.utils.timezone
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import migrations, models
from django.utils.text import slugify

import apps.courses.models as course_models


def populate_course_slugs(apps, schema_editor):
    Course = apps.get_model("courses", "Cours")
    used = set()
    for course in Course.objects.order_by("pk").iterator():
        base = slugify(course.titre)[:200] or f"cours-{course.pk}"
        slug, suffix = base, 2
        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)
        Course.objects.filter(pk=course.pk).update(slug=slug)


def mark_existing_progress_complete(apps, schema_editor):
    Progress = apps.get_model("courses", "LessonProgress")
    Progress.objects.filter(date_terminaison__isnull=False).update(etat="terminee")


def populate_unique_lesson_slugs(apps, schema_editor):
    Lesson = apps.get_model("courses", "Lesson")
    used_by_module = {}
    for lesson in Lesson.objects.order_by("module_id", "pk").iterator():
        used = used_by_module.setdefault(lesson.module_id, set())
        base = slugify(lesson.slug or lesson.titre)[:200] or f"lecon-{lesson.pk}"
        slug, suffix = base, 2
        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)
        Lesson.objects.filter(pk=lesson.pk).update(slug=slug)


def move_legacy_course_files_private(apps, schema_editor):
    Content = apps.get_model("courses", "LessonContent")
    private = course_models.CourseResourceStorage()
    db = schema_editor.connection.alias
    for block in Content.objects.using(db).exclude(fichier="").iterator():
        old_name = block.fichier.name
        if not old_name.startswith("cours/ressources/") or not default_storage.exists(old_name):
            continue
        new_name = "ressources/" + old_name.rsplit("/", 1)[-1]
        with default_storage.open(old_name, "rb") as source:
            saved_name = private.save(new_name, File(source))
        Content.objects.using(db).filter(pk=block.pk).update(fichier=saved_name)
        default_storage.delete(old_name)


def restore_legacy_course_files_public(apps, schema_editor):
    Content = apps.get_model("courses", "LessonContent")
    private = course_models.CourseResourceStorage()
    db = schema_editor.connection.alias
    for block in Content.objects.using(db).exclude(fichier="").iterator():
        private_name = block.fichier.name
        if not private_name.startswith("ressources/") or not private.exists(private_name):
            continue
        old_name = "cours/ressources/" + private_name.rsplit("/", 1)[-1]
        with private.open(private_name, "rb") as source:
            saved_name = default_storage.save(old_name, File(source))
        Content.objects.using(db).filter(pk=block.pk).update(fichier=saved_name)
        private.delete(private_name)


class Migration(migrations.Migration):
    dependencies = [("courses", "0004_inscription_derniere_lecon_and_more")]

    operations = [
        migrations.AddField(
            model_name="cours", name="slug",
            field=models.SlugField(blank=True, max_length=220, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="cours", name="objectifs", field=models.TextField(blank=True, verbose_name="objectifs pédagogiques"),
        ),
        migrations.AddField(
            model_name="cours", name="categorie", field=models.CharField(blank=True, max_length=80, verbose_name="catégorie"),
        ),
        migrations.AddField(
            model_name="cours", name="image_couverture",
            field=models.FileField(blank=True, upload_to="cours/couvertures/", validators=[
                django.core.validators.FileExtensionValidator(["png", "jpg", "jpeg", "webp"]),
                course_models.valider_image_couverture,
            ], verbose_name="image de couverture"),
        ),
        migrations.AddField(
            model_name="cours", name="ordre", field=models.PositiveIntegerField(default=0, verbose_name="ordre d'affichage"),
        ),
        migrations.RunPython(populate_course_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="cours", name="slug", field=models.SlugField(blank=True, max_length=220, unique=True),
        ),
        migrations.AddIndex(
            model_name="cours", index=models.Index(fields=["est_publie", "ordre"], name="cours_publication_ordre_idx"),
        ),
        migrations.AddField(
            model_name="module", name="date_creation",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name="date de création"), preserve_default=False,
        ),
        migrations.AddField(
            model_name="module", name="date_modification",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now, verbose_name="dernière modification"), preserve_default=False,
        ),
        migrations.RunPython(populate_unique_lesson_slugs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="lesson", constraint=models.UniqueConstraint(fields=("module", "slug"), name="lesson_slug_unique_per_module"),
        ),
        migrations.AddField(
            model_name="lessonprogress", name="etat",
            field=models.CharField(choices=[("en_cours", "En cours"), ("terminee", "Terminée")], default="en_cours", max_length=12),
        ),
        migrations.AddField(
            model_name="lessonprogress", name="date_debut",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now), preserve_default=False,
        ),
        migrations.AddField(
            model_name="lessonprogress", name="derniere_consultation",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now), preserve_default=False,
        ),
        migrations.RunPython(mark_existing_progress_complete, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lessonprogress", name="date_terminaison", field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(move_legacy_course_files_private, restore_legacy_course_files_public),
        migrations.AlterField(
            model_name="lessoncontent", name="fichier",
            field=models.FileField(blank=True, storage=course_models.CourseResourceStorage(), upload_to="ressources/", validators=[
                django.core.validators.FileExtensionValidator(["pdf", "docx", "doc", "png", "jpg", "jpeg", "gif", "webp", "mp4", "webm"]),
                course_models.valider_fichier_cours,
            ]),
        ),
    ]
