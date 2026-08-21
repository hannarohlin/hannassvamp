from typing import Optional

from fastapi import APIRouter

from app.config import MVP_REGION, Region, settings
from app.models.schemas import PredictionResponse
from app.services.grid import clamp_resolution_for_max_cells
from app.services.prediction import predict_region

router = APIRouter(prefix="/api", tags=["predictions"])


@router.get("/predictions", response_model=PredictionResponse)
async def get_predictions(
    refresh: bool = False,
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
    resolution: Optional[float] = None,
) -> PredictionResponse:
    """Sannolikhet per rutcell och art (gulkantarell/trattkantarell/svart trumpetsvamp/rödgul trumpetsvamp).

    Utan bbox-parametrar: översiktsvyn över hela MVP-regionen (Uppland +
    Södermanland) i den grova standardupplösningen.

    Med `min_lat`/`max_lat`/`min_lon`/`max_lon` (alla fyra krävs):
    zoom-detaljvyn — en mycket tätare grid (se `resolution`, default
    `settings.detail_resolution_deg`) för just den angivna ytan, tänkt
    för när frontend zoomar in på ett specifikt skogsområde. Upplösningen
    grovas automatiskt upp om bboxen är så stor att den tätare
    upplösningen skulle ge fler än `settings.detail_max_cells` celler —
    det är en säkerhetsspärr mot NMD/SMHI-anropens faktiska
    genomströmning (se app/data_sources/nmd.py), inte ett fel.

    NMD-trädslag och Artportalen-historik cachas på disk (se
    app/services/cache.py) — sätt `?refresh=true` för att tvinga fräscha
    anrop mot källorna istället för att läsa från cachen.
    """
    has_bbox = None not in (min_lat, max_lat, min_lon, max_lon)

    if not has_bbox:
        return await predict_region(MVP_REGION, force_refresh=refresh)

    region = Region(name="Vald yta", min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
    resolution_deg = clamp_resolution_for_max_cells(
        region,
        max(resolution or settings.detail_resolution_deg, settings.detail_min_resolution_deg),
        settings.detail_max_cells,
    )
    return await predict_region(region, resolution_deg=resolution_deg, force_refresh=refresh)
