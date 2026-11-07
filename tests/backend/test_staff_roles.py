"""``User.is_staff`` is derived from the roles (docs/14 §14.2)."""

import pytest
from django.contrib.auth.models import Group

from accounts.models import User
from accounts.roles import STAFF_ROLES, Role
from accounts.staff import refresh_staff_flags
from tests.backend.helpers import PASSWORD

pytestmark = pytest.mark.django_db


def staff_flag(user: User) -> bool:
    return User.objects.get(pk=user.pk).is_staff


def group(role: str) -> Group:
    return Group.objects.get(name=role)


@pytest.mark.parametrize("role", sorted(STAFF_ROLES))
def test_a_staff_role_makes_the_user_staff(make_user, role):
    user = make_user("a@example.cz", roles=(role,))
    assert staff_flag(user)


@pytest.mark.parametrize("role", [Role.OWNER, Role.VET])
def test_application_roles_do_not_make_staff(make_user, role):
    assert not staff_flag(make_user("a@example.cz", roles=(role,)))


def test_a_new_user_is_not_staff(make_user):
    assert not staff_flag(make_user("a@example.cz", roles=()))


def test_a_superuser_is_staff_whatever_the_flag_says():
    created = User.objects.create_user("root@example.cz", PASSWORD, is_superuser=True)
    assert created.is_staff and staff_flag(created)
    explicit = User(email="x@example.cz", is_superuser=True, is_staff=False)
    explicit.save()
    assert explicit.is_staff


def test_the_flag_cannot_be_set_by_hand():
    user = User.objects.create_user("a@example.cz", PASSWORD, is_staff=True)
    assert not staff_flag(user)
    user.is_staff = True
    user.save()
    assert not staff_flag(user)
    user.save(update_fields=["is_staff"])
    assert not staff_flag(user)


def test_the_superuser_flag_drives_the_staff_flag(make_user):
    user = make_user("a@example.cz", roles=())
    user.is_superuser = True
    user.save()
    assert staff_flag(user)
    user.is_superuser = False
    user.save()
    assert not staff_flag(user)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    assert staff_flag(user)


def test_the_staff_flag_survives_a_saving_of_other_fields_only(make_user):
    user = make_user("a@example.cz", roles=(Role.SUPPORT_ADMIN,))
    user.save(update_fields=["first_name"])
    assert staff_flag(user)


def test_adding_and_removing_a_role_updates_the_flag(make_user):
    user = make_user("a@example.cz", roles=())
    user.groups.add(group(Role.DATA_CURATOR))
    assert staff_flag(user)
    user.groups.add(group(Role.OWNER))
    user.groups.remove(group(Role.DATA_CURATOR))
    assert not staff_flag(user)


def test_the_user_keeps_the_flag_while_another_staff_role_remains(make_user):
    user = make_user("a@example.cz", roles=(Role.DATA_CURATOR, Role.SUPPORT_ADMIN))
    user.groups.remove(group(Role.DATA_CURATOR))
    assert staff_flag(user)


def test_set_and_clear_update_the_flag(make_user):
    user = make_user("a@example.cz", roles=())
    user.groups.set([group(Role.NUTRITION_REVIEWER)])
    assert staff_flag(user)
    user.groups.set([group(Role.OWNER)])
    assert not staff_flag(user)
    user.groups.set([group(Role.SUPPORT_ADMIN)])
    user.groups.clear()
    assert not staff_flag(user)


def test_clearing_roles_does_not_demote_a_superuser(make_user):
    root = make_user("root@example.cz", roles=(Role.SUPPORT_ADMIN,), is_superuser=True)
    root.groups.clear()
    assert staff_flag(root)


def test_the_reverse_direction_updates_the_flag_too(make_user):
    first = make_user("a@example.cz", roles=())
    second = make_user("b@example.cz", roles=())
    curators = group(Role.DATA_CURATOR)

    curators.user_set.add(first, second)
    assert staff_flag(first) and staff_flag(second)
    curators.user_set.remove(first)
    assert not staff_flag(first) and staff_flag(second)
    curators.user_set.clear()
    assert not staff_flag(second)


def test_deleting_a_staff_group_demotes_its_members(make_user):
    custom = Group.objects.create(name="custom")
    user = make_user("a@example.cz", roles=(Role.DATA_CURATOR,))
    other = make_user("b@example.cz", roles=(Role.DATA_CURATOR, Role.SUPPORT_ADMIN))
    group(Role.DATA_CURATOR).delete()
    assert not staff_flag(user)
    assert staff_flag(other)  # still in support_admin
    custom.delete()


def test_renaming_a_staff_group_demotes_its_members(make_user):
    user = make_user("a@example.cz", roles=(Role.DATA_CURATOR,))
    curators = group(Role.DATA_CURATOR)
    curators.name = "renamed_group"
    curators.save()
    assert not staff_flag(user)
    curators.name = Role.DATA_CURATOR
    curators.save()
    assert staff_flag(user)


def test_refresh_staff_flags_repairs_every_user_and_is_idempotent(make_user):
    curator = make_user("a@example.cz", roles=(Role.DATA_CURATOR,))
    owner = make_user("b@example.cz")
    root = make_user("root@example.cz", roles=(), is_superuser=True)
    User.objects.filter(pk=curator.pk).update(is_staff=False)
    User.objects.filter(pk__in=[owner.pk, root.pk]).update(is_staff=True)
    User.objects.filter(pk=root.pk).update(is_staff=False)

    assert refresh_staff_flags() == 3  # curator and root granted, owner revoked
    assert refresh_staff_flags() == 0
    assert staff_flag(curator) and staff_flag(root) and not staff_flag(owner)


def test_refresh_staff_flags_can_be_limited_to_some_users(make_user):
    one = make_user("a@example.cz", roles=(Role.DATA_CURATOR,))
    two = make_user("b@example.cz", roles=(Role.DATA_CURATOR,))
    User.objects.update(is_staff=False)

    assert refresh_staff_flags([one.pk]) == 1
    assert staff_flag(one) and not staff_flag(two)


def test_the_field_is_not_editable_in_forms():
    assert User._meta.get_field("is_staff").editable is False
