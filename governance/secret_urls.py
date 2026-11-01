from django.urls import path

from governance.secret_views import secret_reference_create, secret_reference_list


urlpatterns = [
    path("references/", secret_reference_list, name="secret-reference-list"),
    path("references/create/", secret_reference_create, name="secret-reference-create"),
]
