const API_BASE_URL = "http://localhost:8000";

// `options.bounds` = en Leaflet LatLngBounds — om satt hämtas en
// zoom-detaljvy (tätare grid) för just den ytan istället för
// översiktsregionen. `options.resolution` (grader) är valfri, annars
// används backendens default (se settings.detail_resolution_deg).
// `options.signal` = en AbortSignal (från AbortController) så att
// anroparen kan avbryta ett pågående anrop — viktigt för detaljvyn där
// ett nytt zoom/pan annars skulle lämna det gamla, tunga anropet
// hängande i bakgrunden samtidigt som ett nytt startar.
async function fetchPredictions(options = {}) {
  const params = new URLSearchParams();

  if (options.bounds) {
    params.set("min_lat", options.bounds.getSouth());
    params.set("max_lat", options.bounds.getNorth());
    params.set("min_lon", options.bounds.getWest());
    params.set("max_lon", options.bounds.getEast());
  }
  if (options.resolution) {
    params.set("resolution", options.resolution);
  }

  const query = params.toString();
  const url = `${API_BASE_URL}/api/predictions${query ? `?${query}` : ""}`;

  const response = await fetch(url, { signal: options.signal });
  if (!response.ok) {
    throw new Error(`Kunde inte hämta prognoser: ${response.status}`);
  }
  return response.json();
}
