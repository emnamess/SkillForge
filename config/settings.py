"""
Paramètres Django du projet SkillForge.

Les valeurs sensibles sont lues depuis le fichier .env (voir .env.example).
"""

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

CLE_DEV = "django-insecure-dev-only-change-me"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", CLE_DEV)
if not DEBUG and SECRET_KEY in ("", CLE_DEV, "change-me"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY doit être défini en production (DJANGO_DEBUG=False).")

# Domaine public fourni automatiquement par l'hébergeur
# (Render : skillforge.onrender.com, Railway : skillforge-production.up.railway.app)
DOMAINE_PUBLIC = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("RAILWAY_PUBLIC_DOMAIN", "")

ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
if DOMAINE_PUBLIC:
    ALLOWED_HOSTS.append(DOMAINE_PUBLIC)

CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if DOMAINE_PUBLIC:
    CSRF_TRUSTED_ORIGINS.append(f"https://{DOMAINE_PUBLIC}")

# Dossier des données persistantes (fichiers déposés, journaux).
# En local : la racine du projet ; en production : le volume monté (ex. /data).
DATA_DIR = Path(os.getenv("DJANGO_DATA_DIR", BASE_DIR))


# Applications

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

# Un module par membre de l'équipe
LOCAL_APPS = [
    "apps.accounts",       # Utilisateurs et rôles
    "apps.courses",        # Cours et modules
    "apps.quizzes",        # Quiz et correction IA
    "apps.mentoring",      # Mentorat et séances
    "apps.certificates",   # Certificats et statistiques
    "apps.notifications",  # Notifications et messagerie
    "apps.careers",        # Insertion professionnelle — offres, candidatures, recruteurs
]

THIRD_PARTY_APPS = [
    "channels",
]

# daphne doit précéder staticfiles : `runserver` sert alors HTTP et WebSockets (ASGI)
INSTALLED_APPS = ["daphne"] + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # sert les fichiers statiques en production
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Temps réel (Django Channels)
# Sans REDIS_URL, une couche en mémoire suffit pour le développement (un seul processus).

REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


# Base de données
# SQLite en local ; PostgreSQL dès que DATABASE_URL est défini (fourni par Railway).
# Connexions non persistantes (conn_max_age=0) : recommandé avec un serveur ASGI.

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=0, conn_health_checks=True,
    )
}


# Authentification

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrUsernameBackend"]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalisation

LANGUAGE_CODE = "fr-fr"

TIME_ZONE = "Africa/Tunis"

USE_I18N = True

USE_TZ = True


# Fichiers statiques et médias

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# En production, fichiers compressés et versionnés (collectstatic) ; en local, comportement par défaut
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

# Fichiers privés (pièces jointes de la messagerie) : jamais servis directement,
# uniquement via une vue qui vérifie les droits
PRIVATE_MEDIA_ROOT = DATA_DIR / "private_media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# E-mails (affichés dans la console en développement ; SMTP en production si EMAIL_HOST est défini)

EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DJANGO_DEFAULT_FROM_EMAIL", "SkillForge <noreply@skillforge.tn>")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_TIMEOUT = 10

# Adresse du site, utilisée pour les liens dans les e-mails de notification
SITE_URL = os.getenv("DJANGO_SITE_URL") or (
    f"https://{DOMAINE_PUBLIC}" if DOMAINE_PUBLIC else "http://127.0.0.1:8000")


# Sécurité en production (HTTPS assuré par le proxy de Railway)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Redirection HTTPS déjà faite par Railway ; HSTS inutile (et risqué) sur un domaine de démonstration
    SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008"]


# Messagerie : pièces jointes

PIECE_JOINTE_TAILLE_MAX = 10 * 1024 * 1024  # 10 Mo
PIECE_JOINTE_EXTENSIONS = [
    "pdf", "png", "jpg", "jpeg", "gif", "webp",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "txt", "md", "csv",
    "zip", "py", "sql", "ipynb", "json",
]
DATA_UPLOAD_MAX_MEMORY_SIZE = PIECE_JOINTE_TAILLE_MAX + 1024 * 1024


# Modération IA des messages (Google Gemini)
# Sans clé API, la modération se replie sur des règles locales.

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# Niveau de réflexion du modèle (minimal, low, medium, high) ; vide pour la valeur par défaut du modèle
GEMINI_REFLEXION = os.getenv("GEMINI_REFLEXION", "minimal").upper() or None
MODERATION_IA_ACTIVE = os.getenv("MODERATION_IA_ACTIVE", "True") == "True"
MODERATION_TIMEOUT = max(10, int(os.getenv("MODERATION_TIMEOUT", "15")))  # secondes (minimum imposé par l'API : 10)


# Journaux : chaque décision de modération (Gemini, cache ou règles locales)
# s'affiche dans la console et est écrite dans logs/moderation.log

TESTS_EN_COURS = len(sys.argv) > 1 and sys.argv[1] == "test"

LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "moderation": {"format": "{asctime} [Modération] {message}", "style": "{", "datefmt": "%d/%m %H:%M:%S"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "console_moderation": {"class": "logging.StreamHandler", "formatter": "moderation"},
        "fichier_moderation": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "moderation.log",
            "maxBytes": 1024 * 1024,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "moderation",
        },
    },
    # Avertissements et erreurs (ex. erreur 500) visibles dans les journaux de Railway
    # (en local, Django les affiche déjà lui-même)
    "root": {"handlers": [] if DEBUG else ["console"], "level": "WARNING"},
    "loggers": {
        "apps.notifications.moderation": {
            # Pendant les tests, rien n'est affiché ni écrit (le journal reste une preuve fiable)
            "handlers": [] if TESTS_EN_COURS else ["console_moderation", "fichier_moderation"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
