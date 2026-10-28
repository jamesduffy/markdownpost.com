from django.urls import path

from . import views

urlpatterns = [
    path("mcp/", views.mcp_endpoint, name="mcp"),
    path("settings/agents/", views.settings_agents, name="settings_agents"),
    path("settings/agents/label/", views.toggle_agent_label, name="agent_label"),
    path("settings/agents/<int:token_id>/revoke/", views.revoke_token, name="revoke_token"),
]
