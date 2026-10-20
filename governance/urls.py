from django.urls import path

from governance.views import approval_decision, approval_execute, approvals_list


urlpatterns = [
    path("", approvals_list, name="approvals-list"),
    path("<uuid:approval_id>/decision/", approval_decision, name="approval-decision"),
    path("<uuid:approval_id>/execute/", approval_execute, name="approval-execute"),
]
