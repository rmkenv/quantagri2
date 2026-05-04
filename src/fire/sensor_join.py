"""
fire/sensor_join.py — join geocoded articles against NASA FIRMS VIIRS
active fire detections (last 24h CSV, free, no API key needed for public feed).

FIRMS CSV endpoint:
  https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/
  SUOMI_VIIRS_C2_USA_contiguous_and_Hawaii_24h.csv

Each article is matched to the nearest active fire detection within
MAX_DIST_KM. Fire Radiative Power (FRP, MW) is the primary intensity field.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import csv
import io
import logging
import math
from pathlib import Path
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

FIRMS_URL = (
    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/"
    "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_USA_contiguous_and_Hawaii_24h.csv"
)
MAX_DIST_KM = 100.0   # search radius
CACHE_PATH = Path(".cache/firms_viirs_24h.csv")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _download_firms(cache: bool = True) -> Optional[List[dict]]:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if cache and CACHE_PATH.exists():
        logger.info("FIRMS: using cached CSV")
        with open(CACHE_PATH, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    logger.info("FIRMS: downloading %s", FIRMS_URL)
    try:
        r = requests.get(FIRMS_URL, timeout=60)
        r.raise_for_status()
        text = r.text
        if cache:
            CACHE_PATH.write_text(text, encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        logger.debug("FIRMS: loaded %d detections", len(rows))
        return rows
    except requests.exceptions.Timeout:
        logger.error("FIRMS download timeout")
        return None
    except Exception as e:
        logger.error("FIRMS download failed: %s", e)
        return None


def _nearest_fire(detections: List[dict], lat: float, lon: float) -> Optional[dict]:
    best = None
    best_dist = MAX_DIST_KM
    for d in detections:
        try:
            dlat = float(d["latitude"])
            dlon = float(d["longitude"])
        except (KeyError, ValueError):
            continue
        dist = _haversine_km(lat, lon, dlat, dlon)
        if dist < best_dist:
            best_dist = dist
            best = {**d, "dist_km": round(dist, 2)}
    return best


# Module-level cache
_DETECTIONS: list[dict] | None = None


def _get_detections():
    global _DETECTIONS
    if _DETECTIONS is None:
        _DETECTIONS = _download_firms()
    return _DETECTIONS


def join_sensor(rows: List[dict]) -> List[dict]:
    """
    Append nearest FIRMS VIIRS detection fields to each geocoded row.
    """
    detections = _get_detections()
    enriched = []

    for row in rows:
        lat = row.get("lat")
        lon = row.get("lon")

        if detections and lat and lon:
            hit = _nearest_fire(detections, lat, lon)
            if hit:
                row["firms_dist_km"]       = hit["dist_km"]
                row["firms_frp_mw"]        = float(hit.get("frp", 0) or 0)
                row["firms_brightness"]    = float(hit.get("bright_ti4", 0) or 0)
                row["firms_acq_datetime"]  = f"{hit.get('acq_date','')} {hit.get('acq_time','')}"
                row["firms_confidence"]    = hit.get("confidence", "")
                row["firms_daynight"]      = hit.get("daynight", "")
                row["firms_active_fire_nearby"] = True
            else:
                row["firms_dist_km"]            = None
                row["firms_frp_mw"]             = None
                row["firms_brightness"]         = None
                row["firms_acq_datetime"]       = None
                row["firms_confidence"]         = None
                row["firms_daynight"]           = None
                row["firms_active_fire_nearby"] = False
        else:
            for k in ("firms_dist_km","firms_frp_mw","firms_brightness",
                      "firms_acq_datetime","firms_confidence","firms_daynight",
                      "firms_active_fire_nearby"):
                row[k] = None

        enriched.append(row)

    return enriched
