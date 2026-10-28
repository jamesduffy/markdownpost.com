from django.urls import path, register_converter

from . import views
from .converters import SafeStringConverter

register_converter(SafeStringConverter, "safe")

urlpatterns = [
    path("", views.discover, name="discover"),
    path("discover/", views.discover),
    path("new/", views.new_post, name="new_post"),
    path("drafts/", views.drafts, name="drafts"),
    path("offline/", views.offline, name="offline"),
    path("p/<safe:post_id>/", views.legacy_post_url),
    path("@<safe:username>/", views.profile, name="profile"),
    path("@<safe:username>/<safe:post_id>/", views.post_detail, name="post_detail"),
    path("@<safe:username>/<safe:post_id>/edit/", views.edit_post, name="edit_post"),
    path("@<safe:username>/<safe:post_id>/raw/", views.post_raw, name="post_raw"),
    path("@<safe:username>/<safe:post_id>/draft/", views.draft_post, name="draft_post"),
    path("@<safe:username>/<safe:post_id>/delete/", views.delete_post, name="delete_post"),
    path("api/posts/", views.api_create, name="api_create"),
    path("api/posts/<safe:post_id>/", views.api_update, name="api_update"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("media/<path:key>", views.media, name="media"),
]
