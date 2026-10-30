from django.urls import path

from . import views

urlpatterns = [
    path("replies/post/<str:post_id>/", views.create, name="reply_create"),
    path("replies/settings/", views.site_setting, name="replies_setting"),
    path("replies/<str:reply_id>/delete/", views.delete, name="reply_delete"),
    path("replies/<str:reply_id>/hide/", views.hide, name="reply_hide"),
    path("replies/<str:reply_id>/restore/", views.restore, name="reply_restore"),
]
