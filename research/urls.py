from django.urls import path

from research.views import research_contract_create, research_status


urlpatterns = [
    path("adapter/status/", research_status, name="research-adapter-status"),
    path("contracts/create/", research_contract_create, name="research-contract-create"),
]
