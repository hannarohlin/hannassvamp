"""Kombinerar väder-, skogs- och historikdata till en fyndsannolikhet per
cell, för var och en av de fyra arterna i `app/species.py`.

Sannolikheten beräknas som en logistisk regression:
  sigmoid(bias + weather_weight*weather + forest_weight*forest + history_weight*history)

Koefficienterna i `CALIBRATED_WEIGHTS` är INTE gissade — de är skattade
per art av `scripts/calibrate_weights.py` mot verkliga fynd (Artportalen)
med pseudo-frånvaro, 2026-08-20 (n=1200 per art: 600 presence / 600
pseudo-absence) i hela `MVP_REGION` (Uppland+Södermanland). Se
skriptets docstring för metod och begränsningar (litet stickprov,
månadsupplöst historiskt väder).

Att history_weight dominerar stort för alla fyra arter är väntat och
rimligt: kända fyndplatser rapporteras om igen av olika personer/år,
vilket är en äkta (inte cirkulär — leave-one-out används vid
skattningen) signal. weather_weight varierar KRAFTIGT mellan
körningar ÄVEN vid dubblat stickprov (300->600 per art) — t.ex. gick
trattkantarells från +1.00 till -0.13 mellan de två senaste
körningarna samma dag, medan träffsäkerheten genomgående steg
(71-77% -> 76-81%). Det bekräftar att instabiliteten är en äkta
svag/obefintlig signal snarare än ett för litet stickprov: månadsväder
inom regionen varierar för lite geografiskt för att skilja ut VAR ett
fynd sker. Tolka alltså inte tecknet eller den exakta storleken på
weather_weight som meningsfullt, bara att den genomgående är MYCKET
mindre än history_weight.

history_score bygger på ett ÅLDERSVIKTAT antal närliggande fynd (se
`app.data_sources.artportalen.build_history_counter` och
`RECENCY_HALF_LIFE_YEARS`), inte ett råtal — Artportalens sökning har
inget datumfilter, så ett fynd från 1819 skulle annars räknas exakt
lika mycket som ett från förra veckan. Kalibreringen i
`CALIBRATED_WEIGHTS` gjordes dock mot RÅA (oviktade) antal — vikterna
är alltså en approximation här, inte en om-kalibrering mot den nya
viktningen, men rimlig eftersom bulken av fynden (>70%) redan är från
de senaste ~15 åren.

weather_score kommer numera från en RULLANDE fuktmodell (se
`app.data_sources.smhi.rolling_weather_score`), inte en enskild dags
prognos — nederbörd de senaste ~3 veckorna ackumuleras med avklingning
istället för att bara titta på senaste dygnet. Samma resonemang som för
historik ovan: kalibreringen (`scripts/calibrate_weights.py`) matchar
fortfarande mot MÅNADSupplöst historiskt väder (det finns ingen
rullande "idag" att räkna bakåt från för ett fynd gjort 2015), så
`weather_weight` är en approximation mot den nya, mer detaljerade
live-modellen — samma kända begränsning som redan gällde för
history_weight ovan, inte en ny.

SLUTSANNOLIKHETEN multipliceras dessutom med en säsongsfaktor (se
app/services/season.py) byggd från samma daterade Artportalen-fynd som
history_score, men använd HELT OBEROENDE: säsongskurvan avgör bara "är
det säsong för arten just nu" (samma faktor för alla celler samma dag),
medan history_score fortfarande avgör "är just DEN HÄR platsen känd
sedan tidigare" per cell. Utan detta skulle kartan visa samma
sannolikhet i december som i september — verifierat mot verklig data
att alla tre arter i praktiken bara fruktar juli-november i den här
regionen (se season.py:s docstring för exakta siffror).

Varje cell får också en kort textförklaring (se app/services/
explanation.py) grundad i samma vägda bidrag som sannolikheten själv —
inte en separat, påhittad motivering. Förklaringens fyndantal ("N
kända fynd inom ~1 km") är dock det RÅA, oviktade antalet — en enkel
sakuppgift som inte ska bero på hur gamla fynden råkar vara.

forest_score kombinerar NMD:s trädslagsklassning med en jordarts-NUDGE
från SGU (se app/data_sources/sgu.py, `soil_factor`): jordart är INTE
en egen regressionsvariabel (skulle kräva en omkalibrering), utan en
måttlig multiplikator (0.7-1.3) på samma sätt som `wetland_factor`
redan nudgar NMD-poängen. Beräknas bara för celler NMD redan klassat
som skog — se `_get_soil_labels` för varför (SGU:s API kan svara med
enskilda polygoner på 700+ KB, t.ex. sjöar, så det vore både onödigt
och dyrt att fråga för vatten/åker/bebyggt som ändå inte visas).

Fyra cachningar för att hålla svarstiden nere (se app/services/cache.py):
  - NMD-marktäcke och SGU-jordart är art-OBEROENDE (samma klassning
    oavsett vilken art man frågar om), men beräknades tidigare om per
    art — dvs. flera identiska nätverksanrop per cell. Hämtas nu EN
    gång per cell/rutnät och cachas på disk (ändras i praktiken inte
    mellan requests, jordart cachas längst av alla — 90 dygn).
  - Artportalens fyndhistorik per art cachas också på disk (kort TTL,
    eftersom nya fynd droppar in under säsongen).
  - Säsongskurvan (se ovan) delar TTL med fyndhistoriken den byggs
    från, så den räknas bara om när fynden ändå hämtas på nytt.
Väder (SMHI) cachas per grovt rutnät (se `_get_weather_details`) men
är i praktiken "live" — PTHBV:s dagliga arkiv uppdateras bara en gång
per dygn, så cachningen kostar ingen verklig färskhet.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Callable

from app.config import MVP_REGION, Region, settings
from app.data_sources import artportalen, nmd, sgu, smhi
from app.models.schemas import GridCell, PredictionResponse, RegionBounds, SpeciesPrediction
from app.services import cache, season
from app.services.explanation import build_explanation
from app.services.grid import generate_grid
from app.services.logistic_regression import predict_probability
from app.species import ALL_SPECIES, Species

# Skattat 2026-08-20 med scripts/calibrate_weights.py, n=1200 per art
# (600 presence / 600 pseudo-absence) i hela MVP_REGION. Höjt från 300
# till 600 per art efter att den förra körningen visade kraftig
# run-till-run-varians (se docstring ovan) — träffsäkerheten steg
# genomgående (71-77% -> 76-81%), men weather_weight fortsatte variera
# i tecken (t.ex. trattkantarell +1.00 -> -0.13) — bekräftar att
# instabiliteten är en äkta svag/obefintlig signal, inte bara ett för
# litet stickprov.
CALIBRATED_WEIGHTS = {
    "gulkantarell": {"weather": 0.2464, "forest": 2.5592, "history": 6.7123, "bias": -3.7394},
    "trattkantarell": {"weather": -0.1252, "forest": 3.0956, "history": 6.9971, "bias": -3.8110},
    "trumpetsvamp_svart": {"weather": 0.2665, "forest": 2.9133, "history": 8.1300, "bias": -4.0233},
    "trumpetsvamp_rod": {"weather": 0.4428, "forest": 3.5106, "history": 6.9279, "bias": -4.5833},
}

NEUTRAL_WEATHER_SCORE = 0.5


def _point_key(lat: float, lon: float) -> str:
    return f"{lat},{lon}"


def _weather_bucket(lat: float, lon: float) -> tuple[float, float]:
    """Avrundar en punkt till ett grovt väder-rutnät (se
    settings.weather_grid_resolution_deg) — flera närliggande
    prediktionsceller delar då samma PTHBV-anrop istället för att var
    och en frågar exakt samma underliggande 4x4km-ruta på nytt."""
    resolution = settings.weather_grid_resolution_deg
    return (round(round(lat / resolution) * resolution, 4), round(round(lon / resolution) * resolution, 4))


async def _get_weather_details(points: list[tuple[float, float]], force_refresh: bool) -> dict[tuple[float, float], dict]:
    """Hämtar väder-score (rullande fuktmodell, se smhi.py) OCH de råa
    mätvärdena bakom den (ackumulerad fukt, temperatur) för punkterna,
    via en ACKUMULERANDE cache per grovt väder-rutnät (samma mönster som
    `_get_land_cover_labels`, se dess docstring för varför).

    Grov upplösning + batchning är inte en optimering här utan en
    nödvändighet: PTHBV:s dagliga API har en hård gräns på 100 punkter
    per anrop och tål dåligt många små anrop i snabb följd (se
    app/data_sources/smhi.py) — att fråga per PREDIKTIONSCELL (ner till
    ~80m) istället för per väder-ruta gjorde en enda detaljförfrågan ta
    över en minut i test.
    """
    buckets_by_point = {point: _weather_bucket(*point) for point in points}
    unique_buckets = set(buckets_by_point.values())

    cached = {} if force_refresh else (cache.get_weather() or {})
    missing = [bucket for bucket in unique_buckets if _point_key(*bucket) not in cached]

    if missing:
        try:
            fetched = await smhi.fetch_recent_daily_weather_batch(missing)
        except Exception:
            # Ett misslyckat SMHI-anrop (efter omförsök i smhi.py) ska
            # inte krascha hela prediktionen — saknade rutor faller
            # tillbaka på ett neutralt värde nedan istället.
            fetched = {}

        for bucket in missing:
            daily = fetched.get(bucket)
            detail = (
                smhi.rolling_weather_score(daily["precipitation_mm"], daily["temperature_c"])
                if daily is not None
                else {"score": NEUTRAL_WEATHER_SCORE, "moisture_mm": None, "avg_temp_c": None}
            )
            cached[_point_key(*bucket)] = detail
        cache.set_weather(cached)

    return {point: cached[_point_key(*bucket)] for point, bucket in buckets_by_point.items()}


async def _get_land_cover_labels(
    points: list[tuple[float, float]], force_refresh: bool
) -> dict[tuple[float, float], str | None]:
    """Hämtar NMD-klassnamn för punkterna, med en ACKUMULERANDE cache.

    Overview-vyn och zoom-detaljvyn frågar olika punktuppsättningar (olika
    upplösning/bbox) — cachen kan alltså inte anta att "cache finns" ===
    "cache innehåller just dessa punkter". Vi slår upp vad som redan
    finns, hämtar ENDAST det som saknas, och sparar tillbaka den
    utökade cachen. Det gör att en ny zoom-detaljyta bara kostar ett
    nätverksanrop per NY punkt, inte per punkt.
    """
    cached = {} if force_refresh else (cache.get_nmd_labels() or {})
    missing = [p for p in points if _point_key(*p) not in cached]

    if missing:
        try:
            fetched = await asyncio.gather(*(nmd.fetch_land_cover_label(lat, lon) for lat, lon in missing))
        except Exception:
            # nmd.fetch_land_cover_label fångar bara httpx.HTTPError internt
            # (med omförsök) — ett oväntat fel av annat slag (t.ex. trasig
            # JSON i ett svar, NMD är redan känt flakigt vid hög samtidighet)
            # ska ändå inte krascha hela prediktionen. Saknade punkter
            # faller tillbaka på "okänt" (None), samma neutrala hantering
            # som ett enskilt NMD-anrop som gett upp efter omförsök redan ger.
            fetched = [None] * len(missing)
        for (lat, lon), label in zip(missing, fetched):
            cached[_point_key(lat, lon)] = label
        cache.set_nmd_labels(cached)

    return {(lat, lon): cached.get(_point_key(lat, lon)) for lat, lon in points}


def _soil_bucket(lat: float, lon: float) -> tuple[float, float]:
    """Avrundar en punkt till ett grovt jordarts-rutnät (se
    settings.soil_grid_resolution_deg) — samma idé som `_weather_bucket`,
    och av samma skäl: SGU:s API kan svara med enskilda polygoner på
    700+ KB (se app/data_sources/sgu.py), så att fråga per fin
    prediktionscell skulle kunna dra hundratals MB per request."""
    resolution = settings.soil_grid_resolution_deg
    return (round(round(lat / resolution) * resolution, 4), round(round(lon / resolution) * resolution, 4))


async def _get_soil_labels(
    points: list[tuple[float, float]],
    labels_by_point: dict[tuple[float, float], str | None],
    force_refresh: bool,
) -> dict[tuple[float, float], str | None]:
    """Hämtar SGU-jordartsklassning per grovt rutnät (ackumulerande
    cache, samma mönster som väder/NMD ovan) — men BARA för punkter som
    NMD redan klassat som skog. Vatten/åker/bebyggt bryr vi oss aldrig
    om jordarten för (`forest_score` beräknas inte där), och att hoppa
    över dem undviker samtidigt de dyraste fallen: en enskild
    vattenpolygon i skärgården kan själv väga 700+ KB (verifierat i
    praktiken) eftersom sjöar/hav ofta är näst intill de STÖRSTA
    polygonerna i datasetet.
    """
    forest_points = [p for p in points if nmd.is_forest_label(labels_by_point.get(p))]
    buckets_by_point = {point: _soil_bucket(*point) for point in forest_points}
    unique_buckets = set(buckets_by_point.values())

    cached = {} if force_refresh else (cache.get_soil_labels() or {})
    missing = [bucket for bucket in unique_buckets if _point_key(*bucket) not in cached]

    if missing:
        try:
            fetched = await asyncio.gather(*(sgu.fetch_soil_type_label(lat, lon) for lat, lon in missing))
        except Exception:
            # Samma resonemang som i _get_land_cover_labels ovan:
            # sgu.fetch_soil_type_label fångar bara httpx.HTTPError internt,
            # inte t.ex. ett oväntat JSON-fel — ska inte krascha hela
            # prediktionen. Saknade rutor faller tillbaka på "okänt" (None),
            # vilket soil_factor redan behandlar som en neutral faktor.
            fetched = [None] * len(missing)
        for bucket, label in zip(missing, fetched):
            cached[_point_key(*bucket)] = label
        cache.set_soil_labels(cached)

    return {point: cached.get(_point_key(*bucket)) for point, bucket in buckets_by_point.items()}


async def _get_observations_and_season_curve(species: Species, force_refresh: bool) -> tuple[list[dict], list[float]]:
    """Hämtar (och cachar) en arts DATERADE fynd inom HELA `MVP_REGION`,
    plus säsongskurvan (se app/services/season.py) byggd från samma fynd.

    Fynden hämtas medvetet oberoende av vilken (eventuellt mycket
    mindre) grid-region som just nu predikteras — annars skulle den
    första zoom-detaljförfrågan råka cacha ett för litet urval av fynd
    under samma nyckel som overview-vyn använder, och efterföljande
    historik-sökningar (som kollar avstånd mot HELA fyndlistan) skulle
    missa fynd strax utanför den lilla bboxen.

    Datumet behövs för BÅDE åldersviktningen i `artportalen.build_
    history_counter` OCH säsongskurvan — Artportalens sökning har inget
    datumfilter, så utan det skulle ett fynd från 1819 räknas lika
    mycket som ett från förra veckan, och kartan skulle visa samma
    sannolikhet i december som i september.
    """
    cached = None if force_refresh else cache.get_observations(species.key)
    if cached is not None:
        curve = cache.get_season_curve(species.key)
        if curve is None:
            # Säsongskurve-cachen saknas trots att fynd-cachen finns
            # (t.ex. en cache från innan säsongsfunktionen fanns) —
            # bygg om den från de redan cachade fynden, ingen ny
            # Artportalen-förfrågan behövs.
            curve = season.build_season_curve([obs["date"] for obs in cached])
            cache.set_season_curve(species.key, curve)
        return cached, curve

    observations = await artportalen.fetch_dated_observations_in_bbox(
        species.taxon_id, MVP_REGION.min_lat, MVP_REGION.max_lat, MVP_REGION.min_lon, MVP_REGION.max_lon
    )
    cache.set_observations(species.key, observations)

    curve = season.build_season_curve([obs["date"] for obs in observations])
    cache.set_season_curve(species.key, curve)
    return observations, curve


def _score_point(
    lat: float,
    lon: float,
    weather_detail: dict,
    land_cover_label: str | None,
    soil_label: str | None,
    species: Species,
    history_counter: Callable[[float, float], tuple[int, float]],
    season_score: float,
) -> GridCell:
    weather_score = weather_detail["score"]
    # Jordart NUDGAR (multiplicerar) NMD-baserad forest_score istället
    # för att vara en egen regressionsvariabel — se motivering i
    # app/data_sources/sgu.py. Clampas till [0,1] för att hålla sig
    # inom GridCell-schemat, samma spann som forest_score redan hade.
    base_forest_score = nmd.land_cover_label_to_forest_score(land_cover_label, species.key)
    forest_score = min(1.0, base_forest_score * sgu.soil_factor(soil_label, species.key))
    nearby_observation_count, weighted_history_count = history_counter(lat, lon)
    history_score = artportalen.observation_count_to_score(weighted_history_count)

    weights = CALIBRATED_WEIGHTS[species.key]
    base_probability = predict_probability(
        [weights["weather"], weights["forest"], weights["history"]],
        weights["bias"],
        [weather_score, forest_score, history_score],
    )
    # Säsongsfaktorn multipliceras in EFTER regressionen (se
    # motivering i modulens docstring) — den är samma för alla celler
    # samma dag, inte en egen regressionsvariabel.
    probability = base_probability * season_score

    explanation = build_explanation(
        species.key,
        weights,
        weather_score,
        forest_score,
        history_score,
        land_cover_label,
        soil_label,
        weather_detail["moisture_mm"],
        weather_detail["avg_temp_c"],
        nearby_observation_count,
        season_score,
    )

    return GridCell(
        lat=lat,
        lon=lon,
        is_forest=nmd.is_forest_label(land_cover_label),
        weather_score=weather_score,
        forest_score=forest_score,
        history_score=history_score,
        probability=round(probability, 3),
        explanation=explanation,
    )


async def _predict_species(
    species: Species,
    points: list[tuple[float, float]],
    weather_by_point: dict[tuple[float, float], dict],
    labels_by_point: dict[tuple[float, float], str | None],
    soil_by_point: dict[tuple[float, float], str | None],
    force_refresh: bool,
    today: date | None = None,
) -> SpeciesPrediction:
    observations, season_curve = await _get_observations_and_season_curve(species, force_refresh)
    history_counter = artportalen.build_history_counter(observations)
    season_score = season.score_for_date(season_curve, today or date.today())

    cells = [
        _score_point(
            lat,
            lon,
            weather_by_point[(lat, lon)],
            labels_by_point[(lat, lon)],
            soil_by_point.get((lat, lon)),
            species,
            history_counter,
            season_score,
        )
        for lat, lon in points
    ]
    return SpeciesPrediction(
        key=species.key,
        name=species.name,
        scientific_name=species.scientific_name,
        color=species.color,
        cells=cells,
    )


async def predict_region(
    region: Region, resolution_deg: float | None = None, force_refresh: bool = False
) -> PredictionResponse:
    points = generate_grid(region, resolution_deg or settings.grid_resolution_deg)

    # Jordart hämtas bara för skogsceller (se _get_soil_labels), så den
    # måste vänta in NMD-klassningen — väder är helt oberoende och körs
    # samtidigt.
    labels_by_point = await _get_land_cover_labels(points, force_refresh)
    weather_task = _get_weather_details(points, force_refresh)
    soil_task = _get_soil_labels(points, labels_by_point, force_refresh)
    weather_by_point, soil_by_point = await asyncio.gather(weather_task, soil_task)

    species_predictions = await asyncio.gather(
        *(
            _predict_species(species, points, weather_by_point, labels_by_point, soil_by_point, force_refresh)
            for species in ALL_SPECIES
        )
    )
    bounds = RegionBounds(
        min_lat=region.min_lat, max_lat=region.max_lat, min_lon=region.min_lon, max_lon=region.max_lon
    )
    return PredictionResponse(region=region.name, bounds=bounds, species=list(species_predictions))
