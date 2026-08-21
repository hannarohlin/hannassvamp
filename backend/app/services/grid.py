from app.config import Region


def generate_grid(region: Region, resolution_deg: float) -> list[tuple[float, float]]:
    """Genererar (lat, lon)-punkter i ett rutnät över regionens bounding box."""
    points: list[tuple[float, float]] = []
    lat = region.min_lat
    while lat <= region.max_lat:
        lon = region.min_lon
        while lon <= region.max_lon:
            points.append((round(lat, 4), round(lon, 4)))
            lon += resolution_deg
        lat += resolution_deg
    return points


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
        n_lat = int((region.max_lat - region.min_lat) / resolution_deg) + 1
        n_lon = int((region.max_lon - region.min_lon) / resolution_deg) + 1
        if n_lat * n_lon <= max_cells:
            return resolution_deg
        resolution_deg *= 1.25
    return resolution_deg
