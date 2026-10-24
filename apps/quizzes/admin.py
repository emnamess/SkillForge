from django.contrib import admin

from .models import Choix, Question, Quiz, Reponse, Tentative


class ChoixInline(admin.TabularInline):
    model = Choix
    extra = 2


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    show_change_link = True
    fields = ("ordre", "type", "enonce", "points")


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("titre", "formateur", "est_publie", "nombre_questions", "date_creation")
    list_filter = ("est_publie", "date_creation")
    search_fields = ("titre", "description")
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "quiz", "type", "points", "ordre")
    list_filter = ("type", "quiz")
    inlines = [ChoixInline]


class ReponseInline(admin.TabularInline):
    model = Reponse
    extra = 0
    readonly_fields = ("question", "choix_selectionne", "texte_libre", "est_correcte",
                       "points_obtenus", "feedback_ia", "corrigee")


@admin.register(Tentative)
class TentativeAdmin(admin.ModelAdmin):
    list_display = ("apprenant", "quiz", "score", "score_total", "pourcentage", "reussie", "date_debut")
    list_filter = ("reussie", "terminee", "quiz")
    search_fields = ("apprenant__username", "apprenant__email")
    inlines = [ReponseInline]
