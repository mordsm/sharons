from django.urls import path

from marketing.views import (
    marketing_artifact_review,
    marketing_artifact_revise,
    marketing_campaign_brief_create,
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
]
