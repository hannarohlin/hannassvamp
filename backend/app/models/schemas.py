from pydantic import BaseModel, Field


class GridCell(BaseModel):
    lat: float
    lon: float
    is_forest: bool
    weather_score: float = Field(ge=0, le=1)
    forest_score: float = Field(ge=0, le=1)
    history_score: float = Field(ge=0, le=1)
    probability: float = Field(ge=0, le=1)
    explanation: str


class SpeciesPrediction(BaseModel):
    key: str
    name: str
    scientific_name: str
    color: str
    cells: list[GridCell]


class RegionBounds(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class PredictionResponse(BaseModel):
    region: str
    bounds: RegionBounds
    species: list[SpeciesPrediction]
