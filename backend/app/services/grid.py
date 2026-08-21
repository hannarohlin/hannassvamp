from app.config import Region

# Skydd mot flyttalsrepresentationsfel nära en heltalsgräns (t.ex. att
# 22.5/... råkar representeras som 22.499999999997 eller
# 22.500000000004) — utan epsilon kan `int(...)` tippa åt fel håll och
# ge en annan cellräkning än den faktiska grid-genereringen nedan.
# Långt mindre än någon genuin bråkdel (0.5 vid udda/jämn bbox-bredd),
# så en RIKTIG icke-heltalskvot avrundas fortfarande nedåt som väntat.
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


def generate_grid(region: Region, resolution_deg: float) -> list[tuple[float, float]]:
    """Genererar (lat, lon)-punkter i ett rutnät över regionens bounding box.

    Indexbaserad (inte `lat += resolution_deg` i en loop) för att undvika
    flyttalsdrift — annars kan den sista raden/kolumnen tappas tyst när
    ackumulerade avrundningsfel gör att den slutliga koordinaten hamnar
    en nanometerbråkdel över `max_lat`/`max_lon` (verifierat i praktiken:
    17.0 + 375×0.0008 blir 17.300000000000633, inte 17.3).
    """
    n_lat = _steps_along_axis(region.max_lat - region.min_lat, resolution_deg)
    n_lon = _steps_along_axis(region.max_lon - region.min_lon, resolution_deg)
    return [
        (round(region.min_lat + i * resolution_deg, 4), round(region.min_lon + j * resolution_deg, 4))
        for i in range(n_lat)
        for j in range(n_lon)
    ]


def clamp_resolution_for_max_cells(region: Region, resolution_deg: float, max_cells: int) -> float:
    """Gör upplösningen grövre stegvis tills antal celler ryms inom `max_cells`.

    Används för zoom-detaljvyn: en klient kan be om en godtyckligt liten
    bbox med en godtyckligt fin upplösning, men vi vill aldrig svälla
    till fler NMD/SMHI-anrop än vi vet att API:erna klarar (se
    app/data_sources/nmd.py). Grovare upplösning är en säkrare
    fallback än att avvisa requesten.
    """
    resolution_deg = max(resolution_deg, 1e-6)
    while resolution_deg < 5:
        n_lat = _steps_along_axis(region.max_lat - region.min_lat, resolution_deg)
        n_lon = _steps_along_axis(region.max_lon - region.min_lon, resolution_deg)
        if n_lat * n_lon <= max_cells:
            return resolution_deg
        resolution_deg *= 1.25
    return resolution_deg
