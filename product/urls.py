from django.urls import path

from product.views import (
    product_project_readiness,
    product_project_roadmap_view,
    product_feature_prioritization_view,
    product_spec_contract_create,
    product_spec_draft_create,
    product_spec_draft_review,
    product_spec_draft_tasks_propose,
    product_status,
    prd_generate_api,
    features_rank_api,
    feature_rice_update_api,
    milestone_create_api,
    roadmap_timeline_api,
    feedback_ingest_api,
    feedback_summary_api,
    product_dashboard_rendered_view,
)


urlpatterns = [
    path("manager/status/", product_status, name="product-manager-status"),
    path("dashboard/", product_dashboard_rendered_view, name="product-dashboard-rendered"),
    path("features/prioritization/", product_feature_prioritization_view, name="product-feature-prioritization"),
    path("features/rank/", features_rank_api, name="product-features-rank"),
    path("features/<uuid:feature_id>/rice/", feature_rice_update_api, name="product-feature-rice-update"),
    path("prd/generate/", prd_generate_api, name="product-prd-generate"),
    path("milestones/create/", milestone_create_api, name="product-milestone-create"),
    path("roadmap/timeline/", roadmap_timeline_api, name="product-roadmap-timeline"),
    path("feedback/ingest/", feedback_ingest_api, name="product-feedback-ingest"),
    path("feedback/summary/", feedback_summary_api, name="product-feedback-summary"),
    path("spec-contracts/create/", product_spec_contract_create, name="product-spec-contract-create"),
    path("spec-contracts/<uuid:contract_id>/drafts/create/", product_spec_draft_create, name="product-spec-draft-create"),
    path("spec-drafts/<uuid:draft_id>/review/", product_spec_draft_review, name="product-spec-draft-review"),
    path("spec-drafts/<uuid:draft_id>/tasks/propose/", product_spec_draft_tasks_propose, name="product-spec-draft-tasks-propose"),
    path("projects/<uuid:project_id>/readiness/", product_project_readiness, name="product-project-readiness"),
    path("projects/<uuid:project_id>/roadmap/", product_project_roadmap_view, name="product-project-roadmap"),
]
