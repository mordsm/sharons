from django.urls import path

from finance.views import financial_record_create, financial_record_reconcile, financial_records_list


urlpatterns = [
    path("records/", financial_records_list, name="financial-records-list"),
    path("records/create/", financial_record_create, name="financial-record-create"),
    path("records/<uuid:record_id>/reconcile/", financial_record_reconcile, name="financial-record-reconcile"),
]
