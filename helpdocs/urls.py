from django.urls import path

from . import views

urlpatterns = [
    path("help/", views.index, name="help_index"),
    path("help/all.md", views.all_markdown, name="help_all_md"),
    path("help/<slug:slug>.md", views.page_markdown, name="help_page_md"),
    path("help/<slug:slug>/", views.page, name="help_page"),
    path("llms.txt", views.llms_txt, name="llms_txt"),
]
