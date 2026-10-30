from django.urls import path, register_converter
from django.views.decorators.cache import cache_control

from django.contrib.sitemaps import views as sitemap_views

from . import feeds, views, wellknown
from .sitemaps import SITEMAPS
from .converters import SafeStringConverter

register_converter(SafeStringConverter, "safe")

urlpatterns = [
    path("", views.home, name="home"),
    path("discover/", views.discover, name="discover"),
    path("new/", views.new_post, name="new_post"),
    path("drafts/", views.drafts, name="drafts"),
    path("offline/", views.offline, name="offline"),
    path("p/<safe:post_id>/", views.legacy_post_url),
    path("feed.xml", feeds.site_feed, name="feed_site"),
    path("sitemap.xml", cache_control(public=True, max_age=3600)(sitemap_views.index), {"sitemaps": SITEMAPS, "sitemap_url_name": "sitemap_section"}, name="sitemap"),
    path("sitemap-<section>.xml", cache_control(public=True, max_age=3600)(sitemap_views.sitemap), {"sitemaps": SITEMAPS}, name="sitemap_section"),
    path(".well-known/security.txt", wellknown.security_txt, name="security_txt"),
    path("@<safe:username>/feed.xml", feeds.author_feed, name="feed_author"),
    path("@<safe:username>/", views.profile, name="profile"),
    path("@<safe:username>/<safe:post_id>/", views.post_detail, name="post_detail"),
    path("@<safe:username>/<safe:post_id>/edit/", views.edit_post, name="edit_post"),
    path("@<safe:username>/<safe:post_id>.md", views.post_raw, name="post_raw"),
    path("@<safe:username>/<safe:post_id>/helpful/", views.helpful_mark, name="helpful_mark"),
    path("@<safe:username>/<safe:post_id>/helpful/undo/", views.helpful_unmark, name="helpful_unmark"),
    path("@<safe:username>/<safe:post_id>/draft/", views.draft_post, name="draft_post"),
    path("@<safe:username>/<safe:post_id>/delete/", views.delete_post, name="delete_post"),
    path("api/posts/", views.api_create, name="api_create"),
    path("api/posts/<safe:post_id>/", views.api_update, name="api_update"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("media/<path:key>", views.media, name="media"),
]
