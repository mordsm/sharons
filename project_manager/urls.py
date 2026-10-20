from django.urls import path

from project_manager.views import execution_review_create, objective_milestones_propose, project_manager_status_view, task_blocker_review_create


urlpatterns = [
    path("status/", project_manager_status_view, name="project-manager-status"),
    path("execution-reviews/create/", execution_review_create, name="project-manager-execution-review-create"),
    path("objectives/<uuid:objective_id>/milestones/propose/", objective_milestones_propose, name="project-manager-milestones-propose"),
path("tasks/<uuid:task_id>/blocker-review/create/", task_blocker_review_create, name="project-manager-blocker-review-create"),
]
