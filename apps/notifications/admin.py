from django.contrib import admin

from .models import Conversation, Message, Notification, Rappel


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("titre", "destinataire", "type", "lue", "date_creation")
    list_filter = ("type", "lue")
    search_fields = ("titre", "message", "destinataire__email")
    raw_id_fields = ("destinataire",)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("expediteur", "contenu", "lu", "date_envoi")
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("__str__", "date_creation", "date_maj")
    filter_horizontal = ("participants",)
    inlines = [MessageInline]


@admin.register(Rappel)
class RappelAdmin(admin.ModelAdmin):
    list_display = ("titre", "destinataire", "date_envoi", "envoye", "par_email")
    list_filter = ("envoye", "par_email")
    search_fields = ("titre", "destinataire__email")
    raw_id_fields = ("destinataire",)
