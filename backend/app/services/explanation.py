"""Bygger en kort, människoläsbar förklaring till varför en cell fick sin
sannolikhet — inte en påhittad motivering, utan grundad i de faktiska
poängen och deras VIKTADE bidrag (poäng × kalibrerad vikt) till den
logistiska regressionen i `app/services/prediction.py`.

Eftersom historik-vikten dominerar stort för alla tre arter (se
prediction.py) kommer förklaringen oftast lyfta fram historiska fynd och
skogstyp — väder bidrar sällan mest, vilket stämmer med att
weather_weight är litet/svagt negativt i kalibreringen. Det är alltså
en ärlig avspegling av modellen, inte en genväg.

Säsong (se app/services/season.py) är INTE en regressionsvariabel och
ingår därför inte i den vägda rankningen — men när den påtagligt sänker
sannolikheten (utanför/i utkanten av artens säsong) är det viktigare
information än väder/skogstyp/historik-rankningen fångar, så den läggs
alltid till separat istället för att tävla om de 1-2 rankade platserna.
"""

from __future__ import annotations

from app.data_sources import sgu

# Under den här nivån bedöms säsongen påverka sannolikheten nog mycket
# för att alltid nämnas, oavsett vad väder/skogstyp/historik rankar som
# viktigast — annars kan en cell visa "90%, pga skogstyp" mitt i
# december utan att nämna att 90% i sig redan är kraftigt nedjusterat.
SEASON_MENTION_THRESHOLD = 0.5

# Artens huvudsäsong i klartext, härledd från samma fynddata som
# säsongskurvan (se season.py:s docstring) — inte gissad.
SPECIES_SEASON_DESCRIPTIONS = {
    "gulkantarell": "juli–oktober (topp i september)",
    "trattkantarell": "augusti–november (topp i september–oktober)",
    "trumpetsvamp_svart": "augusti–oktober (topp i september)",
    "trumpetsvamp_rod": "augusti–november (topp i september–oktober)",
}


def _forest_type_phrase(land_cover_label: str | None, soil_label: str | None) -> str | None:
    """Gör om ett NMD-klassnamn ("113 Barrblandskog på fastmark") till en
    kort, gemen fras ("barrblandskog") lämplig att infoga i en mening,
    med SGU:s jordart ("sandig morän") tillagd inom parentes när den
    finns — samma "skogstyp"-faktor i rankningen nedan, eftersom
    jordart nudgar forest_score istället för att vara en egen faktor
    (se app/data_sources/sgu.py).

    Jordarten hämtas per GROVT rutnät (~5km, se prediction.py), så en
    enskild skogscell nära en sjö/kust kan råka dela rutnät med en
    vattenpolygon — verifierat i praktiken (2026-08-20). "vatten" filtreras
    därför bort här: en skogscell kan aldrig FAKTISKT ha vatten som
    jordart, och att visa det ("skogstyp: lövskog, vatten") vore bara
    motsägelsefullt, inte informativt.
    """
    if not land_cover_label:
        return None

    text = land_cover_label.strip()
    parts = text.split(" ", 1)
    if parts[0].isdigit() and len(parts) > 1:
        text = parts[1]

    for suffix in (" på fastmark", " på våtmark"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]

    forest_type = text.strip().lower()
    if not forest_type:
        return None

    soil_type = sgu.soil_label_to_phrase(soil_label)
    return f"{forest_type}, {soil_type}" if soil_type else forest_type


def _weather_phrase(moisture_mm: float | None, avg_temp_c: float | None) -> str | None:
    if moisture_mm is None or avg_temp_c is None:
        return None

    # Tröskelvärden i linje med rolling_moisture_to_score i smhi.py
    # (15mm ackumulerad fukt är där poängen börjar bli gynnsam).
    moist = moisture_mm >= 15
    mild = 10 <= avg_temp_c <= 20

    if moist and mild:
        return "fuktig mark efter regn de senaste veckorna och mild temperatur"
    if moist:
        return "fuktig mark efter regn de senaste veckorna"
    if mild:
        return "mild temperatur"
    return "torr mark och/eller ogynnsam temperatur just nu"


def _history_phrase(nearby_observation_count: int) -> str | None:
    if nearby_observation_count <= 0:
        return None
    if nearby_observation_count == 1:
        return "1 känt fynd inom ~1 km"
    return f"{nearby_observation_count} kända fynd inom ~1 km"


def _season_phrase(species_key: str, season_score: float) -> str | None:
    if season_score >= SEASON_MENTION_THRESHOLD:
        return None
    season_description = SPECIES_SEASON_DESCRIPTIONS.get(species_key)
    if not season_description:
        return None
    return f"utanför högsäsong (normalt {season_description})"


def build_explanation(
    species_key: str,
    weights: dict,
    weather_score: float,
    forest_score: float,
    history_score: float,
    land_cover_label: str | None,
    soil_label: str | None,
    moisture_mm: float | None,
    avg_temp_c: float | None,
    nearby_observation_count: int,
    season_score: float,
) -> str:
    """Rankar vilka faktorer som faktiskt bidrog mest (poäng × vikt) och
    bygger en kort mening av de 1–2 viktigaste, med konkreta detaljer när
    de finns (antal fynd, trädslag, väderläge) istället för bara
    faktornamnet. Säsong läggs till separat (se modulens docstring) när
    den drar ner sannolikheten påtagligt."""

    contributions = {
        "history": weights["history"] * history_score,
        "forest": weights["forest"] * forest_score,
        "weather": weights["weather"] * weather_score,
    }
    ranked = sorted(contributions, key=contributions.get, reverse=True)

    def phrase_for(factor: str) -> str | None:
        if factor == "history":
            return _history_phrase(nearby_observation_count)
        if factor == "forest":
            forest_type = _forest_type_phrase(land_cover_label, soil_label)
            return f"skogstyp ({forest_type})" if forest_type else None
        return _weather_phrase(moisture_mm, avg_temp_c)

    parts: list[str] = []
    for factor in ranked:
        if len(parts) >= 2:
            break
        phrase = phrase_for(factor)
        if phrase:
            parts.append(phrase)

    sentence = (
        "Baseras på en sammanvägning av väder, skogstyp och historiska fynd."
        if not parts
        else "Baseras främst på " + " och ".join(parts) + "."
    )

    season_phrase = _season_phrase(species_key, season_score)
    if season_phrase:
        sentence += f" Just nu {season_phrase}."

    return sentence
