// Lokalt (python -m http.server) pekar vi mot backend på localhost;
// på Netlify (eller någon annan icke-lokal host) pekar vi mot den
// publika backend-URL:en istället. TODO: byt ut PRODUCTION_BACKEND_URL
// mot den riktiga URL:en (typ https://<tjänst>.onrender.com) när backend
// är deployad.
const PRODUCTION_BACKEND_URL = "https://REPLACE_WITH_BACKEND_URL";
const API_BASE_URL = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? "http://localhost:8000"
  : PRODUCTION_BACKEND_URL;

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
