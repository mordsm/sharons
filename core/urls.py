from django.urls import path

from core.views import (
    cos_critical_path,
    cos_decision_bundle_api,
    cos_decision_bundle_decide,
    cos_dependency_add,
    cos_dependency_remove,
    cos_intake,
    cos_operating_dashboard,
    cos_objective_next_actions_propose,
    cos_objective_operating_review,
    cos_objective_work_propose,
    cos_objectives_health,
    cos_risk_create,
    cos_risk_update,
    cos_risks_list,
    cos_wip_and_stale,
)


urlpatterns = [
    path("intake/", cos_intake, name="cos-intake"),
    path("operating-dashboard/", cos_operating_dashboard, name="cos-operating-dashboard"),
    path("objectives/health/", cos_objectives_health, name="cos-objectives-health"),
    path("objectives/<uuid:objective_id>/work/propose/", cos_objective_work_propose, name="cos-objective-work-propose"),
    path("objectives/<uuid:objective_id>/operating-review/", cos_objective_operating_review, name="cos-objective-operating-review"),
    path("objectives/<uuid:objective_id>/next-actions/propose/", cos_objective_next_actions_propose, name="cos-objective-next-actions-propose"),
    path("critical-path/", cos_critical_path, name="cos-critical-path"),
    path("dependencies/add/", cos_dependency_add, name="cos-dependency-add"),
    path("dependencies/remove/", cos_dependency_remove, name="cos-dependency-remove"),
    path("wip-and-stale/", cos_wip_and_stale, name="cos-wip-and-stale"),
    path("risks/", cos_risks_list, name="cos-risks-list"),
    path("risks/create/", cos_risk_create, name="cos-risk-create"),
    path("risks/<uuid:risk_id>/", cos_risk_update, name="cos-risk-update"),
    path("decision-bundle/", cos_decision_bundle_api, name="cos-decision-bundle-api"),
    path("decision-bundle/decide/", cos_decision_bundle_decide, name="cos-decision-bundle-decide"),
]

