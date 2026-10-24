from django.urls import path

from . import views

app_name = "quizzes"

urlpatterns = [
    # Page principale
    path("", views.index, name="index"),

    # CRUD Quiz (formateur)
    path("creer/", views.quiz_creer, name="quiz_creer"),
    path("<int:pk>/", views.quiz_detail, name="quiz_detail"),
    path("<int:pk>/modifier/", views.quiz_modifier, name="quiz_modifier"),
    path("<int:pk>/supprimer/", views.quiz_supprimer, name="quiz_supprimer"),

    # Gestion des questions (formateur)
    path("<int:pk>/questions/", views.questions_gerer, name="questions_gerer"),
    path("<int:pk>/questions/ajouter/", views.question_ajouter, name="question_ajouter"),
    path("<int:pk>/questions/generer-ia/", views.quiz_generer_ia, name="quiz_generer_ia"),
    path("<int:pk>/questions/<int:question_pk>/modifier/", views.question_modifier, name="question_modifier"),
    path("<int:pk>/questions/<int:question_pk>/supprimer/", views.question_supprimer, name="question_supprimer"),

    # Résultats (formateur)
    path("<int:pk>/resultats/", views.quiz_resultats, name="quiz_resultats"),

    # Passer un quiz (apprenant)
    path("<int:pk>/passer/", views.passer_quiz, name="passer_quiz"),

    # Tentatives
    path("tentative/<int:pk>/", views.tentative_detail, name="tentative_detail"),
    path("tentative/<int:pk>/recorriger/", views.tentative_recorriger, name="tentative_recorriger"),
    path("mes-tentatives/", views.mes_tentatives, name="mes_tentatives"),
]
