from django.urls import path

from posts import urls as _posts_urls  # noqa: F401  (importing it registers the "safe" path converter used below)

from . import views

# Included BEFORE posts.urls in config/urls.py, so "@name/follow/" is not read as a post id.
urlpatterns = [
    path("following/", views.following, name="following"),
    path("@<safe:username>/follow/", views.follow, name="follow"),
    path("@<safe:username>/unfollow/", views.unfollow, name="unfollow"),
]
