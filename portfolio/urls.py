from django.urls import path

from portfolio.views import known_90_day_projects_register, objective_project_links_list, project_connections_create, project_state_assessments_list, projects_collection


urlpatterns = [
    path("", projects_collection, name="projects-collection"),
    path("known-90-day/register/", known_90_day_projects_register, name="known-90-day-projects-register"),
    path("objective-links/", objective_project_links_list, name="objective-project-links-list"),
    path("state-assessments/", project_state_assessments_list, name="project-state-assessments-list"),
    path("<uuid:project_id>/connections/", project_connections_create, name="project-connections-create"),
]
