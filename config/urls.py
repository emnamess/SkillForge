from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import home

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("comptes/", include("apps.accounts.urls")),
    path("cours/", include("apps.courses.urls")),
    path("quiz/", include("apps.quizzes.urls")),
    path("mentorat/", include("apps.mentoring.urls")),
    path("certificats/", include("apps.certificates.urls")),
    path("notifications/", include("apps.notifications.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
