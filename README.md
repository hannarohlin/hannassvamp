# Kantarellkartan

Webbapp som visar sannolikhet för fynd av fyra svampar på en karta över
Sverige — **gul kantarell**, **trattkantarell**, **svart trumpetsvamp**
och **rödgul trumpetsvamp** (se `app/species.py`) — baserat på:

- **SMHI** — väderdata (nederbörd, temperatur) som proxy för markfukt/tillväxtförhållanden (samma för alla fyra arter)
- **Naturvårdsverkets Nationella Marktäckedata (NMD)** — trädslagsklassning (barrskog/barrblandskog/lövskog m.m.) som proxy för habitat, **artspecifik** eftersom de fyra trivs olika bra i olika skogstyper
- **SGU** — jordart (morän/lera/isälvssediment m.m.), nudgar NMD:s skogstypspoäng — se "Jordart" nedan
- **Artportalen** — historiska fynd, per art (olika Dyntaxa-id)

**Svart trumpetsvamp** (Craterellus cornucopioides) och **rödgul
trumpetsvamp** (Craterellus lutescens) är två skilda arter, inte en
färgvariant av samma art — därför två separata rader att filtrera på,
med olika habitatpreferenser (se `app/data_sources/nmd.py`) och olika
Dyntaxa-id (3772 respektive 3215, båda verifierade mot Artportalen).

MVP omfattar **Uppland och Södermanland** (fastlandsfokuserad bbox, se
`MVP_REGION` i `app/config.py` — trimmad från de fulla administrativa
länsgränserna för Stockholm/Uppsala/Södermanland för att hålla
rutstorleken oförändrad, se "Prestanda och robusthet"). Varje cell och
art får ett tal 0–1 från en logistisk regression som kalibrerats mot
verkliga fynd (se "Kalibrering" nedan), men bara celler som NMD klassar
som skog (`is_forest`) visas — annars ser kartan ut som ett rutnät
slängt över åkrar/sjöar/städer istället för att följa skogens faktiska
form.

**Visas som ett index (0–100), inte en sannolikhet i procent.** Vårt
kalibreringsunderlag (en region, ett begränsat antal fynd) saknar den
statistiska styrkan för att kalla talet en validerad sannolikhet — att
påstå "72% chans" vore att ge ett falskt precisionssken. Samma ärliga
ramverk som liknande tjänster (t.ex. "Svampindex") använder: kartan
visar hur goda FÖRUTSÄTTNINGARNA är, för att jämföra områden — inte ett
löfte om fynd. Se frontend (`.cell-row-index-value`/`.cell-row-index-
unit` i `frontend/src/map.js`) och `frontend/index.html`:s
infomodal/disclaimer för hur detta kommuniceras till användaren.

Talet byggs av tre delar:
- **Väder** — en RULLANDE fuktmodell (inte en enskild dags mätvärde),
  se "Väder: rullande fuktmodell" nedan.
- **Skogstyp** — NMD:s trädslagsklassning, artspecifik (se ovan).
- **Historik** — Artportalens fynd, åldersviktade (se
  `app.data_sources.artportalen.RECENCY_HALF_LIFE_YEARS`).
- **Säsong** — en multiplikativ faktor byggd från fyndens faktiska
  datum, se "Säsong" nedan. Håller isär "är det säsong just nu" (samma
  för alla celler samma dag) från "är just DEN HÄR platsen känd sedan
  tidigare" (historik, per cell).

### Rendering: sannolikhetsytor + dominant-artnål (ersatte konturpolygoner)

Kartans visuella språk kommer från en färdig designbrief
(`frontend/designbrief-svampkarta.md`, från en separat designgenomgång)
och skiljer sig helt från det tidigare MarchingSquaresJS-baserade
kontursystemet:

- **Sannolikhetsytor** (`renderBlobs` i `frontend/src/map.js`) ritas som
  blurrade `L.circle`-ytor i en egen Leaflet-pane (`heat`, CSS
  `filter: blur(16px)` på HELA panen — en enda GPU-komposition, mycket
  billigare än att blurra varje cirkel för sig).

  **Varje art bedöms OBEROENDE mot sin egen sannolikhetsfördelning**
  bland de synliga skogscellerna (`speciesBand`) — INTE en "dominant art
  vinner, övriga tonas ner"-modell, vilket var den första versionen.
  Den första versionen gick sönder på två sätt, båda verifierade mot
  verklig data (Björkhagen/Nacka-området, där alla tre arter har
  snarlika fördelningar, median 0.73-0.76): (1) en fast 45%-tröskel
  klarades av 100% av skogscellerna i ett bra område, så kartan färgades
  helt; (2) "dominant vinner" gjorde att en art som låg bara någon
  hundradel bakom en annan blev osynlig — stängde man av den vinnande
  arten dök den tidigare osynliga plötsligt upp överallt, fastän den
  varit påslagen (och nästan lika bra) hela tiden. Lösningen: en
  relativ percentil av ARTENS EGEN fördelning (topp 45% för att synas
  alls, topp 8% för maximal mättnad) avgör opacitet/radie helt oberoende
  av andra arter — flera arter kan nu synas blandat i ett område om de
  faktiskt är ungefär lika bra där.
- **Nålar** visar bara EN ikon per cell — den dominanta arten (högst
  sannolikhet bland de påslagna), inte en ikon per art. Till skillnad
  från ytorna används fortfarande "dominant vinner" här, eftersom en nål
  bara har plats för EN ikon — det är just det problemet (att en hel
  YTA bara visar en vinnare) som löstes ovan, inte konceptet i sig.
  Nålen (`buildMushroomPinIcon`) är ett `L.divIcon` med tre delar
  (fotocirkel, stjälk, punkt) där `iconAnchor` pekar på punkten, inte
  fotots mitt — annars är det oklart exakt vilken plats en nål gäller.
- **Utglesning vid zoom** (`declutterCandidates`) är den mekanism som
  faktiskt håller nere antalet nålar: ett girigt kollisionstest i
  SKÄRMKOORDINATER (`map.latLngToContainerPoint`, ~150px × en
  zoom-beroende skala — höjt från ett första värde på 58px som visade
  sig knappt större än nålens egen diameter och därför inte gallrade
  bort nästan något). En zoom-beroende PERCENTIL (inte fast värde, av
  samma skäl som ovan) filtrerar bort de svagaste kandidaterna innan
  kollisionstestet, men det är kollisionstestet — inte percentilen — som
  förhindrar en tät klunga i en riktigt bra, stor skog. Ritas om på BÅDE
  `zoomend` (direkt, ingen ny datahämtning) och den debouncade `moveend`
  (hämtar ny data för den nya ytan/upplösningen).
- **Filterpanelens artchips** styr `activeSpeciesKeys`. Eftersom
  sannolikhetsytorna nu är helt oberoende per art påverkar av/på för en
  art bara DEN artens egna ytor — de andra arternas utseende ändras
  inte alls (till skillnad från den första "dominant vinner"-versionen).
  Nålarnas "dominant art"-jämförelse görs fortfarande bara bland de
  påslagna arterna, så en cell där den avstängda arten var starkast
  faller tillbaka på nästa bästa påslagna art istället för att försvinna.
- **Klick på en nål** öppnar en sidopanel (352px, höger) med en rad per
  aktiv art (ikon, namn, procent, färgad stapel, samma `explanation`-text
  som beräknas av backend) — ersätter den tidigare Leaflet-popupen. Bara
  nålar är klickbara nu, till skillnad från tidigare då hela cellen hade
  en osynlig klick-yta — en avsiktlig konsekvens av att gå över till
  pin+sidopanel-modellen.

Utzoomat visas översiktens glesa grid (~9km mellanrum i
Uppland+Södermanland-skala); zoomar man in tillräckligt (nivå 10+)
hämtas istället automatiskt en tätare grid för just den synliga ytan —
se "Zoom-detaljvy" nedan. Till skillnad från de gamla kontur-lagren
behövs ingen separat bokföring av översikts- kontra detaljlager: det
just nu aktuella cellsetet (`currentCombinedCells`) byts bara ut helt
och ritas om, eftersom blob+nål-renderingen är billig att bygga om från
scratch varje gång.

## Struktur

```
svamp/
├── backend/            FastAPI-app som beräknar och exponerar sannolikheter
│   └── app/
│       ├── api/         HTTP-routes
│       ├── data_sources/  klienter mot SMHI / NMD (Naturvårdsverket) / Artportalen
│       ├── models/      Pydantic-scheman
│       ├── services/    grid-generering + prediction-logik
│       └── species.py   register över de fyra arterna (namn, färg, taxon-id)
└── frontend/           Statisk Leaflet-karta (ingen build-steg), fyra färglager + växlare
    └── images/          artikoner, en fil per art: `<art-nyckel>.png` (t.ex. `gulkantarell.png`)
```

## Köra backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fyll i API-nycklar när du har dem
uvicorn app.main:app --reload
```

Backend startar på `http://localhost:8000`. Testa:
`curl http://localhost:8000/api/predictions | jq`

## Köra frontend

Ingen build behövs — servas som statiska filer:

```bash
cd frontend
python -m http.server 5500
```

Öppna `http://localhost:5500`.

## Status för datakällor

| Källa | Status | Anteckning |
|---|---|---|
| SMHI | ✅ Riktig integration (öppet API, ingen nyckel) | `app/data_sources/smhi.py` — PTHBV:s dagliga arkiv, en RULLANDE fuktmodell (se "Väder: rullande fuktmodell" nedan), inte en enskild dags prognos. Hämtas per GROVT väder-rutnät (inte per rutcell och inte per art). Retry+backoff, faller tillbaka till neutralt värde (0.5) om SMHI ändå strular |
| NMD (Naturvårdsverket) | ✅ Riktig integration (öppet API, ingen nyckel) | `app/data_sources/nmd.py` — WMS GetFeatureInfo mot Nationella Marktäckedata, ger riktig trädslagsklass per punkt (t.ex. "113 Barrblandskog på fastmark"), omvandlad till en **artspecifik** poäng (se `SPECIES_FOREST_PREFERENCES`). Ersatte den ursprungliga Skogsstyrelsen-planen: deras riktiga trädslagsraster (`SkogligaGrunddata_3_1`) svarar 401 trots att det kallas "Publikt". Tjänsten är något flaky vid hög samtidighet (~760 anrop per grid, en gång per cell oavsett art) — begränsad med en semafor (40 samtidiga) + delad HTTP-klient + retry/neutral fallback |
| Artportalen | ✅ Riktig integration (kräver API-nyckel) | `app/data_sources/artportalen.py` — via SLU Artdatabankens SOS-API ("Species Observations – multiple data resources"), parametriserad per art (taxon-id i `app/species.py`). Hämtar ALLA fynd av arten i regionen i en paginerad batch och räknar träffar per rutcell lokalt, eftersom API:et 429:ar hårt vid >100 samtidiga anrop |
| SGU | ✅ Riktig integration (öppet API/CC0, ingen nyckel) | `app/data_sources/sgu.py` — OGC API - Features mot jordartskartan 1:25 000-1:100 000 (`grundlager`-kollektionen), ger jordart per punkt (t.ex. "Sandig morän", "Postglacial lera"). NUDGAR (multiplicerar 0.7-1.3) NMD:s forest_score istället för att vara en egen regressionsvariabel — se "Jordart" nedan för prestandalärdomen som gjorde detta nödvändigt |

**Arter** (`app/species.py`): Gul kantarell (*Cantharellus cibarius*, Dyntaxa 3213), Trattkantarell (*Craterellus tubaeformis*, 3217), Svart trumpetsvamp (*Craterellus cornucopioides*, 3772), Rödgul trumpetsvamp (*Craterellus lutescens*, 3215). De skiljer sig i skogspreferens: gulkantarell gynnas av barrblandskog/lövinslag och straffas på våtmark, trattkantarell gynnas av fuktig granskog och tål våtmark bättre, svart trumpetsvamp gynnas av ädellövskog (bok/ek/hassel) och trivs dåligt i ren barrskog, rödgul trumpetsvamp gynnas av fuktig, kalkrik barrskog (myrkanter/mossa) och tål våtmark bäst av alla fyra.

## Förklaring per cell (`app/services/explanation.py`)

Varje `GridCell` har ett `explanation`-fält — en kort mening om VARFÖR
just den cellen fick sin sannolikhet, t.ex. *"Baseras främst på 13 kända
fynd inom ~1 km och skogstyp (granskog)."* Genereras genom att ranka de
tre faktorernas VÄGDA bidrag (`kalibrerad_vikt × score`, samma vikter som
`CALIBRATED_WEIGHTS` i `prediction.py`) och plocka fram konkreta detaljer
för de 1–2 viktigaste: faktiskt antal närliggande fynd (inte bara ett
abstrakt score), NMD:s trädslagsklass i läsbar form, eller
nederbörd/temperatur. En faktor utan konkret detalj att visa (t.ex.
historik med 0 fynd) hoppas över till förmån för nästa — annars hade
"historiska fynd" kunnat visas trots att det inte fanns några, eftersom
`observation_count_to_score` har ett golv på 0.3 även vid 0 fynd. Att
väder sällan nämns är en ärlig avspegling av att `weather_weight` är
litet/svagt negativt i kalibreringen, inte en bugg.

Sidopanelen i `frontend/src/map.js` (`openCellPanel`, `.cell-row-explanation`)
visar förklaringen under varje arts indexvärde. Säsong (se "Säsong"
nedan) är INTE en regressionsvariabel och ingår därför inte i denna
vägda rankning, men läggs alltid till separat som en egen mening när
den sänker indexet påtagligt (`SEASON_MENTION_THRESHOLD` i
explanation.py) — annars hade en cell kunnat visa "80, pga skogstyp"
mitt i december utan att nämna att 80 redan är kraftigt nedjusterat av
säsongen.

## Kalibrering

Sannolikheten i `app/services/prediction.py` är per art en logistisk
regression — `sigmoid(bias + w_weather·weather + w_forest·forest + w_history·history)`
— vars koefficienter är skattade av `scripts/calibrate_weights.py` (körs
en gång per art), inte gissade. Metod: hämta verkliga fynd av arten
(presence), slumpa fram lika många pseudo-frånvaropunkter (samma bbox
och månadsfördelning, men inte nära ett känt fynd), räkna ut samma tre
features för alla punkter (historiskt PTHBV-väder för fyndets faktiska
år/månad — inte dagens prognos — samt artspecifik NMD-trädslagspoäng och
antal närliggande ANDRA fynd av samma art med leave-one-out), och träna
en enkel logistisk regression (ren Python, inga externa ML-beroenden).

Senaste körning (2026-08-20, n=1200 per art: 600 presence / 600
pseudo-absence, hela `MVP_REGION` — Uppland+Södermanland):

| Art | n presence (av totalt) | weather | forest | history | bias | träffsäkerhet |
|---|---|---|---|---|---|---|
| Gul kantarell | 600 (av 3263) | 0.2464 | 2.5592 | 6.7123 | -3.7394 | 75.6% |
| Trattkantarell | 600 (av 2386) | -0.1252 | 3.0956 | 6.9971 | -3.8110 | 77.7% |
| Svart trumpetsvamp | 600 (av 1040) | 0.2665 | 2.9133 | 8.1300 | -4.0233 | 77.8% |
| Rödgul trumpetsvamp | 600 (av 2154) | 0.4428 | 3.5106 | 6.9279 | -4.5833 | 80.8% |

**Höjt från SAMPLE_SIZE 300 till 600 (2026-08-20)** eftersom föregående
körning visade kraftig run-till-run-varians. Effekt: träffsäkerheten
steg genomgående (71-77% → 76-81%), en tydlig, mätbar förbättring. MEN
`weather_weight` fortsatte variera i BÅDE tecken och storlek mellan de
två körningarna (t.ex. trattkantarell +1.00 → -0.13, gulkantarell
-0.08 → +0.25) — dubblat stickprov löste alltså INTE
weather-instabiliteten, vilket bekräftar att den beror på en äkta
svag/obefintlig signal (månadsväder varierar för lite geografiskt
inom regionen för att skilja ut VAR ett fynd sker), inte bara på ett
för litet stickprov. `history_weight` dominerar fortsatt stort för
alla fyra, som väntat — kända fyndplatser rapporteras om av olika
personer/år, en äkta signal eftersom leave-one-out förhindrar att en
punkt "hittar sig själv". Tolka alltså inte tecknet eller den exakta
storleken på `weather_weight` som meningsfullt, bara att den
genomgående är MYCKET mindre än `history_weight`.

**Kvarstående kända begränsningar:** månadsupplöst väder istället för
dygnsvärden, pseudo-frånvaro istället för verifierad frånvaro (vanlig
begränsning med presence-only artdata), och kvarvarande
run-till-run-varians eftersom SOS-API:et inte garanterar stabil
sorteringsordning mellan anrop (samma slump-seed ger ändå olika
subsample om den underliggande listans ordning skiftar) — ett stickprov
på 600 minskade men eliminerade inte detta.

**weather_score i live-prediktionen** (`app.data_sources.smhi.
rolling_weather_score`, se "Väder: rullande fuktmodell" nedan) är en
RULLANDE fuktmodell, men kalibreringen ovan matchar fortfarande mot
MÅNADSupplöst historiskt PTHBV-väder (det finns ingen rullande "idag"
att räkna bakåt från för ett fynd gjort 2015) — samma typ av
proxy-mismatch som redan gäller för `history_score`/åldersviktningen,
inte en ny sorts brist.

**PTHBV-lucka upptäckt och fixad vid den ursprungliga körningen:**
enstaka punkter/månader saknar värde (`null`) i PTHBV:s arkiv (samma
typ av lucka som i det dagliga arkivet, se "Väder: rullande
fuktmodell") — `smhi.extract_month` kraschade tidigare på detta
(`TypeError` vid jämförelse mot `None`). Fixat genom att behandla en
`null`-månad som "data saknas" (samma neutrala fallback som en helt
saknad månad), istället för att låta felet propagera och avbryta hela
kalibreringen.

**Saknad retry upptäckt och fixad vid 600-körningen:**
`fetch_historical_monthly` skapade tidigare en NY `httpx.AsyncClient`
per anrop och saknade retry/backoff helt — ett enda `httpx.ReadError`
(SMHI-anrop är i praktiken något flakiga, samma erfarenhet som med
NMD/dagliga PTHBV-arkivet) kunde krascha hela körningen efter flera
minuters arbete, utan att kunna återhämta sig. Fixat genom att dela
klient/semafor med den rullande dagliga modellen (samma SMHI-domän) —
ger både connection pooling och samma retry-mönster som resten av
modulen redan hade.

## Väder: rullande fuktmodell (`app/data_sources/smhi.py`)

Ersatte en tidigare modell som bara såg ETT dygns nederbörd/temperatur
(SMHI:s `snow1g`-prognos) — den kunde inte skilja på "regnade igår" och
"torrt i tre veckor", vilket i praktiken gav orimligt höga index under
långa torrperioder. Verifierat (2026-08-20): Stockholmsområdet hade en
tydlig torrperiod hela augusti som den gamla modellen helt missade.

Ny modell: `rolling_moisture_mm` ackumulerar nederbörd över de senaste
`ROLLING_WINDOW_DAYS` (21) dagarna med daglig avklingning
(`_daily_decay_factor`, snabbare i varmt väder pga avdunstning) —
källan är PTHBV:s DAGLIGA arkiv (inte en prognos, utan SMHI:s griddade
4x4km-analys av faktiskt uppmätt/interpolerat väder, ~1 dags eftersläpning).
Temperaturdelen använder istället bara de senaste
`RECENT_TEMPERATURE_WINDOW_DAYS` (5) dagarnas snitt, eftersom
fruktkroppsbildningen svarar på AKTUELL temperatur medan fukten är det
som ska vara "minnesfullt".

**Viktig prestandalärdom, verifierad i praktiken:** PTHBV:s dagliga API
har en hård gräns på 100 punkter per anrop (fler ger ett 400-fel) OCH
tål påfallande dåligt många SMÅ anrop i snabb följd oavsett egen
samtidighetsgräns — 77 SAMTIDIGA en-punkts-anrop tog 62 SEKUNDER, mot
~3,5s för ETT batchat 100-punkters-anrop. En första implementation som
frågade per prediktionscell (`fetch_recent_daily_weather`) gjorde en
enda zoom-detaljförfrågan ta över en minut, ibland med krasch när enskilda
PTHBV-punkter (t.ex. i skärgården) saknade värde (`null`) för vissa
dagar. Löst i två steg:
1. **Batchning** (`fetch_recent_daily_weather_batch` i smhi.py): upp
   till 100 punkter per PTHBV-anrop, matchat mot svarets egna
   `north`/`east`-fält (inte positionell ordning).
2. **Grovt väder-rutnät** (`_weather_bucket`/`_get_weather_details` i
   prediction.py, `settings.weather_grid_resolution_deg = 0.05`, ~4-
   5,5km — nära PTHBV:s egen 4x4km-upplösning): flera närliggande
   prediktionsceller delar samma väderanrop, med en ackumulerande
   disk-cache (samma mönster som NMD, se nedan). Det är inte bara en
   optimering — PTHBV:s egen upplösning gör att en finare fråga ändå
   bara skulle returnera samma underliggande värde om och om igen.

Resultat efter fixen (verifierat): en tidigare 54,8s zoom-detaljförfrågan
tog 2,1s med varm väder-cache. En kall översiktsförfrågan (hela
regionen, ~800 väder-rutor) tar ~30-35s — inom den redan existerande
"kan ta upp till någon minut"-förväntan i startskärmen.

## Jordart (`app/data_sources/sgu.py`)

Kompletterar NMD:s trädslagsklassning med markens geologiska ursprung
(morän/lera/isälvssediment/urberg/torv m.m.) från SGU:s öppna
jordartskarta 1:25 000-1:100 000 (OGC API - Features, CC0, ingen
nyckel). Spelar roll för t.ex. kalkkrävande arter (rödgul
trumpetsvamp) och för hur väl marken håller kvar fukt oberoende av
trädslag.

**Ny prestandalärdom, verifierad i praktiken (2026-08-20):** en
enskild punktförfrågan kan ge en FÖRVÅNANSVÄRT stor respons — API:et
skickar alltid med hela polygonens gränslinje, och en enda stor
polygon (en sjö, ett stort moränfält) kan väga över 700 KB, även när
vi bara vill ha en kort textattributsträng. Testade `skipGeometry`/
`properties`-parametrarna (OGC API - Features-tillägg för att trimma
svaret) men den här instansen stödjer inte dem. Att fråga per fin
prediktionscell hade alltså kunnat dra hundratals MB per request.
Löst med samma tvådelade strategi som för väder:
1. **Grovt jordarts-rutnät** (`_soil_bucket`/`_get_soil_labels` i
   prediction.py, `settings.soil_grid_resolution_deg = 0.05`, ~5km):
   ackumulerande disk-cache, samma mönster som NMD/väder.
2. **Bara skogsceller frågas** — vatten/åker/bebyggt påverkar ändå
   aldrig `forest_score`, och det är just DE cellerna (särskilt sjöar)
   som ger de dyraste polygonsvaren. Kräver att NMD-klassningen är klar
   INNAN jordart hämtas (till skillnad från väder, som är helt
   oberoende och körs samtidigt).

**Jordart NUDGAR forest_score, är INTE en egen regressionsvariabel**
(`sgu.soil_factor`, 0.7-1.3, samma princip som `wetland_factor` i
nmd.py) — en omkalibrering hade krävts för att ge jordart en egen
vikt i `CALIBRATED_WEIGHTS`, vilket inte gjordes den här omgången.
Artpreferenserna (`SPECIES_SOIL_PREFERENCES`) är en dokumenterad
heuristik grundad i allmän svampekologi, verifierad mot de jordarts-
klasser som FAKTISKT förekommer i regionen (stickprov över 36 punkter:
morän-varianter, lera-varianter, isälvssediment, urberg, torv,
fyllning) — inte statistiskt skattade.

**Bugg hittad och fixad vid integrationen:** en jordarts-hink (~5km)
kan råka delas mellan en skogscell och en näraliggande sjö, så SGU kan
svara "Vatten" för en cell NMD redan klassat som skog — verifierat i
praktiken. `sgu.soil_label_to_phrase` filtrerar bort "vatten"
(`soil_factor` påverkas inte, ingen preferensklass matchar det ordet),
annars hade förklaringstexten kunnat säga det motsägelsefulla
"skogstyp (lövskog, vatten)".

## Säsong (`app/services/season.py`)

Utan detta skulle kartan visa samma index i december som i september.
Byggd från SAMMA daterade Artportalen-fynd som redan hämtas för
åldersviktningen (`_get_observations_and_season_curve` i
prediction.py) — en cirkulär Gaussisk täthetsskattning
(`build_season_curve`, bandbredd 15 dagar) över fyndens dag-på-året,
normaliserad mot kurvans EGET maxvärde. Cachas med samma TTL som
fynden den byggs från (se `cache.get_season_curve`/`set_season_curve`).

Verifierat mot verklig data (2026-08-19, n=3312 för gul kantarell i
Uppland+Södermanland): säsongspoäng 0.83 för 20 augusti, 0.98 för 15
september (toppen), 0.09 för 1 juni och 0.04 för 20 december — arten
toppar alltså sen sommar/tidig höst i den här regionen, INTE tidig
sommar som man annars lätt kan tro. Övriga tre arter visade samma
mönster (topp september-oktober, verifierat även för rödgul
trumpetsvamp: 48,4% av 2184 fynd i september, 24,5% i oktober — se
`SPECIES_SEASON_DESCRIPTIONS` i explanation.py för exakta procenttal
per art/månad).

**Multipliceras in EFTER regressionen**, inte som en fjärde
regressionsvariabel — säsongen är samma faktor för alla celler samma
dag, medan `history_score` fortfarande är den signal som avgör "är just
DEN HÄR platsen känd sedan tidigare" per cell. De två signalerna svarar
medvetet på olika frågor och hålls isär.

## Prestanda och robusthet

Med 4 arter × ~760 rutceller (grid_resolution_deg=0.08 över
Uppland+Södermanland, se `app/config.py`) finns det gott om externa
anrop per request. NMD:s WMS-tjänst är i praktiken något flaky vid hög
samtidighet, så:

- Anrop till NMD och SMHI återanvänder en delad `httpx.AsyncClient`
  (connection pooling) istället för en ny klient per anrop.
- NMD-anrop begränsas av en semafor (40 samtidiga) — högre värden (100)
  gav 500-fel i tester.
- Enskilda NMD/SMHI-anrop som misslyckas får 2 omförsök med backoff
  innan de faller tillbaka till ett neutralt score, istället för att
  krascha hela requesten.
- Väder hämtas EN gång per rutcell (inte per art) eftersom det inte är
  artspecifikt.

### Cache (`app/services/cache.py`)

NMD-marktäcke, SGU-jordart, Artportalen-historik och väder ändras
knappt mellan sidladdningar (väder: PTHBV:s dagliga arkiv uppdateras
bara en gång per dygn, se ovan), så alla fyra cachas i en JSON-fil
(`backend/.cache/`) istället för att räknas om vid varje request.

- **NMD** (art-oberoende klassnamn per punkt): cachas i 30 dagar,
  ACKUMULERANDE — varje request hämtar bara de punkter som saknas i
  cachen (viktigt för zoom-detaljvyn nedan, som frågar helt andra
  punkter än översiktsgriden) och sparar tillbaka den utökade cachen.
- **SGU** (jordart per grovt rutnät, se "Jordart"): cachas i 90 dagar
  (geologi ändras aldrig i praktiken), ACKUMULERANDE på samma sätt.
- **Artportalen** (fynd per art): cachas i 1 dygn, alltid mot HELA
  `MVP_REGION` oavsett vilken (eventuellt mycket mindre) yta som
  predikteras — annars skulle historik-sökningen i en zoom-detaljvy
  missa fynd som ligger precis utanför den lilla bboxen.
- **Säsongskurvor** (en per art): delar TTL med fynden de byggs från.
- **Väder** (per grovt rutnät, se "Väder: rullande fuktmodell"): cachas
  i 12 timmar, ACKUMULERANDE på samma sätt som NMD — nödvändigt (inte
  bara en optimering), se den sektionen för varför.
- `GET /api/predictions?refresh=true` kringgår all cache och hämtar fräscht.

Effekt i tester (Uppland+Södermanland, ~760 celler/art, 2026-08-20 efter
väder-cachningen ovan): ~35,8s vid helt kall cache (NMD + Artportalen +
väder) mot **~0,2s vid varm cache**. En zoom-detaljförfrågan som innan
väder-cachningen tog 54,8s (per-cell PTHBV-anrop, se "Väder: rullande
fuktmodell") tar nu ~2,1s med varm väder-cache — normalfallet, eftersom
översiktens första kalla laddning redan fyllt väder-cachen för hela
regionen.

**Efter jordarts-integrationen** (samma dag) steg den helt kalla
översiktstiden till ~63s (jordart hämtas EFTER NMD-klassningen, för
alla nya skogsrutor, med enstaka stora polygonsvar — se "Jordart"),
fortfarande inom laddningsskärmens "kan ta upp till någon minut"-
förväntan, men med mindre marginal än innan. Jordartens 90-dagars-TTL
gör detta till en sällan-kostnad snarare än något som händer varje
kall cache.

### Zoom-detaljvy (varför cirklarna inte bara är en gles översiktsgrid)

Översiktsgriden (0.08°, ~5-9km mellan punkter) räcker för att peka ut
"ungefär vilket skogsområde", men inte för "var i just DEN skogen" —
NMD har 10m upplösning i sig, vi frågade den bara väldigt glest över en
stor yta. `GET /api/predictions?min_lat=...&max_lat=...&min_lon=...&max_lon=...`
(alla fyra krävs) hämtar istället en mycket tätare grid
(`settings.detail_resolution_deg`, default ~400-450m) för just den
angivna ytan — upplösningen grovas automatiskt upp
(`clamp_resolution_for_max_cells`) om bboxen är så stor att den skulle
ge fler än `settings.detail_max_cells` (500) celler, som skydd mot
NMD/SMHI:s faktiska genomströmning.

Frontend (`frontend/src/map.js`) hämtar automatiskt en detaljvy för den
synliga ytan när man zoomar in förbi `DETAIL_ZOOM_THRESHOLD` (nivå 10),
debouncat 500ms efter att man slutat panorera/zooma (`moveend`), med en
liten diskret laddningsindikator (`#detail-loading`) — inte den stora
helskärms-spinnern, eftersom detaljvyn kompletterar översikten snarare
än att blockera den. Ett monotont request-id skyddar mot race conditions
om man zoomar/panorerar vidare innan ett svar hunnit komma tillbaka.

**Upplösningen skalar med zoomnivå (`resolutionForZoom` i `map.js`)** —
tidigare begärdes samma FASTA upplösning (`detail_resolution_deg`,
~400m) oavsett exakt zoomnivå så fort man var förbi tröskeln, så att
zooma djupare bara visade en mindre bit av samma grid istället för att
faktiskt bli mer exakt. Nu halveras den begärda upplösningen för varje
zoomsteg ovanför tröskeln (samma princip som kartplattornas egen zoom:
dubbel zoom = dubbel pixeltäthet), ner till säkerhetsgolvet
`detail_min_resolution_deg` (~80-90m). Det ger två saker på samma
gång: en mjukare övergång vid tröskeln (~1.6km-rutor precis vid nivå
10 istället för att hoppa direkt till ~400m) OCH genuint finare
markeringar ju mer man zoomar in, istället för att fastna på samma
upplösning från och med tröskeln.

**Känd incident (löst):** i tidiga tester hängde backend helt (100% CPU
i flera minuter, även `/health` slutade svara) efter att en användare
zoomat/panorerat några gånger i rad. Grundorsaken var att frontend inte
hindrade flera överlappande, tunga detaljanrop från att köras samtidigt
mot backend — varje zoom/pan-steg startade ett NYTT anrop utan att
vänta in eller avbryta det föregående. Fixat med två skydd:
  1. Frontend (`detailFetchInFlight`/`detailUpdateQueued` i `map.js`)
     kör aldrig mer än ett detaljanrop åt gången — nya triggers under
     tiden kö:as till EN uppdatering (med då aktuell yta) efter att det
     pågående anropet svarat.
  2. Backend fick en samtidighetsgräns för SMHI (samma mönster som NMD
     redan hade) och `detail_max_cells` sänktes 1200→500, som
     värsta-fall-skydd även om frontend-skyddet skulle brista.
Verifierat genom att medvetet skicka 4 överlappande tunga anrop
samtidigt mot backend efter fixen — alla fyra slutförde (55–78s,
långsamt men stabilt), CPU gick tillbaka till ~0% direkt efteråt.

## Nästa steg

1. Fortsätta snygga till frontend-vyn (cirkelmarkörer, zoom och den
   större regionen är klart — nästa: t.ex. färgskala/legend-polish,
   mobilanpassning).
2. Utöka till hela Sverige — cache-lagret gör det mer görbart, men
   NMD-genomströmningen sätter fortfarande en gräns för hur fint grid
   som är rimligt på en så stor yta.
3. Ombkalibrera mot `MVP_REGION` (se "Kända begränsningar" i
   Kalibrering-avsnittet) — nuvarande vikter är skattade mot den mindre
   Södermanland-bboxen.
4. Eventuellt komplettera NMD med Skogsstyrelsens riktiga volym-/åldersdata
   (`SkogligaGrunddata_3_1`) om ni skaffar ett Geodatasamverkan-avtal.
5. Köra om kalibreringen med fler punkter och/eller separera "när" (säsong)
   från "var" (plats) istället för att blanda ihop dem i samma modell.
