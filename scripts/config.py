"""
QuantAgri v2 — Shared Configuration
=====================================
Changes from v1:
  - Added 4 new Corn Belt states (Indiana, Minnesota, Nebraska, Ohio)
  - Added Oklahoma + Colorado for wheat
  - LSWI now computed from B8A + B11 (true SWIR-based, not B3)
  - MODIS baseline years / DOY windows defined here for z-score module
  - Phenological gate windows tightened per crop physiology
  - RESOLUTION bumped to 20 m for production (was 60)
"""

from pathlib import Path

# ── Repo root ─────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent
DATA_DIR     = ROOT / "data"
NDVI_DIR     = DATA_DIR / "ndvi"
SIG_DIR      = DATA_DIR / "signals"
NEWS_DIR     = DATA_DIR / "newsletter"
POD_DIR      = DATA_DIR / "podcast"
BASELINE_DIR = DATA_DIR / "baseline"   # NEW: MODIS z-score baseline cache

for d in (NDVI_DIR, SIG_DIR, NEWS_DIR, POD_DIR, BASELINE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Ollama Cloud ──────────────────────────────────────────────────────
OLLAMA_ENDPOINT = "https://ollama.com/api/chat"
DEFAULT_MODEL   = "qwen2.5:7b"

# ── Planetary Computer ────────────────────────────────────────────────
PC_STAC_URL   = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION    = "sentinel-2-l2a"
MAX_CLOUD_PCT = 25
RESOLUTION    = 20   # metres — 20 m uses B8A (narrow NIR) which aligns with B11 SWIR for true LSWI

# ── MODIS baseline ────────────────────────────────────────────────────
# MOD13Q1 (250 m, 16-day NDVI composites) pulled for 2000-2015.
# Used to compute per-region, per-DOY velocity mean + std → z-scores.
MODIS_COLLECTION     = "modis-13Q1-061"   # PC STAC collection name
MODIS_BASELINE_START = "2000-01-01"
MODIS_BASELINE_END   = "2015-12-31"

# ── Commodity nodes ───────────────────────────────────────────────────
# bbox = [lon_min, lat_min, lon_max, lat_max]
# CHANGE: Illinois added to Corn; Indiana, Minnesota, Nebraska, Ohio added.
#         Oklahoma + Colorado added for Wheat.
#         B03 removed from assets — LSWI now uses B8A + B11 only.
NODES = [
    # ── Soybeans ──────────────────────────────────────────────────────
    dict(commodity="Soybeans", region="Iowa_US",          bbox=[-96.7, 40.5, -90.1,  43.5]),
    dict(commodity="Soybeans", region="Illinois_US",      bbox=[-91.5, 37.0, -87.5,  42.5]),
    dict(commodity="Soybeans", region="Indiana_US",       bbox=[-88.1, 37.8, -84.8,  41.8]),   # NEW
    dict(commodity="Soybeans", region="Minnesota_US",     bbox=[-97.2, 43.5, -89.5,  49.0]),   # NEW
    dict(commodity="Soybeans", region="Nebraska_US",      bbox=[-104.0, 40.0, -95.3, 43.0]),   # NEW
    dict(commodity="Soybeans", region="Mato_Grosso_BR",   bbox=[-61.0, -18.0, -50.0, -7.0]),
    dict(commodity="Soybeans", region="Buenos_Aires_AR",  bbox=[-63.0, -39.0, -57.0, -33.0]),

    # ── Corn ──────────────────────────────────────────────────────────
    dict(commodity="Corn",     region="Iowa_US",          bbox=[-96.7, 40.5, -90.1,  43.5]),
    dict(commodity="Corn",     region="Illinois_US",      bbox=[-91.5, 37.0, -87.5,  42.5]),   # NEW
    dict(commodity="Corn",     region="Indiana_US",       bbox=[-88.1, 37.8, -84.8,  41.8]),   # NEW
    dict(commodity="Corn",     region="Minnesota_US",     bbox=[-97.2, 43.5, -89.5,  49.0]),   # NEW
    dict(commodity="Corn",     region="Nebraska_US",      bbox=[-104.0, 40.0, -95.3, 43.0]),   # NEW
    dict(commodity="Corn",     region="Ohio_US",          bbox=[-84.8, 38.4, -80.5,  42.3]),   # NEW
    dict(commodity="Corn",     region="Mato_Grosso_BR",   bbox=[-61.0, -18.0, -50.0, -7.0]),
    dict(commodity="Corn",     region="Heilongjiang_CN",  bbox=[125.0,  44.0, 135.0,  53.0]),

    # ── Wheat ─────────────────────────────────────────────────────────
    dict(commodity="Wheat",    region="Kansas_US",        bbox=[-102.0, 37.0, -94.6,  40.0]),
    dict(commodity="Wheat",    region="Oklahoma_US",      bbox=[-103.0, 33.6, -94.4,  37.0]),  # NEW
    dict(commodity="Wheat",    region="Colorado_US",      bbox=[-109.1, 37.0, -102.0, 41.0]),  # NEW
    dict(commodity="Wheat",    region="Rostov_RU",        bbox=[38.0,   46.0,  44.5,  48.5]),
    dict(commodity="Wheat",    region="Saskatchewan_CA",  bbox=[-110.0, 49.0, -101.0, 55.0]),
    dict(commodity="Wheat",    region="Grand_Est_FR",     bbox=[3.5,    47.5,   8.2,  49.5]),

    # ── Sugar ─────────────────────────────────────────────────────────
    dict(commodity="Sugar",    region="Sao_Paulo_BR",     bbox=[-53.1, -25.3, -44.2, -19.8]),
    dict(commodity="Sugar",    region="Uttar_Pradesh_IN", bbox=[77.0,   25.0,  84.5,  28.5]),

    # ── Cotton ────────────────────────────────────────────────────────
    dict(commodity="Cotton",   region="Texas_US",         bbox=[-106.6, 25.8, -93.5,  36.5]),
    dict(commodity="Cotton",   region="Xinjiang_CN",      bbox=[73.5,   36.0,  96.5,  49.0]),
]

# ── Phenological gate windows (DOY = day of year) ─────────────────────
# CHANGE from v1: tightened to yield-critical windows per crop physiology.
#   Corn:     V6→R4   (DOY 155-218 = mid-Jun to early Aug)   was: Jun-Jul only
#   Soybeans: R1→R6   (DOY 210-265 = late Jul to late Sep)   was: Jun-Jul (too early!)
#   Wheat US: head→soft dough (DOY 110-155 = late Apr to early Jun)  was: Apr-May
#   Wheat RU: same window but shifted +14 days
#   Sugar:    grand growth (DOY 100-200)
#   Cotton:   boll dev (DOY 170-240)
PHENO_GATES = {
    "Corn":     {"doy_start": 155, "doy_end": 218, "months": [6, 7, 8]},
    "Soybeans": {"doy_start": 210, "doy_end": 265, "months": [8, 9]},       # FIXED: was [6,7]
    "Wheat":    {"doy_start": 110, "doy_end": 155, "months": [4, 5, 6]},
    "Sugar":    {"doy_start": 100, "doy_end": 200, "months": [4, 5, 6, 7]},
    "Cotton":   {"doy_start": 170, "doy_end": 240, "months": [6, 7, 8]},
}

# ── Growing season fetch windows (wider than gate — for context) ───────
SEASONS = {
    "Soybeans": ("04", "10"),
    "Corn":     ("04", "10"),
    "Wheat":    ("03", "07"),
    "Sugar":    ("04", "11"),
    "Cotton":   ("04", "11"),
}

COMMODITIES = ["Soybeans", "Corn", "Wheat", "Sugar", "Cotton"]

# ── ETFs tracked in newsletter ────────────────────────────────────────
ETFS = ["CORN", "SOYB", "WEAT", "CANE", "TAGS", "DBA"]
