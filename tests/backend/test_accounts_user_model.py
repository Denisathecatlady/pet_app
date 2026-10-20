"""Custom user model and manager."""

import pytest
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction

from accounts.models import User
from accounts.roles import ROLE_LABELS, Role
from tests.backend.helpers import PASSWORD

pytestmark = pytest.mark.django_db


def test_create_user_normalises_email_and_hashes_password():
    user = User.objects.create_user("  Jana.Novak@Example.CZ ", PASSWORD)

    assert user.email == "jana.novak@example.cz"
    assert user.password != PASSWORD
    assert user.check_password(PASSWORD)
    assert user.is_active and not user.is_staff and not user.is_superuser
    assert not user.activation_pending
    assert str(user) == "jana.novak@example.cz"


def test_user_has_no_username_and_logs_in_by_email():
    assert User.USERNAME_FIELD == "email"
    assert User.REQUIRED_FIELDS == []
    assert "username" not in {field.name for field in User._meta.get_fields()}


def test_create_user_without_password_is_unusable():
    user = User.objects.create_user("bez-hesla@example.cz")
    assert not user.has_usable_password()


@pytest.mark.parametrize("email", ["", "   ", None])
def test_create_user_requires_email(email):
    with pytest.raises(ValueError):
        User.objects.create_user(email, PASSWORD)


def test_create_superuser_sets_flags():
    admin = User.objects.create_superuser("Admin@Example.cz", PASSWORD)
    assert admin.email == "admin@example.cz"
    assert admin.is_staff and admin.is_superuser and admin.is_active


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_rejects_false_flags(flag):
    with pytest.raises(ValueError):
        User.objects.create_superuser("admin@example.cz", PASSWORD, **{flag: False})


def test_email_is_unique_regardless_of_case(user):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(user.email.upper(), PASSWORD)


def test_database_rejects_upper_case_email(user):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(email="Jana@Example.cz")


def test_get_by_natural_key_ignores_case(user):
    assert User.objects.get_by_natural_key("JANA@example.CZ") == user


def test_full_clean_normalises_email():
    user = User(email="Petr@Example.CZ")
    user.set_password(PASSWORD)
    user.full_clean()
    assert user.email == "petr@example.cz"


def test_activation_pending_is_cleared_when_active(make_user):
    user = make_user("pending@example.cz", is_active=False, activation_pending=True)
    assert user.activation_pending

    user.is_active = True
    user.save()
    user.refresh_from_db()
    assert not user.activation_pending


def test_role_properties(make_user):
    owner = make_user("owner@example.cz")
    vet = make_user("vet@example.cz", roles=(Role.VET,))
    staff = make_user("staff@example.cz", roles=(Role.DATA_CURATOR, Role.NUTRITION_REVIEWER))

    assert owner.is_owner and not owner.is_vet
    assert vet.is_vet and not vet.is_owner
    assert staff.is_data_curator and staff.is_nutrition_reviewer and not staff.is_vet
    assert owner.has_role(Role.OWNER)
    assert not User(email="unsaved@example.cz").has_role(Role.OWNER)


def test_role_labels_are_czech(make_user):
    user = make_user("both@example.cz", roles=(Role.OWNER, Role.VET))
    assert user.role_labels() == sorted([ROLE_LABELS["owner"], ROLE_LABELS["vet"]])
    assert User(email="unsaved@example.cz").role_labels() == []


def test_role_labels_fall_back_to_group_name(user):
    user.groups.add(Group.objects.create(name="custom_group"))
    assert "custom_group" in user.role_labels()
