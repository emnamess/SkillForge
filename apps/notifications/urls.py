from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    # Notifications
    path("", views.index, name="index"),
    path("<int:pk>/ouvrir/", views.ouvrir, name="ouvrir"),
    path("<int:pk>/supprimer/", views.supprimer, name="supprimer"),
    path("tout-marquer-lu/", views.tout_marquer_lu, name="tout_marquer_lu"),
    path("api/compteurs/", views.api_compteurs, name="api_compteurs"),

    # Messagerie
    path("messagerie/", views.messagerie, name="messagerie"),
    path("messagerie/nouvelle/", views.nouvelle_conversation, name="nouvelle_conversation"),
    path("messagerie/<int:pk>/", views.messagerie, name="conversation"),
    path("messagerie/<int:pk>/api/", views.api_messages, name="api_messages"),
]
