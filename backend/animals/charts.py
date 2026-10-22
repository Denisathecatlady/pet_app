"""Chart geometry for weight and body condition (docs/08 §8.3, docs/12 §12.11).

Pure functions that turn measurements into what an SVG needs: points, axis ticks, pixel
coordinates, summary statistics and descriptions in words. Nothing here reads the
clock, the database or the settings: ``today`` is always an argument.

Weights, differences, percentages and axis values are :class:`~decimal.Decimal`. Floats
appear only for pixel coordinates (the ``x``/``y`` fields and the ``Frame``), which is
what this presentation module exists for.

The module is **descriptive only**. It states what was recorded (first and last weight,
the change between them, the number of days) and never judges the change: no thresholds,
no "too fast", no advice on feeding. The target weight is drawn as a reference line
labelled by its status (docs/05 §5.3), never as an "ideal".
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    localcontext,
)
from typing import Final, Protocol

from .models import BCS_MAX, BCS_MIN, Assessor, TargetWeightStatus, format_kg
from .text import plural, short_date

MINUS: Final = "\N{MINUS SIGN}"
NBSP: Final = "\N{NO-BREAK SPACE}"

# Fixed context: the same input gives the same ticks on every machine (docs/05 §5.7).
_CONTEXT: Final = Context(prec=28, rounding=ROUND_HALF_EVEN)

CHANGE_DISCLAIMER: Final = "Zda je změna žádoucí, posoudí veterinární lékař."
# The line joins the recorded measurements; between two of them nothing is recorded, however
# far apart they are. Said in the caption and in the description of the weight chart.
GAP_SENTENCE: Final = "Čára spojuje zapsaná měření; mezi nimi nejsou zapsaná žádná data."
# More scores than this are summarised in the description instead of being listed one by one.
MAX_LISTED_SCORES: Final = 12

# --- Periods ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    """A choice of the period switcher: ``param`` is the value of ``?obdobi=``."""

    param: str
    days: int | None  # None = all measurements
    label: str  # in the switcher
    phrase: str  # in a sentence: "… za <phrase>"


PERIODS: Final = (
    Period("30", 30, "30 dní", "posledních 30 dní"),
    Period("90", 90, "90 dní", "posledních 90 dní"),
    Period("365", 365, "1 rok", "poslední rok"),
    Period("vse", None, "Vše", "celou dobu sledování"),
)
DEFAULT_PERIOD: Final = PERIODS[1]


def parse_period(value: str | None) -> Period:
    """Return the period whose ``param`` equals ``value``; anything else gives the default.

    Inputs: the raw query parameter (``None`` when absent).
    Output: one of :data:`PERIODS`. An invalid value is not an error (default: 90 days).
    """
    for period in PERIODS:
        if period.param == value:
            return period
    return DEFAULT_PERIOD


# --- Input and geometry types -------------------------------------------------------------------


class Measured(Protocol):
    """What the chart functions read from a measurement (``BodyMeasurement`` has all of it)."""

    measured_on: date
    weight_kg: Decimal
    bcs: int | None
    assessed_by: str


@dataclass(frozen=True)
class Frame:
    """Size of the SVG viewBox and the plot area inside it (pixels).

    ``compact`` marks the layout for narrow screens (docs/12 §12.11): fewer date ticks, the
    value of the last point right-aligned at the edge and the band label on two lines, so that
    the whole chart fits a phone without sideways scrolling.
    """

    width: int
    height: int
    left: float
    top: float
    right: float
    bottom: float
    title_x: float = 14.0  # horizontal position of the rotated y axis title
    max_x_ticks: int = 7
    compact: bool = False

    @property
    def plot_width(self) -> float:
        return self.right - self.left

    @property
    def center_y(self) -> float:
        """Vertical middle of the plot area (where the rotated y axis title goes)."""
        return (self.top + self.bottom) / 2

    @property
    def y_label_x(self) -> float:
        """Right edge of the y tick labels (they are right-aligned)."""
        return self.left - 8

    @property
    def x_tick_end(self) -> float:
        """End of the short tick marks below the x axis."""
        return self.bottom + 5

    @property
    def x_label_y(self) -> float:
        """Baseline of the x tick labels."""
        return self.bottom + 21


# Room around the plot: 64 px on the left for the rotated axis title and the tick labels,
# 112 px on the right for the value of the last point and the label of the BCS band, 24 px
# on top and 48 px below for the date labels. Both charts share the horizontal layout, so
# the same date is at the same x in both.
WEIGHT_FRAME: Final = Frame(width=640, height=300, left=64.0, top=24.0, right=528.0, bottom=252.0)
BCS_FRAME: Final = Frame(width=640, height=260, left=64.0, top=24.0, right=528.0, bottom=212.0)
# The same charts for screens narrower than 40rem: a 360 unit wide viewBox shows 14 px text at
# about 12 px on a 390 px wide phone, where the 640 unit wide one would show it at 7 to 8 px or
# have to scroll sideways (and hide the newest measurements). 72 units on the right hold the
# value of the last point and the label of the BCS band.
WEIGHT_FRAME_COMPACT: Final = Frame(
    width=360,
    height=300,
    left=56.0,
    top=24.0,
    right=288.0,
    bottom=252.0,
    title_x=12.0,
    max_x_ticks=3,
    compact=True,
)
BCS_FRAME_COMPACT: Final = Frame(
    width=360,
    height=260,
    left=56.0,
    top=24.0,
    right=288.0,
    bottom=212.0,
    title_x=12.0,
    max_x_ticks=3,
    compact=True,
)
TEXT_BASELINE_SHIFT: Final = 4.5  # half the cap height of the 13 px chart text

CIRCLE: Final = "circle"
DIAMOND: Final = "diamond"
# The shape tells who assessed the measurement, so colour is never the only cue.
SHAPES: Final = {Assessor.OWNER.value: CIRCLE, Assessor.VET.value: DIAMOND}
DIAMOND_RADIUS: Final = 7.0

MAX_X_TICKS: Final = 7
COMPACT_LABEL_MARGIN: Final = 4.0  # gap between a right-aligned label and the viewBox edge


@dataclass(frozen=True)
class YTick:
    value: Decimal
    y: float
    label: str


@dataclass(frozen=True)
class XTick:
    value: date
    x: float
    label: str


@dataclass(frozen=True)
class ChartPoint:
    """One measurement on a chart. ``value`` is the weight in kg or the BCS."""

    measured_on: date
    value: Decimal
    assessed_by: str
    x: float
    y: float
    shape: str  # CIRCLE (majitel) or DIAMOND (veterinární lékař)
    description: str  # native tooltip, e.g. "3. 10. 2026: 20,5 kg, posoudil: majitel"

    @property
    def is_vet(self) -> bool:
        return self.shape == DIAMOND

    @property
    def diamond_points(self) -> str:
        """Corners of the diamond marker as an SVG ``points`` value."""
        r = DIAMOND_RADIUS
        corners = (
            (self.x, self.y - r),
            (self.x + r, self.y),
            (self.x, self.y + r),
            (self.x - r, self.y),
        )
        return " ".join(f"{px:g},{py:g}" for px, py in corners)


@dataclass(frozen=True)
class Label:
    """A text drawn inside the SVG; ``anchor`` is the SVG ``text-anchor``."""

    x: float
    y: float
    text: str
    anchor: str


@dataclass(frozen=True)
class TargetLine:
    """Horizontal reference line for the target weight, named by its status.

    ``label`` is the full text ("cílová hmotnost (orientační) 19 kg"); ``label_lines`` is how
    it is drawn: one line, or on the compact layout two (the name, then the weight), because
    the whole text is wider than a phone's plot area.
    """

    weight_kg: Decimal
    status: str
    y: float
    name: str  # "cílová hmotnost (orientační)" or "cílová hmotnost (potvrzeno veterinářem)"
    label: Label
    label_lines: tuple[Label, ...]


@dataclass(frozen=True)
class WeightSummary:
    """Descriptive statistics of the measurements in the period (nothing is judged)."""

    count: int
    first_on: date | None
    first_kg: Decimal | None
    last_on: date | None
    last_kg: Decimal | None
    change_kg: Decimal | None  # last - first; None below two measurements
    change_pct: Decimal | None  # of the first weight, one decimal; None when not defined
    days: int | None  # between the first and the last measurement

    @property
    def change_kg_text(self) -> str:
        """The change in kg for display, e.g. ``"−1,2 kg"``; empty below two measurements."""
        return signed_kg(self.change_kg) if self.change_kg is not None else ""

    @property
    def change_pct_text(self) -> str:
        """The change in percent for display, e.g. ``"−3,8 %"``; empty when not defined."""
        return signed_percent(self.change_pct) if self.change_pct is not None else ""


@dataclass(frozen=True)
class WeightChart:
    period: Period
    start: date
    end: date
    frame: Frame
    points: tuple[ChartPoint, ...]
    y_ticks: tuple[YTick, ...]
    x_ticks: tuple[XTick, ...]
    target: TargetLine | None
    end_label: Label | None
    summary: WeightSummary

    @property
    def drawable(self) -> bool:
        """A line needs two points; below that the page shows an empty state."""
        return len(self.points) >= 2

    @property
    def polyline(self) -> str:
        return " ".join(f"{p.x:g},{p.y:g}" for p in self.points)

    @property
    def has_owner(self) -> bool:
        return any(p.shape == CIRCLE for p in self.points)

    @property
    def has_vet(self) -> bool:
        return any(p.shape == DIAMOND for p in self.points)


@dataclass(frozen=True)
class BcsBand:
    """Shaded band of the scores 4 and 5 (docs/05 §5.3); spans the half-steps around them.

    ``label`` is the full text ("pásmo 4–5 z 9", also used in the description and the legend);
    ``label_lines`` is how it is drawn: one line, or two on the compact layout.
    """

    top: float
    bottom: float
    label: Label
    label_lines: tuple[Label, ...]

    @property
    def height(self) -> float:
        return round(self.bottom - self.top, 2)


@dataclass(frozen=True)
class BcsChart:
    period: Period
    start: date
    end: date
    frame: Frame
    points: tuple[ChartPoint, ...]
    y_ticks: tuple[YTick, ...]
    x_ticks: tuple[XTick, ...]
    band: BcsBand

    @property
    def drawable(self) -> bool:
        return len(self.points) >= 2

    @property
    def has_owner(self) -> bool:
        return any(p.shape == CIRCLE for p in self.points)

    @property
    def has_vet(self) -> bool:
        return any(p.shape == DIAMOND for p in self.points)


@dataclass(frozen=True)
class Tracking:
    """Everything the tracking page draws for one animal and one period."""

    period: Period
    start: date
    end: date
    measurements: tuple[Measured, ...]  # in the period, oldest first
    weight: WeightChart
    bcs: BcsChart
    weight_compact: WeightChart  # the same data laid out for narrow screens
    bcs_compact: BcsChart


# --- Formatting -----------------------------------------------------------------------------------


def kg_text(value: Decimal) -> str:
    """``Decimal("20.50")`` → ``"20,5 kg"`` (no-break space before the unit)."""
    return f"{format_kg(value)}{NBSP}kg"


def signed_kg(value: Decimal) -> str:
    """Signed difference in kg with a real minus sign: ``-1.2`` → ``"−1,2 kg"``, 0 → ``"0 kg"``."""
    sign = "" if value == 0 else (MINUS if value < 0 else "+")
    return f"{sign}{format_kg(abs(value))}{NBSP}kg"


def signed_percent(value: Decimal) -> str:
    """Signed percentage with one decimal: ``-3.8`` → ``"−3,8 %"``, 0 → ``"0,0 %"``."""
    sign = "" if value == 0 else (MINUS if value < 0 else "+")
    return f"{sign}{format(abs(value), 'f').replace('.', ',')}{NBSP}%"


def _assessor_text(assessed_by: str) -> str:
    return Assessor(assessed_by).label


# --- Axes -----------------------------------------------------------------------------------------

_STEP_MULTIPLES: Final = (Decimal(1), Decimal(2), Decimal(5), Decimal(10))
AXIS_PADDING: Final = Decimal("0.08")  # share of the range left free above and below the data
# The axis never spans less than this, so that a wobble of a few grams does not look like a
# big change: at least 1 kg or 5 % of the highest weight, whichever is larger.
MIN_AXIS_SPAN_KG: Final = Decimal(1)
MIN_AXIS_SPAN_SHARE: Final = Decimal("0.05")


def nice_ticks(low: Decimal, high: Decimal, intervals: int = 4) -> tuple[Decimal, ...]:
    """Return evenly spaced round tick values that cover ``[low, high]``.

    The step is 1, 2 or 5 times a power of ten, chosen so that about ``intervals``
    intervals span the range; the first tick is at or below ``low`` and the last at or
    above ``high``. Exact in :class:`~decimal.Decimal`.

    Raises:
        ValueError: ``low`` is not smaller than ``high`` or ``intervals`` is below 1.
    """
    if not low < high or intervals < 1:
        raise ValueError("nice_ticks needs low < high and at least one interval")
    with localcontext(_CONTEXT):
        raw_step = (high - low) / intervals
        magnitude = Decimal(1).scaleb(raw_step.adjusted())
        step = next(m * magnitude for m in _STEP_MULTIPLES if m * magnitude >= raw_step)
        first = (low / step).to_integral_value(ROUND_FLOOR) * step
        last = (high / step).to_integral_value(ROUND_CEILING) * step
        count = int((last - first) / step)
        return tuple(first + step * index for index in range(count + 1))


def widen_to_min_span(low: Decimal, high: Decimal) -> tuple[Decimal, Decimal]:
    """Return ``(low, high)`` widened around its middle to the minimum span of a weight axis.

    The span is at least :data:`MIN_AXIS_SPAN_KG` or :data:`MIN_AXIS_SPAN_SHARE` of the
    highest weight, whichever is larger, so that a difference of a few grams never fills the
    whole height of a chart (the main chart and the sparkline alike).
    """
    with localcontext(_CONTEXT):
        min_span = max(MIN_AXIS_SPAN_KG, high * MIN_AXIS_SPAN_SHARE)
        if high - low < min_span:
            middle = (low + high) / 2
            return middle - min_span / 2, middle + min_span / 2
    return low, high


def weight_axis(values: Iterable[Decimal]) -> tuple[Decimal, ...]:
    """Return y ticks for a weight axis that shows all ``values`` with room around them.

    A flat range (identical values) or a very narrow one is widened to
    :data:`MIN_AXIS_SPAN_KG` / :data:`MIN_AXIS_SPAN_SHARE`, so the axis never magnifies
    noise. The axis does not go below zero.

    Raises:
        ValueError: ``values`` is empty.
    """
    values = tuple(values)
    if not values:
        raise ValueError("weight_axis needs at least one value")
    with localcontext(_CONTEXT):
        low, high = widen_to_min_span(min(values), max(values))
        padding = (high - low) * AXIS_PADDING
        low = max(low - padding, Decimal(0))
        high += padding
        return nice_ticks(low, high)


_DAY_STEPS: Final = (1, 2, 7, 14)
_MONTH_STEPS: Final = (1, 2, 3, 6, 12, 24, 60, 120, 240, 600, 1200, 12000)
_MONTHS: Final = (
    "led",
    "úno",
    "bře",
    "dub",
    "kvě",
    "čvn",
    "čvc",
    "srp",
    "zář",
    "říj",
    "lis",
    "pro",
)
MAX_YEAR: Final = 9999


def _day_grid(start: date, end: date, step: int) -> range:
    """Ordinals of the days in ``[start, end]`` on a fixed grid; a step of 7 falls on Mondays.

    A ``range``: its length is known without visiting a day, so a range of centuries costs
    nothing until a grid with few enough ticks is chosen.
    """
    first = start.toordinal()
    first += -(first - 1) % step
    return range(first, end.toordinal() + 1, step)


def _month_grid(start: date, end: date, step: int) -> range:
    """Month numbers (``year * 12 + month - 1``) of the firsts of months in ``[start, end]``,
    every ``step`` months counted from January; never beyond :data:`MAX_YEAR`."""
    first = start.year * 12 + start.month - 1 + (1 if start.day > 1 else 0)
    first += -first % step
    last = min(end.year * 12 + end.month - 1, MAX_YEAR * 12 + 11)
    return range(first, last + 1, step)


def date_ticks(
    start: date, end: date, max_ticks: int = MAX_X_TICKS
) -> tuple[tuple[date, str], ...]:
    """Return ``(date, label)`` ticks for a date axis from ``start`` to ``end``.

    The finest unit that gives at most ``max_ticks`` ticks wins: days, Mondays, every second
    Monday, then firsts of months (every 1, 2, 3, 6, 12 … months) and years. Day ticks are
    labelled ``"21. 10."``, month ticks ``"říj 2026"``, year ticks ``"2026"``. Ticks lie
    inside ``[start, end]`` and increase strictly. The choice is made from the length of
    each candidate grid, so a very long range costs the same as a short one.

    Raises:
        ValueError: ``end`` is before ``start``.
    """
    if end < start:
        raise ValueError("date_ticks needs start <= end")
    candidates = [("day", step) for step in _DAY_STEPS] + [("month", s) for s in _MONTH_STEPS]
    unit, step = candidates[-1]
    grid = _month_grid(start, end, step)
    for unit, step in candidates:
        grid = (_day_grid if unit == "day" else _month_grid)(start, end, step)
        if len(grid) <= max_ticks:
            break
    if unit == "day":
        ticks = [date.fromordinal(ordinal) for ordinal in grid]
        return tuple((tick, f"{tick.day}. {tick.month}.") for tick in ticks)
    ticks = []
    for index in grid:
        year, month0 = divmod(index, 12)
        ticks.append(date(year, month0 + 1, 1))
    if step % 12 == 0:
        return tuple((tick, str(tick.year)) for tick in ticks)
    return tuple((tick, f"{_MONTHS[tick.month - 1]} {tick.year}") for tick in ticks)


# --- Pixel mapping --------------------------------------------------------------------------------


def _scale(value: Decimal, low: Decimal, high: Decimal, from_px: float, to_px: float) -> float:
    """Map ``value`` from ``[low, high]`` linearly to the pixels ``from_px`` … ``to_px``."""
    with localcontext(_CONTEXT):
        share = (value - low) / (high - low)
    return round(from_px + float(share) * (to_px - from_px), 2)


def _x(frame: Frame, start: date, end: date, day: date) -> float:
    share = (day - start).days / (end - start).days
    return round(frame.left + share * (frame.right - frame.left), 2)


def _x_ticks(frame: Frame, start: date, end: date) -> tuple[XTick, ...]:
    return tuple(
        XTick(value=day, x=_x(frame, start, end, day), label=label)
        for day, label in date_ticks(start, end, frame.max_x_ticks)
    )


def _require_inside(measurements: Sequence[Measured], start: date, end: date) -> None:
    """Refuse a measurement outside ``[start, end]``: it would get a coordinate outside the plot.

    Raises:
        ValueError: ``start`` is not before ``end``, or a measurement lies outside the range.
    """
    if not start < end:
        raise ValueError("a chart needs start < end")
    outside = [m.measured_on for m in measurements if not start <= m.measured_on <= end]
    if outside:
        raise ValueError(
            f"{len(outside)} measurement(s) lie outside {start}..{end} (first: {outside[0]}): "
            "pass only the measurements of the period (select_period)"
        )


# --- Period selection -----------------------------------------------------------------------------


def select_period(
    measurements: Iterable[Measured], period: Period, today: date
) -> tuple[tuple[Measured, ...], date, date]:
    """Return the measurements of ``period`` (oldest first) and the date range of the x axis.

    Inputs: the measurements in recording order (the oldest recorded first), the period
    and today's date. Several measurements of one day keep their input order. Dates after
    ``today`` are ignored. A fixed period covers exactly ``period.days`` calendar days
    ending today; "all" starts on the first measurement. The range always ends today and
    is at least one day long.

    Output: ``(measurements, start, end)`` with ``start < end``.
    """
    ordered = sorted(
        (m for m in measurements if m.measured_on <= today), key=lambda m: m.measured_on
    )
    if period.days is not None:
        start = today - timedelta(days=period.days - 1)
    else:
        start = ordered[0].measured_on if ordered else today
    chosen = tuple(m for m in ordered if m.measured_on >= start)
    if start >= today:
        start = today - timedelta(days=1)
    return chosen, start, today


# --- Summary and descriptions ---------------------------------------------------------------------


def summarize_weight(measurements: Sequence[Measured]) -> WeightSummary:
    """Return the descriptive statistics of ``measurements`` (oldest first).

    The change is last minus first weight; the percentage is relative to the first
    weight, rounded to one decimal. Both are ``None`` below two measurements.
    """
    if not measurements:
        return WeightSummary(0, None, None, None, None, None, None, None)
    first, last = measurements[0], measurements[-1]
    if len(measurements) < 2:
        return WeightSummary(
            1,
            first.measured_on,
            first.weight_kg,
            first.measured_on,
            first.weight_kg,
            None,
            None,
            None,
        )
    change = last.weight_kg - first.weight_kg
    percent = None
    if first.weight_kg:
        with localcontext(_CONTEXT):
            percent = (change / first.weight_kg * 100).quantize(Decimal("0.1"))
    days = (last.measured_on - first.measured_on).days
    return WeightSummary(
        len(measurements),
        first.measured_on,
        first.weight_kg,
        last.measured_on,
        last.weight_kg,
        change,
        percent,
        days,
    )


def change_sentence(summary: WeightSummary) -> str | None:
    """Return the sentence about the change in the period, or ``None`` below two measurements.

    Example: ``"Změna hmotnosti za zvolené období: −1,2 kg (−3,8 %). Zda je změna žádoucí,
    posoudí veterinární lékař."`` The sentence only states the numbers.
    """
    if summary.change_kg is None:
        return None
    figures = signed_kg(summary.change_kg)
    if summary.change_pct is not None:
        figures += f" ({signed_percent(summary.change_pct)})"
    return f"Změna hmotnosti za zvolené období: {figures}. {CHANGE_DISCLAIMER}"


def outside_period_sentence(count: int) -> str | None:
    """Return the sentence about measurements outside the shown period, or ``None`` for none.

    Czech counted noun: ``1`` → "Mimo zobrazené období je další 1 měření", ``2``–``4`` →
    "… jsou další 3 měření", ``5`` and more → "… je dalších 5 měření".
    """
    if count <= 0:
        return None
    if count == 1:
        return "Mimo zobrazené období je další 1 měření"
    if count <= 4:
        return f"Mimo zobrazené období jsou další {count} měření"
    return f"Mimo zobrazené období je dalších {count} měření"


def _shapes_sentence(has_owner: bool, has_vet: bool) -> str:
    """Say which marker shape means which assessor, for the shapes that are drawn."""
    owner = "kolečka značí měření zapsaná majitelem"
    vet = "kosočtverce značí měření zapsaná veterinárním lékařem"
    if has_owner and has_vet:
        return f"{owner.capitalize()}, {vet}."
    if has_owner:
        return f"{owner.capitalize()}."
    if has_vet:
        return f"{vet.capitalize()}."
    return ""


def describe_weight_chart(chart: WeightChart) -> str:
    """Describe the weight chart in words (for the SVG ``<desc>``).

    Output: Czech text with the period, the number of measurements, first and last
    weight, the change and its disclaimer, the target weight line and the meaning of the
    marker shapes. It judges nothing.
    """
    summary = chart.summary
    count = summary.count
    parts = [
        (
            f"Čárový graf hmotnosti za {chart.period.phrase} "
            f"({short_date(chart.start)} – {short_date(chart.end)}): "
            f"{count} {plural(count, 'měření', 'měření', 'měření')}."
        )
    ]
    if summary.first_on is not None and summary.last_on is not None and count >= 2:
        parts.append(
            f"První hmotnost {kg_text(summary.first_kg)} dne {short_date(summary.first_on)}, "
            f"poslední {kg_text(summary.last_kg)} dne {short_date(summary.last_on)}."
        )
        parts.append(change_sentence(summary) or "")
    if count >= 2:
        parts.append(GAP_SENTENCE)
    if chart.target is not None:
        parts.append(f"Čárkovaná čára: {chart.target.name} {kg_text(chart.target.weight_kg)}.")
    parts.append(_shapes_sentence(chart.has_owner, chart.has_vet))
    parts.append("Stejná data jsou v tabulce pod grafem.")
    return " ".join(part for part in parts if part)


def describe_bcs_chart(chart: BcsChart) -> str:
    """Describe the BCS chart in words (for the SVG ``<desc>``); it judges nothing."""
    count = len(chart.points)
    parts = [
        (
            f"Graf hodnocení BCS na devítibodové škále za {chart.period.phrase} "
            f"({short_date(chart.start)} – {short_date(chart.end)}): "
            f"{count} {plural(count, 'hodnocení', 'hodnocení', 'hodnocení')}."
        )
    ]
    if 0 < count <= MAX_LISTED_SCORES:
        scores = ", ".join(f"{short_date(p.measured_on)}: {p.value}/9" for p in chart.points)
        parts.append(f"Zapsaná skóre: {scores}.")
    elif count > MAX_LISTED_SCORES:
        # A screen reader reads the whole description: with daily weighing a list of every
        # score would be thousands of characters. The table below the chart has them all.
        first, last = chart.points[0], chart.points[-1]
        values = [p.value for p in chart.points]
        parts.append(
            f"První skóre {first.value}/9 dne {short_date(first.measured_on)}, "
            f"poslední {last.value}/9 dne {short_date(last.measured_on)}; "
            f"nejnižší zapsané skóre {min(values)}/9, nejvyšší {max(values)}/9."
        )
    parts.append(f"Podkladem je vyznačeno {chart.band.label.text}, jen jako vodítko na škále.")
    parts.append(_shapes_sentence(chart.has_owner, chart.has_vet))
    parts.append("Stejná data jsou v tabulce pod grafem.")
    return " ".join(part for part in parts if part)


# --- Weight chart ---------------------------------------------------------------------------------

TARGET_STATUS_TEXT: Final = {
    TargetWeightStatus.UNVERIFIED.value: "orientační",
    TargetWeightStatus.VET_CONFIRMED.value: "potvrzeno veterinářem",
}


def _target_line(
    frame: Frame, low: Decimal, high: Decimal, weight_kg: Decimal, status: str
) -> TargetLine:
    if status not in TARGET_STATUS_TEXT:
        raise ValueError(f"Unknown target weight status: {status!r}")
    y = _scale(weight_kg, low, high, frame.bottom, frame.top)
    name = f"cílová hmotnost ({TARGET_STATUS_TEXT[status]})"
    x = frame.left + 6
    # The text goes above the line, or below it when there is no room under the plot top.
    text_y = y - 6 if y - 6 - 13 >= 1 else y + 17
    label = Label(x, text_y, f"{name} {kg_text(weight_kg)}", "start")
    lines = (label,)
    if frame.compact:  # two lines, the weight under the name
        above = y - 6 - 17 - 13 >= 1
        first_y = y - 6 - 17 if above else y + 17
        lines = (
            Label(x, first_y, name, "start"),
            Label(x, first_y + 17, kg_text(weight_kg), "start"),
        )
    return TargetLine(weight_kg, status, y, name, label, lines)


def _point(
    frame: Frame, start: date, end: date, measurement: Measured, value: Decimal, y: float, text: str
) -> ChartPoint:
    return ChartPoint(
        measured_on=measurement.measured_on,
        value=value,
        assessed_by=measurement.assessed_by,
        x=_x(frame, start, end, measurement.measured_on),
        y=y,
        shape=SHAPES[measurement.assessed_by],
        description=f"{short_date(measurement.measured_on)}: {text}, "
        f"posoudil: {_assessor_text(measurement.assessed_by)}",
    )


def build_weight_chart(
    measurements: Sequence[Measured],
    period: Period,
    start: date,
    end: date,
    *,
    target_weight_kg: Decimal | None = None,
    target_status: str | None = None,
    frame: Frame = WEIGHT_FRAME,
) -> WeightChart:
    """Build the weight chart of ``measurements`` (oldest first, already inside the period).

    Inputs: the measurements of the period, the period, the date range of the x axis
    (from :func:`select_period`) and, optionally, the target weight with its status
    (``UNVERIFIED`` or ``VET_CONFIRMED``). The y axis covers the data and the target
    weight, so the target line is always inside the plot.

    Output: :class:`WeightChart`; ``drawable`` is false below two points. With no
    measurement and no target weight the y axis is empty.

    Raises:
        ValueError: a target weight without a known status, ``start`` not before ``end``, or a
            measurement outside ``[start, end]``.
    """
    if target_weight_kg is not None and target_status not in TARGET_STATUS_TEXT:
        raise ValueError(f"Unknown target weight status: {target_status!r}")
    _require_inside(measurements, start, end)
    values = [m.weight_kg for m in measurements]
    if target_weight_kg is not None:
        values.append(target_weight_kg)
    ticks = weight_axis(values) if values else ()
    low, high = (ticks[0], ticks[-1]) if ticks else (Decimal(0), Decimal(1))
    points = tuple(
        _point(
            frame,
            start,
            end,
            m,
            m.weight_kg,
            _scale(m.weight_kg, low, high, frame.bottom, frame.top),
            kg_text(m.weight_kg),
        )
        for m in measurements
    )
    end_label = None
    if points:
        last = points[-1]  # its value stands to the right of the last point
        y = round(last.y + TEXT_BASELINE_SHIFT, 2)
        if frame.compact:  # the margin is narrow: right-aligned at the edge of the viewBox
            end_label = Label(frame.width - COMPACT_LABEL_MARGIN, y, kg_text(last.value), "end")
        else:
            end_label = Label(last.x + 10, y, kg_text(last.value), "start")
    return WeightChart(
        period=period,
        start=start,
        end=end,
        frame=frame,
        points=points,
        y_ticks=tuple(
            YTick(tick, _scale(tick, low, high, frame.bottom, frame.top), format_kg(tick))
            for tick in ticks
        ),
        x_ticks=_x_ticks(frame, start, end),
        target=(
            _target_line(frame, low, high, target_weight_kg, target_status)
            if target_weight_kg is not None
            else None
        ),
        end_label=end_label,
        summary=summarize_weight(measurements),
    )


# --- BCS chart ------------------------------------------------------------------------------------

BCS_AXIS_LOW: Final = Decimal("0.5")
BCS_AXIS_HIGH: Final = Decimal("9.5")
# docs/05 §5.3: the scores 4–5 are the band for which the estimate may start from the
# current weight. It is drawn as a reference on the scale, never called "ideal".
BCS_BAND: Final = (4, 5)
BCS_BAND_LABEL: Final = "pásmo 4–5 z 9"


def build_bcs_chart(
    measurements: Sequence[Measured],
    period: Period,
    start: date,
    end: date,
    *,
    frame: Frame = BCS_FRAME,
) -> BcsChart:
    """Build the BCS chart: one point per measurement that has a score (1–9).

    Inputs: the measurements of the period (oldest first), the period and the date
    range of the x axis. Measurements without a score are left out. The y axis is the
    whole nine-point scale; the band of the scores 4 and 5 is shaded and labelled.

    Output: :class:`BcsChart`; ``drawable`` is false below two points.

    Raises:
        ValueError: ``start`` not before ``end``, or a measurement outside ``[start, end]``.
    """
    _require_inside(measurements, start, end)

    def y_of(score: Decimal) -> float:
        return _scale(score, BCS_AXIS_LOW, BCS_AXIS_HIGH, frame.bottom, frame.top)

    points = tuple(
        _point(frame, start, end, m, Decimal(m.bcs), y_of(Decimal(m.bcs)), f"BCS {m.bcs}/9")
        for m in measurements
        if m.bcs is not None
    )
    band_top = y_of(Decimal(BCS_BAND[1]) + Decimal("0.5"))
    band_bottom = y_of(Decimal(BCS_BAND[0]) - Decimal("0.5"))
    # The label stands in the right margin, so it never covers a point.
    middle = (band_top + band_bottom) / 2
    label = Label(frame.right + 8, round(middle + TEXT_BASELINE_SHIFT, 2), BCS_BAND_LABEL, "start")
    lines = (label,)
    if frame.compact:  # the margin holds seven characters: two lines, one above the other
        first, second = BCS_BAND_LABEL.split(" ", 1)
        lines = (
            Label(frame.right + 8, round(middle - 8 + TEXT_BASELINE_SHIFT, 2), first, "start"),
            Label(frame.right + 8, round(middle + 10 + TEXT_BASELINE_SHIFT, 2), second, "start"),
        )
    band = BcsBand(band_top, band_bottom, label, lines)
    scores = range(BCS_MIN, BCS_MAX + 1)
    return BcsChart(
        period=period,
        start=start,
        end=end,
        frame=frame,
        points=points,
        y_ticks=tuple(YTick(Decimal(score), y_of(Decimal(score)), str(score)) for score in scores),
        x_ticks=_x_ticks(frame, start, end),
        band=band,
    )


def build_tracking(
    measurements: Iterable[Measured],
    period: Period,
    today: date,
    *,
    target_weight_kg: Decimal | None = None,
    target_status: str | None = None,
) -> Tracking:
    """Build both charts for ``period``, each in the wide and in the compact layout.

    Inputs: the animal's measurements in recording order (oldest recorded first), the
    period, today's date (never read from the clock here) and optionally the target
    weight with its status. Output: :class:`Tracking`.

    Raises:
        ValueError: a target weight without a known status.
    """
    chosen, start, end = select_period(measurements, period, today)
    target = {"target_weight_kg": target_weight_kg, "target_status": target_status}
    return Tracking(
        period=period,
        start=start,
        end=end,
        measurements=chosen,
        weight=build_weight_chart(chosen, period, start, end, **target),
        bcs=build_bcs_chart(chosen, period, start, end),
        weight_compact=build_weight_chart(
            chosen, period, start, end, frame=WEIGHT_FRAME_COMPACT, **target
        ),
        bcs_compact=build_bcs_chart(chosen, period, start, end, frame=BCS_FRAME_COMPACT),
    )


# --- Sparkline for the dashboard ----------------------------------------------------------------


@dataclass(frozen=True)
class Sparkline:
    """A tiny weight line for an animal card (no axes). ``text`` is its text alternative."""

    width: int
    height: int
    points: str  # SVG polyline points
    last_x: float
    last_y: float
    last_kg: Decimal
    change_kg: Decimal
    days: int
    text: str


SPARK_WIDTH: Final = 160
SPARK_HEIGHT: Final = 36
SPARK_PADDING: Final = 4.0


def build_sparkline(measurements: Iterable[Measured]) -> Sparkline | None:
    """Return the sparkline of ``measurements``, or ``None`` below two measurements.

    Inputs: measurements in recording order (the oldest recorded first). The x axis runs
    from the first to the last date; the y axis from the lowest to the highest weight,
    widened to the minimum span of the weight axis (:func:`widen_to_min_span`), so a flat
    series is drawn in the middle and a change of grams is not magnified. Measurements of
    one day only are spread evenly.

    Output: :class:`Sparkline` whose ``text`` reads, for example, ``"poslední hmotnost
    21 kg, změna −0,4 kg za 33 dní"`` (change = last minus first weight).
    """
    ordered = sorted(measurements, key=lambda m: m.measured_on)
    if len(ordered) < 2:
        return None
    first, last = ordered[0], ordered[-1]
    days = (last.measured_on - first.measured_on).days
    weights = [m.weight_kg for m in ordered]
    # The same minimum span as the weight axis: a difference of a few grams stays a flat line
    # instead of becoming a full-height slope on the card.
    low, high = widen_to_min_span(min(weights), max(weights))
    inner_width = SPARK_WIDTH - 2 * SPARK_PADDING
    coordinates = []
    for index, m in enumerate(ordered):
        if days == 0:
            share = index / (len(ordered) - 1)
        else:
            share = (m.measured_on - first.measured_on).days / days
        y = _scale(m.weight_kg, low, high, SPARK_HEIGHT - SPARK_PADDING, SPARK_PADDING)
        coordinates.append((round(SPARK_PADDING + share * inner_width, 2), round(y, 2)))
    change = last.weight_kg - first.weight_kg
    span = f"za {days} {plural(days, 'den', 'dny', 'dní')}" if days else "(měření téhož dne)"
    return Sparkline(
        width=SPARK_WIDTH,
        height=SPARK_HEIGHT,
        points=" ".join(f"{x:g},{y:g}" for x, y in coordinates),
        last_x=coordinates[-1][0],
        last_y=coordinates[-1][1],
        last_kg=last.weight_kg,
        change_kg=change,
        days=days,
        text=f"poslední hmotnost {kg_text(last.weight_kg)}, změna {signed_kg(change)} {span}",
    )
