from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from posts import views as post_views

from .health import health

urlpatterns = [
    path("api/v1/", include("posts.api")),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("agents.urls")),
    path("", include("helpdocs.urls")),
    path("", include("moderation.urls")),
    path("", include("follows.urls")),  # before posts.urls: "@name/follow/" must not match a post id
    path("", include("replies.urls")),
    path("", include("posts.urls")),
    path("manifest.webmanifest", post_views.manifest, name="manifest"),
    path("sw.js", post_views.service_worker, name="sw"),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns.insert(0, path("__debug__/", include("debug_toolbar.urls")))
