from django.urls import path

from operations.views import task_assign, task_detail_page, task_evidence, task_list_page, task_transition, task_upsert, task_verify


urlpatterns = [
    path("", task_list_page, name="task-list"),
    path("upsert/", task_upsert, name="task-upsert"),
    path("<uuid:task_id>/", task_detail_page, name="task-detail"),
    path("<uuid:task_id>/assign/", task_assign, name="task-assign"),
    path("<uuid:task_id>/transition/", task_transition, name="task-transition"),
    path("<uuid:task_id>/evidence/", task_evidence, name="task-evidence"),
    path("<uuid:task_id>/verify/", task_verify, name="task-verify"),
]
