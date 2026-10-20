from django.urls import path

from developer.views import developer_status_view, developer_work_contract_create, implementation_plan_create, implementation_plan_deliver


urlpatterns = [
    path("status/", developer_status_view, name="developer-status"),
    path("work-contracts/create/", developer_work_contract_create, name="developer-work-contract-create"),
    path("work-contracts/<uuid:contract_id>/implementation-plans/create/", implementation_plan_create, name="developer-implementation-plan-create"),
    path("implementation-plans/<uuid:plan_id>/deliver/", implementation_plan_deliver, name="developer-implementation-plan-deliver"),
]

