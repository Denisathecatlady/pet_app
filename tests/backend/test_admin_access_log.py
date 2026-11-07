"""The access log of the administration (docs/12 §12.8 point 5, docs/14 §14.7): what is logged
for each kind of view, what never is, who may read it and how it is purged."""

import io
from datetime import timedelta
from itertools import count
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import Role
from animals.models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    HealthCondition,
)
from backoffice.access_log import (
    AccessLoggedAdminMixin,
    access_logged_action,
    admin_mixin_missing,
    is_personal_data,
    log_admin_access,
    log_command_access,
)
from backoffice.apps import check_personal_data_admins
from backoffice.models import AdminAccessAction as Action
from backoffice.models import AdminAccessLog
from backoffice.services import purge_admin_access_log
from catalog.models import ScientificSource
from tests.backend.helpers import PASSWORD, log_in_verified

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(client, superuser):
    log_in_verified(client, superuser)
    AdminAccessLog.objects.all().delete()  # (the sign-in itself is logged: start clean)
    client.account = superuser
    return client


@pytest.fixture
def records(make_user, make_animal, make_measurement, vet_user):
    owner = make_user("owner@example.cz")
    animal = make_animal(owner, target_weight_kg=Decimal("20"))
    condition = HealthCondition.objects.get(code="CKD")
    return {
        "user": owner,
        "animal": animal,
        "measurement": make_measurement(animal),
        "condition": AnimalHealthCondition.objects.create(animal=animal, condition=condition),
        "share": AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=owner),
    }


def rows(**filters):
    return list(AdminAccessLog.objects.filter(**filters).order_by("pk"))


def only_row(**filters) -> AdminAccessLog:
    found = rows(**filters)
    assert len(found) == 1, found
    return found[0]


# --- The model ----------------------------------------------------------------------------------


def test_a_row_cannot_be_rewritten():
    row = AdminAccessLog.objects.create(staff_email="a@example.cz", action=Action.LOGIN)

    row.action = Action.CHANGE
    with pytest.raises(ValueError, match="cannot be changed"):
        row.save()
    assert AdminAccessLog.objects.get(pk=row.pk).action == Action.LOGIN


def test_the_actions_of_the_specification_exist():
    assert {"VIEW_LIST", "VIEW_OBJECT", "CHANGE", "EXPORT", "UNLOCK", "LOGIN"} <= set(Action.values)


def test_the_row_survives_the_deletion_of_the_staff_account(make_staff):
    staff = make_staff()
    row = AdminAccessLog.objects.create(
        staff_user=staff, staff_email=staff.email, action=Action.VIEW_LIST
    )

    staff.delete()

    row.refresh_from_db()
    assert row.staff_user is None and row.staff_email == "support_admin@example.cz"


def test_the_model_is_flagged_as_personal_data():
    assert AdminAccessLog.contains_personal_data is True


# --- Writing a row --------------------------------------------------------------------------------


def request_for(user, path="/admin/accounts/user/", **extra):
    request = RequestFactory().get(path, **extra)
    request.user = user
    return request


def test_a_row_has_who_what_where_and_never_the_query(superuser):
    request = request_for(superuser, "/admin/accounts/user/?q=jana%40example.cz&is_active=1")
    request.META["REMOTE_ADDR"] = "203.0.113.7"

    (row,) = log_admin_access(request, Action.VIEW_LIST, User)

    row = AdminAccessLog.objects.get(pk=row.pk)
    assert (row.staff_user, row.staff_email) == (superuser, superuser.email)
    assert (row.action, row.app_label, row.model, row.object_pk) == (
        "VIEW_LIST",
        "accounts",
        "user",
        "",
    )
    assert row.ip_address == "203.0.113.7"
    assert row.path == "/admin/accounts/user/"
    assert "jana" not in str(row.__dict__) and "?" not in row.path


def test_one_row_per_record(superuser):
    created = log_admin_access(request_for(superuser), Action.EXPORT, User, [3, 4, "five"])

    assert [row.object_pk for row in created] == ["3", "4", "five"]
    assert AdminAccessLog.objects.count() == 3


def test_the_ip_address_uses_the_trusted_proxy_logic_of_axes(superuser):
    request = request_for(
        superuser, HTTP_X_FORWARDED_FOR="198.51.100.1, 203.0.113.5", REMOTE_ADDR="10.0.0.1"
    )

    with override_settings(TRUSTED_PROXY_COUNT=0):
        (direct,) = log_admin_access(request, Action.VIEW_LIST, User)
    with override_settings(TRUSTED_PROXY_COUNT=1):
        (proxied,) = log_admin_access(request, Action.VIEW_LIST, User)

    assert AdminAccessLog.objects.get(pk=direct.pk).ip_address == "10.0.0.1"
    # Behind one proxy: the last entry, the one the proxy added; what the client wrote is ignored.
    assert AdminAccessLog.objects.get(pk=proxied.pk).ip_address == "203.0.113.5"


@pytest.mark.parametrize("garbage", ["not an address", "999.1.1.1", "", "1.2.3.4, <script>"])
def test_a_garbage_address_does_not_break_the_log(superuser, garbage):
    request = request_for(superuser, HTTP_X_FORWARDED_FOR=garbage, REMOTE_ADDR="10.0.0.1")

    with override_settings(TRUSTED_PROXY_COUNT=1):
        (row,) = log_admin_access(request, Action.VIEW_LIST, User)

    stored = AdminAccessLog.objects.get(pk=row.pk).ip_address
    assert stored in (None, "10.0.0.1")


def test_a_long_path_is_cut(superuser):
    request = request_for(superuser, "/admin/" + "a" * 600 + "/")

    (row,) = log_admin_access(request, Action.VIEW_LIST, User)

    assert len(AdminAccessLog.objects.get(pk=row.pk).path) == 255


def test_without_a_signed_in_user_the_row_has_no_name(rf):
    from django.contrib.auth.models import AnonymousUser

    request = rf.get("/admin/")
    request.user = AnonymousUser()

    (row,) = log_admin_access(request, Action.LOGIN)

    saved = AdminAccessLog.objects.get(pk=row.pk)
    assert saved.staff_user is None and saved.staff_email == ""
    assert (saved.app_label, saved.model) == ("", "")


def test_a_command_is_logged_without_a_request(user):
    log_command_access("reset_2fa", Action.CHANGE, User, [user.pk])

    row = only_row(path="manage.py reset_2fa")
    assert (row.staff_email, row.object_pk, row.ip_address) == (
        "manage.py reset_2fa",
        str(user.pk),
        None,
    )


# --- Each kind of view ----------------------------------------------------------------------------


def test_the_list_is_logged(root, records):
    root.get(reverse("admin:accounts_user_changelist"))

    row = only_row()
    assert (row.action, row.model, row.object_pk) == (Action.VIEW_LIST, "user", "")
    assert row.staff_user == root.account and row.path == "/admin/accounts/user/"


def test_search_terms_filters_and_ordering_are_never_stored(root, records):
    root.get(
        reverse("admin:accounts_user_changelist"),
        {"q": "tajny-hledany-vyraz", "is_active__exact": "1", "o": "1", "groups__id__exact": "1"},
    )

    row = only_row()
    stored = " ".join(str(v) for v in row.__dict__.values())
    assert "tajny-hledany-vyraz" not in stored and "is_active" not in stored
    assert row.path == "/admin/accounts/user/"


def test_the_record_is_logged_with_its_key(root, records):
    root.get(reverse("admin:accounts_user_change", args=[records["user"].pk]))

    row = only_row()
    assert (row.action, row.model, row.object_pk) == (
        Action.VIEW_OBJECT,
        "user",
        str(records["user"].pk),
    )


def test_the_history_page_is_logged(root, records):
    animal = records["animal"]
    root.get(reverse("admin:animals_animal_history", args=[animal.pk]))

    row = only_row()
    assert (row.action, row.model, row.object_pk) == (Action.VIEW_OBJECT, "animal", str(animal.pk))
    assert row.path.endswith("/history/")


def test_an_old_version_in_the_history_is_logged(root, records):
    animal = records["animal"]
    version = animal.history.first()

    response = root.get(
        reverse("admin:animals_animal_simple_history", args=[animal.pk, version.pk])
    )

    assert response.status_code == 200
    row = only_row()
    assert (row.action, row.model, row.object_pk) == (Action.VIEW_OBJECT, "animal", str(animal.pk))
    assert f"/history/{version.pk}/" in row.path


def test_the_deletion_page_is_logged_as_a_view_and_the_deletion_as_a_deletion(root, records):
    share = records["share"]
    url = reverse("admin:animals_animalshare_delete", args=[share.pk])

    root.get(url)
    assert [r.action for r in rows()] == [Action.VIEW_OBJECT]

    root.post(url, {"post": "yes"})
    assert [r.action for r in rows()] == [Action.VIEW_OBJECT, Action.DELETE]
    assert rows()[-1].object_pk == str(share.pk)


def test_a_saved_change_is_logged_once_as_a_change(root, records):
    url = reverse("admin:accounts_user_change", args=[records["user"].pk])
    data = {"email": "owner@example.cz", "first_name": "Eva", "is_active": "on"}

    assert root.post(url, data).status_code == 302

    assert [r.action for r in rows()] == [Action.CHANGE]
    assert rows()[0].object_pk == str(records["user"].pk)


def test_a_rejected_form_is_a_view_not_a_change(root, records):
    url = reverse("admin:accounts_user_change", args=[records["user"].pk])

    response = root.post(url, {"email": "not an address", "is_active": "on"})

    assert response.status_code == 200
    assert [r.action for r in rows()] == [Action.VIEW_OBJECT]


def test_adding_a_record_is_logged(root):
    response = root.post(reverse("admin:accounts_user_add"), {"email": "new@example.cz"})

    assert response.status_code == 302
    created = User.objects.get(email="new@example.cz")
    add = [r for r in rows() if r.action == Action.ADD]
    assert [r.object_pk for r in add] == [str(created.pk)]


def test_a_bulk_deletion_logs_every_record(root, make_user):
    victims = [make_user(f"v{n}@example.cz") for n in range(3)]
    ids = [v.pk for v in victims]

    root.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "delete_selected", "_selected_action": ids, "post": "yes"},
    )

    deleted = [r for r in rows() if r.action == Action.DELETE]
    assert sorted(r.object_pk for r in deleted) == sorted(str(i) for i in ids)
    assert not [r for r in rows() if r.action == Action.VIEW_LIST]  # (an action is not a list view)


def test_the_confirmation_of_a_bulk_deletion_deletes_and_logs_nothing(root, make_user):
    victim = make_user("v@example.cz")

    root.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "delete_selected", "_selected_action": [victim.pk]},
    )

    assert rows() == [] and User.objects.filter(pk=victim.pk).exists()


def test_a_custom_action_is_logged_per_record(root, records, make_user):
    second = make_user("second@example.cz")

    root.post(
        reverse("admin:accounts_user_changelist"),
        {
            "action": "send_password_reset_link",
            "_selected_action": [records["user"].pk, second.pk],
        },
    )

    changed = [r for r in rows() if r.action == Action.CHANGE]
    assert sorted(r.object_pk for r in changed) == sorted([str(records["user"].pk), str(second.pk)])


def test_every_model_with_personal_data_logs_list_record_and_history(root, records):
    for name, obj in [
        ("animals_animal", records["animal"]),
        ("animals_bodymeasurement", records["measurement"]),
        ("animals_animalhealthcondition", records["condition"]),
        ("animals_animalshare", records["share"]),
        ("accounts_user", records["user"]),
    ]:
        AdminAccessLog.objects.all().delete()
        root.get(reverse(f"admin:{name}_changelist"))
        root.get(reverse(f"admin:{name}_change", args=[obj.pk]))
        root.get(reverse(f"admin:{name}_history", args=[obj.pk]))

        actions = [(r.action, r.model, r.object_pk) for r in rows()]
        model = name.split("_", 1)[1]
        assert actions == [
            (Action.VIEW_LIST, model, ""),
            (Action.VIEW_OBJECT, model, str(obj.pk)),
            (Action.VIEW_OBJECT, model, str(obj.pk)),
        ], name


def test_models_without_personal_data_are_not_logged(root, make_source):
    source = make_source()
    condition = HealthCondition.objects.get(code="CKD")

    root.get(reverse("admin:catalog_scientificsource_changelist"))
    root.get(reverse("admin:catalog_scientificsource_change", args=[source.pk]))
    root.get(reverse("admin:animals_healthcondition_changelist"))
    root.get(reverse("admin:animals_healthcondition_change", args=[condition.pk]))
    root.get(reverse("admin:auth_group_changelist"))
    root.get(reverse("admin:index"))

    assert rows() == []


def test_a_refused_request_leaves_no_row(client, make_staff, records):
    log_in_verified(client, make_staff(Role.DATA_CURATOR))
    AdminAccessLog.objects.all().delete()

    assert client.get(reverse("admin:accounts_user_changelist")).status_code == 403
    assert (
        client.get(reverse("admin:animals_animal_change", args=[records["animal"].pk])).status_code
        == 403
    )

    assert rows() == []


def test_a_missing_record_leaves_no_row(root):
    response = root.get(reverse("admin:accounts_user_change", args=[999_999]))

    assert response.status_code == 302 and rows() == []


# --- Sign-in, unlocking, exports ------------------------------------------------------------------


def test_the_sign_in_of_a_staff_member_is_logged_with_the_address(client, make_staff):
    staff = make_staff()

    client.post(
        reverse("accounts:login"),
        {"email": staff.email, "password": PASSWORD},
        REMOTE_ADDR="203.0.113.9",
    )

    row = only_row(action=Action.LOGIN)
    assert (row.staff_user, row.staff_email, row.ip_address) == (staff, staff.email, "203.0.113.9")
    assert row.path == reverse("accounts:login") and (row.app_label, row.model) == ("", "")


def test_the_sign_in_of_an_ordinary_user_is_not_logged(client, user):
    client.post(reverse("accounts:login"), {"email": user.email, "password": PASSWORD})

    assert rows() == []


_attempts = count(1)


def attempt():
    from axes.models import AccessAttempt

    return AccessAttempt.objects.create(
        username="someone@example.cz",
        ip_address="10.0.0.9",
        user_agent=f"browser {next(_attempts)}",
        failures_since_start=5,
    )


def test_unlocking_through_the_action_is_logged_as_unlock(client, make_staff):
    log_in_verified(client, make_staff())
    AdminAccessLog.objects.all().delete()
    counters = [attempt(), attempt()]

    client.post(
        reverse("admin:axes_accessattempt_changelist"),
        {"action": "unlock_selected", "_selected_action": [c.pk for c in counters]},
    )

    from axes.models import AccessAttempt

    assert not AccessAttempt.objects.exists()
    unlocked = rows(action=Action.UNLOCK)
    assert sorted(r.object_pk for r in unlocked) == sorted(str(c.pk) for c in counters)
    assert {r.model for r in unlocked} == {"accessattempt"}
    assert rows(action=Action.DELETE) == []


def test_unlocking_through_the_delete_page_is_logged_as_unlock(client, make_staff):
    log_in_verified(client, make_staff())
    counter = attempt()
    AdminAccessLog.objects.all().delete()
    url = reverse("admin:axes_accessattempt_delete", args=[counter.pk])

    client.get(url)
    client.post(url, {"post": "yes"})

    assert [r.action for r in rows()] == [Action.VIEW_OBJECT, Action.UNLOCK]


def test_the_failed_sign_in_counters_are_listed_and_logged(client, make_staff):
    log_in_verified(client, make_staff())
    counter = attempt()
    AdminAccessLog.objects.all().delete()

    content = client.get(reverse("admin:axes_accessattempt_changelist")).content.decode()
    client.get(reverse("admin:axes_accessattempt_change", args=[counter.pk]))

    assert "someone@example.cz" in content and "zamčeno" in content
    assert "barf-status--danger" in content
    assert [r.action for r in rows()] == [Action.VIEW_LIST, Action.VIEW_OBJECT]


def test_the_counters_show_no_submitted_form_data(client, make_staff):
    from axes.models import AccessAttempt

    log_in_verified(client, make_staff())
    counter = AccessAttempt.objects.create(
        username="someone@example.cz",
        ip_address="10.0.0.9",
        user_agent="x",
        failures_since_start=1,
        post_data="email=someone@example.cz\npassword=tajne-heslo-123",
    )

    content = client.get(
        reverse("admin:axes_accessattempt_change", args=[counter.pk])
    ).content.decode()

    assert "tajne-heslo-123" not in content and "post_data" not in content


class RecordingAdmin(AccessLoggedAdminMixin, admin.ModelAdmin):
    @access_logged_action(Action.EXPORT)
    def export_it(self, request, queryset):
        """Exports without logging by itself."""

    def quiet(self, request, queryset):
        """A change that forgot to log."""

    def logs_itself(self, request, queryset):
        self.record_access(request, Action.EXPORT, object_pks=[1])


def run_action(model_admin, name, user, selected):
    request = request_for(user)
    func = model_admin.get_actions(request)[name][0]
    func(model_admin, request, User.objects.filter(pk__in=[u.pk for u in selected]))


@pytest.fixture
def recording_admin():
    model_admin = RecordingAdmin(User, AdminSite())
    model_admin.actions = ["export_it", "quiet", "logs_itself"]
    return model_admin


def test_an_action_marked_as_export_is_logged_as_an_export_per_record(
    recording_admin, superuser, make_user
):
    others = [make_user("a@example.cz"), make_user("b@example.cz")]

    run_action(recording_admin, "export_it", superuser, others)

    exported = rows(action=Action.EXPORT)
    assert sorted(r.object_pk for r in exported) == sorted(str(u.pk) for u in others)


def test_an_action_that_forgot_to_log_is_logged_as_a_change(recording_admin, superuser, user):
    run_action(recording_admin, "quiet", superuser, [user])

    assert [(r.action, r.object_pk) for r in rows()] == [(Action.CHANGE, str(user.pk))]


def test_an_action_that_logs_itself_is_not_logged_twice(recording_admin, superuser, user):
    run_action(recording_admin, "logs_itself", superuser, [user])

    assert [r.action for r in rows()] == [Action.EXPORT]


# --- The rule that every admin of personal data logs ----------------------------------------------

FLAGGED = {
    "accounts.User",
    "animals.Animal",
    "animals.BodyMeasurement",
    "animals.AnimalHealthCondition",
    "animals.AnimalShare",
    "accounts.VetVerificationRequest",
    "accounts.DataSubjectRequest",
    "backoffice.AdminAccessLog",
    "axes.AccessAttempt",
    "axes.AccessLog",
    "axes.AccessFailureLog",
}
# Registered models that hold no personal data (a new model must be put in one of the two lists).
NO_PERSONAL_DATA = {"animals.HealthCondition", "catalog.ScientificSource", "auth.Group"}


def test_every_admin_of_a_model_with_personal_data_uses_the_mixin():
    for model, model_admin in admin.site._registry.items():
        if is_personal_data(model):
            assert isinstance(model_admin, AccessLoggedAdminMixin), model._meta.label


def test_the_registry_has_exactly_the_expected_models():
    registered = {model._meta.label for model in admin.site._registry}

    assert registered == FLAGGED | NO_PERSONAL_DATA


def test_every_registered_model_is_classified():
    """A model that is registered but neither flagged nor listed as free of personal data fails:
    whoever adds an admin has to decide (the failure names the model)."""
    unclassified = [
        model._meta.label
        for model in admin.site._registry
        if not is_personal_data(model) and model._meta.label not in NO_PERSONAL_DATA
    ]

    assert unclassified == []


def test_the_flagged_models_and_their_history_are_recognised():
    for model in (
        User,
        Animal,
        BodyMeasurement,
        AnimalHealthCondition,
        AnimalShare,
        AdminAccessLog,
    ):
        assert is_personal_data(model), model
    for model in (Animal, BodyMeasurement, AnimalHealthCondition, AnimalShare):
        assert is_personal_data(model.history.model), model
    assert not is_personal_data(HealthCondition) and not is_personal_data(ScientificSource)
    assert not is_personal_data(HealthCondition.history.model)


def test_a_flagged_model_with_a_plain_admin_is_reported(monkeypatch):
    class PlainAdmin(admin.ModelAdmin):
        pass

    registry = dict(admin.site._registry)
    registry[Animal] = PlainAdmin(Animal, admin.site)
    monkeypatch.setattr(admin.site, "_registry", registry)

    assert admin_mixin_missing() == ["animals.Animal"]
    errors = check_personal_data_admins(None)
    assert [e.id for e in errors] == ["backoffice.E001"]
    assert "animals.Animal" in errors[0].msg


def test_the_system_check_passes_for_the_real_registry():
    assert admin_mixin_missing() == []
    assert check_personal_data_admins(None) == []


# --- Reading the log ------------------------------------------------------------------------------


def test_the_log_is_listed_for_a_superuser_and_viewing_it_is_logged(root):
    AdminAccessLog.objects.create(staff_email="x@example.cz", action=Action.LOGIN)

    response = root.get(reverse("admin:backoffice_adminaccesslog_changelist"))

    assert response.status_code == 200 and "x@example.cz" in response.content.decode()
    assert [(r.action, r.model) for r in rows(model="adminaccesslog")] == [
        (Action.VIEW_LIST, "adminaccesslog")
    ]


def test_nobody_can_add_change_or_delete_a_row_in_the_admin(root):
    row = AdminAccessLog.objects.create(staff_email="x@example.cz", action=Action.LOGIN)

    assert root.get(reverse("admin:backoffice_adminaccesslog_add")).status_code == 403
    assert (
        root.post(
            reverse("admin:backoffice_adminaccesslog_delete", args=[row.pk]), {"post": "yes"}
        ).status_code
        == 403
    )
    change = root.post(
        reverse("admin:backoffice_adminaccesslog_change", args=[row.pk]), {"action": "CHANGE"}
    )
    assert change.status_code == 403
    assert root.post(
        reverse("admin:backoffice_adminaccesslog_changelist"),
        {"action": "delete_selected", "_selected_action": [row.pk], "post": "yes"},
    ).status_code in (200, 302)
    assert AdminAccessLog.objects.filter(pk=row.pk, action=Action.LOGIN).exists()


def test_a_row_is_shown_read_only(root):
    row = AdminAccessLog.objects.create(
        staff_email="x@example.cz", action=Action.CHANGE, app_label="accounts", model="user"
    )

    content = root.get(
        reverse("admin:backoffice_adminaccesslog_change", args=[row.pk])
    ).content.decode()

    assert "x@example.cz" in content
    assert 'name="_save"' not in content and 'name="action"' not in content


def test_the_log_filters_by_action(root):
    AdminAccessLog.objects.create(staff_email="login@example.cz", action=Action.LOGIN)
    AdminAccessLog.objects.create(staff_email="unlock@example.cz", action=Action.UNLOCK)

    content = root.get(
        reverse("admin:backoffice_adminaccesslog_changelist"), {"action__exact": "UNLOCK"}
    ).content.decode()

    assert "unlock@example.cz" in content and "login@example.cz" not in content


# --- Retention ------------------------------------------------------------------------------------


def age(row, days, **extra):
    AdminAccessLog.objects.filter(pk=row.pk).update(
        timestamp=timezone.now() - timedelta(days=days, **extra)
    )


def test_the_default_retention_is_a_year():
    from django.conf import settings

    assert settings.ADMIN_ACCESS_LOG_RETENTION_DAYS == 365


def test_old_rows_are_purged_and_new_ones_kept():
    old = AdminAccessLog.objects.create(staff_email="old@example.cz", action=Action.LOGIN)
    edge_in = AdminAccessLog.objects.create(staff_email="in@example.cz", action=Action.LOGIN)
    edge_out = AdminAccessLog.objects.create(staff_email="out@example.cz", action=Action.LOGIN)
    new = AdminAccessLog.objects.create(staff_email="new@example.cz", action=Action.LOGIN)
    age(old, 400)
    age(edge_in, 364, hours=23)
    age(edge_out, 365, minutes=1)

    deleted = purge_admin_access_log()

    assert deleted == 2
    assert set(AdminAccessLog.objects.values_list("pk", flat=True)) == {edge_in.pk, new.pk}


def test_the_retention_is_a_setting():
    row = AdminAccessLog.objects.create(staff_email="a@example.cz", action=Action.LOGIN)
    age(row, 40)

    with override_settings(ADMIN_ACCESS_LOG_RETENTION_DAYS=30):
        assert purge_admin_access_log() == 1
    assert purge_admin_access_log() == 0


def test_the_clock_can_be_given():
    AdminAccessLog.objects.create(staff_email="a@example.cz", action=Action.LOGIN)

    assert purge_admin_access_log(now=timezone.now() + timedelta(days=366)) == 1


@pytest.mark.parametrize("value", [0, -1, None, "365", 1.5, True])
def test_a_wrong_setting_deletes_nothing(value):
    row = AdminAccessLog.objects.create(staff_email="a@example.cz", action=Action.LOGIN)
    age(row, 4000)

    with (
        override_settings(ADMIN_ACCESS_LOG_RETENTION_DAYS=value),
        pytest.raises(ValueError, match="positive number of days"),
    ):
        purge_admin_access_log()
    assert AdminAccessLog.objects.filter(pk=row.pk).exists()


def test_the_command_reports_and_purges():
    row = AdminAccessLog.objects.create(staff_email="a@example.cz", action=Action.LOGIN)
    age(row, 400)
    out = io.StringIO()

    call_command("purge_admin_access_log", stdout=out)

    assert "365 dní: 1" in out.getvalue() and not AdminAccessLog.objects.exists()
    out = io.StringIO()
    call_command("purge_admin_access_log", stdout=out)
    assert "365 dní: 0" in out.getvalue()


def test_the_command_refuses_a_wrong_setting():
    with (
        override_settings(ADMIN_ACCESS_LOG_RETENTION_DAYS=0),
        pytest.raises(CommandError, match="Nic nebylo smazáno"),
    ):
        call_command("purge_admin_access_log", stdout=io.StringIO())
