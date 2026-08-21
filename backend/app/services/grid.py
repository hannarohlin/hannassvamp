import math

from app.config import Region

# Skydd mot flyttalsrepresentationsfel nära en heltalsgräns (t.ex. att
# 22.5/... råkar representeras som 22.499999999997 eller
# 22.500000000004) — utan epsilon kan `int(...)`/`floor(...)` tippa åt
# fel håll och ge en annan cellräkning/rutplacering än avsett. Långt
# mindre än någon genuin bråkdel (0.5 vid udda/jämn bbox-bredd), så en
# RIKTIG icke-heltalskvot avrundas fortfarande nedåt/uppåt som väntat.
_EPSILON = 1e-9


def _steps_along_axis(span_deg: float, resolution_deg: float) -> int:
    """Antal rutpunkter längs en axel (bredd `span_deg`, steg `resolution_deg`),
    inklusive både start- och slutkant. Delad mellan `generate_grid` och
    `clamp_resolution_for_max_cells` — de MÅSTE räkna likadant, annars kan
    den faktiska griden bli större än det antal `clamp_resolution_for_max_cells`
    redan godkänt mot `detail_max_cells` (verifierat i praktiken: en
    tidigare avrundningsskillnad gav 747 celler mot en godkänd gräns på 496).
    """
    return int(span_deg / resolution_deg + _EPSILON) + 1


def _snap_down(value: float, resolution_deg: float) -> float:
    """Rundar `value` nedåt till närmaste multipel av `resolution_deg`,
    räknat från en global nollpunkt — INTE regionens egen min-koordinat.

    Det här är vad som gör att två överlappande men inte identiska
    bounding boxar (t.ex. zoomar ut och sedan in igen till ungefär
    samma plats, där kartans exakta synliga hörn skiljer sig någon
    pixel från förra gången) genererar EXAKT samma absoluta rutpunkter
    för den överlappande ytan. Utan detta ankras rutnätet i varje
    enskild förfrågans egna hörn, så nästan ingen punkt återanvänds
    mellan zoom/pan-steg — NMD/SGU/väder-cachen (som nycklas på exakt
    lat/lon, se app/services/cache.py) missar då nästan alltid, även
    för mark man redan tittat på, vilket gör upprepad zoomning märkbart
    segt (verifierat i praktiken).
    """
    return math.floor(value / resolution_deg + _EPSILON) * resolution_deg


def _axis_points(min_val: float, max_val: float, resolution_deg: float) -> list[float]:
    start = _snap_down(min_val, resolution_deg)
    n = _steps_along_axis(max_val - start, resolution_deg)
    return [round(start + i * resolution_deg, 4) for i in range(n)]


def _axis_count(min_val: float, max_val: float, resolution_deg: float) -> int:
    start = _snap_down(min_val, resolution_deg)
    return _steps_along_axis(max_val - start, resolution_deg)


def generate_grid(region: Region, resolution_deg: float) -> list[tuple[float, float]]:
    """Genererar (lat, lon)-punkter i ett rutnät över regionens bounding box.

    Rutnätet är snäppt till en global rutlinje (se `_snap_down`), inte
    ankrat i regionens egna min-hörn — annars skulle två olika men
    överlappande bounding boxar (typiskt: zoomar ut och in igen)
    generera helt olika punkter för samma mark och aldrig träffa
    cachen. Konsekvens: griden kan sträcka sig upp till en rutstorlek
    utanför regionens exakta min-kant (avsiktligt, harmlöst — celler
    utanför skog filtreras redan bort på annat håll).

    Indexbaserad (inte `lat += resolution_deg` i en loop) för att undvika
    flyttalsdrift — annars kan den sista raden/kolumnen tappas tyst när
    ackumulerade avrundningsfel gör att den slutliga koordinaten hamnar
    en nanometerbråkdel över `max_lat`/`max_lon` (verifierat i praktiken:
    17.0 + 375×0.0008 blir 17.300000000000633, inte 17.3).
    """
    lats = _axis_points(region.min_lat, region.max_lat, resolution_deg)
    lons = _axis_points(region.min_lon, region.max_lon, resolution_deg)
    return [(lat, lon) for lat in lats for lon in lons]


def clamp_resolution_for_max_cells(region: Region, resolution_deg: float, max_cells: int) -> float:
    """Gör upplösningen grövre stegvis tills antal celler ryms inom `max_cells`.

    Används för zoom-detaljvyn: en klient kan be om en godtyckligt liten
    bbox med en godtyckligt fin upplösning, men vi vill aldrig svälla
    till fler NMD/SMHI-anrop än vi vet att API:erna klarar (se
    app/data_sources/nmd.py). Grovare upplösning är en säkrare
    fallback än att avvisa requesten.

    Räknar celler med SAMMA snäppta rutlogik som `generate_grid` (se
    `_axis_count`/`_snap_down`) — annars kan den faktiska griden bli
    större än vad den här funktionen trodde den godkände.
    """
    resolution_deg = max(resolution_deg, 1e-6)
    while resolution_deg < 5:
        n_lat = _axis_count(region.min_lat, region.max_lat, resolution_deg)
        n_lon = _axis_count(region.min_lon, region.max_lon, resolution_deg)
        if n_lat * n_lon <= max_cells:
            return resolution_deg
        resolution_deg *= 1.25
    return resolution_deg
