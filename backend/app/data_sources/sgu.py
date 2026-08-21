"""Klient mot SGU:s (Sveriges geologiska undersökning) öppna jordartsdata.

Tjänst: OGC API - Features, `jordarter25k-100k`, kollektionen `grundlager`
(SGU:s jordartskarta 1:25 000-1:100 000, jordartsklassning per polygon).
Öppen data (CC0), ingen nyckel krävs.
Dokumentation: https://api.sgu.se/oppnadata/jordarter25k-100k/ogc/features/v1

Jordart kompletterar NMD:s trädslagsklassning (app/data_sources/nmd.py)
med markens geologiska ursprung — morän/lera/isälvssediment/urberg/torv
osv. — vilket t.ex. spelar roll för kalkkrävande arter (rödgul
trumpetsvamp) och för hur väl marken håller kvar fukt oberoende av
trädslag.

VIKTIG PRESTANDALÄRDOM (verifierad i praktiken 2026-08-20): en enskild
punktförfrågan kan ge en förvånansvärt STOR respons — geometrin för en
enda polygon (t.ex. en sjö eller ett stort moränfält) kan väga över
700 KB, eftersom API:et alltid skickar med hela polygonens gränslinje
även om vi bara vill ha en enda textattributstring (`jg2_tx`). Testade
`skipGeometry`/`properties`-parametrarna för att trimma svaret, men
den här instansen av OGC API - Features stödjer inte det. Att fråga per
FIN prediktionscell (ner till ~80m) skulle alltså kunna dra flera hundra
MB per request. Lösningen (se `app.services.prediction._get_soil_labels`)
är densamma som för väder: ett GROVT rutnät + ackumulerande cache, och
frågas bara för celler som NMD redan klassat som skog.
"""

from __future__ import annotations

import asyncio

import httpx

_semaphore: asyncio.Semaphore | None = None
_client: httpx.AsyncClient | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(20)
    return _semaphore


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=20, max_keepalive_connections=20))
    return _client


BASE_URL = "https://api.sgu.se/oppnadata/jordarter25k-100k/ogc/features/v1/collections/grundlager/items"

# Halva bredden (grader) på förfrågningsrutan runt punkten — samma idé
# som NMD:s QUERY_HALF_WIDTH_DEG, bara en liten ruta runt punkten.
QUERY_HALF_WIDTH_DEG = 0.0005


async def fetch_soil_type_label(lat: float, lon: float, attempts: int = 3) -> str | None:
    """Hämtar SGU:s jordartsklassning (`jg2_tx`, t.ex. "Sandig morän",
    "Postglacial lera", "Isälvssediment") för en punkt.

    Samma försiktighetsprincip som NMD: ett par omförsök med backoff,
    ger sedan upp till None (→ neutral faktor, se `soil_factor`) istället
    för att låta ett trögt/misslyckat anrop krascha hela prediktionen.
    """
    d = QUERY_HALF_WIDTH_DEG
    params = {
        "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "limit": 1,
        "f": "json",
    }

    for attempt in range(attempts):
        try:
            async with _get_semaphore():
                response = await _get_client().get(BASE_URL, params=params)
                response.raise_for_status()
                features = response.json().get("features") or []
                if not features:
                    return None
                return features[0].get("properties", {}).get("jg2_tx")
        except httpx.HTTPError:
            if attempt == attempts - 1:
                return None
            await asyncio.sleep(0.5 * (attempt + 1))


# Per art: en multiplikator (INTE en egen 0-1-poäng) som nudgar
# NMD-baserade forest_score upp eller ner utifrån jordart — analogt med
# hur wetland_factor redan nudgar forest_score i nmd.py. Medvetet en
# MODERAT multiplikator (0.7-1.3) snarare än en egen regressionsvariabel,
# eftersom jordart inte ingår i kalibreringen (scripts/calibrate_weights.py)
# — en omkalibrering skulle krävas för att ge jordart en egen vikt, se
# README.
#
# Klasserna nedan är verifierade mot verklig data (stickprov över 36
# punkter spridda i Uppland+Södermanland, 2026-08-20): morän-varianter,
# lera-varianter, isälvssediment, urberg, torv och fyllning är de klasser
# som faktiskt förekommer. Preferenserna själva är en dokumenterad
# heuristik grundad i allmän svampekologi (samma sorts placeholder som
# SPECIES_FOREST_PREFERENCES i nmd.py), inte statistiskt skattade.
SPECIES_SOIL_PREFERENCES: dict[str, dict] = {
    "gulkantarell": {
        # Trivs bäst på väldränerad, näringsfattig mark (isälvssediment/
        # rullstensåsar är klassisk tallskogsmark) — ogynnas av
        # vattenhållande lera och torv.
        "isälvssediment": 1.3,
        "sandig morän": 1.15,
        "morän": 1.0,
        "lerig morän": 0.9,
        "urberg": 0.9,
        "postglacial finsand": 1.1,
        "lera": 0.75,
        "torv": 0.7,
        "fyllning": 0.8,
    },
    "trattkantarell": {
        # Fuktighetshållande morän gynnar den fuktiga, mossrika
        # granskog arten trivs i — för väldränerat (isälvssediment)
        # blir det för torrt, ren torv/kärr blir å andra sidan för blött.
        "lerig morän": 1.15,
        "morän": 1.1,
        "sandig morän": 0.95,
        "lera": 1.0,
        "isälvssediment": 0.8,
        "urberg": 0.85,
        "torv": 0.9,
        "fyllning": 0.8,
    },
    "trumpetsvamp_svart": {
        # Kalkgynnad, ädellövassocierad — leråkermark/lerig morän ger
        # ofta den näringsrikare, mer basiska marken ädellövskog trivs
        # på, till skillnad från näringsfattig sand/isälvssediment.
        "lera": 1.2,
        "lerig morän": 1.1,
        "morän": 1.0,
        "isälvssediment": 0.75,
        "sandig morän": 0.8,
        "urberg": 0.8,
        "torv": 0.7,
        "fyllning": 0.85,
    },
    "trumpetsvamp_rod": {
        # Fuktig, kalkrik mark, ofta vid myrkanter (se app/species.py)
        # — starkast preferens för lera/torv-närhet av de fyra.
        "lera": 1.2,
        "lerig morän": 1.15,
        "torv": 1.1,
        "morän": 1.0,
        "sandig morän": 0.85,
        "isälvssediment": 0.75,
        "urberg": 0.8,
        "fyllning": 0.8,
    },
}

# Ingen jordartsklassning tillgänglig (t.ex. utanför kartlagt område,
# eller ett nätverksfel som redan gett upp efter omförsök) — neutral
# faktor, påverkar inte forest_score alls, hellre än att gissa.
NEUTRAL_SOIL_FACTOR = 1.0

# Golv/tak så en enskild jordart aldrig kan dominera över den redan
# etablerade NMD-baserade skogstypspoängen — det här är en NUDGE, inte
# en egen huvudfaktor.
SOIL_FACTOR_MIN = 0.7
SOIL_FACTOR_MAX = 1.3


def soil_factor(label: str | None, species_key: str) -> float:
    """Multiplikator (0.7-1.3) för att nudga forest_score utifrån
    jordart. Längsta matchande klassnamn vinner (samma princip som
    `nmd.land_cover_label_to_forest_score`), så t.ex. "sandig morän"
    inte råkar matchas av den kortare, mer generiska frasen "morän".
    """
    if not label:
        return NEUTRAL_SOIL_FACTOR

    preferences = SPECIES_SOIL_PREFERENCES[species_key]
    text = label.lower()

    for phrase in sorted(preferences, key=len, reverse=True):
        if phrase in text:
            return max(SOIL_FACTOR_MIN, min(SOIL_FACTOR_MAX, preferences[phrase]))

    return NEUTRAL_SOIL_FACTOR


def soil_label_to_phrase(label: str | None) -> str | None:
    """Gör om ett SGU-klassnamn ("Sandig morän") till en kort, gemen
    fras lämplig att infoga i en förklaringsmening.

    "vatten" filtreras bort: jordarten hämtas per grovt rutnät (se
    prediction.py), så en skogscell nära en sjö/kust kan råka dela
    rutnät med en vattenpolygon — en skogscell kan aldrig FAKTISKT ha
    vatten som jordart, verifierat i praktiken 2026-08-20.
    """
    if not label:
        return None
    text = label.strip().lower()
    if not text or text == "vatten":
        return None
    return text
