from django.urls import path

from marketing.views import (
    marketing_artifact_review,
    marketing_artifact_revise,
    marketing_calendar_create,
    marketing_calendar_review,
    marketing_campaign_brief_create,
    marketing_claim_create,
    marketing_claim_review,
    marketing_experiment_create,
    marketing_experiment_review,
    marketing_performance_analyze,
    marketing_request_create,
    marketing_request_detail,
    marketing_status_view,
)


urlpatterns = [
    path("status/", marketing_status_view, name="marketing-status"),
    path("requests/create/", marketing_request_create, name="marketing-request-create"),
    path("requests/<uuid:request_id>/", marketing_request_detail, name="marketing-request-detail"),
    path("requests/<uuid:request_id>/campaign-briefs/create/", marketing_campaign_brief_create, name="marketing-campaign-brief-create"),
    path("artifacts/<uuid:artifact_id>/review/", marketing_artifact_review, name="marketing-artifact-review"),
    path("artifacts/<uuid:artifact_id>/revise/", marketing_artifact_revise, name="marketing-artifact-revise"),
    path("performance/analyze/", marketing_performance_analyze, name="marketing-performance-analyze"),
    path("requests/<uuid:request_id>/calendar/create/", marketing_calendar_create, name="marketing-calendar-create"),
    path("calendar/<uuid:item_id>/review/", marketing_calendar_review, name="marketing-calendar-review"),
    path("requests/<uuid:request_id>/experiments/create/", marketing_experiment_create, name="marketing-experiment-create"),
    path("experiments/<uuid:experiment_id>/review/", marketing_experiment_review, name="marketing-experiment-review"),
    path("requests/<uuid:request_id>/claims/create/", marketing_claim_create, name="marketing-claim-create"),
    path("claims/<uuid:claim_id>/review/", marketing_claim_review, name="marketing-claim-review"),
]
