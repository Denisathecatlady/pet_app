"""Views of the animals app, mounted under ``/zvirata/``.

Every view resolves the animal through ``permissions.get_animal_for`` (HTTP 404 for
animals the user may not see, 403 for forbidden actions). State changes happen only
on POST with a CSRF token; destructive actions have a GET confirmation page.
"""

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import charts, services
from .forms import (
    AnimalForm,
    ConditionForm,
    ConfirmTargetWeightForm,
    MeasurementForm,
    ShareForm,
)
from .models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    Assessor,
    BodyMeasurement,
    format_kg,
)
from .permissions import Action, AnimalAccess, Relation, get_animal_for

# --- Animal -----------------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def animal_create(request: HttpRequest) -> HttpResponse:
    """New animal of the signed-in user."""
    form = AnimalForm(request.POST or None, instance=Animal(owner=request.user))
    if request.method == "POST" and form.is_valid():
        animal = form.save()
        messages.success(request, f"Zvíře {animal.name} bylo přidáno.")
        return redirect(animal)
    return render(request, "animals/animal_form.html", {"form": form, "animal": None})


@login_required
@require_GET
def animal_detail(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """Profile, attention level, target weight, measurements, conditions and shares.

    Data minimisation (docs/12 §12.6): a shared vet sees the e-mail of another vet
    (author of a measurement, confirmer of the target weight) only when it is their own.
    """
    access = get_animal_for(request.user, animal_uuid, Action.VIEW)
    animal = access.animal
    conditions = animal.conditions.select_related("condition")
    context = {
        "access": access,
        "animal": animal,
        "age": services.age_text(animal),
        "attention": services.attention(animal),
        "measurements": animal.measurements.select_related("created_by"),
        "conditions": conditions,
        "suggest_food_allergy": bool(animal.allergies)
        and not any(item.condition.code == "FOOD_ALLERGY" for item in conditions),
        "shares": (
            animal.shares.active().select_related("vet")
            if access.is_owner
            else AnimalShare.objects.none()
        ),
    }
    return render(request, "animals/animal_detail.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def animal_edit(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """Edit the profile. Changing the target weight, species or state cancels a confirmation.

    A POST validates and saves the row locked with ``SELECT … FOR UPDATE``: a vet's
    confirmation committed while the owner was editing is then compared and kept (or
    cancelled by a real change), never overwritten with stale values.
    """
    access = get_animal_for(request.user, animal_uuid, Action.EDIT)
    if request.method == "POST":
        with transaction.atomic():
            # A separate instance: a rejected POST must not change what the page shows.
            instance = Animal.objects.select_for_update().get(pk=access.animal.pk)
            form = AnimalForm(request.POST, instance=instance)
            if form.is_valid():
                animal = form.save()
                messages.success(request, "Změny byly uloženy.")
                return redirect(animal)
    else:
        form = AnimalForm(instance=Animal.objects.get(pk=access.animal.pk))
    return render(request, "animals/animal_form.html", {"form": form, "animal": access.animal})


@login_required
@require_http_methods(["GET", "POST"])
def animal_delete(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """Confirmation page (GET) and deletion of the animal with all its records (POST)."""
    access = get_animal_for(request.user, animal_uuid, Action.DELETE)
    animal = access.animal
    if request.method == "POST":
        name = animal.name
        animal.delete()
        messages.success(request, f"Zvíře {name} a všechny jeho záznamy byly smazány.")
        return redirect("core:dashboard")
    conditions = animal.conditions.count()
    condition_noun = services.plural(
        conditions, "zdravotní stav", "zdravotní stavy", "zdravotních stavů"
    )
    context = {
        "animal": animal,
        "title": f"Smazat zvíře {animal.name}?",
        "details": [
            "Smaže se profil zvířete, "
            f"{animal.measurements.count()} měření, "
            f"{conditions} {condition_noun}, sdílení s veterinárními lékaři "
            "a historie změn těchto záznamů.",
            "Smazání je nevratné.",
        ],
        "button": "Trvale smazat zvíře",
    }
    return render(request, "animals/confirm.html", context)


# --- Measurements -----------------------------------------------------------------------------

# "Měření se uloží jako posouzené …" (instrumental case of the assessor).
ASSESSED_BY_TEXT = {Assessor.OWNER: "majitelem", Assessor.VET: "veterinárním lékařem"}


@login_required
@require_http_methods(["GET", "POST"])
def measurement_add(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """Record weight, BCS and MCS. A shared vet's record is stored as assessed by a vet."""
    access = get_animal_for(request.user, animal_uuid, Action.ADD_MEASUREMENT)
    assessor = Assessor.OWNER if access.relation is Relation.OWNER else Assessor.VET
    instance = BodyMeasurement(animal=access.animal, assessed_by=assessor, created_by=request.user)
    form = MeasurementForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Měření bylo uloženo.")
        return redirect(access.animal)
    context = {
        "form": form,
        "animal": access.animal,
        "assessed_by": ASSESSED_BY_TEXT[Assessor(assessor)],
    }
    return render(request, "animals/measurement_form.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def measurement_delete(
    request: HttpRequest, animal_uuid: UUID, measurement_uuid: UUID
) -> HttpResponse:
    """Confirmation page (GET) and deletion (POST) of one measurement; owner only."""
    access = get_animal_for(request.user, animal_uuid, Action.EDIT)
    measurement = get_object_or_404(access.animal.measurements, uuid=measurement_uuid)
    if request.method == "POST":
        measurement.delete()
        messages.success(request, "Měření bylo smazáno.")
        return redirect(access.animal)
    context = {
        "animal": access.animal,
        "title": "Smazat měření?",
        "details": [
            f"Měření ze dne {services.short_date(measurement.measured_on)} "
            f"({format_kg(measurement.weight_kg)} kg) se smaže i s historií změn.",
            "Smazání je nevratné.",
        ],
        "button": "Smazat měření",
    }
    return render(request, "animals/confirm.html", context)


@login_required
@require_GET
def tracking(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """Weight and body-condition charts with the data table (docs/12 §12.11).

    ``?obdobi=`` picks the period (``30``, ``90``, ``365`` or ``vse``); anything else
    falls back to 90 days. The page only describes the records: it never judges a
    change of weight or recommends anything. The table is the accessible alternative of
    the charts and has the same content as the charts for the chosen period; like the
    detail page, it shows the e-mail of a vet who wrote a measurement only to the owner
    and to that vet.
    """
    access = get_animal_for(request.user, animal_uuid, Action.VIEW)
    animal = access.animal
    period = charts.parse_period(request.GET.get("obdobi"))
    # Newest first from the database; the charts want the oldest recorded first.
    measurements = list(animal.measurements.select_related("created_by"))
    data = charts.build_tracking(
        reversed(measurements),
        period,
        timezone.localdate(),
        target_weight_kg=animal.target_weight_kg,
        target_status=animal.target_weight_status,
    )
    context = {
        "access": access,
        "animal": animal,
        "period": period,
        "periods": [(item, item == period) for item in charts.PERIODS],
        "data": data,
        "weight": data.weight,
        "bcs": data.bcs,
        "weight_description": charts.describe_weight_chart(data.weight),
        "bcs_description": charts.describe_bcs_chart(data.bcs),
        "change_sentence": charts.change_sentence(data.weight.summary),
        "rows": list(reversed(data.measurements)),
        "outside_period": len(measurements) - len(data.measurements),
        "total": len(measurements),
    }
    return render(request, "animals/tracking.html", context)


# --- Health conditions ------------------------------------------------------------------------


def _condition_for(access: AnimalAccess, code: str) -> AnimalHealthCondition:
    return get_object_or_404(
        access.animal.conditions.select_related("condition"), condition__code=code
    )


@login_required
@require_http_methods(["GET", "POST"])
def condition_add(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    access = get_animal_for(request.user, animal_uuid, Action.MANAGE_CONDITIONS)
    form = ConditionForm(request.POST or None, instance=AnimalHealthCondition(animal=access.animal))
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                item = form.save()
        except IntegrityError:  # added concurrently
            form.add_error("condition", "Tento zdravotní stav už je u zvířete zadaný.")
        else:
            messages.success(request, f"Zdravotní stav „{item.condition.name_cs}“ byl přidán.")
            return redirect(access.animal)
    return render(
        request,
        "animals/condition_form.html",
        {"form": form, "animal": access.animal, "item": None},
    )


@login_required
@require_http_methods(["GET", "POST"])
def condition_edit(request: HttpRequest, animal_uuid: UUID, code: str) -> HttpResponse:
    access = get_animal_for(request.user, animal_uuid, Action.MANAGE_CONDITIONS)
    item = _condition_for(access, code)
    form = ConditionForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Změny byly uloženy.")
        return redirect(access.animal)
    return render(
        request,
        "animals/condition_form.html",
        {"form": form, "animal": access.animal, "item": item},
    )


@login_required
@require_http_methods(["GET", "POST"])
def condition_remove(request: HttpRequest, animal_uuid: UUID, code: str) -> HttpResponse:
    access = get_animal_for(request.user, animal_uuid, Action.MANAGE_CONDITIONS)
    item = _condition_for(access, code)
    if request.method == "POST":
        item.delete()
        messages.success(request, f"Zdravotní stav „{item.condition.name_cs}“ byl odebrán.")
        return redirect(access.animal)
    context = {
        "animal": access.animal,
        "title": f"Odebrat zdravotní stav „{item.condition.name_cs}“?",
        "details": ["Záznam o stavu se smaže i s historií změn. Smazání je nevratné."],
        "button": "Odebrat stav",
    }
    return render(request, "animals/confirm.html", context)


# --- Sharing with a vet -----------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def share_add(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """Share the animal with a vet account identified by e-mail."""
    access = get_animal_for(request.user, animal_uuid, Action.MANAGE_SHARES)
    form = ShareForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            share = services.share_with_vet(access.animal, form.cleaned_data["email"], request.user)
        except ValidationError as error:
            form.add_error("email", error)
        else:
            messages.success(
                request,
                f"Zvíře {access.animal.name} nyní sdílíte s {share.vet.email}. Sdílení můžete "
                "kdykoli zrušit.",
            )
            return redirect(access.animal)
    return render(request, "animals/share_form.html", {"form": form, "animal": access.animal})


@login_required
@require_http_methods(["GET", "POST"])
def share_revoke(request: HttpRequest, animal_uuid: UUID, share_uuid: UUID) -> HttpResponse:
    """Confirmation page (GET) and end of an active share (POST). The vet loses access now."""
    access = get_animal_for(request.user, animal_uuid, Action.MANAGE_SHARES)
    share = get_object_or_404(access.animal.shares.active().select_related("vet"), uuid=share_uuid)
    if request.method == "POST":
        services.revoke_share(share)
        messages.success(request, f"Sdílení s {share.vet.email} bylo zrušeno.")
        return redirect(access.animal)
    context = {
        "animal": access.animal,
        "title": f"Zrušit sdílení s {share.vet.email}?",
        "details": [
            f"Veterinární lékař {share.vet.email} ihned ztratí přístup ke zvířeti "
            f"{access.animal.name}. Měření, která zapsal, zůstanou.",
            "Znovu sdílet můžete kdykoli zadáním jeho e-mailu.",
        ],
        "button": "Zrušit sdílení",
        "cancel": "Ponechat sdílení",
    }
    return render(request, "animals/confirm.html", context)


# --- Target weight ----------------------------------------------------------------------------


@login_required
@require_POST
def target_weight_confirm(request: HttpRequest, animal_uuid: UUID) -> HttpResponse:
    """A vet with an active share confirms the target weight they saw (POST only)."""
    access = get_animal_for(request.user, animal_uuid, Action.CONFIRM_TARGET_WEIGHT)
    form = ConfirmTargetWeightForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Potvrzení se nepodařilo. Načtěte stránku a zkuste to znovu.")
        return redirect(access.animal)
    try:
        services.confirm_target_weight(access.animal, request.user, form.expected())
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, "Cílová hmotnost je potvrzená.")
    return redirect(access.animal)
