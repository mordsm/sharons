import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from governance.services import APPROVAL_DECIDER_GROUP, APPROVAL_VIEWER_GROUP, provision_approval_groups


@pytest.mark.django_db
def test_provision_approval_groups_creates_exact_permissions():
    groups = provision_approval_groups()

    assert groups[APPROVAL_VIEWER_GROUP] == ["view_approvalrequest"]
    assert groups[APPROVAL_DECIDER_GROUP] == ["decide_approvalrequest", "view_approvalrequest"]

    viewer = Group.objects.get(name=APPROVAL_VIEWER_GROUP)
    decider = Group.objects.get(name=APPROVAL_DECIDER_GROUP)
    assert list(viewer.permissions.values_list("codename", flat=True)) == ["view_approvalrequest"]
    assert sorted(decider.permissions.values_list("codename", flat=True)) == [
        "decide_approvalrequest",
        "view_approvalrequest",
    ]


@pytest.mark.django_db
def test_provision_approval_groups_is_idempotent():
    provision_approval_groups()
    provision_approval_groups()

    assert Group.objects.filter(name=APPROVAL_VIEWER_GROUP).count() == 1
    assert Group.objects.filter(name=APPROVAL_DECIDER_GROUP).count() == 1


@pytest.mark.django_db
def test_provision_approval_permissions_command_outputs_groups(capsys):
    call_command("provision_approval_permissions")

    output = capsys.readouterr().out
    assert APPROVAL_VIEWER_GROUP in output
    assert APPROVAL_DECIDER_GROUP in output
    assert "Provisioned approval permission groups." in output
