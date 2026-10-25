"""
Paramètres Django du projet SkillForge.

Les valeurs sensibles sont lues depuis le fichier .env (voir .env.example).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")

DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


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
    "apps.courses",        # Emna Ben Miled — cours et modules
    "apps.quizzes",        # Mariem Ferjani — quiz et correction IA
    "apps.mentoring",      # Saif Tannoubi — mentorat et séances
    "apps.certificates",   # Mohamed Karim Kebaili — certificats et statistiques
    "apps.notifications",  # Emna Messaoudi — notifications et messagerie
    "apps.careers",        # Insertion professionnelle — offres, candidatures, recruteurs
]

THIRD_PARTY_APPS = [
    "channels",
]

# daphne doit précéder staticfiles : `runserver` sert alors HTTP et WebSockets (ASGI)
INSTALLED_APPS = ["daphne"] + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
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

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Fichiers privés (pièces jointes de la messagerie) : jamais servis directement,
# uniquement via une vue qui vérifie les droits
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# E-mails (affichés dans la console en développement)

EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DJANGO_DEFAULT_FROM_EMAIL", "SkillForge <noreply@skillforge.tn>")

# Adresse du site, utilisée pour les liens dans les e-mails de notification
SITE_URL = os.getenv("DJANGO_SITE_URL", "http://127.0.0.1:8000")


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

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "moderation": {"format": "{asctime} [Modération] {message}", "style": "{", "datefmt": "%d/%m %H:%M:%S"},
    },
    "handlers": {
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
    "loggers": {
        "apps.notifications.moderation": {
            # Pendant les tests, rien n'est affiché ni écrit (le journal reste une preuve fiable)
            "handlers": [] if TESTS_EN_COURS else ["console_moderation", "fichier_moderation"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
