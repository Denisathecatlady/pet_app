"""Forms of the animals app (Czech labels and messages).

Cross-field rules live in the model ``clean()`` methods; ModelForms run them.
Decimal fields accept both a decimal comma and a decimal point.
"""

from decimal import Decimal
from typing import Any

from django import forms
from django.utils import timezone

from .models import (
    BCS_MAX,
    BCS_MIN,
    Animal,
    AnimalHealthCondition,
    BodyMeasurement,
    HealthCondition,
    normalize_allergies,
)

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _weight_widget() -> forms.TextInput:
    return forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"})


def _with_empty_label(field: forms.Field, label: str) -> None:
    """Replace Django's "---------" choice of a select with a Czech label."""
    field.choices = [("", label)] + [choice for choice in field.choices if choice[0]]


def _trimmed(value: Decimal | None) -> Decimal | None:
    """``Decimal("18.500")`` → ``Decimal("18.5")`` (no exponent), so inputs show ``18,5``."""
    return None if value is None else Decimal(format(value.normalize(), "f"))


class AllergiesField(forms.CharField):
    """Comma-separated text in the form, a normalised list of strings in the model."""

    def prepare_value(self, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return ", ".join(value)
        return value

    def to_python(self, value: Any) -> list[str]:  # type: ignore[override]
        return normalize_allergies(super().to_python(value))


class AnimalForm(forms.ModelForm):
    required_css_class = "required"

    allergies = AllergiesField(
        label="Alergie a nesnášenlivosti",
        required=False,
        help_text=(
            "Oddělte čárkou, např. kuřecí maso, hovězí. Aplikace položky jen eviduje "
            "a nijak je nevyhodnocuje. Potravní alergii zjištěnou veterinárním lékařem "
            "zadejte také jako zdravotní stav „Potravní alergie“."
        ),
    )

    class Meta:
        model = Animal
        fields = (
            "name",
            "species",
            "sex",
            "neutered",
            "birth_date",
            "birth_date_estimated",
            "breed",
            "size_category",
            "physiological_state",
            "activity_level",
            "expected_adult_weight_kg",
            "target_weight_kg",
            "current_feeding",
            "allergies",
            "notes",
        )
        labels = {
            "neutered": "Kastrované zvíře",
            "birth_date_estimated": "Datum narození je jen odhad",
        }
        help_texts = {
            "birth_date": "Pokud přesné datum neznáte, zadejte odhad a zaškrtněte políčko níže.",
            "size_category": "Jen u psů. U koček nechte prázdné.",
            "physiological_state": (
                "Štěně nebo kotě, které ještě roste, má stav „růst“. Pro růst, březost "
                "a laktaci aplikace doporučení nenabízí: výživu má naplánovat veterinární "
                "lékař nebo veterinární nutriční specialista."
            ),
            "activity_level": "Vyberte popis, který nejlépe odpovídá běžnému dni zvířete.",
            "expected_adult_weight_kg": "Nepovinné. Užitečné hlavně u rostoucích zvířat.",
            "target_weight_kg": (
                "Nepovinné. Zadaná cílová hmotnost je orientační; ideální hmotnost by měl "
                "potvrdit veterinář podle BCS. Změnou hodnoty, druhu nebo fyziologického "
                "stavu se zruší případné potvrzení."
            ),
            "current_feeding": "Čím a jak zvíře nyní krmíte (volný text).",
        }
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "off"}),
            "birth_date": DATE_WIDGET,
            "expected_adult_weight_kg": _weight_widget(),
            "target_weight_kg": _weight_widget(),
            "current_feeding": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for name in ("expected_adult_weight_kg", "target_weight_kg"):
            self.fields[name].localize = True
            self.initial[name] = _trimmed(self.initial.get(name))
        choose = ["species", "sex", "activity_level"]
        if self.instance.pk is None:
            # A new animal has no preselected state: an owner of a puppy or kitten must
            # not end up in "adult" by leaving the default (docs/09 §9.2, growth).
            choose.append("physiological_state")
            self.initial["physiological_state"] = None
        for name in choose:
            _with_empty_label(self.fields[name], "— vyberte —")
        _with_empty_label(self.fields["size_category"], "— nezadáno —")
        # Changing the target weight, species or state cancels a vet's confirmation:
        # Animal.clean() does it, so it applies to the admin as well (docs/05 §5.3).


BCS_CHOICES = [("", "— nezadáno —")] + [
    (str(value), f"{value}/9") for value in range(BCS_MIN, BCS_MAX + 1)
]


class MeasurementForm(forms.ModelForm):
    """Measurement of an animal; the view sets animal, assessor and author on the instance."""

    required_css_class = "required"

    bcs = forms.TypedChoiceField(
        label="Skóre tělesné kondice (BCS)",
        choices=BCS_CHOICES,
        coerce=int,
        empty_value=None,
        required=False,
        help_text=(
            "Devítibodová škála: 1 = vyhublé, 4–5 = střed škály, 9 = těžká obezita. "
            "Pokud si nejste jistí, nechte nezadané nebo se poraďte s veterinárním lékařem."
        ),
    )

    class Meta:
        model = BodyMeasurement
        fields = ("measured_on", "weight_kg", "bcs", "mcs", "note")
        labels = {"weight_kg": "Hmotnost (kg)", "mcs": "Svalová kondice (MCS)"}
        help_texts = {
            "weight_kg": "V kilogramech, např. 12,4.",
            "mcs": "Hodnocení svalové hmoty podle WSAVA. Nepovinné.",
        }
        widgets = {
            "measured_on": DATE_WIDGET,
            "weight_kg": _weight_widget(),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["weight_kg"].localize = True
        _with_empty_label(self.fields["mcs"], "— nezadáno —")
        if self.instance.measured_on is None:
            self.initial["measured_on"] = timezone.localdate()


class ConditionForm(forms.ModelForm):
    """Health condition of an animal. ``condition`` is chosen only when adding."""

    required_css_class = "required"

    class Meta:
        model = AnimalHealthCondition
        fields = ("condition", "diagnosed_by_vet", "since", "vet_diet_restrictions", "note")
        labels = {
            "condition": "Zdravotní stav",
            "diagnosed_by_vet": "Stav diagnostikoval veterinární lékař",
            "since": "Od kdy",
            "vet_diet_restrictions": "Omezení stravy podle veterinárního lékaře",
        }
        help_texts = {
            "vet_diet_restrictions": (
                "Opište doporučení veterináře. Aplikace text jen zobrazí; nevyhodnocuje ho "
                "a nepoužívá ho k žádnému výpočtu."
            ),
        }
        widgets = {
            "since": DATE_WIDGET,
            "vet_diet_restrictions": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["condition"]
            return
        used = AnimalHealthCondition.objects.filter(animal=self.instance.animal).values("condition")
        field = self.fields["condition"]
        # Conditions already recorded are not offered (unique per animal).
        field.queryset = HealthCondition.objects.exclude(pk__in=used)
        field.empty_label = "— vyberte —"
        field.label_from_instance = lambda condition: (
            f"{condition.name_cs} ({condition.get_mode_display()})"
        )


class ShareForm(forms.Form):
    email = forms.EmailField(
        label="E-mail účtu veterinárního lékaře",
        max_length=254,
        help_text="Veterinární lékař musí mít v aplikaci účet s rolí veterinárního lékaře.",
        widget=forms.EmailInput(attrs={"autocomplete": "off"}),
    )


class ConfirmTargetWeightForm(forms.Form):
    """Hidden copy of the value the vet saw, compared again on confirmation."""

    target_weight_kg = forms.DecimalField(max_digits=6, decimal_places=3, widget=forms.HiddenInput)

    def expected(self) -> Decimal:
        return self.cleaned_data["target_weight_kg"]
