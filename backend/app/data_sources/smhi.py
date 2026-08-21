"""Klient mot SMHI:s öppna väderdata.

Två separata API:er används numera:
  - PTHBV:s DAGLIGA arkiv (griddat, 4x4km, sedan 1961) — för den LIVA
    prediktionens rullande fuktmodell (se `fetch_recent_daily_weather`/
    `rolling_weather_score` nedan). Ersatte den tidigare prognosbaserade
    modellen (`snow1g`), som bara såg ETT dygns nederbörd i taget och
    därför inte kunde skilja på "regnade igår" och "torrt i tre veckor"
    — verifierat i praktiken (2026-08-20) att Stockholmsområdet hade en
    tydlig torrperiod hela augusti som den gamla modellen missade helt.
  - Samma PTHBV, MÅNADSupplöst, för kalibreringsskriptet (se längre ner).

Ingen API-nyckel krävs för något av dem.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx

# Delad klient (återanvänd TCP/TLS-anslutningar) istället för en ny
# httpx.AsyncClient per anrop — se motsvarande kommentar i nmd.py.
# Skapas lazy för att inte binda till fel event loop vid modul-import.
#
# Semafor: om flera överlappande requests (t.ex. flera zoom-detaljanrop
# igång samtidigt) tillsammans skulle vilja göra tusentals samtidiga
# SMHI-anrop kan själva bokföringen av så många väntande coroutines/
# anslutningar bli tung nog att blockera event-loopen (sett i praktiken
# som en hängande server). Samma sorts skydd som NMD redan hade.
_client: httpx.AsyncClient | None = None
_semaphore: asyncio.Semaphore | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=20, limits=httpx.Limits(max_connections=40, max_keepalive_connections=40)
        )
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(40)
    return _semaphore


# Kantarell fruktar bäst vid milda temperaturer efter regn.
IDEAL_TEMP_MIN_C = 10.0
IDEAL_TEMP_MAX_C = 20.0

PRECIPITATION_WEIGHT = 0.6
TEMPERATURE_WEIGHT = 0.4


def temperature_to_score(avg_temp_c: float) -> float:
    """Normaliserar medeltemperatur till en poäng 0–1.

    Placeholder-heuristik: 10-20°C anses gynnsamt för fruktkroppsbildning,
    poängen avtar ju längre utanför intervallet temperaturen ligger.
    """
    if IDEAL_TEMP_MIN_C <= avg_temp_c <= IDEAL_TEMP_MAX_C:
        return 0.9
    distance = (
        IDEAL_TEMP_MIN_C - avg_temp_c if avg_temp_c < IDEAL_TEMP_MIN_C else avg_temp_c - IDEAL_TEMP_MAX_C
    )
    return max(0.1, 0.9 - distance * 0.08)


# --- Rullande fuktmodell (live prediktion) --------------------------------
#
# PTHBV:s DAGLIGA arkiv ligger ~1 dag efter realtid (verifierat
# 2026-08-20: senaste tillgängliga dag var 2026-08-19). Vi hämtar hela
# innevarande år (API:t tar bara årtal, inte exakta datum) och plockar
# ut de sista ROLLING_WINDOW_DAYS dagarna själva.
PTHBV_DAILY_URL = (
    "https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/version/1"
    "/geotype/multipoint/from/{year}/to/{year}/period/daily/data.json"
)

# ~3 veckor — matchar bättre mot mycelets fördröjda respons på regn än
# ett enskilt dygn (se modulens docstring för den verifierade torrperioden
# den gamla modellen missade).
ROLLING_WINDOW_DAYS = 21

# Senaste dagarnas medeltemperatur representerar dagens
# fruktkroppsbildning bättre än ett 3-veckorssnitt (som är till för
# FUKTEN, inte temperaturen).
RECENT_TEMPERATURE_WINDOW_DAYS = 5

# Markfukt avklingar snabbare i varmt väder (avdunstning) — decay_factor
# minskar per grad över referenstemperaturen. Gränserna (0.6-0.97) är en
# säkerhetsspärr mot orimliga värden, inte kalibrerade konstanter.
MOISTURE_DECAY_BASE = 0.90
MOISTURE_DECAY_TEMP_SENSITIVITY = 0.01
MOISTURE_DECAY_REFERENCE_TEMP_C = 10.0


# PTHBV:s dagliga API accepterar max så här många punkter per anrop
# (verifierat: 150 gav ett tydligt 400-fel "The maximum no points for
# one request is 100"). Dessutom tål API:et påfallande dåligt MÅNGA
# SMÅ anrop i snabb följd oavsett vår egen samtidighetsgräns — verifierat
# att 77 SAMTIDIGA en-punkts-anrop tog 62 SEKUNDER, mot ~3,5s för ETT
# anrop med 100 punkter batchat i samma förfrågan. Batchning (inte lägre
# samtidighet) är alltså den faktiska fixen.
PTHBV_MAX_POINTS_PER_REQUEST = 100


async def fetch_recent_daily_weather_batch(
    points: list[tuple[float, float]], today: date | None = None, attempts: int = 3
) -> dict[tuple[float, float], dict]:
    """Hämtar PTHBV:s dagliga nederbörd/temperatur för FLERA punkter,
    batchat i grupper om `PTHBV_MAX_POINTS_PER_REQUEST` (se konstantens
    motivering ovan) istället för ett anrop per punkt.

    Returnerar `{(lat, lon): {"dates", "precipitation_mm",
    "temperature_c"}}`, matchat mot svarets egna `north`/`east`-fält
    (inte positionell ordning — API:et råkar redan skicka tillbaka
    exakt vilken koordinat varje post gäller, säkrare att lita på det
    än att anta att ordningen bevaras).

    Punkter som av någon anledning saknas i svaret (t.ex. utanför
    PTHBV:s täckningsområde) finns helt enkelt inte med i den
    returnerade dicten — anroparen avgör hur den vill falla tillbaka.
    """
    reference = today or date.today()
    url = PTHBV_DAILY_URL.format(year=reference.year)
    unique_points = list({(round(lat, 4), round(lon, 4)) for lat, lon in points})
    result: dict[tuple[float, float], dict] = {}

    for batch_start in range(0, len(unique_points), PTHBV_MAX_POINTS_PER_REQUEST):
        batch = unique_points[batch_start : batch_start + PTHBV_MAX_POINTS_PER_REQUEST]
        params = {"epsg": 4326, "ll": [f"{lon},{lat}" for lat, lon in batch], "var": ["p", "t"]}

        for attempt in range(attempts):
            try:
                async with _get_semaphore():
                    response = await _get_client().get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

        dates = data.get("dates", [])
        for point_value in data.get("point_values", []):
            lat, lon = point_value.get("north"), point_value.get("east")
            if lat is None or lon is None:
                continue
            precipitation = point_value.get("p", [])
            temperature = point_value.get("t", [])
            n = min(len(dates), len(precipitation), len(temperature))

            # Vissa dagar/punkter (t.ex. nära kust/skärgård, i utkanten
            # av PTHBV:s täckning) saknar värde (null) — verifierat i
            # praktiken att det förekommer i vår region. Filtrera bort
            # dem istället för att krascha på None i uträkningarna.
            recent = [
                (p, t) for p, t in zip(precipitation[:n][-ROLLING_WINDOW_DAYS:], temperature[:n][-ROLLING_WINDOW_DAYS:])
                if p is not None and t is not None
            ]
            result[(lat, lon)] = {
                "precipitation_mm": [p for p, _ in recent],
                "temperature_c": [t for _, t in recent],
            }

    return result


def _daily_decay_factor(temp_c: float) -> float:
    decay = MOISTURE_DECAY_BASE - MOISTURE_DECAY_TEMP_SENSITIVITY * (temp_c - MOISTURE_DECAY_REFERENCE_TEMP_C)
    return min(0.97, max(0.6, decay))


def rolling_moisture_mm(daily_precipitation_mm: list[float], daily_temperature_c: list[float]) -> float:
    """Ackumulerad, avklingande markfukt-proxy — regn tillför, varmare
    väder torkar ut snabbare. Kräver KRONOLOGISK ordning (äldst först,
    vilket är ordningen PTHBV redan svarar i).

    Verifierat mot verklig data (Stockholm, senaste 30 dagarna innan
    2026-08-19): en tydlig torrperiod syns tydligt som avklingande
    värden ner mot ~0, i linje med hur markfukt faktiskt beter sig —
    till skillnad från ett enskilt dygns nederbörd, som inte kan skilja
    på "torrt sedan tre veckor" och "regnade för en timme sedan".
    """
    moisture = 0.0
    for precipitation, temperature in zip(daily_precipitation_mm, daily_temperature_c):
        moisture = moisture * _daily_decay_factor(temperature) + precipitation
    return moisture


def rolling_moisture_to_score(moisture_mm: float) -> float:
    """Normaliserar ackumulerad markfukt till en poäng 0-1.

    Placeholder-heuristik: 15-40mm ACKUMULERAT (inte samma skala som ett
    enskilt dygns nederbörd, eftersom det här är en avklingande SUMMA
    över ~3 veckor) anses gynnsamt.
    """
    if moisture_mm <= 0:
        return 0.05
    if moisture_mm < 15:
        return 0.05 + (moisture_mm / 15) * 0.55
    if moisture_mm <= 40:
        return 0.85
    return max(0.25, 0.85 - (moisture_mm - 40) * 0.015)


def rolling_weather_score(daily_precipitation_mm: list[float], daily_temperature_c: list[float]) -> dict:
    """Kombinerar rullande fukt och senaste dagarnas temperatur till en
    samlad väder-poäng 0-1, plus de råa mätvärdena (för
    app/services/explanation.py)."""
    moisture_mm = rolling_moisture_mm(daily_precipitation_mm, daily_temperature_c)
    moisture_score = rolling_moisture_to_score(moisture_mm)

    recent_temps = daily_temperature_c[-RECENT_TEMPERATURE_WINDOW_DAYS:]
    avg_temp_c = sum(recent_temps) / len(recent_temps) if recent_temps else None
    temperature_score = temperature_to_score(avg_temp_c) if avg_temp_c is not None else 0.5

    score = round(PRECIPITATION_WEIGHT * moisture_score + TEMPERATURE_WEIGHT * temperature_score, 3)
    return {
        "score": score,
        "moisture_mm": round(moisture_mm, 1),
        "avg_temp_c": round(avg_temp_c, 1) if avg_temp_c is not None else None,
    }


# --- Historiskt väder (PTHBV, månadsupplöst) — används endast för
# kalibrering ---------------------------------------------------------
#
# Kalibreringsskriptet matchar historiska fynd mot vädret vid FYNDETS
# år/månad, långt tillbaka i tiden — då räcker inte ett 3 veckors
# rullande fönster (det finns ingen "idag" att räkna bakåt ifrån), utan
# månadsupplösning är den rimliga kompromissen. Dokumentation:
# https://opendata.smhi.se/apidocs/pthbv/

PTHBV_URL = (
    "https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/version/1"
    "/geotype/multipoint/from/{from_year}/to/{to_year}/period/monthly/data.json"
)


async def fetch_historical_monthly(lat: float, lon: float, from_year: int, to_year: int, attempts: int = 3) -> dict:
    """Hämtar PTHBV:s månadsvärden (nederbörd `p` mm, medeltemp `t` °C) för en punkt.

    EN förfrågan täcker hela årsintervallet — anropa en gång per unik
    punkt, inte en gång per fynd-datum.

    Delar klient/semafor med den dagliga rullande modellen ovan (samma
    SMHI-domän) — ger connection pooling OCH retry/backoff, vilket
    tidigare saknades här. Upptäckt i praktiken vid en större
    omkalibreringskörning (2026-08-20): en enskild `httpx.ReadError`
    kunde annars krascha hela körningen efter flera minuters arbete,
    utan möjlighet att återhämta sig.
    """
    url = PTHBV_URL.format(from_year=from_year, to_year=to_year)
    params = {"epsg": 4326, "ll": f"{lon},{lat}", "var": ["p", "t"]}

    for attempt in range(attempts):
        try:
            async with _get_semaphore():
                response = await _get_client().get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))


def extract_month(data: dict, year: int, month: int) -> tuple[float, float] | None:
    """Plockar ut (nederbörd mm, medeltemp °C) för en given år/månad ur PTHBV-svaret.

    Returnerar None om månaden saknas ELLER om värdet är null (samma
    typ av lucka som förekommer i PTHBV:s dagliga arkiv, t.ex. nära
    kust/skärgård eller för en preliminär/ofärdig månad — verifierat i
    praktiken vid kalibreringskörning 2026-08-20) — anroparen faller då
    tillbaka på ett neutralt värde istället för att krascha.
    """
    key = f"{year:04d}-{month:02d}"
    dates = data.get("dates", [])
    if key not in dates:
        return None
    index = dates.index(key)
    point = (data.get("point_values") or [{}])[0]
    precipitation = point.get("p", [])
    temperature = point.get("t", [])
    if index >= len(precipitation) or index >= len(temperature):
        return None
    if precipitation[index] is None or temperature[index] is None:
        return None
    return precipitation[index], temperature[index]


def monthly_precipitation_to_score(precipitation_mm: float) -> float:
    """Normaliserar total månadsnederbörd till en poäng 0–1.

    Placeholder-heuristik: 50-100mm för hela månaden anses gynnsamt
    (grovt sett en fuktig men inte översvämmad sommar-/höstmånad).
    """
    if precipitation_mm <= 0:
        return 0.1
    if precipitation_mm < 50:
        return 0.1 + (precipitation_mm / 50) * 0.5
    if precipitation_mm <= 100:
        return 0.9
    return max(0.3, 0.9 - (precipitation_mm - 100) * 0.01)


def historical_weather_score(precipitation_mm: float, avg_temp_c: float) -> float:
    """Samma vägning (PRECIPITATION_WEIGHT/TEMPERATURE_WEIGHT) som
    `rolling_weather_score`, för historiska månadsvärden."""
    precipitation_score = monthly_precipitation_to_score(precipitation_mm)
    temperature_score = temperature_to_score(avg_temp_c)
    return round(
        PRECIPITATION_WEIGHT * precipitation_score + TEMPERATURE_WEIGHT * temperature_score, 3
    )
