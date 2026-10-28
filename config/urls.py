from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from posts import views as post_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("agents.urls")),
    path("", include("posts.urls")),
    path("manifest.webmanifest", post_views.manifest, name="manifest"),
    path("sw.js", post_views.service_worker, name="sw"),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns.insert(0, path("__debug__/", include("debug_toolbar.urls")))
