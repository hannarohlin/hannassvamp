"""Registret över svampar kartan visar sannolikhet för.

En art definieras av sitt Dyntaxa-id (för Artportalen-sökningar) och en
uppsättning NMD-marktäckepreferenser (se `app/data_sources/nmd.py`) som
fångar att de fyra trivs olika bra i olika skogstyper:

- Gul kantarell: barrblandskog/barrskog med lövinslag, torrare-medium mark.
- Trattkantarell: fuktig granskog/barrblandskog, tål våtmark bättre.
- Svart trumpetsvamp: lövskog/ädellövskog (bok/ek/hassel), trivs dåligt i ren barrskog.
- Rödgul trumpetsvamp: fuktig, kalkrik barrskog — ofta vid myrkanter och i
  mossa (Craterellus lutescens, taxon 3215, verifierat mot Artportalen
  2026-08-20: 2184 fynd i regionen) — en annan art än svart trumpetsvamp,
  inte bara en färgvariant, därför en egen rad i filterpanelen.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Species:
    key: str
    name: str
    scientific_name: str
    color: str
    taxon_id: int


GULKANTARELL = Species(
    key="gulkantarell",
    name="Gul kantarell",
    scientific_name="Cantharellus cibarius",
    color="#D99A16",
    taxon_id=3213,
)

TRATTKANTARELL = Species(
    key="trattkantarell",
    name="Trattkantarell",
    scientific_name="Craterellus tubaeformis",
    # Blå (inte grön) för att inte kunna förväxlas med OpenStreetMap-
    # kartans egna gröna markeringar (skog, naturreservat/nationalparker).
    color="#4E7A9E",
    taxon_id=3217,
)

TRUMPETSVAMP_SVART = Species(
    key="trumpetsvamp_svart",
    name="Svart trumpetsvamp",
    scientific_name="Craterellus cornucopioides",
    # Plommonlila — grafitgrått läste som "avstängt" i designgenomgången.
    color="#8A4A6B",
    taxon_id=3772,
)

TRUMPETSVAMP_ROD = Species(
    key="trumpetsvamp_rod",
    name="Rödgul trumpetsvamp",
    scientific_name="Craterellus lutescens",
    # Tegelröd — skild från både gult (gulkantarell) och lila (svart
    # trumpetsvamp), matchar även artens rödbruna hatt.
    color="#B5432F",
    taxon_id=3215,
)

ALL_SPECIES = [GULKANTARELL, TRATTKANTARELL, TRUMPETSVAMP_SVART, TRUMPETSVAMP_ROD]

BY_KEY = {species.key: species for species in ALL_SPECIES}
