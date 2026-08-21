from datetime import date

import pytest

from app.data_sources import artportalen as ap


def test_observation_count_to_score_is_bounded():
    for count in [0, 1, 3, 10, 100]:
        score = ap.observation_count_to_score(count)
        assert 0 <= score <= 1


def test_observation_count_to_score_increases_with_count():
    none = ap.observation_count_to_score(0)
    one = ap.observation_count_to_score(1)
    many = ap.observation_count_to_score(10)

    assert one > none
    assert many > one
    assert many <= 0.9


def test_build_history_counter_counts_only_nearby_observations():
    observations = [
        {"lat": 58.90, "lon": 16.90, "date": "2026-08-01T00:00:00+02:00"},  # nära
        {"lat": 58.901, "lon": 16.901, "date": "2026-08-01T00:00:00+02:00"},  # nära
        {"lat": 59.50, "lon": 17.90, "date": "2026-08-01T00:00:00+02:00"},  # långt bort
    ]
    counter = ap.build_history_counter(observations, reference_date=date(2026, 8, 19))

    count, _ = counter(58.90, 16.90)
    assert count == 2
    count, _ = counter(58.10, 16.00)
    assert count == 0


def test_build_history_counter_weights_recent_observations_more() -> None:
    reference = date(2026, 8, 19)
    recent = [{"lat": 58.90, "lon": 16.90, "date": "2026-08-01T00:00:00+02:00"}]
    old = [{"lat": 58.90, "lon": 16.90, "date": "1990-08-01T00:00:00+02:00"}]

    _, weighted_recent = ap.build_history_counter(recent, reference_date=reference)(58.90, 16.90)
    _, weighted_old = ap.build_history_counter(old, reference_date=reference)(58.90, 16.90)

    assert weighted_recent == pytest.approx(1.0, abs=0.01)
    assert weighted_old < weighted_recent
    assert weighted_old >= ap.RECENCY_FLOOR_WEIGHT


def test_build_history_counter_treats_missing_date_as_fresh() -> None:
    observations = [{"lat": 58.90, "lon": 16.90, "date": None}]
    counter = ap.build_history_counter(observations, reference_date=date(2026, 8, 19))

    _, weighted = counter(58.90, 16.90)
    assert weighted == pytest.approx(1.0)
