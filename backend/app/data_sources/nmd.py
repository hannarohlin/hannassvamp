"""Klient mot Naturvårdsverkets Nationella Marktäckedata (NMD).

Ersätter den tidigare Skogsstyrelsen-baserade nyckelbiotop-proxyn.
Skogsstyrelsens riktiga trädslagsraster (`SkogligaGrunddata_3_1`) kräver
ett Geodatasamverkan-avtal (svarar 401 trots att det kallas "Publikt"),
men Naturvårdsverket publicerar en likvärdig, riktig trädslagsklassning
helt öppet via en WMS-tjänst — ingen nyckel krävs.

Tjänst: https://geodata.naturvardsverket.se/inspire/lc-nmd/wms
Lager: LC.LandCoverRaster.Bas_2.0 (NMD2023 basskikt, v2.0)

Vi frågar med GetFeatureInfo för en enskild punkt (NMD har 10m upplösning)
och får ett självbeskrivande klassnamn tillbaka, t.ex.
"112 Granskog på fastmark" eller "113 Barrblandskog på fastmark".
Verifierat mot riktiga punkter i Södermanland — se README för exempel.

Klasserna som faktiskt observerats i Södermanland (icke uttömmande):
  111 Tallskog, 112 Granskog, 113 Barrblandskog, 114 Lövblandad barrskog,
  115/117 Triviallövskog (med/utan ädellövinslag), 116 Ädellövskog,
  118 Temporärt ej skog, samt våtmarksvarianter (12x) och öppen mark/
  åker/väg/vatten/bebyggt för icke-skog.

De tre svamparna trivs olika bra i olika skogstyper (se
`SPECIES_FOREST_PREFERENCES`), så poängen räknas per art istället för
med en gemensam tabell.
"""

from __future__ import annotations

import asyncio

import httpx

# Begränsar hur många samtidiga NMD-anrop som görs. Med 3 arter × 510
# rutceller blir det annars ~1530 samtidiga anrop, vilket gav ReadTimeout
# i tester — dels av för hög samtidighet, dels av att en NY TCP/TLS-
# anslutning öppnades för varje enskilt anrop istället för att
# återanvändas. Semafor + delad klient skapas lazy (inte vid modul-
# import) för att undvika att binda till fel event loop innan uvicorn
# startat sin.
_semaphore: asyncio.Semaphore | None = None
_client: httpx.AsyncClient | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(40)
    return _semaphore


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=30, limits=httpx.Limits(max_connections=40, max_keepalive_connections=40)
        )
    return _client

WMS_URL = "https://geodata.naturvardsverket.se/inspire/lc-nmd/wms"
LAYER = "LC.LandCoverRaster.Bas_2.0"

# Halva bredden (grader) på förfrågningsrutan runt punkten. NMD har 10m
# upplösning, så en liten ruta räcker för att träffa rätt pixel.
QUERY_HALF_WIDTH_DEG = 0.0005

# Per art: bas-poäng (0–1) för varje NMD-klass (matchas som substräng mot
# klassnamnet, längsta match vinner så att t.ex. "triviallövskog med
# ädellövinslag" inte råkar matcha på bara "triviallövskog"), samt en
# faktor som våtmarksvarianter av samma klass multipliceras med.
SPECIES_FOREST_PREFERENCES: dict[str, dict] = {
    "gulkantarell": {
        "classes": {
            "barrblandskog": 0.9,
            "lövblandad barrskog": 0.9,
            "tallskog": 0.8,
            "granskog": 0.8,
            "triviallövskog med ädellövinslag": 0.55,
            "triviallövskog": 0.5,
            "ädellövskog": 0.4,
            "temporärt ej skog": 0.3,
        },
        "default": 0.1,
        "wetland_factor": 0.7,
    },
    "trattkantarell": {
        # Trivs bäst i fuktig, mossrik granskog/barrblandskog — tål
        # våtmark klart bättre än gulkantarell.
        "classes": {
            "granskog": 0.9,
            "barrblandskog": 0.85,
            "lövblandad barrskog": 0.75,
            "tallskog": 0.55,
            "triviallövskog med ädellövinslag": 0.45,
            "triviallövskog": 0.4,
            "ädellövskog": 0.35,
            "temporärt ej skog": 0.25,
        },
        "default": 0.1,
        "wetland_factor": 0.95,
    },
    "trumpetsvamp_svart": {
        # Associerad med ädellövträd (bok/ek/hassel) — trivs dåligt i
        # ren barrskog, till skillnad från de andra tre.
        "classes": {
            "ädellövskog": 0.9,
            "triviallövskog med ädellövinslag": 0.85,
            "triviallövskog": 0.6,
            "lövblandad barrskog": 0.5,
            "granskog": 0.3,
            "barrblandskog": 0.3,
            "tallskog": 0.25,
            "temporärt ej skog": 0.2,
        },
        "default": 0.1,
        "wetland_factor": 0.8,
    },
    "trumpetsvamp_rod": {
        # Craterellus lutescens: fuktig, kalkrik mark — ofta vid
        # myrkanter och i mossa i barrskog (dyntaxa.se/artfakta.se) —
        # snarlik trattkantarell men ännu mer barrskogsbunden och tål
        # våtmark minst lika bra.
        "classes": {
            "granskog": 0.85,
            "barrblandskog": 0.85,
            "tallskog": 0.7,
            "lövblandad barrskog": 0.6,
            "triviallövskog med ädellövinslag": 0.35,
            "triviallövskog": 0.3,
            "ädellövskog": 0.25,
            "temporärt ej skog": 0.2,
        },
        "default": 0.1,
        "wetland_factor": 1.0,
    },
}

# Poäng när NMD inte gav något klassnamn alls (t.ex. nätverksfel längre
# upp har redan hanterats — det här är bara "ingen feature hittad").
MISSING_LABEL_SCORE = 0.4

# De faktiska NMD-skogsklasserna (samma nycklar används av alla tre
# arter ovan, bara med olika poäng) — används för att avgöra om en punkt
# är skog ÖVERHUVUDTAGET, oberoende av art. Frontend använder detta för
# att inte rita ut något alls på åkermark/vatten/bebyggt/öppen mark,
# istället för att visa en missvisande låg-men-inte-noll-poäng där.
FOREST_CLASSES = tuple(SPECIES_FOREST_PREFERENCES["gulkantarell"]["classes"])


def is_forest_label(label: str | None) -> bool:
    """True om NMD-klassnamnet är en skogsklass (oavsett art eller fastmark/våtmark)."""
    if not label:
        return False
    text = label.lower()
    return any(keyword in text for keyword in FOREST_CLASSES)


async def fetch_land_cover_label(lat: float, lon: float, attempts: int = 3) -> str | None:
    """Hämtar NMD:s klassnamn (t.ex. "112 Granskog på fastmark") för en punkt.

    NMD:s WMS-tjänst är i praktiken lite flaky under hög samtidig
    belastning (enstaka ReadTimeout även vid samma samtidighet som
    annars fungerar). Ett enda trögt anrop ska inte få krascha hela
    prediktionen för alla celler — därför försöker vi ett par gånger med
    backoff och ger upp till neutralt (None -> MISSING_LABEL_SCORE)
    istället för att låta felet propagera.
    """
    d = QUERY_HALF_WIDTH_DEG
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": LAYER,
        "query_layers": LAYER,
        "styles": "",
        "crs": "CRS:84",
        "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
        "width": "3",
        "height": "3",
        "i": "1",
        "j": "1",
        "info_format": "application/json",
    }

    for attempt in range(attempts):
        try:
            async with _get_semaphore():
                response = await _get_client().get(WMS_URL, params=params)
                response.raise_for_status()
                features = response.json().get("features") or []
                if not features:
                    return None
                return features[0].get("properties", {}).get("Label_Värde_kod")
        except httpx.HTTPError:
            if attempt == attempts - 1:
                return None
            await asyncio.sleep(0.5 * (attempt + 1))


def land_cover_label_to_forest_score(label: str | None, species_key: str) -> float:
    """Normaliserar ett NMD-klassnamn till en poäng 0–1 för en given art.

    Placeholder-heuristik baserad på varje arts kända habitat-preferens
    (se modul-docstring och `SPECIES_FOREST_PREFERENCES`). Längsta
    matchande klassnamn vinner, så mer specifika klasser (t.ex.
    "triviallövskog med ädellövinslag") inte råkar matchas av en kortare
    generisk fras (t.ex. "triviallövskog").
    """
    if not label:
        return MISSING_LABEL_SCORE

    preferences = SPECIES_FOREST_PREFERENCES[species_key]
    text = label.lower()
    is_wetland = "våtmark" in text

    matched_score = None
    for phrase in sorted(preferences["classes"], key=len, reverse=True):
        if phrase in text:
            matched_score = preferences["classes"][phrase]
            break

    base = matched_score if matched_score is not None else preferences["default"]
    if is_wetland:
        base *= preferences["wetland_factor"]

    return round(base, 3)


async def fetch_forest_score(lat: float, lon: float, species_key: str) -> float:
    label = await fetch_land_cover_label(lat, lon)
    return land_cover_label_to_forest_score(label, species_key)
