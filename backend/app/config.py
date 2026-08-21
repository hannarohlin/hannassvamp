from pydantic_settings import BaseSettings, SettingsConfigDict


class Region:
    """Bounding box och grid-upplösning för en avgränsad MVP-region."""

    def __init__(self, name: str, min_lat: float, max_lat: float, min_lon: float, max_lon: float):
        self.name = name
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon


# Ungefärlig bounding box för Södermanlands län (kvar för referens/historik,
# används inte längre av appen — se MVP_REGION nedan).
SODERMANLAND = Region(
    name="Södermanland",
    min_lat=58.6,
    max_lat=59.4,
    min_lon=16.2,
    max_lon=17.7,
)

# Fastlandsfokuserad bbox för Uppland + Södermanland + Stockholmsområdet.
# Verkliga länsgränser (via OSM Nominatim) för Stockholms/Uppsala/
# Södermanlands län är betydligt större (upp till lon 20.0 pga Stockholms
# skärgård, lat 60.9 i norra Uppland) — trimmat hit för att hålla samma
# rutstorlek (grid_resolution_deg) utan att NMD-anropen (se
# app/data_sources/nmd.py) skenar iväg i tid. ~4x Södermanlands yta,
# ~800 rutor/art.
UPPLAND_SODERMANLAND = Region(
    name="Uppland och Södermanland",
    min_lat=58.5,
    max_lat=60.3,
    min_lon=16.2,
    max_lon=18.8,
)

# Regionen som exponeras via API:et. Byt referens här om ni vill växla
# tillbaka till en mindre/snabbare region.
MVP_REGION = UPPLAND_SODERMANLAND


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    artportalen_api_key: str = ""

    # 0.08° gav ~220 celler i (den mindre) Södermanland-regionen och
    # hölls oförändrad när regionen utökades till Uppland+Södermanland
    # (~800 celler) — se README "Prestanda och robusthet".
    grid_resolution_deg: float = 0.08

    # Zoom-detaljvy: när frontend zoomar in på en specifik yta hämtas en
    # mycket tätare grid för bara den synliga viewporten (se
    # /api/predictions bbox-parametrar), istället för att lita på den
    # grova översiktsgriden för att avgöra "var i skogen" man ska gå.
    detail_resolution_deg: float = 0.004  # ~350-450m, fallback om klienten inte anger `resolution`
    # Säkerhetsgolv — frontend (se resolutionForZoom i map.js) begär
    # numera PROGRESSIVT finare upplösning ju mer man zoomar in, istället
    # för samma fasta upplösning oavsett zoom. Sänkt från 0.0015
    # (~150-170m) till ~80-90m eftersom NMD:s underliggande data har 10m
    # upplösning — gott om utrymme kvar. Ofarligt att sänka: antal rutor
    # per förfrågan begränsas ändå av `detail_max_cells` nedan, och en
    # zoomad-in viewport är samtidigt geografiskt mindre, så cellantalet
    # växer inte okontrollerat bara för att golvet sänks.
    detail_min_resolution_deg: float = 0.0008
    # Sänkt från 1200: om frontend av misstag skickar flera överlappande
    # detaljförfrågningar (t.ex. flera snabba zoom/pan-steg) innan den
    # första hunnit svara, multipliceras kostnaden per förfrågan. Lägre
    # tak begränsar värsta-fallet per anrop, som komplement till att
    # frontend nu köar istället för att skicka overlappande anrop.
    detail_max_cells: int = 500

    # Väder hämtas per GROVT rutnät (~4-5.5km, nära PTHBV:s egen 4x4km-
    # upplösning), inte per prediktionscell — annars frågas exakt samma
    # underliggande PTHBV-ruta om och om igen för varje fin
    # prediktionscell inom den. Verifierat att detta krävs: PTHBV:s
    # dagliga API har en hård gräns på 100 punkter/anrop OCH tål dåligt
    # många små anrop i snabb följd (77 samtidiga en-punkts-anrop tog
    # 62s, mot ~3,5s för ett batchat 100-punkters-anrop) — se
    # app/data_sources/smhi.py.
    weather_grid_resolution_deg: float = 0.05

    # Jordart hämtas per GROVT rutnät av samma skäl som väder ovan —
    # SGU:s jordarts-API kan svara med enskilda polygoner på 700+ KB
    # (t.ex. en sjö eller ett stort moränfält), så att fråga per fin
    # prediktionscell skulle kunna dra hundratals MB per request. Se
    # app/data_sources/sgu.py.
    soil_grid_resolution_deg: float = 0.05

    cors_origins: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500"]

    # Tom sträng = använd standardplatsen bredvid koden (backend/.cache),
    # bra för lokal utveckling. I produktion på en plattform med
    # ephemeral filsystem MÅSTE detta istället pekas mot en monterad,
    # beständig disk (t.ex. "/data/.cache" på en Render-disk monterad på
    # /data) — annars nollställs cachen vid varje omdeploy/omstart och
    # hela poängen med de långa TTL:erna (30/90 dagar för NMD/SGU) går
    # förlorad.
    cache_dir: str = ""


settings = Settings()
