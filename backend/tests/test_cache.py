import time

import pytest

from app.services import cache


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(cache, "CACHE_FILE", tmp_path / ".cache" / "prediction_cache.json")
    yield
    cache.clear()


def test_nmd_labels_round_trip():
    assert cache.get_nmd_labels() is None

    cache.set_nmd_labels({"58.6,16.2": "112 Granskog på fastmark"})

    assert cache.get_nmd_labels() == {"58.6,16.2": "112 Granskog på fastmark"}


def test_nmd_labels_expire_after_ttl(monkeypatch):
    cache.set_nmd_labels({"58.6,16.2": "112 Granskog på fastmark"})

    monkeypatch.setattr(cache, "NMD_TTL_SECONDS", 0)
    time.sleep(0.01)

    assert cache.get_nmd_labels() is None


def test_observations_round_trip():
    assert cache.get_observations("gulkantarell") is None

    points = [
        {"lat": 58.9, "lon": 16.9, "date": "2020-08-01T00:00:00+02:00"},
        {"lat": 59.0, "lon": 17.0, "date": "2021-09-01T00:00:00+02:00"},
    ]
    cache.set_observations("gulkantarell", points)

    assert cache.get_observations("gulkantarell") == points
    # Andra arter ska inte påverkas.
    assert cache.get_observations("trattkantarell") is None


def test_season_curve_round_trip():
    assert cache.get_season_curve("gulkantarell") is None

    curve = [0.0] + [0.5] * 365
    cache.set_season_curve("gulkantarell", curve)

    assert cache.get_season_curve("gulkantarell") == curve
    # Andra arter ska inte påverkas.
    assert cache.get_season_curve("trattkantarell") is None


def test_season_curve_expires_after_ttl(monkeypatch):
    cache.set_season_curve("gulkantarell", [0.0] + [0.5] * 365)

    monkeypatch.setattr(cache, "OBSERVATIONS_TTL_SECONDS", 0)
    time.sleep(0.01)

    assert cache.get_season_curve("gulkantarell") is None


def test_soil_labels_round_trip():
    assert cache.get_soil_labels() is None

    cache.set_soil_labels({"59.3,18.15": "Sandig morän"})

    assert cache.get_soil_labels() == {"59.3,18.15": "Sandig morän"}


def test_soil_labels_expire_after_ttl(monkeypatch):
    cache.set_soil_labels({"59.3,18.15": "Sandig morän"})

    monkeypatch.setattr(cache, "SOIL_TTL_SECONDS", 0)
    time.sleep(0.01)

    assert cache.get_soil_labels() is None


def test_clear_removes_cache_file():
    cache.set_nmd_labels({"58.6,16.2": "112 Granskog på fastmark"})
    cache.clear()

    assert cache.get_nmd_labels() is None
