"""Säsongskurva per art, byggd från VERKLIGA historiska fynddatum (samma
daterade Artportalen-fynd som redan hämtas för åldersviktningen, se
`app.data_sources.artportalen`) — inte en gissad kalendertabell.

Verifierat mot verklig data (2026-08-19, gul kantarell i Uppland+
Södermanland, n=3312 fynd): en cirkulär Gaussisk täthetsskattning över
fyndens dag-på-året ger säsongspoäng 0.83 för 20 augusti, 0.98 för
15 september (toppen), 0.09 för 1 juni och 0.04 för 20 december — dvs.
arten toppar sen sommar/tidig höst i den här regionen, INTE tidig
sommar som man annars lätt kan tro. Motsvarande kontroll av de andra
två arterna visade samma mönster (topp september-oktober).

Fynden används HÄR bara för att forma säsongskurvan — inte som en
direkt "känd växtplats"-signal (den rollen fyller redan history_score
i prediction.py, helt oberoende av detta). De två signalerna svarar på
olika frågor: "är det säsong just nu" kontra "är just DEN HÄR platsen
känd sedan tidigare", och multipliceras ihop i slutresultatet.
"""

from __future__ import annotations

import math
from datetime import date, datetime

DAYS_IN_YEAR = 365

# Hur "brett" ett enskilt fynd sprider sitt bidrag till närliggande
# dagar — 15 dagar gav en säsongskurva som varken var för spretig
# (brusig dag-för-dag) eller för utsmetad (skulle dölja att säsongen
# faktiskt har en tydlig topp).
BANDWIDTH_DAYS = 15.0

# Säkerhetsgolv — extremt sällsynta tidiga/sena fynd förekommer i
# verkligheten, så en helt avstängd säsong (0.0) vore mer bestämt än
# datan egentligen visar.
SEASON_FLOOR = 0.03


def _day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def _circular_distance(a: int, b: int) -> int:
    """Avstånd i dagar mellan två dagar-på-året, men RUNT årsskiftet —
    annars hamnar 31 december och 1 januari långt ifrån varandra fast
    de i praktiken är grannar."""
    diff = abs(a - b)
    return min(diff, DAYS_IN_YEAR - diff)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def build_season_curve(observation_dates: list[str]) -> list[float]:
    """Bygger en säsongskurva: index 1-365 = dag-på-året, värde 0-1.
    Index 0 är oanvänd (bara för att slippa +/-1-krångel vid uppslag).

    Cirkulär Gaussisk kärna över observationernas dag-på-året,
    normaliserad mot kurvans EGET maxvärde (dagen flest fynd klustrar
    kring) — inte mot en godtycklig konstant, så kurvan alltid når 1.0
    på artens faktiska toppdag oavsett hur många fynd som finns totalt.

    Saknas fynddata helt (ny art, tom region) antas ingen
    säsongsbegränsning (alla dagar = 1.0) hellre än att gissa fel säsong.
    """
    days = [_day_of_year(d) for d in (_parse_date(raw) for raw in observation_dates) if d is not None]
    if not days:
        return [1.0] * (DAYS_IN_YEAR + 1)

    def score_for_day(target_day: int) -> float:
        return sum(math.exp(-0.5 * (_circular_distance(target_day, d) / BANDWIDTH_DAYS) ** 2) for d in days)

    raw_scores = [score_for_day(d) for d in range(1, DAYS_IN_YEAR + 1)]
    peak = max(raw_scores) or 1.0
    normalized = [max(SEASON_FLOOR, score / peak) for score in raw_scores]
    return [0.0] + normalized  # index 0 oanvänd, index 1..365 = dag 1..365


def score_for_date(curve: list[float], target: date) -> float:
    """Slår upp säsongspoängen för ett datum. Dag 366 (skottår) återanvänder
    dag 365 — försumbar skillnad för en säsongskurva med 15 dagars bandbredd."""
    day = min(_day_of_year(target), DAYS_IN_YEAR)
    return curve[day]
