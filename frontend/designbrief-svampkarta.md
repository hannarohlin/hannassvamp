# Designändringar – svampkartan

Referens: designförslaget i `Svampkarta.dc.html` (Leaflet + inline-styles).

## 1. Baskarta
- Byt till en dämpad, labelfri baskarta: Carto **Voyager nolabels**
  `https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png`
- Lägg etikettlagret (`voyager_only_labels`) i ett lager **ovanför** svampdatan (t.ex. `pane: 'shadowPane'`) så ortnamn alltid är läsbara.
- Flytta zoomkontrollen till `bottomright`, dölj default zoom-control (`zoomControl: false`).
- Motiv: den nuvarande kartan har starka väg-/vattenfärger som konkurrerar med svampfärgerna.

## 2. Sannolikhetsytor i stället för hårda polygoner
- Rita varje område som en `L.circle` utan kantlinje i en egen pane (`map.createPane('heat')`, `zIndex: 350`, `pointer-events: none`, `filter: blur(16px)`, `opacity: .85`).
- Radie och opacitet skalar med sannolikheten; ytor under ~45 % ritas inte.
- Per område: **dominant art** = stor, mättad yta (`fillOpacity ≈ .16 + p/100*.3`); **övriga arter** = mindre, svagare ytor (`≈ .1 + p/100*.12`). Utan detta blir överlappande ytor gråa.
- Använd `mixBlendMode: 'normal'` (inte multiply – det avfärgar överlappen).

## 3. Markörernas placering (viktigast)
Nuvarande problem: ikonerna svävar och det är oklart vilken punkt de gäller.
- Ny markör = pin med tre delar: cirkel med artfärgad ram + svampfoto, en 2 px stjälk nedåt, och en liten färgad punkt i botten som sitter på den exakta koordinaten.
- `iconAnchor` = [bredd/2, höjd] så spetsen sitter i koordinaten.
- Vald markör: kraftigare skugga, lyft 3 px, samt en ring runt bottenpunkten.
- Visa **bara områdets starkaste art** som ikon – inte en ikon per art.

## 4. Utglesning vid zoom (declutter)
- Rita om markörerna på `zoomend` och `moveend`.
- Filtrera på synligt `map.getBounds().pad(0.15)`.
- Sannolikhetströskel per zoom: z≤9 → 82 %, z10 → 72 %, z11 → 64 %, z≥12 → 55 %.
- Skala markören: z≤9 → 0.62, z10 → 0.78, z11 → 0.9, annars 1.
- Kollisionstest i skärmkoordinater (`latLngToContainerPoint`): hoppa över markörer närmare än ~58 px × skalan från en redan placerad. Sortera på (vald först, sedan högst sannolikhet) så de viktigaste vinner.

## 5. Filterpanel (ersätter kryssrutorna nere till höger)
- Panel uppe till vänster: titel, en rad förklarande text, rubrik "VISA ARTER" och tre stora klickbara art-chips (svampikon + namn + färgprick).
- Av-läge: transparent bakgrund, grå ram, `opacity .5`. På-läge: artfärgad bakgrund (`färg + 1F`) och ram (`färg + 55`).
- Under panelen: liten legend "Sannolikhet – Låg → Hög" med en gradientstapel.

## 6. Infopanel i stället för popup
- Klick på markör öppnar en panel till höger (352 px, full höjd, radie 22 px) i stället för en Leaflet-popup över kartan.
- Innehåll: område som rubrik, en rad per aktiv art med ikon, namn, procent i serif-siffror och en färgad stapel, samt en rad om vad siffran bygger på (antal kända fynd inom ~1 km, skogstyp, nederbörd senaste dygnet).
- Nederst avsnittet "Underlag" som taggar: `Väder · SMHI`, `Skogstyp · NMD`, `Fynd · Artportalen` + en disclaimer att det är en modelluppskattning.
- Stängkryss uppe till höger, `animation: rise .22s ease-out` vid öppning.

## 7. "Så funkar det"-modal
- Pill-knapp uppe till höger öppnar en modal (520 px) som förklarar: mjuka fält = modellens bedömning, nålen = områdets mittpunkt (ej exakt fyndplats), samt en rad per art om var de trivs, och vilken data som används.

## 8. Visuellt språk
- Färger: gul kantarell `#D99A16`, trattkantarell `#4E7A9E`, trumpetsvamp `#8A4A6B` (plommon – grafitgrått läste som "avstängt").
- Text `#1B2A20`, sekundär `#5C6B60`, labels `#8B9689`, accent `#2F6B4F`, panelbakgrund `rgba(253,252,249,.92)` med `backdrop-filter: blur(14px)`.
- Typografi: **Instrument Serif** för rubriker och procentsiffror, **Instrument Sans** för allt annat. Versala labels 10 px med `letter-spacing: .12em`.
- Paneler: radie 16–22 px, 1 px ram `rgba(27,42,32,.09)`, skugga `0 12px 30px -14px rgba(27,42,32,.3)`.
- Ladda svampikoner som `background: url(...) center/contain no-repeat` i panelerna.
