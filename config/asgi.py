"""
Point d'entrée ASGI de SkillForge : HTTP (Django) et WebSockets (Channels).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Initialise Django avant d'importer le code qui utilise les modèles
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.notifications.routing import websocket_urlpatterns as notifications_ws  # noqa: E402

# Chaque module qui a besoin de WebSockets ajoute ses routes ici
websocket_urlpatterns = notifications_ws

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
})
