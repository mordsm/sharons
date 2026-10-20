from django.urls import path

from mailbox.views import email_list, mock_email_ingest


urlpatterns = [
    path("emails/", email_list, name="email-list"),
    path("mock-gmail/inbound/", mock_email_ingest, name="mock-email-ingest"),
]
