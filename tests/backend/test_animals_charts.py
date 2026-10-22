"""Chart geometry (animals.charts): pure functions, no database.

Covers periods, nice ticks, date ticks, the descriptive summary, the weight and BCS
charts, the sparkline and hypothesis properties (coordinates inside the plot area, x
monotone in date, ticks covering the data, deterministic output).
"""

import re
import tracemalloc
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from animals import charts
from animals.charts import (
    BCS_FRAME,
    BCS_FRAME_COMPACT,
    DEFAULT_PERIOD,
    PERIODS,
    WEIGHT_FRAME,
    WEIGHT_FRAME_COMPACT,
    build_bcs_chart,
    build_sparkline,
    build_tracking,
    build_weight_chart,
    change_sentence,
    date_ticks,
    nice_ticks,
    outside_period_sentence,
    parse_period,
    select_period,
    summarize_weight,
    weight_axis,
    widen_to_min_span,
)

D = Decimal
NBSP = "\xa0"
TODAY = date(2026, 10, 21)  # a Wednesday
P30, P90, P365, PALL = PERIODS


class Reading(NamedTuple):
    measured_on: date
    weight_kg: Decimal
    bcs: int | None = None
    assessed_by: str = "OWNER"


def days_ago(days: int, weight: str = "20", **fields) -> Reading:
    return Reading(TODAY - timedelta(days=days), D(weight), **fields)


# --- Periods ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("30", P30), ("90", P90), ("365", P365), ("vse", PALL)],
)
def test_parse_period_accepts_the_whitelist(value, expected):
    assert parse_period(value) is expected


@pytest.mark.parametrize(
    "value", [None, "", "0", "7", "-30", "030", "30 ", "VSE", "all", "1e2", "<script>", "30;90"]
)
def test_parse_period_falls_back_to_the_default(value):
    assert parse_period(value) is DEFAULT_PERIOD
    assert DEFAULT_PERIOD.param == "90"


def test_periods_are_30_90_365_and_all():
    assert [(p.param, p.days) for p in PERIODS] == [
        ("30", 30),
        ("90", 90),
        ("365", 365),
        ("vse", None),
    ]


# --- select_period -------------------------------------------------------------------------------


def test_fixed_period_covers_exactly_its_days_ending_today():
    inside = days_ago(29)
    outside = days_ago(30)
    chosen, start, end = select_period([outside, inside, days_ago(0)], P30, TODAY)
    assert chosen == (inside, days_ago(0))
    assert (start, end) == (TODAY - timedelta(days=29), TODAY)


def test_all_starts_on_the_first_measurement():
    chosen, start, end = select_period([days_ago(10), days_ago(400)], PALL, TODAY)
    assert [m.measured_on for m in chosen] == [TODAY - timedelta(days=400), TODAY - timedelta(10)]
    assert (start, end) == (TODAY - timedelta(days=400), TODAY)


def test_measurements_are_sorted_by_date_and_future_dates_are_ignored():
    future = Reading(TODAY + timedelta(days=1), D("30"))
    newer, older = days_ago(1), days_ago(5)
    chosen, _, _ = select_period([newer, future, older], P90, TODAY)
    assert chosen == (older, newer)


def test_same_day_measurements_keep_their_input_order():
    first = days_ago(3, "20.0")
    second = days_ago(3, "21.0")
    assert select_period([first, second], P90, TODAY)[0] == (first, second)
    assert select_period([second, first], P90, TODAY)[0] == (second, first)


def test_empty_input_gives_an_empty_period_with_a_valid_range():
    for period in PERIODS:
        chosen, start, end = select_period([], period, TODAY)
        assert chosen == ()
        assert start < end == TODAY


def test_range_is_at_least_one_day_when_everything_is_today():
    chosen, start, end = select_period([days_ago(0)], PALL, TODAY)
    assert len(chosen) == 1
    assert (end - start).days == 1


# --- nice_ticks and weight_axis -------------------------------------------------------------------


def test_nice_ticks_exact_values():
    assert nice_ticks(D("20"), D("24")) == (D(20), D(21), D(22), D(23), D(24))
    assert nice_ticks(D("19.4"), D("22.1")) == (D(19), D(20), D(21), D(22), D(23))
    assert nice_ticks(D("0.5"), D("0.9")) == (D("0.5"), D("0.6"), D("0.7"), D("0.8"), D("0.9"))
    assert nice_ticks(D("3"), D("43")) == (D(0), D(10), D(20), D(30), D(40), D(50))


@pytest.mark.parametrize(
    ("low", "high", "intervals"), [("5", "5", 4), ("6", "5", 4), ("1", "2", 0)]
)
def test_nice_ticks_rejects_an_empty_range(low, high, intervals):
    with pytest.raises(ValueError, match="nice_ticks"):
        nice_ticks(D(low), D(high), intervals)


def test_flat_range_gets_a_padded_axis():
    ticks = weight_axis([D("20"), D("20"), D("20")])
    assert ticks == (D("19"), D("19.5"), D("20"), D("20.5"), D("21"))


def test_narrow_range_is_widened_so_noise_is_not_magnified():
    ticks = weight_axis([D("20.000"), D("20.100")])
    assert ticks[-1] - ticks[0] >= D("1")


def test_axis_never_goes_below_zero():
    assert weight_axis([D("0.5")])[0] >= 0


def test_axis_covers_all_values_including_far_apart_ones():
    ticks = weight_axis([D("4.1"), D("90"), D("4.4")])
    assert ticks[0] <= D("4.1") and ticks[-1] >= D("90")


def test_axis_needs_a_value():
    with pytest.raises(ValueError, match="weight_axis"):
        weight_axis([])


# --- date_ticks ------------------------------------------------------------------------------


def test_short_span_has_daily_ticks():
    ticks = date_ticks(date(2026, 10, 19), date(2026, 10, 21))
    assert [t for t, _ in ticks] == [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)]
    assert [label for _, label in ticks] == ["19. 10.", "20. 10.", "21. 10."]


def test_30_days_has_weekly_ticks_on_mondays():
    ticks = date_ticks(TODAY - timedelta(days=29), TODAY)
    assert [t.weekday() for t, _ in ticks] == [0] * len(ticks)
    assert len(ticks) in (4, 5)
    assert ticks[0][1] == f"{ticks[0][0].day}. {ticks[0][0].month}."


def test_90_days_has_at_most_seven_ticks_every_second_monday():
    ticks = date_ticks(TODAY - timedelta(days=89), TODAY)
    days = [t for t, _ in ticks]
    assert 4 <= len(days) <= charts.MAX_X_TICKS
    assert {(b - a).days for a, b in zip(days, days[1:], strict=False)} == {14}


def test_a_year_has_bimonthly_ticks_labelled_with_month_and_year():
    ticks = date_ticks(TODAY - timedelta(days=364), TODAY)
    assert all(t.day == 1 for t, _ in ticks)
    assert len(ticks) <= charts.MAX_X_TICKS
    assert [t.month for t, _ in ticks] == [11, 1, 3, 5, 7, 9]  # every second month from January
    assert ticks[-1][1] == "zář 2026"
    assert re.fullmatch(r"[a-zěščřžýáíé]{3} \d{4}", ticks[0][1])


def test_many_years_have_yearly_ticks():
    ticks = date_ticks(date(2014, 3, 9), TODAY)
    assert all(t.month == 1 and t.day == 1 for t, _ in ticks)
    assert [label for _, label in ticks] == [str(t.year) for t, _ in ticks]
    assert len(ticks) <= charts.MAX_X_TICKS


def test_date_ticks_rejects_a_reversed_range():
    with pytest.raises(ValueError, match="date_ticks"):
        date_ticks(TODAY, TODAY - timedelta(days=1))


# --- Summary and text ---------------------------------------------------------------------------


def test_summary_of_nothing_and_of_one_measurement():
    nothing = summarize_weight([])
    assert nothing.count == 0 and nothing.first_kg is None and nothing.change_kg is None
    one = summarize_weight([days_ago(4, "20.5")])
    assert one.count == 1 and one.first_kg == one.last_kg == D("20.5")
    assert one.change_kg is None and one.change_pct is None and one.days is None
    assert change_sentence(nothing) is None and change_sentence(one) is None


def test_summary_of_two_measurements_and_the_sentence_of_the_task():
    summary = summarize_weight([days_ago(30, "31.5"), days_ago(0, "30.3")])
    assert (summary.count, summary.days) == (2, 30)
    assert summary.change_kg == D("-1.2") and summary.change_pct == D("-3.8")
    assert change_sentence(summary) == (
        f"Změna hmotnosti za zvolené období: \N{MINUS SIGN}1,2{NBSP}kg "
        f"(\N{MINUS SIGN}3,8{NBSP}%). Zda je změna žádoucí, posoudí veterinární lékař."
    )


def test_gain_is_signed_with_plus_and_zero_has_no_sign():
    gain = change_sentence(summarize_weight([days_ago(9, "10"), days_ago(0, "10.5")]))
    assert f"+0,5{NBSP}kg (+5,0{NBSP}%)" in gain
    flat = change_sentence(summarize_weight([days_ago(9, "10"), days_ago(0, "10.000")]))
    assert f"Změna hmotnosti za zvolené období: 0{NBSP}kg (0,0{NBSP}%)." in flat


def test_percentage_rounds_half_even_to_one_decimal_and_never_shows_minus_zero():
    tiny = summarize_weight([days_ago(9, "20"), days_ago(0, "19.99")])
    assert tiny.change_kg == D("-0.01") and tiny.change_pct == D("-0.0")
    assert f"(0,0{NBSP}%)" in change_sentence(tiny)
    assert "(\N{MINUS SIGN}0,0" not in change_sentence(tiny)
    half = summarize_weight([days_ago(9, "20"), days_ago(0, "20.05")])
    assert half.change_pct == D("0.2")  # 0.25 rounds to the even digit


def test_several_measurements_on_one_day_use_input_order_for_first_and_last():
    summary = summarize_weight(
        [days_ago(9, "20"), days_ago(0, "21"), days_ago(0, "19"), days_ago(0, "20.5")]
    )
    assert summary.last_kg == D("20.5") and summary.change_kg == D("0.5") and summary.days == 9
    assert summary.count == 4


def test_change_text_never_judges():
    text = change_sentence(summarize_weight([days_ago(9, "30"), days_ago(0, "20")])).lower()
    for word in ("ideál", "zdrav", "doporuč", "nebezpeč", "rychl", "příliš", "v pořádku"):
        assert word not in text


# --- Weight chart --------------------------------------------------------------------------------


def weight_chart(readings, period=P90, **kwargs):
    return build_tracking(readings, period, TODAY, **kwargs).weight


def test_points_are_chronological_with_shape_by_assessor():
    chart = weight_chart(
        [
            days_ago(2, "20.4", assessed_by="VET"),
            days_ago(40, "21.0"),
            days_ago(10, "20.6"),
        ]
    )
    assert [p.measured_on for p in chart.points] == sorted(p.measured_on for p in chart.points)
    assert [p.shape for p in chart.points] == ["circle", "circle", "diamond"]
    assert chart.has_owner and chart.has_vet
    assert chart.points[2].is_vet and not chart.points[0].is_vet
    assert chart.drawable


def test_higher_weight_is_higher_on_the_screen_and_dates_go_right():
    chart = weight_chart([days_ago(40, "21"), days_ago(10, "20")])
    older, newer = chart.points
    assert older.x < newer.x
    assert older.y < newer.y  # SVG y grows downwards: the heavier point is higher up


def test_marker_description_is_plain_text_without_user_data():
    chart = weight_chart([days_ago(3, "20.5", assessed_by="VET"), days_ago(0, "20")])
    assert chart.points[0].description == f"18. 10. 2026: 20,5{NBSP}kg, posoudil: veterinární lékař"
    assert chart.points[1].description.endswith("posoudil: majitel")


def test_diamond_has_four_corners_around_the_point():
    chart = weight_chart([days_ago(3, "20", assessed_by="VET"), days_ago(0, "20")])
    corners = [
        tuple(map(float, pair.split(","))) for pair in chart.points[0].diamond_points.split()
    ]
    assert len(corners) == 4
    assert corners[0][0] == corners[2][0] == chart.points[0].x
    assert corners[1][1] == corners[3][1] == chart.points[0].y


def test_identical_weights_render_a_line_inside_a_padded_axis():
    chart = weight_chart([days_ago(20, "20"), days_ago(10, "20"), days_ago(0, "20")])
    frame = chart.frame
    assert {p.y for p in chart.points} == {chart.points[0].y}
    assert frame.top < chart.points[0].y < frame.bottom
    values = [t.value for t in chart.y_ticks]
    assert values[0] < D(20) < values[-1]


def test_several_measurements_on_one_date_share_x_and_all_are_drawn():
    chart = weight_chart([days_ago(5, "20"), days_ago(5, "21"), days_ago(0, "20.5")])
    assert len(chart.points) == 3
    assert chart.points[0].x == chart.points[1].x
    assert chart.points[0].y != chart.points[1].y


def test_a_long_gap_is_drawn_to_scale():
    chart = weight_chart([days_ago(89, "20"), days_ago(88, "20.2"), days_ago(0, "19")])
    a, b, c = chart.points
    assert (c.x - b.x) / (b.x - a.x) == pytest.approx(88, rel=1e-2)


def test_period_range_is_the_x_axis_even_when_data_covers_a_part():
    chart = weight_chart([days_ago(2, "20"), days_ago(1, "20.1")], period=P365)
    assert chart.end == TODAY and (chart.end - chart.start).days == 364
    assert chart.points[0].x > chart.frame.right - 5  # near the right edge, not stretched
    assert chart.x_ticks[0].x < chart.points[0].x


def test_zero_and_one_measurement_are_not_drawable():
    assert weight_chart([]).points == () and not weight_chart([]).drawable
    assert weight_chart([]).y_ticks == () and weight_chart([]).end_label is None
    one = weight_chart([days_ago(1, "20")])
    assert len(one.points) == 1 and not one.drawable and one.summary.count == 1


def test_measurements_outside_the_period_are_left_out():
    chart = weight_chart([days_ago(100, "30"), days_ago(5, "20"), days_ago(1, "20.2")], P30)
    assert [p.value for p in chart.points] == [D(20), D("20.2")]
    assert chart.summary.count == 2


def test_last_point_value_stands_to_its_right():
    chart = weight_chart([days_ago(40, "21"), days_ago(0, "20.25")])
    last = chart.points[-1]
    assert chart.end_label.text == f"20,25{NBSP}kg"
    assert chart.end_label.x > last.x and chart.end_label.anchor == "start"
    assert chart.end_label.x + 60 <= chart.frame.width


# --- Target weight --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "name"),
    [
        ("UNVERIFIED", "cílová hmotnost (orientační)"),
        ("VET_CONFIRMED", "cílová hmotnost (potvrzeno veterinářem)"),
    ],
)
def test_target_line_is_named_by_its_status(status, name):
    chart = weight_chart(
        [days_ago(9, "20"), days_ago(0, "19.6")], target_weight_kg=D("19"), target_status=status
    )
    assert chart.target.name == name
    assert chart.target.label.text == f"{name} 19{NBSP}kg"
    assert "ideál" not in chart.target.label.text.lower()
    assert chart.frame.top <= chart.target.y <= chart.frame.bottom
    assert chart.target.y > chart.points[1].y  # 19 kg is lighter than 19.6 kg: lower on screen


def test_target_outside_the_data_range_extends_the_axis():
    chart = weight_chart(
        [days_ago(9, "20"), days_ago(0, "20.4")],
        target_weight_kg=D("15"),
        target_status="UNVERIFIED",
    )
    assert chart.y_ticks[0].value <= D(15)
    assert chart.frame.top <= chart.target.y <= chart.frame.bottom
    high = weight_chart(
        [days_ago(9, "20"), days_ago(0, "20.4")],
        target_weight_kg=D("30"),
        target_status="UNVERIFIED",
    )
    assert high.y_ticks[-1].value >= D(30)
    assert high.target.y < high.points[0].y


def test_no_target_means_no_line():
    assert weight_chart([days_ago(9, "20"), days_ago(0, "20.4")]).target is None


@pytest.mark.parametrize("status", [None, "", "IDEAL", "confirmed"])
def test_target_needs_a_known_status(status):
    with pytest.raises(ValueError, match="target weight status"):
        weight_chart([days_ago(1, "20")], target_weight_kg=D("19"), target_status=status)


def test_target_alone_gives_an_axis_without_points():
    chart = weight_chart([], target_weight_kg=D("12"), target_status="UNVERIFIED")
    assert chart.points == () and chart.target is not None
    assert chart.y_ticks[0].value <= D(12) <= chart.y_ticks[-1].value


def test_weight_chart_needs_a_positive_x_range():
    with pytest.raises(ValueError, match="start < end"):
        build_weight_chart([], P90, TODAY, TODAY)


# --- BCS chart ------------------------------------------------------------------------------------


def bcs_chart(readings, period=P90):
    return build_tracking(readings, period, TODAY).bcs


def test_bcs_chart_has_only_measurements_with_a_score():
    readings = [
        days_ago(30, "20", bcs=6),
        days_ago(20, "20.1"),
        days_ago(10, "20.2", bcs=5, assessed_by="VET"),
        days_ago(1, "20.3", bcs=4),
    ]
    chart = bcs_chart(readings)
    assert [p.value for p in chart.points] == [D(6), D(5), D(4)]
    assert [p.shape for p in chart.points] == ["circle", "diamond", "circle"]
    assert chart.drawable
    assert chart.points[1].description.startswith("11. 10. 2026: BCS 5/9")
    # The weight chart of the same data keeps the measurement without a score.
    assert len(weight_chart(readings).points) == 4


def test_bcs_axis_is_the_whole_nine_point_scale():
    chart = bcs_chart([])
    assert [t.value for t in chart.y_ticks] == [D(n) for n in range(1, 10)]
    assert [t.label for t in chart.y_ticks] == [str(n) for n in range(1, 10)]
    ys = [t.y for t in chart.y_ticks]
    assert ys == sorted(ys, reverse=True)  # 9 at the top
    assert chart.frame.top < ys[-1] and ys[0] < chart.frame.bottom


def test_band_covers_scores_4_and_5_and_not_3_or_6():
    chart = bcs_chart([])
    y = {t.value: t.y for t in chart.y_ticks}
    band = chart.band
    assert band.top < y[D(5)] < band.bottom and band.top < y[D(4)] < band.bottom
    assert y[D(6)] < band.top and y[D(3)] > band.bottom
    assert band.label.text == "pásmo 4–5 z 9"
    assert band.height == pytest.approx(band.bottom - band.top, abs=0.01)
    assert band.label.x > chart.frame.right  # in the margin, never over a point


def test_bcs_points_sit_on_the_tick_of_their_score():
    chart = bcs_chart([days_ago(5, "20", bcs=7), days_ago(2, "20", bcs=1)])
    y = {t.value: t.y for t in chart.y_ticks}
    assert [p.y for p in chart.points] == [y[D(7)], y[D(1)]]


def test_bcs_chart_with_one_score_is_not_drawable():
    chart = bcs_chart([days_ago(5, "20", bcs=5), days_ago(2, "20")])
    assert len(chart.points) == 1 and not chart.drawable


# --- Descriptions ---------------------------------------------------------------------------------


def test_weight_description_states_the_numbers_and_nothing_else():
    tracking = build_tracking(
        [days_ago(30, "31.5"), days_ago(0, "30.3", assessed_by="VET")],
        P90,
        TODAY,
        target_weight_kg=D("29"),
        target_status="UNVERIFIED",
    )
    text = charts.describe_weight_chart(tracking.weight)
    assert "za posledních 90 dní" in text and "2 měření" in text
    assert f"První hmotnost 31,5{NBSP}kg dne 21. 9. 2026" in text
    assert f"poslední 30,3{NBSP}kg dne 21. 10. 2026" in text
    assert "Zda je změna žádoucí, posoudí veterinární lékař." in text
    assert f"Čárkovaná čára: cílová hmotnost (orientační) 29{NBSP}kg." in text
    assert "Kolečka značí měření zapsaná majitelem, kosočtverce značí" in text
    assert "tabulce pod grafem" in text
    for word in ("ideál", "zdravá", "doporuč"):
        assert word not in text.lower()


def test_descriptions_of_empty_charts_do_not_break():
    empty = build_tracking([], P30, TODAY)
    assert "0 měření" in charts.describe_weight_chart(empty.weight)
    assert "0 hodnocení" in charts.describe_bcs_chart(empty.bcs)


def test_bcs_description_lists_the_scores_and_the_band_as_a_guide():
    tracking = build_tracking([days_ago(9, "20", bcs=5), days_ago(0, "20", bcs=6)], P90, TODAY)
    text = charts.describe_bcs_chart(tracking.bcs)
    assert "12. 10. 2026: 5/9, 21. 10. 2026: 6/9" in text
    assert "pásmo 4–5 z 9, jen jako vodítko" in text
    assert "ideál" not in text.lower()


# --- Sparkline ------------------------------------------------------------------------------------


def test_sparkline_needs_two_measurements():
    assert build_sparkline([]) is None
    assert build_sparkline([days_ago(1)]) is None


def test_sparkline_text_and_geometry():
    spark = build_sparkline([days_ago(0, "21"), days_ago(33, "21.4")])  # any order
    assert spark.text == f"poslední hmotnost 21{NBSP}kg, změna \N{MINUS SIGN}0,4{NBSP}kg za 33 dní"
    assert (spark.last_kg, spark.change_kg, spark.days) == (D(21), D("-0.4"), 33)
    first_x, first_y = map(float, spark.points.split()[0].split(","))
    assert first_x == charts.SPARK_PADDING and first_y < spark.last_y  # started higher
    assert spark.last_x == spark.width - charts.SPARK_PADDING


@pytest.mark.parametrize(
    ("days", "noun"), [(1, "1 den"), (2, "2 dny"), (4, "4 dny"), (5, "5 dní"), (21, "21 dní")]
)
def test_sparkline_text_declines_days(days, noun):
    assert build_sparkline([days_ago(days), days_ago(0)]).text.endswith(f"za {noun}")


def test_sparkline_flat_and_same_day():
    flat = build_sparkline([days_ago(5, "20"), days_ago(0, "20")])
    ys = {float(pair.split(",")[1]) for pair in flat.points.split()}
    assert ys == {charts.SPARK_HEIGHT / 2}
    assert flat.text.endswith(f"změna 0{NBSP}kg za 5 dní")
    same_day = build_sparkline([days_ago(2, "20"), days_ago(2, "20.5"), days_ago(2, "21")])
    xs = [float(pair.split(",")[0]) for pair in same_day.points.split()]
    assert xs == sorted(set(xs)) and len(xs) == 3  # spread out, not stacked
    assert same_day.text.endswith(f"změna +1{NBSP}kg (měření téhož dne)")


# --- Properties (hypothesis) ----------------------------------------------------------------------

readings_strategy = st.lists(
    st.builds(
        Reading,
        measured_on=st.dates(date(2018, 1, 1), TODAY),
        weight_kg=st.decimals(D("0.5"), D("120"), places=3),
        bcs=st.none() | st.integers(1, 9),
        assessed_by=st.sampled_from(["OWNER", "VET"]),
    ),
    max_size=40,
)
period_strategy = st.sampled_from(PERIODS)
target_strategy = st.none() | st.decimals(D("0.5"), D("120"), places=3)
PROPERTY_SETTINGS = settings(max_examples=150, deadline=None)


def inside(frame, x, y) -> bool:
    return frame.left <= x <= frame.right and frame.top <= y <= frame.bottom


@PROPERTY_SETTINGS
@given(readings_strategy, period_strategy, target_strategy)
def test_property_all_coordinates_are_inside_the_plot_area(readings, period, target):
    status = "UNVERIFIED" if target is not None else None
    tracking = build_tracking(
        readings, period, TODAY, target_weight_kg=target, target_status=status
    )
    layouts = (tracking.weight, tracking.bcs, tracking.weight_compact, tracking.bcs_compact)
    for chart in layouts:
        assert all(inside(chart.frame, p.x, p.y) for p in chart.points)
        assert all(chart.frame.top <= t.y <= chart.frame.bottom for t in chart.y_ticks)
        assert all(chart.frame.left <= t.x <= chart.frame.right for t in chart.x_ticks)
        assert len(chart.x_ticks) <= chart.frame.max_x_ticks
    for weight in (tracking.weight, tracking.weight_compact):
        if weight.target is not None:
            assert weight.frame.top <= weight.target.y <= weight.frame.bottom
            for line in weight.target.label_lines:  # the text stays inside the picture
                assert 0 <= line.x < weight.frame.width and 0 < line.y < weight.frame.height
        if weight.end_label is not None:
            assert 0 < weight.end_label.x <= weight.frame.width
    assert tracking.weight.frame is WEIGHT_FRAME and tracking.bcs.frame is BCS_FRAME
    assert tracking.weight_compact.frame is WEIGHT_FRAME_COMPACT
    assert tracking.bcs_compact.frame is BCS_FRAME_COMPACT


@PROPERTY_SETTINGS
@given(readings_strategy, period_strategy)
def test_property_x_is_monotone_in_date(readings, period):
    tracking = build_tracking(readings, period, TODAY)
    for chart in (tracking.weight, tracking.bcs):
        pairs = [(p.measured_on, p.x) for p in chart.points]
        assert pairs == sorted(pairs)  # dates and x ascend together
        for (d1, x1), (d2, x2) in zip(pairs, pairs[1:], strict=False):
            assert (d1 < d2) <= (x1 < x2) and (d1 == d2) <= (x1 == x2)
        ticks = [(t.value, t.x) for t in chart.x_ticks]
        assert ticks == sorted(ticks) and len({v for v, _ in ticks}) == len(ticks)


@PROPERTY_SETTINGS
@given(readings_strategy, period_strategy, target_strategy)
def test_property_y_ticks_cover_the_data_and_are_evenly_spaced(readings, period, target):
    status = "VET_CONFIRMED" if target is not None else None
    chart = build_tracking(
        readings, period, TODAY, target_weight_kg=target, target_status=status
    ).weight
    values = [p.value for p in chart.points] + ([target] if target is not None else [])
    if not values:
        assert chart.y_ticks == ()
        return
    ticks = [t.value for t in chart.y_ticks]
    assert len(ticks) >= 2 and ticks[0] >= 0
    assert ticks[0] <= min(values) and ticks[-1] >= max(values)
    steps = {b - a for a, b in zip(ticks, ticks[1:], strict=False)}
    assert len(steps) == 1 and min(steps) > 0
    ys = [t.y for t in chart.y_ticks]
    assert ys == sorted(ys, reverse=True)  # larger weight, higher on the screen


@PROPERTY_SETTINGS
@given(st.dates(date(2000, 1, 1), date(2100, 1, 1)), st.integers(0, 4000))
def test_property_x_ticks_lie_inside_the_range_and_are_few(start, length):
    end = start + timedelta(days=length)
    ticks = date_ticks(start, end)
    days = [t for t, _ in ticks]
    assert all(start <= t <= end for t in days)
    assert days == sorted(set(days))
    assert len(days) <= charts.MAX_X_TICKS
    assert all(label for _, label in ticks)
    if length >= 7:
        assert days  # a week or more always has a tick


@PROPERTY_SETTINGS
@given(readings_strategy, period_strategy, target_strategy)
def test_property_output_is_deterministic(readings, period, target):
    status = "UNVERIFIED" if target is not None else None
    kwargs = {"target_weight_kg": target, "target_status": status}
    first = build_tracking(readings, period, TODAY, **kwargs)
    again = build_tracking(list(readings), period, TODAY, **kwargs)
    assert first == again
    assert charts.describe_weight_chart(first.weight) == charts.describe_weight_chart(again.weight)


@PROPERTY_SETTINGS
@given(readings_strategy, period_strategy, st.randoms(use_true_random=False))
def test_property_input_order_does_not_matter_for_distinct_dates(readings, period, rnd):
    unique = list({r.measured_on: r for r in readings}.values())
    shuffled = unique[:]
    rnd.shuffle(shuffled)
    assert build_tracking(unique, period, TODAY) == build_tracking(shuffled, period, TODAY)


@PROPERTY_SETTINGS
@given(readings_strategy, period_strategy)
def test_property_summary_matches_the_points(readings, period):
    tracking = build_tracking(readings, period, TODAY)
    summary = tracking.weight.summary
    chosen = tracking.measurements
    assert summary.count == len(chosen) == len(tracking.weight.points)
    assert len(tracking.bcs.points) == sum(1 for m in chosen if m.bcs is not None)
    if len(chosen) >= 2:
        assert summary.change_kg == chosen[-1].weight_kg - chosen[0].weight_kg
        assert summary.days == (chosen[-1].measured_on - chosen[0].measured_on).days
        assert change_sentence(summary).endswith("posoudí veterinární lékař.")
    else:
        assert summary.change_kg is None and change_sentence(summary) is None
    assert all(tracking.start <= m.measured_on <= tracking.end for m in chosen)


@PROPERTY_SETTINGS
@given(readings_strategy)
def test_property_sparkline_stays_inside_its_box(readings):
    spark = build_sparkline(readings)
    if len(readings) < 2:
        assert spark is None
        return
    for pair in spark.points.split():
        x, y = map(float, pair.split(","))
        assert 0 <= x <= spark.width and 0 <= y <= spark.height
    assert spark.change_kg == (
        sorted(readings, key=lambda r: r.measured_on)[-1].weight_kg
        - sorted(readings, key=lambda r: r.measured_on)[0].weight_kg
    )


# --- Compact layout for narrow screens ---------------------------------------------------------


def compact_weight(readings, **kwargs):
    chosen, start, end = select_period(readings, P365, TODAY)
    return build_weight_chart(chosen, P365, start, end, frame=WEIGHT_FRAME_COMPACT, **kwargs)


def test_compact_frames_fit_a_phone_and_keep_a_margin_for_the_labels():
    for frame in (WEIGHT_FRAME_COMPACT, BCS_FRAME_COMPACT):
        assert frame.compact and frame.width == 360 and frame.max_x_ticks == 3
        assert frame.width - frame.right >= 72  # the value of the last point, the band label
        assert frame.left >= 56  # the y tick labels and the rotated axis title
    for frame in (WEIGHT_FRAME, BCS_FRAME):
        assert not frame.compact and frame.width == 640 and frame.max_x_ticks == charts.MAX_X_TICKS


def test_compact_chart_has_the_same_points_and_summary_as_the_wide_one():
    readings = [days_ago(300, "23"), days_ago(120, "21.4", assessed_by="VET"), days_ago(2, "19.4")]
    tracking = build_tracking(
        readings, P365, TODAY, target_weight_kg=D("19"), target_status="UNVERIFIED"
    )

    wide, compact = tracking.weight, tracking.weight_compact
    assert [(p.measured_on, p.value, p.shape) for p in wide.points] == [
        (p.measured_on, p.value, p.shape) for p in compact.points
    ]
    assert wide.summary == compact.summary and wide.start == compact.start
    assert wide.target.name == compact.target.name


def test_compact_chart_has_at_most_three_date_ticks_at_every_scale():
    for days in (1, 6, 29, 89, 364, 1000, 20000):
        ticks = date_ticks(TODAY - timedelta(days=days), TODAY, WEIGHT_FRAME_COMPACT.max_x_ticks)
        assert len(ticks) <= 3, days
    assert len(date_ticks(TODAY - timedelta(days=89), TODAY)) == 6  # the wide chart: up to 7


def test_compact_end_label_is_right_aligned_at_the_edge():
    chart = compact_weight([days_ago(40, "21"), days_ago(0, "120")])
    label = chart.end_label
    assert label.anchor == "end" and label.x == chart.frame.width - charts.COMPACT_LABEL_MARGIN
    assert label.text == f"120{NBSP}kg"
    assert chart.points[-1].x < label.x


def test_compact_target_label_is_two_lines_and_never_wider_than_the_plot():
    chart = compact_weight(
        [days_ago(40, "21"), days_ago(0, "20")],
        target_weight_kg=D("19"),
        target_status="VET_CONFIRMED",
    )
    first, second = chart.target.label_lines
    assert first.text == "cílová hmotnost (potvrzeno veterinářem)"
    assert second.text == f"19{NBSP}kg" and second.y > first.y
    assert chart.target.label.text == f"{first.text} {second.text}"  # the full text stays
    wide = weight_chart(
        [days_ago(40, "21"), days_ago(0, "20")],
        target_weight_kg=D("19"),
        target_status="VET_CONFIRMED",
    )
    assert len(wide.target.label_lines) == 1 and wide.target.label_lines[0] == wide.target.label


def test_compact_band_label_is_two_lines_in_the_margin():
    chosen, start, end = select_period([days_ago(9, bcs=5), days_ago(2, bcs=6)], P90, TODAY)
    wide = build_bcs_chart(chosen, P90, start, end)
    compact = build_bcs_chart(chosen, P90, start, end, frame=BCS_FRAME_COMPACT)

    assert [line.text for line in wide.band.label_lines] == ["pásmo 4–5 z 9"]
    assert [line.text for line in compact.band.label_lines] == ["pásmo", "4–5 z 9"]
    assert compact.band.label.text == "pásmo 4–5 z 9"
    assert all(line.x > compact.frame.right for line in compact.band.label_lines)
    top, bottom = compact.band.label_lines
    assert compact.band.top < top.y < bottom.y < compact.band.bottom + 20


# --- A measurement outside the period is refused -------------------------------------------------


def test_charts_refuse_a_measurement_outside_the_range_instead_of_drawing_it_outside_the_plot():
    start, end = TODAY - timedelta(days=29), TODAY
    inside_range = days_ago(5, "20", bcs=5)
    for outside in (days_ago(40, "21", bcs=5), Reading(TODAY + timedelta(days=1), D(20), 5)):
        with pytest.raises(ValueError, match="outside"):
            build_weight_chart([outside, inside_range], P30, start, end)
        with pytest.raises(ValueError, match="outside"):
            build_bcs_chart([outside, inside_range], P30, start, end)
    assert len(build_weight_chart([inside_range], P30, start, end).points) == 1
    with pytest.raises(ValueError, match="start < end"):
        build_bcs_chart([], P30, end, end)


# --- Date ticks cost the same for a short and a very long range ----------------------------------


def reference_date_ticks(start: date, end: date, max_ticks: int) -> list[date]:
    """The straightforward algorithm: build the whole list for every candidate step."""
    steps = [("day", s) for s in (1, 2, 7, 14)] + [
        ("month", s) for s in (1, 2, 3, 6, 12, 24, 60, 120, 240, 600, 1200, 12000)
    ]
    ticks: list[date] = []
    for unit, step in steps:
        if unit == "day":
            first = start.toordinal() + -(start.toordinal() - 1) % step
            ticks = [date.fromordinal(n) for n in range(first, end.toordinal() + 1, step)]
        else:
            index = start.year * 12 + start.month - 1 + (1 if start.day > 1 else 0)
            index += -index % step
            ticks = []
            while index // 12 <= 9999 and date(index // 12, index % 12 + 1, 1) <= end:
                ticks.append(date(index // 12, index % 12 + 1, 1))
                index += step
        if len(ticks) <= max_ticks:
            break
    return ticks


@given(
    st.dates(date(1, 1, 1), date(2100, 1, 1)),
    st.integers(0, 800_000),
    st.sampled_from([3, 4, 7]),
)
@settings(max_examples=300, deadline=None)
def test_property_date_ticks_equal_the_straightforward_algorithm(start, length, max_ticks):
    end = min(start + timedelta(days=length), date(9999, 12, 31))
    assert [t for t, _ in date_ticks(start, end, max_ticks)] == reference_date_ticks(
        start, end, max_ticks
    )


def test_a_range_of_two_thousand_years_is_not_materialised_day_by_day():
    """An animal without a birth date accepted a measurement dated year 1: the "all" period
    then built about 1.2 million dates, 45 MB and half a second, on every request."""
    tracemalloc.start()
    try:
        ticks = date_ticks(date(1, 1, 2), TODAY)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert [t.year for t, _ in ticks] == [1000, 2000]
    assert peak < 200_000  # a few dozen objects, not millions


# --- Descriptions stay short for a long history ---------------------------------------------------


def test_bcs_description_lists_few_scores_but_summarises_many():
    few = [days_ago(d, "20", bcs=5) for d in range(11, 0, -1)]  # 11 scores
    many = [days_ago(d, "20", bcs=1 + d % 9) for d in range(300, 0, -1)]  # one a day
    short = charts.describe_bcs_chart(build_tracking(few, P90, TODAY).bcs)
    long = charts.describe_bcs_chart(build_tracking(many, PALL, TODAY).bcs)

    assert "Zapsaná skóre:" in short and short.count("/9") == 11
    assert "Zapsaná skóre:" not in long
    assert "300 hodnocení" in long and "nejnižší zapsané skóre 1/9, nejvyšší 9/9" in long
    assert "První skóre" in long and "poslední" in long
    assert len(long) < 600, len(long)  # 41 436 characters for 3000 scores before
    assert "Stejná data jsou v tabulce pod grafem." in long


def test_bcs_description_threshold_is_the_documented_one():
    scores = [days_ago(d, "20", bcs=5) for d in range(charts.MAX_LISTED_SCORES + 1, 0, -1)]
    limit = scores[1:]  # exactly MAX_LISTED_SCORES scores: still listed one by one
    assert "Zapsaná skóre:" in charts.describe_bcs_chart(build_tracking(limit, P90, TODAY).bcs)
    assert "Zapsaná skóre:" not in charts.describe_bcs_chart(build_tracking(scores, P90, TODAY).bcs)


def test_weight_description_says_the_line_joins_recorded_measurements_only():
    two = build_tracking([days_ago(9), days_ago(0)], P90, TODAY).weight
    one = build_tracking([days_ago(1)], P90, TODAY).weight

    assert (
        charts.GAP_SENTENCE == "Čára spojuje zapsaná měření; mezi nimi nejsou zapsaná žádná data."
    )
    assert charts.GAP_SENTENCE in charts.describe_weight_chart(two)
    assert charts.GAP_SENTENCE not in charts.describe_weight_chart(one)  # no line at all


@pytest.mark.parametrize(
    ("count", "sentence"),
    [
        (0, None),
        (-1, None),
        (1, "Mimo zobrazené období je další 1 měření"),
        (2, "Mimo zobrazené období jsou další 2 měření"),
        (3, "Mimo zobrazené období jsou další 3 měření"),
        (4, "Mimo zobrazené období jsou další 4 měření"),
        (5, "Mimo zobrazené období je dalších 5 měření"),
        (21, "Mimo zobrazené období je dalších 21 měření"),
    ],
)
def test_outside_period_sentence_declines_the_czech_count(count, sentence):
    assert outside_period_sentence(count) == sentence


# --- The sparkline uses the same minimum span as the weight axis ----------------------------------


def test_widen_to_min_span_follows_the_rule_of_the_axis():
    assert widen_to_min_span(D("20"), D("20")) == (D("19.5"), D("20.5"))  # 1 kg
    low, high = widen_to_min_span(D("100"), D("100.5"))  # 5 % of 100.5 = 5.025 kg
    assert high - low == D("5.025") and (low + high) / 2 == D("100.25")
    assert widen_to_min_span(D("10"), D("14")) == (D("10"), D("14"))  # wide enough: unchanged
    assert weight_axis([D("20"), D("20.05")]) == weight_axis([D("19.9"), D("20.15")])


def test_a_difference_of_grams_is_not_magnified_on_the_card():
    """20.000 -> 20.050 kg drew a full-height slope (28 of 36 px); the main chart draws about
    2 % of its height for the same data."""
    spark = build_sparkline([days_ago(10, "20.000"), days_ago(0, "20.050")])
    ys = [float(pair.split(",")[1]) for pair in spark.points.split()]
    height = charts.SPARK_HEIGHT - 2 * charts.SPARK_PADDING

    assert abs(ys[0] - ys[1]) < 0.05 * height
    big = build_sparkline([days_ago(10, "20"), days_ago(0, "22")])  # 2 kg: a visible slope
    big_ys = [float(pair.split(",")[1]) for pair in big.points.split()]
    assert abs(big_ys[0] - big_ys[1]) == pytest.approx(height)  # span 1.1 kg < 2 kg: full height
    cat = build_sparkline([days_ago(10, "5.1"), days_ago(0, "4.9")])  # -0.2 kg of 1 kg
    cat_ys = [float(pair.split(",")[1]) for pair in cat.points.split()]
    assert abs(cat_ys[0] - cat_ys[1]) == pytest.approx(0.2 * height)
