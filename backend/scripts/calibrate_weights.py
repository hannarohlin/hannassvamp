"""Kalibrerar väder-/skogs-/historik-vikterna för varje svampart mot
verkliga fynd.

Körs manuellt, inte som del av den vanliga request-vägen:

    cd backend && source .venv/bin/activate
    python scripts/calibrate_weights.py

Metod (logistisk regression med pseudo-frånvaro), per art i
`app/species.py`:
  1. Hämta alla historiska fynd av arten (Artportalen/SOS) i MVP-
     regionen (`app.config.MVP_REGION`), med datum — "presence"-punkter.
  2. Slumpa fram lika många "pseudo-absence"-punkter: samma bbox, samma
     månadsfördelning som de verkliga fynden (för att inte introducera en
     säsongsskevhet), men inte inom sökradien från ett känt fynd.
  3. Räkna ut samma tre features för varje punkt (presence + absence):
       - weather_score: PTHBV:s historiska månadsväder för fyndets/
         punktens år+månad (INTE dagens prognos — se smhi.py). Samma för
         alla arter — det finns ingen artspecifik väderpreferens-data.
       - forest_score: NMD:s trädslagsklass, artspecifik (se nmd.py).
       - history_score: antal ANDRA fynd av SAMMA art inom sökradien
         (leave-one-out för presence-punkter, annars skulle varje
         presence-punkt trivialt "hitta sig själv").
  4. Träna en logistisk regression (presence=1, absence=0) på de tre
     scorerna och skriv ut vikterna — dessa ska sedan klistras in i
     `CALIBRATED_WEIGHTS` i `app/services/prediction.py`.

Antal punkter per art är avsiktligt begränsat (se SAMPLE_SIZE) för att
vara schysst mot Naturvårdsverkets och SMHI:s öppna tjänster — vi
behöver inte tiotusentals punkter för att skatta 3 koefficienter.

Höjt från 300 till 600 (2026-08-20) efter att vikterna visat sig
variera KRAFTIGT mellan körningar med 300 (t.ex. trattkantarells
weather_weight gick från -0.28 till +1.00 mellan två körningar samma
dag) — ett tecken på att stickprovet var för litet för en stabil
skattning, inte att vädersignalen i sig ändrades. 600 är fortfarande
under den minsta artens (svart trumpetsvamp) totala antal fynd (1040),
så `min(SAMPLE_SIZE, len(all_presence))`-golvet i koden nedan aldrig
tvingar ner den arten under 600 heller.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

from app.config import MVP_REGION
from app.data_sources import artportalen, nmd, smhi
from app.services.logistic_regression import fit_logistic_regression, predict_probability
from app.species import ALL_SPECIES, Species

SAMPLE_SIZE = 600
CONCURRENCY = 20

# PTHBV:s arkiv börjar 1961 — äldre Artportalen-fynd (finns några från
# 1900-talets mitt) kan inte matchas mot historiskt väder.
PTHBV_START_YEAR = 1961


def _parse_year_month(date_str: str) -> tuple[int, int]:
    dt = datetime.fromisoformat(date_str)
    return dt.year, dt.month


def _count_nearby(lat: float, lon: float, points: list[tuple[float, float]], exclude_index: int | None) -> int:
    count = 0
    for i, (obs_lat, obs_lon) in enumerate(points):
        if i == exclude_index:
            continue
        if abs(obs_lat - lat) <= artportalen.SEARCH_RADIUS_DEG and abs(obs_lon - lon) <= artportalen.SEARCH_RADIUS_DEG:
            count += 1
    return count


def _is_far_from_all(lat: float, lon: float, points: list[tuple[float, float]]) -> bool:
    return all(
        abs(obs_lat - lat) > artportalen.SEARCH_RADIUS_DEG or abs(obs_lon - lon) > artportalen.SEARCH_RADIUS_DEG
        for obs_lat, obs_lon in points
    )


def _make_pseudo_absence(n: int, presence_dates: list[str], presence_coords: list[tuple[float, float]]) -> list[dict]:
    region = MVP_REGION
    absences = []
    attempts = 0
    while len(absences) < n and attempts < n * 20:
        attempts += 1
        lat = random.uniform(region.min_lat, region.max_lat)
        lon = random.uniform(region.min_lon, region.max_lon)
        if not _is_far_from_all(lat, lon, presence_coords):
            continue
        date = random.choice(presence_dates)
        absences.append({"lat": lat, "lon": lon, "date": date})
    return absences


async def _fetch_features(lat: float, lon: float, date_str: str, species_key: str, sem: asyncio.Semaphore) -> tuple[float, float]:
    """Returnerar (weather_score, forest_score) för en punkt+datum."""
    year, month = _parse_year_month(date_str)

    async with sem:
        forecast_data, forest_score = await asyncio.gather(
            smhi.fetch_historical_monthly(lat, lon, year, year),
            nmd.fetch_forest_score(lat, lon, species_key),
        )

    monthly = smhi.extract_month(forecast_data, year, month)
    if monthly is None:
        weather_score = 0.5
    else:
        precipitation_mm, avg_temp_c = monthly
        weather_score = smhi.historical_weather_score(precipitation_mm, avg_temp_c)

    return weather_score, forest_score


async def calibrate_species(species: Species) -> dict:
    region = MVP_REGION
    print(f"[{species.key}] Hämtar historiska fynd i {region.name}...")
    all_presence = await artportalen.fetch_dated_observations_in_bbox(
        species.taxon_id, region.min_lat, region.max_lat, region.min_lon, region.max_lon
    )
    all_presence = [p for p in all_presence if _parse_year_month(p["date"])[0] >= PTHBV_START_YEAR]
    print(f"[{species.key}]   {len(all_presence)} fynd totalt (efter {PTHBV_START_YEAR}), subsamplar till {SAMPLE_SIZE}.")

    random.seed(42)
    presence = random.sample(all_presence, min(SAMPLE_SIZE, len(all_presence)))
    presence_coords = [(p["lat"], p["lon"]) for p in presence]
    presence_dates = [p["date"] for p in presence]

    absence = _make_pseudo_absence(len(presence), presence_dates, presence_coords)
    absence_coords = [(a["lat"], a["lon"]) for a in absence]

    print(f"[{species.key}] Hämtar features för {len(presence) + len(absence)} punkter...")
    sem = asyncio.Semaphore(CONCURRENCY)

    presence_features = await asyncio.gather(
        *(_fetch_features(p["lat"], p["lon"], p["date"], species.key, sem) for p in presence)
    )
    absence_features = await asyncio.gather(
        *(_fetch_features(a["lat"], a["lon"], a["date"], species.key, sem) for a in absence)
    )

    features: list[list[float]] = []
    labels: list[int] = []

    for i, (weather_score, forest_score) in enumerate(presence_features):
        history_score = artportalen.observation_count_to_score(
            _count_nearby(presence_coords[i][0], presence_coords[i][1], presence_coords, exclude_index=i)
        )
        features.append([weather_score, forest_score, history_score])
        labels.append(1)

    for i, (weather_score, forest_score) in enumerate(absence_features):
        history_score = artportalen.observation_count_to_score(
            _count_nearby(absence_coords[i][0], absence_coords[i][1], presence_coords, exclude_index=None)
        )
        features.append([weather_score, forest_score, history_score])
        labels.append(0)

    print(f"[{species.key}] Tränar logistisk regression...")
    weights, bias = fit_logistic_regression(features, labels)

    correct = sum(
        1
        for x, y in zip(features, labels)
        if (predict_probability(weights, bias, x) >= 0.5) == bool(y)
    )
    accuracy = correct / len(labels)

    return {
        "n": len(labels),
        "n_presence": len(presence),
        "n_absence": len(absence),
        "weather_weight": weights[0],
        "forest_weight": weights[1],
        "history_weight": weights[2],
        "bias": bias,
        "accuracy": accuracy,
    }


async def main() -> None:
    results = {}
    for species in ALL_SPECIES:
        results[species.key] = await calibrate_species(species)

    print()
    print("=== Resultat per art ===")
    for species in ALL_SPECIES:
        r = results[species.key]
        print(f"\n[{species.key}] n={r['n']} ({r['n_presence']} presence / {r['n_absence']} pseudo-absence), träffsäkerhet={r['accuracy']:.1%}")
        print(f"  weather={r['weather_weight']:.4f}  forest={r['forest_weight']:.4f}  history={r['history_weight']:.4f}  bias={r['bias']:.4f}")

    print()
    print("Klistra in i app/services/prediction.py:")
    print("CALIBRATED_WEIGHTS = {")
    for species in ALL_SPECIES:
        r = results[species.key]
        print(
            f'    "{species.key}": {{"weather": {r["weather_weight"]:.4f}, '
            f'"forest": {r["forest_weight"]:.4f}, "history": {r["history_weight"]:.4f}, '
            f'"bias": {r["bias"]:.4f}}},'
        )
    print("}")


if __name__ == "__main__":
    asyncio.run(main())
