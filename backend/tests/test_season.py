from datetime import date

from app.services import season


def _dates_in_month(year: int, month: int, count: int) -> list[str]:
    day = min(28, 15)
    return [f"{year:04d}-{month:02d}-{day:02d}T00:00:00+02:00" for _ in range(count)]


def test_build_season_curve_peaks_near_clustered_observations():
    observation_dates = _dates_in_month(2020, 9, 50) + _dates_in_month(2021, 9, 50)
    curve = season.build_season_curve(observation_dates)

    peak_score = season.score_for_date(curve, date(2026, 9, 15))
    off_season_score = season.score_for_date(curve, date(2026, 12, 20))

    assert peak_score > 0.9
    assert off_season_score < 0.2
    assert off_season_score >= season.SEASON_FLOOR


def test_build_season_curve_returns_no_restriction_when_no_data():
    curve = season.build_season_curve([])

    assert season.score_for_date(curve, date(2026, 1, 1)) == 1.0
    assert season.score_for_date(curve, date(2026, 7, 1)) == 1.0


def test_build_season_curve_is_circular_across_year_boundary():
    # Fynd klustrade kring årsskiftet ska ge hög poäng för BÅDE slutet
    # av december och början av januari, inte bara den ena sidan.
    observation_dates = _dates_in_month(2020, 12, 30) + [
        f"2021-01-{day:02d}T00:00:00+01:00" for day in range(1, 11)
    ]
    curve = season.build_season_curve(observation_dates)

    late_december = season.score_for_date(curve, date(2026, 12, 28))
    early_january = season.score_for_date(curve, date(2026, 1, 3))

    assert late_december > 0.5
    assert early_january > 0.5


def test_score_for_date_handles_leap_day():
    curve = season.build_season_curve(_dates_in_month(2020, 6, 20))
    # Ska inte krascha eller indexa utanför listan för dag 366.
    score = season.score_for_date(curve, date(2024, 12, 31))
    assert 0 <= score <= 1
