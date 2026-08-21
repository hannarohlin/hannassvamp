"""Verifierar att en oväntad (icke-httpx) krasch i en enskild NMD- eller
SGU-punktförfrågan inte får hela prediktionen att krascha — se
_get_land_cover_labels/_get_soil_labels i app/services/prediction.py.

Tidigare saknade dessa två den try/except som _get_weather_details redan
hade, så ett enda oväntat fel (t.ex. trasig JSON) hade propagerat upp
genom asyncio.gather och kraschat hela /api/predictions-anropet.
"""

import pytest

from app.data_sources import nmd, sgu
from app.services import cache, prediction


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(cache, "CACHE_FILE", tmp_path / ".cache" / "prediction_cache.json")
    yield
    cache.clear()


@pytest.mark.asyncio
async def test_get_land_cover_labels_survives_unexpected_exception(monkeypatch):
    async def _boom(lat, lon):
        raise ValueError("trasig JSON, inte ett httpx.HTTPError")

    monkeypatch.setattr(nmd, "fetch_land_cover_label", _boom)

    labels = await prediction._get_land_cover_labels([(59.3, 18.1), (59.4, 18.2)], force_refresh=True)

    assert labels == {(59.3, 18.1): None, (59.4, 18.2): None}


@pytest.mark.asyncio
async def test_get_soil_labels_survives_unexpected_exception(monkeypatch):
    async def _boom(lat, lon):
        raise ValueError("trasig JSON, inte ett httpx.HTTPError")

    monkeypatch.setattr(sgu, "fetch_soil_type_label", _boom)

    points = [(59.3, 18.1)]
    labels_by_point = {(59.3, 18.1): "112 Granskog på fastmark"}  # klassat som skog av NMD

    soil_by_point = await prediction._get_soil_labels(points, labels_by_point, force_refresh=True)

    assert soil_by_point[(59.3, 18.1)] is None
