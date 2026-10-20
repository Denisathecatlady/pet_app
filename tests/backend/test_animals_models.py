"""Models of the animals app: validation, DB constraints, history and the condition catalog."""

import importlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.apps import apps
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from animals.models import (
    WEIGHT_BOUNDS_KG,
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    HealthCondition,
    PhysiologicalState,
    Sex,
    SizeCategory,
    Species,
    TargetWeightStatus,
    normalize_allergies,
    weight_error,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


def assert_clean_error(instance, field):
    with pytest.raises(ValidationError) as error:
        instance.full_clean()
    assert field in error.value.message_dict, error.value.message_dict
    return error.value.message_dict[field]


def assert_db_rejects(instance):
    with pytest.raises(IntegrityError), transaction.atomic():
        instance.save()


def dog(owner, **fields):
    values = {"name": "Rex", "species": Species.DOG, "sex": Sex.MALE, "activity_level": "LOW"}
    return Animal(owner=owner, **{**values, **fields})


# --- Animal validation ------------------------------------------------------------------------


def test_valid_animal_passes(user):
    animal = dog(
        user,
        birth_date=TODAY() - timedelta(days=800),
        birth_date_estimated=True,
        size_category=SizeCategory.LARGE,
        expected_adult_weight_kg=Decimal("30"),
        target_weight_kg=Decimal("28.5"),
        allergies=["Kuřecí ", "kuřecí"],
    )
    animal.full_clean()
    animal.save()
    assert animal.allergies == ["kuřecí"]
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert animal.uuid is not None


def test_birth_date_must_not_be_in_the_future(user):
    message = assert_clean_error(dog(user, birth_date=TODAY() + timedelta(days=1)), "birth_date")
    assert message == ["Datum narození nemůže být v budoucnosti."]


def test_estimate_requires_birth_date(user):
    assert_clean_error(dog(user, birth_date_estimated=True), "birth_date_estimated")
    assert_db_rejects(dog(user, birth_date_estimated=True))


def test_size_category_only_for_dogs(user):
    cat = dog(user, species=Species.CAT, size_category=SizeCategory.SMALL)
    assert assert_clean_error(cat, "size_category") == ["Velikostní kategorie se zadává jen u psů."]
    assert_db_rejects(dog(user, species=Species.CAT, size_category=SizeCategory.SMALL))


@pytest.mark.parametrize("state", [PhysiologicalState.GESTATION, PhysiologicalState.LACTATION])
def test_gestation_and_lactation_only_for_females(user, state):
    assert_clean_error(dog(user, sex=Sex.MALE, physiological_state=state), "physiological_state")
    assert_db_rejects(dog(user, sex=Sex.MALE, physiological_state=state))
    dog(user, sex=Sex.FEMALE, physiological_state=state).full_clean()


@pytest.mark.parametrize(
    ("species", "value", "valid"),
    [
        (Species.DOG, "0.5", True),
        (Species.DOG, "120", True),
        (Species.DOG, "0.499", False),
        (Species.DOG, "120.001", False),
        (Species.CAT, "0.5", True),
        (Species.CAT, "15", True),
        (Species.CAT, "15.001", False),
        (Species.CAT, "30", False),
        (Species.DOG, "0", False),
        (Species.DOG, "-5", False),
    ],
)
@pytest.mark.parametrize("field", ["target_weight_kg", "expected_adult_weight_kg"])
def test_weights_within_technical_bounds(user, species, value, valid, field):
    animal = dog(user, species=species, **{field: Decimal(value)})
    if valid:
        animal.full_clean()
        animal.save()
    else:
        assert "technickou kontrolu" in assert_clean_error(animal, field)[0]
        assert_db_rejects(dog(user, species=species, **{field: Decimal(value)}))


def test_weight_bounds_constants():
    assert WEIGHT_BOUNDS_KG[Species.DOG] == (Decimal("0.5"), Decimal("120"))
    assert WEIGHT_BOUNDS_KG[Species.CAT] == (Decimal("0.5"), Decimal("15"))
    assert weight_error(Species.DOG, None) is None
    assert weight_error("FISH", Decimal("999")) is None


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "   "},
        {"species": "COW"},
        {"sex": "OTHER"},
        {"activity_level": "EXTREME"},
        {"size_category": "HUGE"},
        {"physiological_state": "SENIOR"},
    ],
)
def test_db_rejects_invalid_values(user, fields):
    assert_db_rejects(dog(user, **fields))


def test_target_weight_confirmation_constraint(user, vet_user):
    now = timezone.now()
    # VET_CONFIRMED needs a value, the vet and the time.
    for missing in (
        {"target_weight_confirmed_by": None},
        {"target_weight_confirmed_at": None},
        {"target_weight_kg": None},
    ):
        values = {
            "target_weight_kg": Decimal("20"),
            "target_weight_status": TargetWeightStatus.VET_CONFIRMED,
            "target_weight_confirmed_by": vet_user,
            "target_weight_confirmed_at": now,
            **missing,
        }
        assert_db_rejects(dog(user, **values))
    # UNVERIFIED carries no confirmation.
    assert_db_rejects(
        dog(user, target_weight_kg=Decimal("20"), target_weight_confirmed_by=vet_user)
    )
    assert_db_rejects(dog(user, target_weight_kg=Decimal("20"), target_weight_confirmed_at=now))
    dog(
        user,
        target_weight_kg=Decimal("20"),
        target_weight_status=TargetWeightStatus.VET_CONFIRMED,
        target_weight_confirmed_by=vet_user,
        target_weight_confirmed_at=now,
    ).save()


def test_constraint_violation_message_is_czech(user):
    animal = dog(user, target_weight_kg=Decimal("20"), target_weight_status="VET_CONFIRMED")
    with pytest.raises(ValidationError) as error:
        animal.full_clean()
    assert any("Potvrzená cílová hmotnost" in m for m in error.value.messages)


def test_species_change_checks_existing_measurements(user, make_animal, make_measurement):
    animal = make_animal(user)
    make_measurement(animal, weight_kg=Decimal("30"))
    animal.species = Species.CAT
    assert "Druh nelze změnit" in assert_clean_error(animal, "species")[0]


def confirmed_dog(owner, vet, **fields):
    animal = dog(
        owner,
        target_weight_kg=Decimal("20"),
        target_weight_status=TargetWeightStatus.VET_CONFIRMED,
        target_weight_confirmed_by=vet,
        target_weight_confirmed_at=timezone.now(),
        **fields,
    )
    animal.full_clean()
    animal.save()
    return Animal.objects.get(pk=animal.pk)


@pytest.mark.parametrize(
    "change",
    [
        {"target_weight_kg": Decimal("35")},
        {"species": Species.CAT, "target_weight_kg": Decimal("10")},
        {"physiological_state": PhysiologicalState.GROWTH},
    ],
    ids=["target_weight", "species", "state"],
)
def test_clean_cancels_confirmation_when_its_basis_changes(user, vet_user, change):
    """docs/05 §5.3: the vet confirmed this value for this animal; any edit path."""
    animal = confirmed_dog(user, vet_user)
    for name, value in change.items():
        setattr(animal, name, value)

    animal.full_clean()
    animal.save()

    animal.refresh_from_db()
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert animal.target_weight_confirmed_by is None


def test_clean_keeps_confirmation_for_other_changes(user, vet_user):
    animal = confirmed_dog(user, vet_user)
    animal.name = "Rexík"
    animal.target_weight_kg = Decimal("20.000")  # same value
    animal.full_clean()
    assert animal.target_weight_status == TargetWeightStatus.VET_CONFIRMED


def test_new_confirmation_must_name_a_vet(user, make_user):
    owner_only = make_user("not-a-vet@example.cz")
    animal = dog(
        user,
        target_weight_kg=Decimal("20"),
        target_weight_status=TargetWeightStatus.VET_CONFIRMED,
        target_weight_confirmed_by=owner_only,
        target_weight_confirmed_at=timezone.now(),
    )
    message = assert_clean_error(animal, NON_FIELD_ERRORS)
    assert "jen účet s rolí veterinárního lékaře" in message[0]


def test_stored_confirmation_of_a_former_vet_does_not_block_other_edits(user, vet_user):
    animal = confirmed_dog(user, vet_user)
    # Bypass the role signal to model a confirmation stored before this rule existed.
    Animal.objects.filter(pk=animal.pk).update(target_weight_confirmed_by=user)
    animal.refresh_from_db()
    animal.name = "Rexík"
    animal.full_clean()  # does not raise: only a new confirmation is checked


def test_reset_target_weight_confirmation(user, vet_user):
    animal = dog(
        user,
        target_weight_kg=Decimal("20"),
        target_weight_status=TargetWeightStatus.VET_CONFIRMED,
        target_weight_confirmed_by=vet_user,
        target_weight_confirmed_at=timezone.now(),
    )
    animal.reset_target_weight_confirmation()
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert animal.target_weight_confirmed_by is None
    assert animal.target_weight_confirmed_at is None


# --- Allergies --------------------------------------------------------------------------------


def test_allergies_are_normalised_and_deduplicated():
    raw = "  Kuřecí   maso, HOVĚZÍ; kuřecí maso\n, ,ryby "
    assert normalize_allergies(raw) == ["kuřecí maso", "hovězí", "ryby"]
    assert normalize_allergies(["Vejce", "vejce "]) == ["vejce"]
    assert normalize_allergies(None) == []
    assert normalize_allergies("") == []


@pytest.mark.parametrize(
    "value", [{"a": 1}, [1, 2], "x" * 61, ",".join(f"a{i}" for i in range(31))]
)
def test_allergies_reject_invalid_values(value):
    with pytest.raises(ValidationError):
        normalize_allergies(value)


def test_model_clean_rejects_malformed_allergies(user):
    assert_clean_error(dog(user, allergies={"kuře": True}), "allergies")


# --- Measurements -----------------------------------------------------------------------------


def test_measurement_date_not_in_future(user, make_animal):
    animal = make_animal(user)
    measurement = BodyMeasurement(
        animal=animal,
        measured_on=TODAY() + timedelta(days=1),
        weight_kg=Decimal("20"),
        assessed_by="OWNER",
    )
    assert assert_clean_error(measurement, "measured_on") == [
        "Datum měření nemůže být v budoucnosti."
    ]


@pytest.mark.parametrize("estimated", [False, True])
def test_measurement_date_not_before_exact_birth_date(user, make_animal, estimated):
    birth = TODAY() - timedelta(days=100)
    animal = make_animal(user, birth_date=birth, birth_date_estimated=estimated)
    measurement = BodyMeasurement(
        animal=animal,
        measured_on=birth - timedelta(days=1),
        weight_kg=Decimal("5"),
        assessed_by="OWNER",
    )
    if estimated:  # an estimate may be off: nothing is rejected against it
        measurement.full_clean()
    else:
        message = assert_clean_error(measurement, "measured_on")[0]
        assert message.startswith("Datum měření nemůže být dřívější než datum narození")
    measurement.measured_on = birth
    measurement.full_clean()


def test_condition_since_not_before_exact_birth_date(user, make_animal):
    birth = TODAY() - timedelta(days=100)
    animal = make_animal(user, birth_date=birth)
    item = AnimalHealthCondition(
        animal=animal,
        condition=HealthCondition.objects.get(code="CKD"),
        since=birth - timedelta(days=1),
    )
    assert "dřívější než datum narození" in assert_clean_error(item, "since")[0]


def test_birth_date_not_after_stored_records(user, make_animal, make_measurement):
    animal = make_animal(user, birth_date=TODAY() - timedelta(days=400))
    make_measurement(animal, measured_on=TODAY() - timedelta(days=300))
    animal.birth_date = TODAY() - timedelta(days=200)
    assert "pozdější než některé uložené měření" in assert_clean_error(animal, "birth_date")[0]
    animal.birth_date_estimated = True
    animal.full_clean()


def test_measurement_weight_uses_species_bounds(user, make_animal):
    cat = make_animal(user, species=Species.CAT, name="Micka")
    measurement = BodyMeasurement(
        animal=cat, measured_on=TODAY(), weight_kg=Decimal("20"), assessed_by="OWNER"
    )
    assert "kočky" in assert_clean_error(measurement, "weight_kg")[0]


@pytest.mark.parametrize(
    "fields",
    [
        {"weight_kg": Decimal("0.4")},
        {"weight_kg": Decimal("120.5")},
        {"bcs": 0},
        {"bcs": 10},
        {"mcs": "GOOD"},
        {"assessed_by": "VETS"},
    ],
)
def test_measurement_db_constraints(user, make_animal, fields):
    animal = make_animal(user)
    values = {"measured_on": TODAY(), "weight_kg": Decimal("20"), "assessed_by": "OWNER", **fields}
    assert_db_rejects(BodyMeasurement(animal=animal, **values))


def test_measurement_bcs_validation_message(user, make_animal):
    animal = make_animal(user)
    measurement = BodyMeasurement(
        animal=animal, measured_on=TODAY(), weight_kg=Decimal("20"), bcs=10, assessed_by="OWNER"
    )
    assert assert_clean_error(measurement, "bcs") == ["BCS musí být celé číslo 1–9."]


def test_measurements_are_ordered_newest_first(user, make_animal, make_measurement):
    animal = make_animal(user)
    old = make_measurement(animal, measured_on=TODAY() - timedelta(days=10))
    new = make_measurement(animal, measured_on=TODAY())
    middle = make_measurement(animal, measured_on=TODAY() - timedelta(days=5))
    assert list(animal.measurements.all()) == [new, middle, old]


# --- Conditions and shares --------------------------------------------------------------------


def test_condition_unique_per_animal(user, make_animal):
    animal = make_animal(user)
    ckd = HealthCondition.objects.get(code="CKD")
    AnimalHealthCondition.objects.create(animal=animal, condition=ckd)
    assert_db_rejects(AnimalHealthCondition(animal=animal, condition=ckd))


def test_condition_since_not_in_future(user, make_animal):
    item = AnimalHealthCondition(
        animal=make_animal(user),
        condition=HealthCondition.objects.get(code="CKD"),
        since=TODAY() + timedelta(days=3),
    )
    assert_clean_error(item, "since")


def test_catalog_condition_in_use_is_protected(user, make_animal):
    ckd = HealthCondition.objects.get(code="CKD")
    AnimalHealthCondition.objects.create(animal=make_animal(user), condition=ckd)
    with pytest.raises(ProtectedError):
        ckd.delete()


def test_one_active_share_per_vet(user, make_animal, vet_user):
    animal = make_animal(user)
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    assert_db_rejects(AnimalShare(animal=animal, vet=vet_user, granted_by=user))


def test_revoked_shares_do_not_block_a_new_one(user, make_animal, vet_user):
    animal = make_animal(user)
    now = timezone.now()
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user, revoked_at=now)
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user, revoked_at=now)
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)
    assert AnimalShare.objects.active().count() == 1


def test_share_with_owner_is_invalid(user, make_animal):
    share = AnimalShare(animal=make_animal(user), vet=user, granted_by=user)
    assert_clean_error(share, "vet")


def test_share_recipient_must_be_a_vet(user, make_animal, make_user, vet_user):
    animal = make_animal(user)
    neighbour = make_user("soused@example.cz")
    message = assert_clean_error(AnimalShare(animal=animal, vet=neighbour, granted_by=user), "vet")
    assert message == ["Sdílet lze jen s účtem, který má roli veterinárního lékaře."]
    AnimalShare(animal=animal, vet=vet_user, granted_by=user).full_clean()


# --- History ----------------------------------------------------------------------------------


def test_history_records_created_on_change(user, make_animal, make_measurement, vet_user):
    animal = make_animal(user)
    animal.name = "Rexík"
    animal.save()
    measurement = make_measurement(animal)
    item = AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code="CKD")
    )
    item.note = "kontrola za měsíc"
    item.save()
    share = AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)

    assert [h.history_type for h in animal.history.order_by("history_date")] == ["+", "~"]
    assert animal.history.earliest("history_date").name == "Rex"
    assert measurement.history.count() == 1
    assert [h.history_type for h in item.history.order_by("history_date")] == ["+", "~"]
    assert share.history.count() == 1


def test_catalog_has_history():
    condition = HealthCondition.objects.get(code="CKD")
    condition.description_cs = "upraveno"
    condition.save()
    # The seeded state (migration 0003) and the change.
    assert [r.history_type for r in condition.history.order_by("history_date")] == ["+", "~"]
    assert condition.history.earliest("history_date").description_cs.startswith("Úprava P")


def test_every_catalog_entry_starts_with_a_created_record():
    assert HealthCondition.history.filter(history_type="+").count() == len(EXPECTED_CATALOG)
    backfill = importlib.import_module("animals.migrations.0003_health_condition_initial_history")
    backfill.add_initial_history(apps, None)  # running again adds nothing
    assert HealthCondition.history.count() == len(EXPECTED_CATALOG)


seed_migration = importlib.import_module("animals.migrations.0002_seed_health_conditions")


def test_seed_migration_is_idempotent_and_reversible():
    seed_migration.seed(apps, None)
    assert HealthCondition.objects.count() == len(EXPECTED_CATALOG)

    seed_migration.unseed(apps, None)
    assert not HealthCondition.objects.exists()

    seed_migration.seed(apps, None)
    assert HealthCondition.objects.count() == len(EXPECTED_CATALOG)


def test_seed_migration_reverses_with_conditions_in_use(user, make_animal):
    """Codes recorded at an animal are protected; reversing keeps them instead of failing."""
    AnimalHealthCondition.objects.create(
        animal=make_animal(user), condition=HealthCondition.objects.get(code="CKD")
    )

    seed_migration.unseed(apps, None)

    assert list(HealthCondition.objects.values_list("code", flat=True)) == ["CKD"]
    seed_migration.seed(apps, None)
    assert HealthCondition.objects.count() == len(EXPECTED_CATALOG)


def test_deleting_an_animal_deletes_its_records_and_history(
    user, make_animal, make_measurement, vet_user
):
    animal = make_animal(user)
    make_measurement(animal)
    AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code="CKD")
    )
    AnimalShare.objects.create(animal=animal, vet=vet_user, granted_by=user)

    animal.delete()

    for model in (Animal, BodyMeasurement, AnimalHealthCondition, AnimalShare):
        assert not model.objects.exists()
        assert not model.history.model.objects.exists(), model


# --- Catalog seed (docs/09 §9.2) --------------------------------------------------------------

EXPECTED_CATALOG = {
    "CKD": ("Chronické onemocnění ledvin (CKD)", "BLOCKED"),
    "LIVER_DISEASE": ("Onemocnění jater", "BLOCKED"),
    "PANCREATITIS": ("Pankreatitida", "BLOCKED"),
    "HYPERLIPIDEMIA": ("Hyperlipidémie", "BLOCKED"),
    "DIABETES_MELLITUS": ("Diabetes mellitus", "BLOCKED"),
    "UROLITHIASIS": ("Urolitiáza a onemocnění močových cest", "BLOCKED"),
    "FOOD_ALLERGY": ("Potravní alergie", "EXPERT_REQUIRED"),
    "MEDICATION_AFFECTING_DIET": ("Užívání léků ovlivňujících výživu", "EXPERT_REQUIRED"),
    "OTHER_CHRONIC": ("Jiné chronické onemocnění", "EXPERT_REQUIRED"),
}


def test_catalog_seed_is_exact():
    catalog = {c.code: (c.name_cs, c.mode) for c in HealthCondition.objects.all()}
    assert catalog == EXPECTED_CATALOG


def test_catalog_descriptions_follow_docs_09():
    descriptions = dict(HealthCondition.objects.values_list("code", "description_cs"))
    assert descriptions["CKD"].startswith("Úprava P, bílkovin, Na")
    assert descriptions["PANCREATITIS"] == descriptions["HYPERLIPIDEMIA"]
    assert descriptions["MEDICATION_AFFECTING_DIET"] == "Interakce posoudí veterinář"


def test_catalog_source_notes_name_the_specialist():
    for condition in HealthCondition.objects.all():
        assert "docs/09 §9.2" in condition.source_note
        assert "veterinární nutriční specialista" in condition.source_note
    other = HealthCondition.objects.get(code="OTHER_CHRONIC")
    assert "mimo tabulku §9.2" in other.source_note


def test_catalog_contains_no_numbers():
    for condition in HealthCondition.objects.all():
        text = condition.name_cs + condition.description_cs
        assert not any(char.isdigit() for char in text), condition.code
