# 🌡️🌵🔥💧 climatewire

Four automated climate hazard news wires running on GitHub Actions. Each wire finds US news events, verifies relevance with an LLM, geocodes locations, joins observational sensor data, and commits results as GeoJSON + CSV directly to this repo. No database required.

---

## Wires

| Wire | Hazard | Sensor Join | Schedule |
|---|---|---|---|
| **heatwire** | Extreme heat events, heat emergencies | Open-Meteo → WBGT (°F flag) | 06:00 ET daily |
| **droughtwire** | Drought declarations, water shortages | NOAA US Drought Monitor (D0–D4) | 08:00 ET daily |
| **firewire** | Wildfires, evacuations, red flag warnings | NASA FIRMS VIIRS active fire detections | 04:00 ET daily |
| **waterwire** | Water restrictions, aquifer depletion | USGS streamflow + groundwater gauges | 07:00 ET daily |

---

## Architecture

```
SerpAPI Google News  (3 queries × 4 wires = 12 API calls/day)
    ↓  core/extract.py
Regex pre-filter     (drops figurative uses, non-US articles)
    ↓  core/screen.py
Ollama Cloud LLM     (gpt-oss:120b, yes/no per article)
    ↓  core/geocode.py
spaCy NER + OSM Nominatim  (1 req/sec, no API key)
    ↓  {wire}/sensor_join.py
Open-Meteo / USDM / NASA FIRMS / USGS (all free, no key)
    ↓  core/load.py
data/{wire}.geojson  +  data/{wire}.csv  (appended, committed)
```

---

## Repository structure

```
.github/workflows/
  heatwire.yml
  droughtwire.yml
  firewire.yml
  waterwire.yml
src/
  core/
    extract.py      ← shared SerpAPI fetch + regex filter
    screen.py       ← shared Ollama LLM screener
    geocode.py      ← shared spaCy NER + Nominatim geocoder
    load.py         ← shared GeoJSON + CSV writer (dedup on article_id)
    utils.py        ← config loader + logging
  heat/
    main.py         ← orchestrator
    sensor_join.py  ← Open-Meteo WBGT
  drought/
    main.py
    sensor_join.py  ← NOAA US Drought Monitor shapefile
  fire/
    main.py
    sensor_join.py  ← NASA FIRMS VIIRS CSV (haversine join)
  water/
    main.py
    sensor_join.py  ← USGS Water Services REST API
data/
  heat.geojson / heat.csv
  drought.geojson / drought.csv
  fire.geojson / fire.csv
  water.geojson / water.csv
config.example.yaml
requirements.txt
```

---

## Quickstart

### Prerequisites

- Python 3.9+
- SerpAPI key (free tier: 250 searches/month)
- Ollama Cloud key (pay-per-use, low volume)

### Local setup

```bash
git clone https://github.com/YOUR_USERNAME/climatewire.git
cd climatewire

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

cp config.example.yaml config.yaml
# Edit config.yaml — add your API keys

# Test a wire (10 articles, no file writes)
python src/heat/main.py --test
python src/drought/main.py --test
python src/fire/main.py --test
python src/water/main.py --test

# Real run
python src/heat/main.py
```

---

## GitHub Actions setup

1. Push repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `SERPAPI_KEY` | Your SerpAPI key |
| `OLLAMA_API_KEY` | Your Ollama Cloud key |
| `USER_AGENT` | `yourname@example.com` (required by Nominatim) |

3. Go to **Actions → any wire → Run workflow** to trigger a test run

All four wires run automatically on their own schedules, committing updated data files back to the repo.

---

## Output format

### GeoJSON (`data/{wire}.geojson`)

Standard FeatureCollection. Each feature has a `geometry.coordinates` point and a `properties` object with all fields listed below.

### CSV (`data/{wire}.csv`)

Same fields, plus `lat` and `lon` columns. Load with pandas:

```python
import pandas as pd
import geopandas as gpd

df  = pd.read_csv("data/heat.csv")
gdf = gpd.read_file("data/heat.geojson")
```

### Common fields (all wires)

| Field | Description |
|---|---|
| `article_id` | URL (dedup key) |
| `title` | Article headline |
| `snippet` | Article excerpt |
| `url` | Full article URL |
| `source` | News outlet name |
| `published_at` | Publication timestamp |
| `wire` | Wire name (`heat`, `drought`, `fire`, `water`) |
| `event_type` | Classified event subtype |
| `mention_text` | Location string that was geocoded |
| `lat`, `lon` | WGS84 coordinates |
| `osm_display` | Nominatim display name |
| `run_at` | Pipeline run timestamp |

### Wire-specific sensor fields

**heatwire**: `sensor_temp_f`, `sensor_rh_pct`, `sensor_wind_mph`, `sensor_solar_wm2`, `wbgt_f`, `wbgt_flag` (`green`/`yellow`/`red`/`black`/`black_plus`)

**droughtwire**: `usdm_dm_category` (0–4), `usdm_dm_label` (D0–D4), `usdm_in_drought`

**firewire**: `firms_dist_km`, `firms_frp_mw`, `firms_brightness`, `firms_acq_datetime`, `firms_confidence`, `firms_active_fire_nearby`

**waterwire**: `usgs_streamflow_cfs`, `usgs_streamflow_site_no`, `usgs_gw_depth_ft`, `usgs_gw_site_no`

---

## API keys & costs

| Service | Used by | Free tier | Key needed |
|---|---|---|---|
| SerpAPI | All wires | 250 searches/month | Yes |
| Ollama Cloud | All wires | Pay-per-use | Yes |
| OSM Nominatim | All wires | Free, 1 req/sec | No (set `user_agent`) |
| Open-Meteo | heatwire | Free, unlimited | No |
| NOAA USDM | droughtwire | Free shapefile | No |
| NASA FIRMS | firewire | Free CSV | No |
| USGS Water Services | waterwire | Free REST API | No |

At 1 run/day with ~50 articles/run across 4 wires:
- SerpAPI: 12 calls/day = **~360/month** (within 250 free at low volume; upgrade if needed)
- Ollama: ~200 calls/day — check [ollama.com/pricing](https://ollama.com/pricing)

---

## CLI reference

```bash
python src/{wire}/main.py                 # last 24h, full run
python src/{wire}/main.py --test          # 10 articles, no file writes
python src/{wire}/main.py --no-screen     # skip Ollama screening
python src/{wire}/main.py --config /path/to/cfg.yaml
```

---

## Related projects

- [floodwire2](https://github.com/rmkenv/floodwire2) — flood news ETL (same architecture, this repo extends it)
- [wbgt](https://github.com/rmkenv/wbgt) — WBGT forecast dashboard (sensor logic reused in heatwire)

---

## License

MIT
