import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command

from governance.services import APPROVAL_DECIDER_GROUP, setup_ceo_reviewer


@pytest.mark.django_db
def test_setup_ceo_reviewer_creates_user_with_unusable_password_by_default():
    user, created = setup_ceo_reviewer(username="ceo", email="ceo@example.com")

    assert created is True
    assert user.email == "ceo@example.com"
    assert user.has_usable_password() is False
    assert user.groups.filter(name=APPROVAL_DECIDER_GROUP).exists()


@pytest.mark.django_db
def test_setup_ceo_reviewer_sets_explicit_password():
    user, created = setup_ceo_reviewer(username="ceo", password="temporary-strong-password")

    assert created is True
    assert user.has_usable_password() is True
    assert user.check_password("temporary-strong-password") is True


@pytest.mark.django_db
def test_setup_ceo_reviewer_updates_existing_user_and_is_idempotent():
    User.objects.create_user(username="ceo", email="old@example.com")

    user, created = setup_ceo_reviewer(username="ceo", email="new@example.com")
    setup_ceo_reviewer(username="ceo", email="new@example.com")

    assert created is False
    assert User.objects.filter(username="ceo").count() == 1
    user.refresh_from_db()
    assert user.email == "new@example.com"
    assert Group.objects.filter(name=APPROVAL_DECIDER_GROUP).count() == 1
    assert user.groups.filter(name=APPROVAL_DECIDER_GROUP).exists()


@pytest.mark.django_db
def test_setup_ceo_reviewer_command_outputs_status(capsys):
    call_command("setup_ceo_reviewer", "--username", "ceo", "--email", "ceo@example.com")

    output = capsys.readouterr().out
    assert "Created reviewer 'ceo'" in output
    assert APPROVAL_DECIDER_GROUP in output
