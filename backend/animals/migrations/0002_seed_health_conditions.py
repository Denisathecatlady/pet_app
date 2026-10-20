"""Seed the health condition catalog from docs/09 §9.2 (safety gate).

Names, levels and reasons are copied from the table in docs/09 §9.2; the row
"Pankreatitida, hyperlipidémie" is split into two entries. ``OTHER_CHRONIC`` is not
a row of that table: it is a catch-all added by the application so that an owner can
record a chronic disease outside the list (level as specified for this iteration).
The data are frozen here on purpose: migrations must not import app code.
"""

from django.db import migrations

SOURCE_NOTE = (
    "Bezpečnostní brána docs/09 §9.2. Seznam spravuje a schvaluje veterinární nutriční "
    "specialista; texty i úrovně čekají na jeho revizi."
)
OTHER_SOURCE_NOTE = (
    SOURCE_NOTE + " Položka doplněná aplikací pro chronická onemocnění mimo tabulku §9.2."
)

CONDITIONS = (
    (
        "CKD",
        "Chronické onemocnění ledvin (CKD)",
        "Úprava P, bílkovin, Na a dalších podle stadia vyžaduje veterinární plán",
        "BLOCKED",
        SOURCE_NOTE,
    ),
    (
        "LIVER_DISEASE",
        "Onemocnění jater",
        "Individuální úprava bílkovin, Cu a dalších",
        "BLOCKED",
        SOURCE_NOTE,
    ),
    (
        "PANCREATITIS",
        "Pankreatitida",
        "Strop tuku stanoví veterinář. Syrové tučné suroviny jsou rizikové",
        "BLOCKED",
        SOURCE_NOTE,
    ),
    (
        "HYPERLIPIDEMIA",
        "Hyperlipidémie",
        "Strop tuku stanoví veterinář. Syrové tučné suroviny jsou rizikové",
        "BLOCKED",
        SOURCE_NOTE,
    ),
    (
        "DIABETES_MELLITUS",
        "Diabetes mellitus",
        "Vazba na terapii inzulinem a režim krmení",
        "BLOCKED",
        SOURCE_NOTE,
    ),
    (
        "UROLITHIASIS",
        "Urolitiáza a onemocnění močových cest",
        "Závisí na typu urolitu (struvit, oxalát, urát…)",
        "BLOCKED",
        SOURCE_NOTE,
    ),
    (
        "FOOD_ALLERGY",
        "Potravní alergie",
        "Eliminační dieta je diagnostický postup. Aplikace umí jen filtrovat alergeny",
        "EXPERT_REQUIRED",
        SOURCE_NOTE,
    ),
    (
        "MEDICATION_AFFECTING_DIET",
        "Užívání léků ovlivňujících výživu",
        "Interakce posoudí veterinář",
        "EXPERT_REQUIRED",
        SOURCE_NOTE,
    ),
    (
        "OTHER_CHRONIC",
        "Jiné chronické onemocnění",
        "Chronické onemocnění, které v seznamu není. Vliv na výživu posoudí veterinář",
        "EXPERT_REQUIRED",
        OTHER_SOURCE_NOTE,
    ),
)


def seed(apps, schema_editor):
    HealthCondition = apps.get_model("animals", "HealthCondition")
    for code, name_cs, description_cs, mode, source_note in CONDITIONS:
        HealthCondition.objects.update_or_create(
            code=code,
            defaults={
                "name_cs": name_cs,
                "description_cs": description_cs,
                "mode": mode,
                "source_note": source_note,
            },
        )


def unseed(apps, schema_editor):
    HealthCondition = apps.get_model("animals", "HealthCondition")
    HealthCondition.objects.filter(code__in=[row[0] for row in CONDITIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("animals", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
