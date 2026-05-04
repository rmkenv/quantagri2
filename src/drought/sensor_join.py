"""
drought/sensor_join.py — join geocoded articles against the current
NOAA US Drought Monitor (USDM) weekly shapefile.

USDM publishes a fresh shapefile every Thursday at:
https://droughtmonitor.unl.edu/data/shapefiles/...
The file is free, no API key needed.

Drought categories:
  D0 = Abnormally Dry
  D1 = Moderate Drought
  D2 = Severe Drought
  D3 = Extreme Drought
  D4 = Exceptional Drought

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import io
import logging
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

USDM_BASE = "https://droughtmonitor.unl.edu/data/shapefiles/us"
CACHE_PATH = Path(".cache/usdm_current.zip")

DM_LABELS = {
    -1: "none",
    0: "D0_abnormally_dry",
    1: "D1_moderate",
    2: "D2_severe",
    3: "D3_extreme",
    4: "D4_exceptional",
}


def _latest_usdm_url():
    """USDM releases every Tuesday (valid through following Monday). Find last Tuesday."""
    today = date.today()
    days_since_tuesday = (today.weekday() - 1) % 7
    last_tuesday = today - timedelta(days=days_since_tuesday)
    date_str = last_tuesday.strftime("%Y%m%d")
    return "{}/USDM_{}.zip".format(USDM_BASE, date_str), date_str


def _download_usdm(cache: bool = True) -> Optional[bytes]:
    url, date_str = _latest_usdm_url()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if cache and CACHE_PATH.exists():
        logger.info("USDM: using cached shapefile")
        return CACHE_PATH.read_bytes()

    logger.info("USDM: downloading %s", url)
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if cache:
            CACHE_PATH.write_bytes(r.content)
        return r.content
    except requests.exceptions.Timeout:
        logger.error("USDM download timeout for %s", url)
        return None
    except Exception as e:
        logger.error("USDM download failed: %s", e)
        return None


def _load_geodataframe(zip_bytes: bytes):
    """Load USDM shapefile from zip bytes into a GeoDataFrame."""
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            shp_names = [n for n in zf.namelist() if n.endswith(".shp")]
            if not shp_names:
                return None
            # Write all shapefile components to a temp dir
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                shp_path = os.path.join(tmp, shp_names[0])
                gdf = gpd.read_file(shp_path)
        return gdf
    except ImportError:
        logger.warning("geopandas not installed — drought sensor join unavailable")
        return None
    except Exception as e:
        logger.error(f"USDM shapefile load error: {e}")
        return None


def _dm_category_at_point(gdf, lat: float, lon: float) -> int:
    """Return DM category (0-4) at lat/lon, or -1 if outside drought area."""
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        hits = gdf[gdf.geometry.contains(pt)]
        if hits.empty:
            return -1
        # DM column is 'DM' in USDM shapefiles
        return int(hits.iloc[0]["DM"])
    except Exception as e:
        logger.debug(f"Point-in-polygon error: {e}")
        return -1


# Module-level GDF cache so we only load once per run
_GDF = None


def _get_gdf():
    global _GDF
    if _GDF is None:
        zip_bytes = _download_usdm()
        if zip_bytes:
            _GDF = _load_geodataframe(zip_bytes)
    return _GDF


def join_sensor(rows: List[dict]) -> List[dict]:
    """
    Append USDM drought category fields to each geocoded row.
    """
    gdf = _get_gdf()
    enriched = []

    for row in rows:
        lat = row.get("lat")
        lon = row.get("lon")

        if gdf is not None and lat and lon:
            cat = _dm_category_at_point(gdf, lat, lon)
            row["usdm_dm_category"]   = cat
            row["usdm_dm_label"]      = DM_LABELS.get(cat, "unknown")
            row["usdm_in_drought"]    = cat >= 0
        else:
            row["usdm_dm_category"] = None
            row["usdm_dm_label"]    = None
            row["usdm_in_drought"]  = None

        enriched.append(row)

    return enriched
