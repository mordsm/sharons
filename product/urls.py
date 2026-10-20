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
)


urlpatterns = [
    path("manager/status/", product_status, name="product-manager-status"),
    path("features/prioritization/", product_feature_prioritization_view, name="product-feature-prioritization"),
    path("spec-contracts/create/", product_spec_contract_create, name="product-spec-contract-create"),
    path("spec-contracts/<uuid:contract_id>/drafts/create/", product_spec_draft_create, name="product-spec-draft-create"),
    path("spec-drafts/<uuid:draft_id>/review/", product_spec_draft_review, name="product-spec-draft-review"),
    path("spec-drafts/<uuid:draft_id>/tasks/propose/", product_spec_draft_tasks_propose, name="product-spec-draft-tasks-propose"),
    path("projects/<uuid:project_id>/readiness/", product_project_readiness, name="product-project-readiness"),
    path("projects/<uuid:project_id>/roadmap/", product_project_roadmap_view, name="product-project-roadmap"),
]
