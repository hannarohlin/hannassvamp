"""Klient mot SLU Artdatabankens Species Observation System (SOS).

Produkten att prenumerera på i api-portal.artdatabanken.se är
"Species Observations - multiple data resources" (SOS) — den öppna,
aktivt underhållna efterträdaren till de numera stängda
"Artportalen - Read"-produkterna. Täcker Artportalen plus några andra
svenska datakällor (iNaturalist m.fl.).

API-nyckeln skickas i headern `Ocp-Apim-Subscription-Key`.

OBS 1: API:et validerar inte request-body strikt — okända fältnamn
ignoreras tyst istället för att ge valideringsfel. Fält-strukturen nedan
(`geographics.boundingBox.topLeft`/`bottomRight`, `taxon.ids`) är
verifierad genom faktiska anrop, inte bara dokumentation.

OBS 2: API:et har en aggressiv rate limit — >100 samtidiga anrop från
samma nyckel gav 429 Too Many Requests i tester, även utspritt över en
kort period. Att fråga en gång per rutcell (så som NMD- och
SMHI-klienterna gör) skalar därför inte. Istället hämtar vi ALLA fynd i
regionens bounding box (för en given art, se `app/species.py`) i EN
paginerad förfrågningsserie och räknar träffar per cell lokalt — se
`fetch_dated_observations_in_bbox` + `build_history_counter`.

OBS 3: API:et har INGET datumfilter i sökningen — ett fynd från 1819
returneras exakt lika villkorslöst som ett från förra veckan. Fynd
åldersviktas därför lokalt istället, se `RECENCY_HALF_LIFE_YEARS`.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from app.config import settings

BASE_URL = "https://api.artdatabanken.se/species-observation-system/v1/observations/search"

# Sökradie runt varje punkt (grader), ~1km i Södermanlands breddgrad.
SEARCH_RADIUS_DEG = 0.01

# API:t tillåter max 1000 poster per sida och 10 000 totalt per sökning.
PAGE_SIZE = 1000
MAX_RECORDS = 10_000

# Åldersviktning av fynd: Artportalen-sökningen har INGET datumfilter
# (se modulens docstring) — ett fynd från 1819 räknas annars exakt
# likadant som ett från förra veckan. Verkligt datauttag för regionen
# (2026-08-19) visade fynd ända från 1819, men med kraftig övervikt mot
# 2000-talet (t.ex. 3312 gulkantarell-fynd totalt, varav >2400 sedan
# 2008) — citizen science-rapportering har exploderat, inte att svampen
# plötsligt blivit vanligare. Ett gammalt fynd är dock INTE värdelöst:
# kantarellställen kan vara stabila i decennier om skogen inte avverkas.
# Exponentiell avklingning med ett golv fångar båda: ett färskt fynd
# väger fullt, ett 10 år gammalt ~58%, ett sekelgammalt asymptotiskt mot
# golvet (15%) snarare än 0.
RECENCY_HALF_LIFE_YEARS = 10.0
RECENCY_FLOOR_WEIGHT = 0.15


def _headers() -> dict[str, str]:
    return {"Ocp-Apim-Subscription-Key": settings.artportalen_api_key}


def _bbox_body(taxon_id: int, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict:
    return {
        "taxon": {"ids": [taxon_id]},
        "geographics": {
            "boundingBox": {
                "topLeft": {"latitude": max_lat, "longitude": min_lon},
                "bottomRight": {"latitude": min_lat, "longitude": max_lon},
            }
        },
    }


async def _fetch_records_in_bbox(
    taxon_id: int, min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[dict]:
    """Hämtar alla rå fynd-poster för en art inom en bounding box (paginerat).

    Paginerar i steg om `PAGE_SIZE` tills alla poster hämtats eller
    `MAX_RECORDS` nås. Görs EN gång per region och art, inte per rutcell.
    """
    body = _bbox_body(taxon_id, min_lat, max_lat, min_lon, max_lon)
    records: list[dict] = []
    skip = 0

    async with httpx.AsyncClient(timeout=20) as client:
        while skip < MAX_RECORDS:
            response = await client.post(
                f"{BASE_URL}?take={PAGE_SIZE}&skip={skip}", json=body, headers=_headers()
            )
            response.raise_for_status()
            data = response.json()
            records.extend(data.get("records", []))

            skip += PAGE_SIZE
            if skip >= data.get("totalCount", 0):
                break

    return records


async def fetch_dated_observations_in_bbox(
    taxon_id: int, min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[dict]:
    """Hämtar (lat, lon, datum) för alla fynd av en art inom en bounding box.

    Datumet behövs av BÅDE kalibreringsskriptet (matchar varje fynd mot
    historiskt väder för samma år/månad) OCH den vanliga prediction-vägen
    (åldersviktar fynd, se `RECENCY_HALF_LIFE_YEARS` och
    `build_history_counter`).
    """
    records = await _fetch_records_in_bbox(taxon_id, min_lat, max_lat, min_lon, max_lon)
    observations: list[dict] = []
    for record in records:
        location = record.get("location", {})
        lat = location.get("decimalLatitude")
        lon = location.get("decimalLongitude")
        start_date = record.get("event", {}).get("startDate")
        if lat is not None and lon is not None and start_date:
            observations.append({"lat": lat, "lon": lon, "date": start_date})
    return observations


def observation_count_to_score(count: float) -> float:
    """Normaliserar (ev. åldersviktat) antal närliggande historiska fynd
    till en poäng 0–1.

    Tar emot ett FLYTTAL, inte bara ett heltal: `build_history_counter`
    matar in en åldersviktad summa (t.ex. 2.3 "effektiva" fynd om ett är
    färskt och ett gammalt), inte bara ett råräknat antal.

    Placeholder-heuristik: inga kända fynd ger ett lägre värde (0.3) än
    NMD-proxyns "okänd" (0.4), eftersom Artportalen har god
    rapporteringstäckning i bebodda/besökta delar av Södermanland — så
    frånvaro av fynd är en svagare men ändå negativ signal här. Samma
    heuristik används för alla tre arter.
    """
    if count <= 0:
        return 0.3
    return round(min(0.9, 0.4 + count * 0.1), 3)


def _parse_observation_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _recency_weight(observation_date: date | None, reference_date: date) -> float:
    """Vikt 0–1 för hur mycket ETT fynd ska räknas, baserat på hur
    gammalt det är — se motiveringen vid `RECENCY_HALF_LIFE_YEARS`.
    Saknas datum (bör inte hända i praktiken, se `fetch_dated_
    observations_in_bbox`) antas fyndet vara färskt hellre än att tyst
    kasseras.
    """
    if observation_date is None or observation_date >= reference_date:
        return 1.0
    age_years = (reference_date - observation_date).days / 365.25
    decay = 0.5 ** (age_years / RECENCY_HALF_LIFE_YEARS)
    return RECENCY_FLOOR_WEIGHT + (1 - RECENCY_FLOOR_WEIGHT) * decay


def build_history_counter(observations: list[dict], reference_date: date | None = None):
    """Bygger en synkron uppslagsfunktion från en förhämtad lista av
    daterade fynd (`{"lat", "lon", "date"}`).

    Undviker ett nätverksanrop per rutcell: alla fynd i regionen (för en
    given art) hämtas en gång (se `fetch_dated_observations_in_bbox`) och
    räknas lokalt per punkt. Returnerar per punkt ett par:
      - RÅTT antal närliggande fynd, oviktat — för en förklaringstext
        ska kunna säga "3 kända fynd inom ~1 km", en enkel sakuppgift som
        inte ska bero på hur gamla fynden råkar vara.
      - ÅLDERSVIKTAD summa — ett färskt fynd bidrar med ~1.0, ett
        decennier gammalt med mindre (se `_recency_weight`). Det är
        DENNA som ska användas för själva sannolikhetsberäkningen.
    Åldersvikten räknas ut EN gång per fynd (inte en gång per rutcell)
    eftersom den bara beror på fyndets datum, inte på vilken punkt som
    frågas.
    """
    reference = reference_date or date.today()
    weighted_points = [
        (obs["lat"], obs["lon"], _recency_weight(_parse_observation_date(obs.get("date")), reference))
        for obs in observations
    ]

    def nearby_stats(lat: float, lon: float) -> tuple[int, float]:
        count = 0
        weighted_count = 0.0
        for obs_lat, obs_lon, weight in weighted_points:
            if abs(obs_lat - lat) <= SEARCH_RADIUS_DEG and abs(obs_lon - lon) <= SEARCH_RADIUS_DEG:
                count += 1
                weighted_count += weight
        return count, weighted_count

    return nearby_stats
