"""
QuantAgri — Shared Configuration
All commodity nodes, season windows, and output paths live here.
"""

from pathlib import Path

# ── Repo root ─────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
NDVI_DIR = DATA_DIR / "ndvi"
SIG_DIR  = DATA_DIR / "signals"
NEWS_DIR = DATA_DIR / "newsletter"
POD_DIR  = DATA_DIR / "podcast"

for d in (NDVI_DIR, SIG_DIR, NEWS_DIR, POD_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Ollama Cloud ──────────────────────────────────────────────────────
OLLAMA_ENDPOINT = "https://ollama.com/api/chat"
DEFAULT_MODEL   = "qwen2.5:7b"

# ── Planetary Computer ────────────────────────────────────────────────
PC_STAC_URL  = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION   = "sentinel-2-l2a"
MAX_CLOUD_PCT = 25
RESOLUTION   = 60          # metres (use 10 for production, 60 for CI speed)

# ── Commodity nodes ───────────────────────────────────────────────────
# bbox = [lon_min, lat_min, lon_max, lat_max]
NODES = [
    # ── Soybeans ──
    dict(commodity="Soybeans", region="Iowa_US",          bbox=[-96.7, 40.5, -90.1, 43.5]),
    dict(commodity="Soybeans", region="Mato_Grosso_BR",   bbox=[-61.0, -18.0, -50.0,  -7.0]),
    dict(commodity="Soybeans", region="Illinois_US",      bbox=[-91.5, 37.0, -87.5,  42.5]),
    dict(commodity="Soybeans", region="Buenos_Aires_AR",  bbox=[-63.0, -39.0, -57.0, -33.0]),
    # ── Corn ──
    dict(commodity="Corn",     region="Iowa_US",          bbox=[-96.7, 40.5, -90.1,  43.5]),
    dict(commodity="Corn",     region="Mato_Grosso_BR",   bbox=[-61.0, -18.0, -50.0,  -7.0]),
    dict(commodity="Corn",     region="Heilongjiang_CN",  bbox=[125.0,  44.0, 135.0,  53.0]),
    # ── Wheat ──
    dict(commodity="Wheat",    region="Kansas_US",        bbox=[-102.0, 37.0, -94.6,  40.0]),
    dict(commodity="Wheat",    region="Rostov_RU",        bbox=[38.0,  46.0,  44.5,  48.5]),
    dict(commodity="Wheat",    region="Saskatchewan_CA",  bbox=[-110.0, 49.0, -101.0, 55.0]),
    dict(commodity="Wheat",    region="Grand_Est_FR",     bbox=[3.5,   47.5,   8.2,  49.5]),
    # ── Sugar ──
    dict(commodity="Sugar",    region="Sao_Paulo_BR",     bbox=[-53.1, -25.3, -44.2, -19.8]),
    dict(commodity="Sugar",    region="Uttar_Pradesh_IN", bbox=[77.0,  25.0,  84.5,  28.5]),
    # ── Cotton ──
    dict(commodity="Cotton",   region="Texas_US",         bbox=[-106.6, 25.8, -93.5,  36.5]),
    dict(commodity="Cotton",   region="Xinjiang_CN",      bbox=[73.5,  36.0,  96.5,  49.0]),
]

# ── Growing season windows by commodity ───────────────────────────────
SEASONS = {
    "Soybeans": ("04", "10"),
    "Corn":     ("04", "10"),
    "Wheat":    ("03", "08"),
    "Sugar":    ("04", "11"),
    "Cotton":   ("04", "11"),
}

# ── Unique commodity list ─────────────────────────────────────────────
COMMODITIES = ["Soybeans", "Corn", "Wheat", "Sugar", "Cotton"]

# ── ETFs tracked in newsletter ────────────────────────────────────────
ETFS = ["CORN", "SOYB", "WEAT", "CANE", "TAGS", "DBA"]
