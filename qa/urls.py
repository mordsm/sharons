from django.urls import path

from qa.views import qa_status_view, qa_task_review, qa_verification_queue


urlpatterns = [
    path("status/", qa_status_view, name="qa-status"),
    path("verification-queue/", qa_verification_queue, name="qa-verification-queue"),
    path("tasks/<uuid:task_id>/review/", qa_task_review, name="qa-task-review"),
]

