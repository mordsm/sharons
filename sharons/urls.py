from django.contrib import admin
from django.urls import include, path

from core.views import (
    conversation_finalize,
    event_create,
    executive_dashboard,
    history_search,
    memory_create,
    weekly_decision_bundle_page,
    weekly_review_api,
    weekly_review_page,
)
from executive_assistant.views import executive_assistant_dashboard, executive_brief_detail
from finance.views import finance_dashboard
from governance.views import approval_detail, approval_inbox, audit_list, outbox_dashboard, outbox_dead_letter, outbox_list, outbox_retry, rule_activate, rule_activation_request, rule_event, rule_proposal, rule_test, rule_validate, rules_engine_dashboard, rules_engine_dry_run, rules_engine_run_detail, rules_engine_runs_list, rules_engine_work_item_update, rules_engine_work_items_list
from mailbox.views import inbox_dashboard
from operations.views import agent_invoke, agent_performance_detail, agents_list, plan_detail, plans_collection
from portfolio.views import objectives_list


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", executive_dashboard, name="executive-dashboard"),
    path("review/weekly/", weekly_review_page, name="weekly-review"),
    path("review/weekly/decision-bundle/", weekly_decision_bundle_page, name="weekly-decision-bundle-page"),
    path("approvals/", approval_inbox, name="approval-inbox"),
    path("approvals/<uuid:approval_id>/", approval_detail, name="approval-detail"),
    path("outbox/", outbox_dashboard, name="outbox-dashboard"),
    path("rules-engine/", rules_engine_dashboard, name="rules-engine-dashboard"),
    path("finance/", finance_dashboard, name="finance-dashboard"),
    path("inbox/", inbox_dashboard, name="inbox-dashboard"),
    path("executive-assistant/", executive_assistant_dashboard, name="executive-assistant-dashboard"),
    path("executive-assistant/briefs/<uuid:brief_id>/", executive_brief_detail, name="executive-brief-detail"),
    path("api/v1/cos/", include("core.urls")),
    path("api/v1/developer/", include("developer.urls")),
    path("api/v1/history/search/", history_search, name="history-search"),
    path("api/v1/events/", event_create, name="event-create"),
    path("api/v1/executive-assistant/", include("executive_assistant.urls")),
    path("api/v1/conversation/finalize/", conversation_finalize, name="conversation-finalize"),
    path("api/v1/memory/", memory_create, name="memory-create"),
    path("api/v1/reports/weekly/", weekly_review_api, name="weekly-review-api"),
    path("api/v1/agents/invoke/", agent_invoke, name="agent-invoke"),
    path("api/v1/agents/<str:agent_id>/performance/", agent_performance_detail, name="agent-performance"),
    path("api/v1/agents/", agents_list, name="agents-list"),
    path("api/v1/plans/", plans_collection, name="plans-collection"),
    path("api/v1/plans/<uuid:plan_id>/", plan_detail, name="plan-detail"),
    path("api/v1/approvals/", include("governance.urls")),
    path("api/v1/rules/proposals/", rule_proposal, name="rule-proposal"),
    path("api/v1/rules/events/", rule_event, name="rule-event"),
    path("api/v1/rules-engine/dry-run/", rules_engine_dry_run, name="rules-engine-dry-run"),
    path("api/v1/rules-engine/runs/", rules_engine_runs_list, name="rules-engine-runs-list"),
    path("api/v1/rules-engine/runs/<uuid:run_id>/", rules_engine_run_detail, name="rules-engine-run-detail"),
    path("api/v1/rules-engine/work-items/", rules_engine_work_items_list, name="rules-engine-work-items-list"),
    path("api/v1/rules-engine/work-items/<uuid:item_id>/update/", rules_engine_work_item_update, name="rules-engine-work-item-update"),
    path("api/v1/rules/<uuid:rule_id>/validate/", rule_validate, name="rule-validate"),
    path("api/v1/rules/<uuid:rule_id>/test/", rule_test, name="rule-test"),
    path("api/v1/rules/<uuid:rule_id>/activation-request/", rule_activation_request, name="rule-activation-request"),
    path("api/v1/rules/<uuid:rule_id>/activate/", rule_activate, name="rule-activate"),
    path("api/v1/audit/", audit_list, name="audit-list"),
    path("api/v1/outbox/", outbox_list, name="outbox-list"),
    path("api/v1/outbox/<uuid:message_id>/retry/", outbox_retry, name="outbox-retry"),
    path("api/v1/outbox/<uuid:message_id>/dead-letter/", outbox_dead_letter, name="outbox-dead-letter"),
    path("api/v1/objectives/", objectives_list, name="objectives-list"),
    path("api/v1/finance/", include("finance.urls")),
    path("api/v1/mailbox/", include("mailbox.urls")),
    path("api/v1/payments/", include("payments.urls")),
    path("api/v1/product/", include("product.urls")),
    path("api/v1/project-manager/", include("project_manager.urls")),
    path("api/v1/projects/", include("portfolio.urls")),
    path("api/v1/qa/", include("qa.urls")),
    path("api/v1/research/", include("research.urls")),
    path("api/v1/tasks/", include("operations.urls")),
]
