from django.urls import path

from . import views

urlpatterns = [
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("content-policy/", views.content_policy, name="content_policy"),
    path("contact/", views.contact, name="contact"),
    path("contact/sent/", views.contact_sent, name="contact_sent"),
    path("report/", views.report, name="report"),
    path("report/sent/", views.report_sent, name="report_sent"),
]
