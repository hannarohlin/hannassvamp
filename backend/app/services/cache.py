"""Enkel disk-cache (en JSON-fil) för data som knappt ändras mellan
sidladdningar: NMD-marktäcke, SGU-jordart, Artportalen-fyndhistorik, de
säsongskurvor (se app/services/season.py) som byggs av samma fynddata,
och väder per grovt rutnät (se WEATHER_TTL_SECONDS för varför väder
numera cachas här trots att det ska kännas "live").

Ingen databas eller externt beroende behövs för det här — en JSON-fil
räcker gott för en enda MVP-region med några hundra rutceller.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import settings

# `settings.cache_dir` pekar mot en monterad, beständig volym i produktion
# (se config.py) — tom sträng (lokal utveckling) faller tillbaka på en
# katalog bredvid koden, som tidigare.
CACHE_DIR = Path(settings.cache_dir) if settings.cache_dir else Path(__file__).resolve().parent.parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "prediction_cache.json"

# NMD-marktäckedata uppdateras av Naturvårdsverket ungefär vart 5:e år —
# ingen anledning att hämta live varje request.
NMD_TTL_SECONDS = 30 * 24 * 3600

# Nya Artportalen-fynd droppar in löpande under säsongen, men inte
# minut-för-minut — ett dygns cache är en rimlig avvägning.
OBSERVATIONS_TTL_SECONDS = 24 * 3600

# PTHBV:s DAGLIGA arkiv uppdateras bara en gång per dygn (verifierat
# 2026-08-20: senaste tillgängliga dag var alltid "igår"), så en
# request mitt på dagen skulle ändå bara få samma data som en request
# på morgonen — 12h cache kostar därför ingen verklig färskhet, bara
# onödiga upprepade PTHBV-batchanrop (se app/data_sources/smhi.py för
# varför de är dyra att göra om och om igen).
WEATHER_TTL_SECONDS = 12 * 3600

# Jordart ändras i praktiken aldrig (geologisk tidsskala) — samma
# resonemang som NMD, men ännu längre TTL eftersom det är ännu mer
# statiskt än trädslag (som ju faktiskt avverkas/planteras om).
SOIL_TTL_SECONDS = 90 * 24 * 3600


def _load() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data))


def get_nmd_labels() -> dict[str, str | None] | None:
    """Returnerar cachade NMD-klassnamn (nyckel `"lat,lon"`), eller None om
    cachen saknas/är för gammal."""
    entry = _load().get("nmd_labels")
    if not entry or time.time() - entry["fetched_at"] > NMD_TTL_SECONDS:
        return None
    return entry["labels"]


def set_nmd_labels(labels: dict[str, str | None]) -> None:
    data = _load()
    data["nmd_labels"] = {"fetched_at": time.time(), "labels": labels}
    _save(data)


def get_observations(species_key: str) -> list[dict] | None:
    """Returnerar cachade fynd (`{"lat", "lon", "date"}`) för en art,
    eller None om cachen saknas/är för gammal."""
    entry = _load().get("observations", {}).get(species_key)
    if not entry or time.time() - entry["fetched_at"] > OBSERVATIONS_TTL_SECONDS:
        return None
    return entry["points"]


def set_observations(species_key: str, points: list[dict]) -> None:
    data = _load()
    data.setdefault("observations", {})[species_key] = {
        "fetched_at": time.time(),
        "points": points,
    }
    _save(data)


def get_season_curve(species_key: str) -> list[float] | None:
    """Returnerar en cachad säsongskurva (se app/services/season.py) för
    en art, eller None om cachen saknas/är för gammal. Delar TTL med
    observationerna den byggdes från — den ska aldrig anses färskare
    (eller staplare) än sin källdata."""
    entry = _load().get("season_curves", {}).get(species_key)
    if not entry or time.time() - entry["fetched_at"] > OBSERVATIONS_TTL_SECONDS:
        return None
    return entry["curve"]


def set_season_curve(species_key: str, curve: list[float]) -> None:
    data = _load()
    data.setdefault("season_curves", {})[species_key] = {
        "fetched_at": time.time(),
        "curve": curve,
    }
    _save(data)


def get_weather() -> dict[str, dict] | None:
    """Returnerar cachat väder per grovt rutnät (nyckel `"lat,lon"`,
    värde = weather_detail-dict från smhi.rolling_weather_score), eller
    None om cachen saknas/är för gammal."""
    entry = _load().get("weather")
    if not entry or time.time() - entry["fetched_at"] > WEATHER_TTL_SECONDS:
        return None
    return entry["buckets"]


def set_weather(buckets: dict[str, dict]) -> None:
    data = _load()
    data["weather"] = {"fetched_at": time.time(), "buckets": buckets}
    _save(data)


def get_soil_labels() -> dict[str, str | None] | None:
    """Returnerar cachade SGU-jordartsklassningar per grovt rutnät
    (nyckel `"lat,lon"`), eller None om cachen saknas/är för gammal."""
    entry = _load().get("soil_labels")
    if not entry or time.time() - entry["fetched_at"] > SOIL_TTL_SECONDS:
        return None
    return entry["labels"]


def set_soil_labels(labels: dict[str, str | None]) -> None:
    data = _load()
    data["soil_labels"] = {"fetched_at": time.time(), "labels": labels}
    _save(data)


def clear() -> None:
    """Tar bort hela cachen (t.ex. för att tvinga fräscha data)."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
