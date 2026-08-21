const map = L.map("map", {
  center: [59.4, 17.5], // Ungefärligt mittpunkt för Uppland+Södermanland tills riktiga bounds laddats
  zoom: 8,
  minZoom: 6,
  maxZoom: 18,
  zoomControl: false, // egen zoomkontroll längre ner, i bottomright
  scrollWheelZoom: true,
  doubleClickZoom: true,
});

L.control.zoom({ position: "bottomright" }).addTo(map);

// Dämpad, labelfri baskarta (Carto Voyager) istället för standard-OSM —
// standard-OSM:s starka väg-/vattenfärger konkurrerade visuellt med
// artfärgerna. Etiketterna (ortnamn) läggs i ett EGET lager i
// `shadowPane` (zIndex 500) — ovanför sannolikhetsytorna (`heat`-panen,
// zIndex 350) så namnen alltid är läsbara genom de blurrade ytorna, men
// under markörerna (markerPane, zIndex 600).
const CARTO_SUBDOMAINS = "abcd";
const CARTO_ATTRIBUTION = "&copy; OpenStreetMap-bidragsgivare &copy; CARTO";

L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png", {
  attribution: CARTO_ATTRIBUTION,
  maxZoom: 18,
  subdomains: CARTO_SUBDOMAINS,
}).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png", {
  pane: "shadowPane",
  maxZoom: 18,
  subdomains: CARTO_SUBDOMAINS,
}).addTo(map);
map.getPane("shadowPane").style.pointerEvents = "none";

// Sannolikhetsytornas egna pane, under Leaflets standardlager (400) men
// över kartplattorna (200) — se .leaflet-heat-pane i style.css för själva
// blur-effekten (ligger på HELA panen, inte per cirkel).
map.createPane("heat");
map.getPane("heat").style.zIndex = 350;

// Foto per art i nålarna/filterchipsen — lägg till fler här när fler
// bilder finns (frontend/images/<art-nyckel>.png).
const SPECIES_ICON_PATHS = {
  gulkantarell: "images/gulkantarell.png",
  trattkantarell: "images/trattkantarell.png",
  trumpetsvamp_svart: "images/trumpetsvamp_svart.png",
  trumpetsvamp_rod: "images/trumpetsvamp_röd.png",
};

// Från den här zoomnivån och uppåt hämtas en tät detaljgrid för den
// synliga ytan (ungefär "man har zoomat in på en specifik skog").
const DETAIL_ZOOM_THRESHOLD = 10;
const DETAIL_FETCH_DEBOUNCE_MS = 500;

// Upplösningen (grader mellan rutpunkter) som begärs precis vid
// DETAIL_ZOOM_THRESHOLD — grövre än den gamla FASTA detaljupplösningen
// (0.004), medvetet, som ett mellansteg: annars hoppar kartan direkt
// från översiktens grova ~9km-rutor till en 20x finare grid i samma
// ögonblick man passerar tröskeln, vilket var precis "hoppet" som kändes
// knasigt vid zoom.
const DETAIL_BASE_RESOLUTION_DEG = 0.016;

// Upplösningen HALVERAS för varje zoomsteg ovanför tröskeln (se
// resolutionForZoom) istället för att vara fast — samma princip som
// kartplattornas egen zoom (dubbel zoom = dubbel pixeltäthet), så
// konturernas "kantighet" känns ungefär lika grov/fin relativt det man
// ser på skärmen oavsett zoomnivå, samtidigt som man faktiskt FÅR mer
// exakta rutor ju mer man zoomar in.
function resolutionForZoom(zoom) {
  return DETAIL_BASE_RESOLUTION_DEG * Math.pow(2, DETAIL_ZOOM_THRESHOLD - zoom);
}

// --- Sannolikhetsytor (blurrade L.circle, se .leaflet-heat-pane) --------

// FASTA sannolikhetströsklar (45% för ytor, 55-82% för nålar) visade sig
// otillräckliga i praktiken: verifierat mot verklig data för ett
// skogsområde nära Handen där ALLA 169 skogsceller klarade 45%-tröskeln
// och 96% klarade även den strängaste nål-nivån — ett genuint bra
// skogsområde gör en fast tröskel helt urskillningslös (exakt samma
// fälla som löstes för artikonerna tidigare i projektet, se
// `docs/`-historik i README, nu återuppstånden i blob/nål-systemet).
// Lösningen är densamma: en RELATIV percentil av det som faktiskt syns
// just nu, med en låg absolut golvnivå kvar som säkerhetsspärr (så att
// "minst dåliga" celler i ett genuint uselt område inte ändå målas som
// om de vore bra).
const BLOB_MIN_PROBABILITY = 0.35; // absolut golv, bara en säkerhetsspärr

// Varje art bedöms OBEROENDE mot SIN EGEN sannolikhetsfördelning bland
// de synliga skogscellerna — inte mot en "dominant art vinner, övriga
// tonas ner"-modell (det gamla upplägget). Verifierat mot verklig data
// (Björkhagen/Nacka-området) att alla tre arter ofta har snarlika
// fördelningar (median 0.73-0.76) med bara små cell-för-cell-skillnader
// i vem som råkar vinna — en "dominant vinner"-modell gjorde då att en
// art som stängdes av/på verkade dyka upp eller försvinna helt (fastän
// den varit påslagen hela tiden och haft en nästan lika hög
// sannolikhet), och gav i praktiken bara EN synlig färgton även med
// tre arter aktiva samtidigt. Oberoende normalisering per art löser
// båda: varje art visar sina EGNA relativa toppar, oavsett vilka andra
// arter som råkar vara påslagna, och flera arter kan synas blandat i
// samma område om de faktiskt är ungefär lika bra där.
const BLOB_LOW_PERCENTILE = 0.55; // en cell måste ligga i artens EGEN topp 45% för att synas alls
const BLOB_HIGH_PERCENTILE = 0.92; // artens EGEN topp 8% ger maximal mättnad/radie
const BLOB_OPACITY_MIN = 0.08;
const BLOB_OPACITY_MAX = 0.42;
const BLOB_RADIUS_MIN_FACTOR = 0.35;
const BLOB_RADIUS_MAX_FACTOR = 0.85;

// Grov omvandling grader → meter (varierar egentligen med latitud för
// longitud, men skillnaden är försumbar för en rent kosmetisk radie).
const DEGREES_TO_METERS = 111_000;

// --- Nålar: dominant art per cell, utglesade vid zoom -------------------

const PIN_PHOTO_SIZE_PX = 44;
const PIN_STALK_HEIGHT_PX = 10;
const PIN_DOT_SIZE_PX = 10;

const MARKER_MIN_PROBABILITY = 0.35; // absolut golv, samma resonemang som BLOB_MIN_PROBABILITY

// Minsta avstånd i SKÄRMPIXLAR mellan två nålar (skalat med
// markerScaleForZoom). Höjt kraftigt från ett tidigare värde (58px) som
// visade sig vara knappt större än nålens EGEN diameter (~50px) — det
// gav i praktiken nästan ingen utglesning alls, bara en tät matta av en
// nål per rutcell. 150px tvingar fram ett faktiskt gap mellan nålar.
const MARKER_COLLISION_BASE_PX = 150;

// Zoom-beroende PERCENTIL (inte fast värde) — hur stor andel av de
// synliga skogscellernas bästa sannolikhet som får bli nål-kandidater.
// Grövre (lägre andel) utzoomat, eftersom varje nål då representerar ett
// mycket större geografiskt område.
function candidatePercentileForZoom(zoom) {
  if (zoom <= 9) return 0.9; // topp 10%
  if (zoom === 10) return 0.82; // topp 18%
  if (zoom === 11) return 0.75; // topp 25%
  return 0.65; // topp 35%
}

// Zoom-beroende skala på själva nålen — mindre utzoomat så flera fler
// får plats innan de kolliderar med varandra.
function markerScaleForZoom(zoom) {
  if (zoom <= 9) return 0.62;
  if (zoom === 10) return 0.78;
  if (zoom === 11) return 0.9;
  return 1;
}

// Percentil (0–1) av en sorterad lista — percentile(sorted, 0.9) ger
// VÄRDET vid gränsen för topp 10%. Relativt till det som FAKTISKT syns
// just nu, så en tröskel aldrig blir urskillningslös bara för att en
// hel synlig yta råkar vara ovanligt bra eller dålig.
function percentile(sortedValues, p) {
  if (sortedValues.length === 0) return null;
  const index = Math.min(sortedValues.length - 1, Math.floor(sortedValues.length * p));
  return sortedValues[index];
}

// Avståndet mellan två grannpunkter i griden (oavsett om det är
// översiktens glesa grid eller en zoomad, finare detaljgrid) — dvs den
// minsta POSITIVA skillnaden mellan sorterade unika koordinatvärden.
// Används för att skala sannolikhetsytornas radie relativt hur tätt
// rutnätet faktiskt är just nu.
function gridStep(sortedUniqueValues) {
  let step = null;
  for (let i = 1; i < sortedUniqueValues.length; i++) {
    const diff = sortedUniqueValues[i] - sortedUniqueValues[i - 1];
    if (diff > 0 && (step === null || diff < step)) step = diff;
  }
  return step;
}

function withAlpha(hex, alphaHex) {
  return `${hex}${alphaHex}`;
}

// --- Kombinerar de tre arternas cellistor till EN lista -----------------
// Alla tre arter delar samma grid (samma lat/lon-ordning, samma
// is_forest per index) — se app/services/prediction.py. Att kombinera
// dem en gång här (istället för att hålla tre separata lager, ett per
// art) gör att "dominant art i den här cellen" blir en ren uppslagning
// istället för att behöva jämföra tre parallella lager vid varje
// rendering.
function combineCells(speciesList) {
  const referenceCells = speciesList[0]?.cells ?? [];
  return referenceCells.map((refCell, i) => {
    const bySpecies = {};
    speciesList.forEach((species) => {
      const c = species.cells[i];
      bySpecies[species.key] = {
        key: species.key,
        name: species.name,
        color: species.color,
        probability: c.probability,
        explanation: c.explanation,
      };
    });
    return { lat: refCell.lat, lon: refCell.lon, isForest: refCell.is_forest, bySpecies };
  });
}

function cellKey(cell) {
  return `${cell.lat},${cell.lon}`;
}

// Dominant art = högst sannolikhet BLAND DE ARTER SOM ÄR PÅSLAGNA i
// filterpanelen just nu — stänger man av en art ska celler där den
// arten råkade vara starkast falla tillbaka på nästa bästa påslagna
// art, inte försvinna eller fortsätta visa den avstängda arten.
function dominantSpecies(cell, activeKeys) {
  let best = null;
  activeKeys.forEach((key) => {
    const candidate = cell.bySpecies[key];
    if (candidate && (!best || candidate.probability > best.probability)) best = candidate;
  });
  return best;
}

// --- Globalt render-state -------------------------------------------------

let speciesMeta = []; // [{key, name, color}], ordning som backend skickar
const activeSpeciesKeys = new Set();
let overviewCombinedCells = [];
let detailCombinedCells = null; // null = ingen detaljyta laddad, visa översikt
let selectedCellKey = null;
let blobLayer = null;
let markerLayer = null;

let detailFetchTimer = null;
let latestDetailRequestId = 0;
// Skydd mot att flera tunga detaljanrop körs samtidigt mot backend: om
// användaren zoomar/panorerar flera gånger på kort tid (fullt normalt)
// AVBRYTS det pågående anropet direkt (via AbortController) och ersätts
// av ett nytt för den senaste ytan, istället för att köa och vänta in
// det gamla — annars jagar kartan alltid en yta man redan lämnat. Utan
// något skydd här kan flera överlappande, tunga beräkningar (tusentals
// vädersökningar + historikjämförelser vardera) byggas upp på backend
// samtidigt, vilket vi såg hänga hela servern (100% CPU i flera minuter).
let detailAbortController = null;

function currentCombinedCells() {
  return detailCombinedCells ?? overviewCombinedCells;
}

// --- Sannolikhetsytor -----------------------------------------------------

// Artens EGNA låg/hög-percentil bland de synliga skogscellerna just
// nu — grunden för den oberoende normaliseringen (se motivering vid
// BLOB_LOW_PERCENTILE).
function speciesBand(forestCells, key) {
  const sorted = forestCells
    .map((cell) => cell.bySpecies[key]?.probability)
    .filter((p) => p != null)
    .sort((a, b) => a - b);
  const low = Math.max(BLOB_MIN_PROBABILITY, percentile(sorted, BLOB_LOW_PERCENTILE) ?? BLOB_MIN_PROBABILITY);
  const high = Math.max(low + 0.01, percentile(sorted, BLOB_HIGH_PERCENTILE) ?? low + 0.01);
  return { low, high };
}

function renderBlobs() {
  if (blobLayer) map.removeLayer(blobLayer);

  const forestCells = currentCombinedCells().filter((cell) => cell.isForest);
  if (forestCells.length === 0) {
    blobLayer = null;
    return;
  }

  const lats = [...new Set(forestCells.map((c) => c.lat))].sort((a, b) => a - b);
  const lons = [...new Set(forestCells.map((c) => c.lon))].sort((a, b) => a - b);
  const stepDeg = [gridStep(lats), gridStep(lons)].filter((v) => v != null).sort((a, b) => a - b)[0] ?? 0.01;
  const stepMeters = stepDeg * DEGREES_TO_METERS;

  const bandsByKey = {};
  activeSpeciesKeys.forEach((key) => {
    bandsByKey[key] = speciesBand(forestCells, key);
  });

  blobLayer = L.layerGroup();
  forestCells.forEach((cell) => {
    activeSpeciesKeys.forEach((key) => {
      const entry = cell.bySpecies[key];
      const band = bandsByKey[key];
      if (!entry || !band || entry.probability < band.low) return;

      // t = 0 vid artens egen lågtröskel, 1 vid artens egen högtröskel
      // — samma cell kan alltså se helt olika ut för olika arter,
      // exakt vad vi vill: varje art visar SINA EGNA relativa toppar.
      const t = Math.min(1, (entry.probability - band.low) / (band.high - band.low));
      const opacity = BLOB_OPACITY_MIN + t * (BLOB_OPACITY_MAX - BLOB_OPACITY_MIN);
      const radius = stepMeters * (BLOB_RADIUS_MIN_FACTOR + t * (BLOB_RADIUS_MAX_FACTOR - BLOB_RADIUS_MIN_FACTOR));

      L.circle([cell.lat, cell.lon], {
        pane: "heat",
        radius,
        stroke: false,
        fillColor: entry.color,
        fillOpacity: opacity,
        interactive: false,
      }).addTo(blobLayer);
    });
  });

  blobLayer.addTo(map);
}

// --- Nålar (dominant art per cell, utglesade vid zoom) -------------------

function buildMushroomPinIcon(dominant, scale, isSelected) {
  const photoSize = Math.round(PIN_PHOTO_SIZE_PX * scale);
  const stalkHeight = Math.round(PIN_STALK_HEIGHT_PX * scale);
  const dotSize = Math.round(PIN_DOT_SIZE_PX * scale);
  const totalHeight = photoSize + stalkHeight + dotSize;
  const iconPath = SPECIES_ICON_PATHS[dominant.key];

  const html = `
    <div class="mushroom-pin${isSelected ? " is-selected" : ""}" style="--pin-color:${dominant.color}">
      <div class="mushroom-pin-photo" style="width:${photoSize}px;height:${photoSize}px;background-image:url('${iconPath ?? ""}')"></div>
      <div class="mushroom-pin-stalk" style="height:${stalkHeight}px"></div>
      <div class="mushroom-pin-dot" style="width:${dotSize}px;height:${dotSize}px"></div>
    </div>`;

  // iconAnchor = [bredd/2, höjd] så att den lilla punkten (inte fotot)
  // sitter exakt på koordinaten — annars är det oklart vilken plats en
  // nål egentligen gäller.
  return L.divIcon({
    html,
    className: "mushroom-pin-wrapper",
    iconSize: [photoSize, totalHeight],
    iconAnchor: [photoSize / 2, totalHeight],
  });
}

function buildMarkerCandidates(cells, zoom) {
  const bounds = map.getBounds().pad(0.15);
  const visible = cells
    .filter((cell) => cell.isForest && bounds.contains([cell.lat, cell.lon]))
    .map((cell) => ({ cell, dominant: dominantSpecies(cell, activeSpeciesKeys) }))
    .filter(({ dominant }) => dominant != null);

  // Relativ tröskel, samma resonemang som för sannolikhetsytorna: en
  // fast andel (55-82%) visade sig urskillningslös i ett genomgående
  // bra synligt område — verifierat mot verklig data där 96% av
  // cellerna klarade den strängaste nivån.
  const sortedProbabilities = visible.map(({ dominant }) => dominant.probability).sort((a, b) => a - b);
  const threshold = Math.max(
    MARKER_MIN_PROBABILITY,
    percentile(sortedProbabilities, candidatePercentileForZoom(zoom)) ?? MARKER_MIN_PROBABILITY
  );

  // Den VALDA cellen (om sidopanelen är öppen för den) ska alltid vara
  // en kandidat, oavsett tröskel — annars kan nålen tyst försvinna vid
  // en zoom/pan-ändring medan panelen står kvar öppen utan att visa
  // vilken plats den gäller. Se även renderMarkers, som stänger panelen
  // om cellen inte ens är synlig (utanför bounds/inte skog) längre.
  return visible
    .filter(({ cell, dominant }) => cellKey(cell) === selectedCellKey || dominant.probability >= threshold)
    .map(({ cell, dominant }) => ({ cell, dominant, isSelected: cellKey(cell) === selectedCellKey }));
}

// Girigt kollisionstest i SKÄRMKOORDINATER (inte grader) — det som
// faktiskt håller nere antalet nålar oavsett hur många celler som
// klarar sannolikhetströskeln. Sorterar vald-nålen och högst
// sannolikhet först, så de viktigaste vinner om två konkurrerar om
// samma yta.
function declutterCandidates(candidates, scale) {
  const minDistancePx = MARKER_COLLISION_BASE_PX * scale;
  const sorted = [...candidates].sort((a, b) => {
    if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
    return b.dominant.probability - a.dominant.probability;
  });

  const placedPoints = [];
  const kept = [];
  sorted.forEach((candidate) => {
    const point = map.latLngToContainerPoint([candidate.cell.lat, candidate.cell.lon]);
    const tooClose = placedPoints.some((placed) => point.distanceTo(placed) < minDistancePx);
    if (!tooClose) {
      placedPoints.push(point);
      kept.push(candidate);
    }
  });
  return kept;
}

function renderMarkers() {
  if (markerLayer) map.removeLayer(markerLayer);
  markerLayer = L.layerGroup().addTo(map);

  const cells = currentCombinedCells();
  const zoom = map.getZoom();
  const scale = markerScaleForZoom(zoom);
  const candidates = buildMarkerCandidates(cells, zoom);
  const kept = declutterCandidates(candidates, scale);

  // Den valda cellen bryter igenom tröskeln i buildMarkerCandidates så
  // länge den är SYNLIG (i bounds, skog, en påslagen art har data där)
  // — men om användaren panorerat/zoomat bort från den helt finns den
  // inte ens bland kandidaterna. Stäng då panelen istället för att låta
  // den stå kvar öppen utan en nål att peka på.
  if (selectedCellKey && !kept.some(({ cell }) => cellKey(cell) === selectedCellKey)) {
    document.getElementById("cell-panel").classList.add("hidden");
    selectedCellKey = null;
  }

  kept.forEach(({ cell, dominant, isSelected }) => {
    const icon = buildMushroomPinIcon(dominant, scale, isSelected);
    L.marker([cell.lat, cell.lon], { icon })
      .on("click", () => selectCell(cell))
      .addTo(markerLayer);
  });

  updateSpeciesEmptyNotes(cells);
}

// En hel art kan sakna nålar helt i en synlig yta trots att den är
// påslagen — inte ett fel, utan `MARKER_MIN_PROBABILITY`-golvet som
// aldrig klaras (verifierat mot verklig data, Orminge-området
// 2026-08-20: trattkantarells HÖGSTA värde bland 193 skogsceller var
// bara 0.228, långt under golvet på 0.35, eftersom säsongsfaktorn för
// just den dagen/arten var 0.27 — se app/services/season.py). Utan en
// förklaring ser ett sådant "tomt" resultat ut som ett trasigt filter
// istället för en äkta säsongseffekt.
function updateSpeciesEmptyNotes(cells) {
  document.querySelectorAll(".species-chip-note").forEach((note) => {
    const key = note.dataset.speciesKey;
    if (!activeSpeciesKeys.has(key)) {
      note.classList.add("hidden");
      return;
    }

    const hasCandidate = cells.some(
      (cell) => cell.isForest && (cell.bySpecies[key]?.probability ?? 0) >= MARKER_MIN_PROBABILITY
    );
    note.classList.toggle("hidden", hasCandidate);
  });
}

function renderAll() {
  renderBlobs();
  renderMarkers();
}

// --- Sidopanel (ersätter Leaflet-popupen) --------------------------------

function openCellPanel(cell) {
  const rows = speciesMeta
    .filter((species) => activeSpeciesKeys.has(species.key))
    .map((species) => cell.bySpecies[species.key])
    .filter(Boolean)
    .map((entry) => {
      // VISAS som ett index 0-100, inte "XX%" — vår kalibrering (litet
      // stickprov, en region, se prediction.py) har inte den
      // statistiska styrkan som krävs för att kalla det en validerad
      // sannolikhet i procent. Samma ärliga ramverk som andra
      // svampkartetjänster använder (se README).
      const indexValue = Math.round(entry.probability * 100);
      const iconPath = SPECIES_ICON_PATHS[entry.key] ?? "";
      return `
        <div class="cell-row">
          <div class="cell-row-header">
            <span class="cell-row-icon" style="background-image:url('${iconPath}')"></span>
            <span class="cell-row-name">${entry.name}</span>
            <span class="cell-row-index-value">${indexValue}</span>
            <span class="cell-row-index-unit">index</span>
          </div>
          <div class="cell-row-bar-track">
            <div class="cell-row-bar-fill" style="width:${indexValue}%;background:${entry.color}"></div>
          </div>
          <p class="cell-row-explanation">${entry.explanation}</p>
        </div>`;
    })
    .join("");

  document.getElementById("cell-panel-rows").innerHTML = rows;

  const panel = document.getElementById("cell-panel");
  panel.classList.remove("hidden");
  // Kör om "rise"-animationen även om panelen redan var öppen (klick på
  // en ny nål medan panelen visas) — annars syns den bara första gången.
  panel.style.animation = "none";
  void panel.offsetWidth;
  panel.style.animation = "";
}

function closeCellPanel() {
  document.getElementById("cell-panel").classList.add("hidden");
  selectedCellKey = null;
  renderMarkers();
}

function selectCell(cell) {
  selectedCellKey = cellKey(cell);
  renderMarkers(); // ritar om så den valda nålen får lyft-styling
  openCellPanel(cell);
}

// --- Filterpanelens artchips ----------------------------------------------

function buildSpeciesChips(speciesList) {
  const container = document.getElementById("species-chips");
  container.innerHTML = speciesList
    .map((species) => {
      const iconPath = SPECIES_ICON_PATHS[species.key] ?? "";
      const onBg = withAlpha(species.color, "1F");
      const onBorder = withAlpha(species.color, "55");
      return `
        <div class="species-chip-group">
          <button
            type="button"
            class="species-chip is-active"
            data-species-key="${species.key}"
            aria-pressed="true"
            style="--chip-on-bg:${onBg};--chip-on-border:${onBorder}"
          >
            <span class="species-chip-icon" style="background-image:url('${iconPath}')"></span>
            <span class="species-chip-name">${species.name}</span>
            <span class="species-chip-dot" style="background:${species.color}"></span>
          </button>
          <p class="species-chip-note hidden" data-species-key="${species.key}">
            Inga tydliga platser för ${species.name.toLowerCase()} i den här vyn just nu — ofta för att
            det inte är säsong för arten än, ibland för att skogstypen inte passar här.
          </p>
        </div>`;
    })
    .join("");

  container.querySelectorAll(".species-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const key = chip.dataset.speciesKey;
      const isActive = chip.classList.toggle("is-active");
      chip.setAttribute("aria-pressed", String(isActive));
      if (isActive) activeSpeciesKeys.add(key);
      else activeSpeciesKeys.delete(key);
      renderAll();
    });
  });
}

// --- Datahämtning (översikt + zoom-detaljvy) ------------------------------

function setDetailLoading(isLoading) {
  document.getElementById("detail-loading").classList.toggle("visible", isLoading);
}

async function updateDetailView() {
  if (detailAbortController) {
    // Ett tidigare detaljanrop är fortfarande inflight (t.ex. flera
    // snabba zoom/pan-steg i rad) — avbryt det direkt istället för att
    // vänta in det, så att kartan alltid jagar den SENASTE synliga ytan.
    console.log("[detaljvy] avbryter tidigare inaktuellt anrop");
    detailAbortController.abort();
    detailAbortController = null;
  }

  const zoom = map.getZoom();
  console.log(`[detaljvy] moveend, zoom=${zoom} (tröskel=${DETAIL_ZOOM_THRESHOLD})`);

  if (zoom < DETAIL_ZOOM_THRESHOLD) {
    console.log("[detaljvy] under tröskeln, visar bara översikt");
    detailCombinedCells = null;
    renderAll();
    return;
  }

  const requestId = ++latestDetailRequestId;
  const controller = new AbortController();
  detailAbortController = controller;
  setDetailLoading(true);
  const bounds = map.getBounds();
  const resolutionDeg = resolutionForZoom(zoom);
  console.log(
    `[detaljvy] hämtar för bounds=${bounds.toBBoxString()}, upplösning=${resolutionDeg.toFixed(4)}°`
  );

  try {
    const data = await fetchPredictions({ bounds, resolution: resolutionDeg, signal: controller.signal });
    console.log(`[detaljvy] svar mottaget, ${data.species[0]?.cells.length ?? 0} celler/art`);

    // Bältet-och-hängslena-koll: AbortController bör redan ha förhindrat
    // att vi hamnar här med ett inaktuellt svar, men skyddar även mot
    // det osannolika race där svaret hann komma in innan abort() slog
    // igenom.
    if (requestId !== latestDetailRequestId) {
      console.log("[detaljvy] inaktuellt svar, ignorerar");
      return;
    }

    detailCombinedCells = combineCells(data.species);
    renderAll();
    console.log("[detaljvy] renderad klart");
  } catch (error) {
    if (error.name === "AbortError") {
      console.log("[detaljvy] anrop avbrutet (ersatt av ett nyare)");
      return;
    }
    console.error("[detaljvy] FEL vid hämtning:", error);
  } finally {
    if (detailAbortController === controller) detailAbortController = null;
    if (requestId === latestDetailRequestId) setDetailLoading(false);
  }
}

function scheduleDetailUpdate() {
  console.log("[detaljvy] moveend inregistrerad, väntar", DETAIL_FETCH_DEBOUNCE_MS, "ms");
  if (detailFetchTimer) clearTimeout(detailFetchTimer);
  detailFetchTimer = setTimeout(updateDetailView, DETAIL_FETCH_DEBOUNCE_MS);
}

async function init() {
  const loadingEl = document.getElementById("loading");
  try {
    const data = await fetchPredictions();

    const bounds = [
      [data.bounds.min_lat, data.bounds.min_lon],
      [data.bounds.max_lat, data.bounds.max_lon],
    ];
    map.fitBounds(bounds, { padding: [16, 16] });

    speciesMeta = data.species.map((species) => ({
      key: species.key,
      name: species.name,
      color: species.color,
    }));
    speciesMeta.forEach((species) => activeSpeciesKeys.add(species.key));
    overviewCombinedCells = combineCells(data.species);

    buildSpeciesChips(data.species);
    renderAll();

    loadingEl.classList.add("hidden");

    // zoomend ritar bara om markörerna (billigt, ingen ny data) så
    // deklutter känns direkt responsiv. moveend (debouncad) hämtar ny
    // data för den nya ytan/upplösningen och ritar sedan om allt.
    map.on("zoomend", renderMarkers);
    map.on("moveend", scheduleDetailUpdate);
    scheduleDetailUpdate();
  } catch (error) {
    console.error(error);
    loadingEl.classList.add("hidden");
    L.popup()
      .setLatLng(map.getCenter())
      .setContent("Kunde inte ladda prognosdata. Är backend igång?")
      .openOn(map);
  }
}

// Infoknappen, "Så funkar det"-modalen och sidopanelens stängkryss är
// oberoende av kartan/datat — knyts alltid, oavsett om prognosdatan
// senare misslyckas att laddas.
function initInfoDialog() {
  const dialog = document.getElementById("info-dialog");
  const openButton = document.getElementById("info-button");
  const closeButton = document.getElementById("info-close");
  if (!dialog || !openButton || !closeButton) return;

  const close = () => dialog.classList.add("hidden");

  openButton.addEventListener("click", () => dialog.classList.remove("hidden"));
  closeButton.addEventListener("click", close);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close(); // klick på den mörka bakgrunden
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
  });
}

function initCellPanel() {
  const closeButton = document.getElementById("cell-panel-close");
  if (!closeButton) return;
  closeButton.addEventListener("click", closeCellPanel);
}

initInfoDialog();
initCellPanel();
init();
