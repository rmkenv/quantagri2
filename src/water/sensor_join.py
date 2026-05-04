"""
water/sensor_join.py — fetch nearest USGS gauge streamflow (00060) and
groundwater depth (72019) at a geocoded point via USGS Water Services REST API.
Free, no API key required.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import logging
import math
import requests
from typing import Optional

logger = logging.getLogger(__name__)

USGS_IV_URL   = "https://waterservices.usgs.gov/nwis/iv/"
USGS_SITE_URL = "https://waterservices.usgs.gov/nwis/site/"

SEARCH_RADIUS_DEG = 1.0   # ~110 km bounding box half-width
MAX_DIST_KM       = 80.0  # drop if nearest gauge is farther than this


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _find_nearest_gauge(lat: float, lon: float, param_cd: str) -> Optional[dict]:
    """
    Find the nearest USGS gauge that measures param_cd within SEARCH_RADIUS_DEG.
    Returns dict with site_no, station_nm, site_lat, site_lon, dist_km or None.
    """
    bbox = (
        f"{lon - SEARCH_RADIUS_DEG},"
        f"{lat - SEARCH_RADIUS_DEG},"
        f"{lon + SEARCH_RADIUS_DEG},"
        f"{lat + SEARCH_RADIUS_DEG}"
    )
    params = {
        "format": "rdb",
        "bBox": bbox,
        "parameterCd": param_cd,
        "siteStatus": "active",
        "hasDataTypeCd": "iv",
    }
    try:
        r = requests.get(USGS_SITE_URL, params=params, timeout=15)
        r.raise_for_status()
        lines = [l for l in r.text.splitlines() if not l.startswith("#") and l.strip()]
        # RDB: first line is header, second is type row, rest are data
        if len(lines) < 3:
            return None
        headers = lines[0].split("\t")
        best = None
        best_dist = MAX_DIST_KM
        for line in lines[2:]:
            parts = line.split("\t")
            if len(parts) < len(headers):
                continue
            row = dict(zip(headers, parts))
            try:
                slat = float(row.get("dec_lat_va", 0))
                slon = float(row.get("dec_long_va", 0))
            except ValueError:
                continue
            dist = _haversine_km(lat, lon, slat, slon)
            if dist < best_dist:
                best_dist = dist
                best = {
                    "site_no":    row.get("site_no", "").strip(),
                    "station_nm": row.get("station_nm", "").strip(),
                    "site_lat":   slat,
                    "site_lon":   slon,
                    "dist_km":    round(dist, 2),
                }
        return best
    except Exception as e:
        logger.debug(f"USGS site search error: {e}")
        return None


def _fetch_latest_value(site_no: str, param_cd: str) -> Optional[float]:
    """Fetch most recent instantaneous value for site + parameter."""
    params = {
        "format": "json",
        "sites": site_no,
        "parameterCd": param_cd,
        "siteStatus": "active",
    }
    try:
        r = requests.get(USGS_IV_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        ts_list = data["value"]["timeSeries"]
        if not ts_list:
            return None
        values = ts_list[0]["values"][0]["value"]
        if not values:
            return None
        return float(values[-1]["value"])
    except Exception as e:
        logger.debug(f"USGS IV error site={site_no} param={param_cd}: {e}")
        return None


def join_sensor(rows: list) -> list:
    """
    Append nearest USGS streamflow + groundwater fields to each geocoded row.
    """
    enriched = []

    for row in rows:
        lat = row.get("lat")
        lon = row.get("lon")

        if lat and lon:
            # --- streamflow (00060, cfs) ---
            sf_gauge = _find_nearest_gauge(lat, lon, "00060")
            if sf_gauge:
                sf_val = _fetch_latest_value(sf_gauge["site_no"], "00060")
                row["usgs_streamflow_site_no"] = sf_gauge["site_no"]
                row["usgs_streamflow_name"]    = sf_gauge["station_nm"]
                row["usgs_streamflow_dist_km"] = sf_gauge["dist_km"]
                row["usgs_streamflow_cfs"]     = sf_val
            else:
                row["usgs_streamflow_site_no"] = None
                row["usgs_streamflow_name"]    = None
                row["usgs_streamflow_dist_km"] = None
                row["usgs_streamflow_cfs"]     = None

            # --- groundwater depth (72019, ft below land surface) ---
            gw_gauge = _find_nearest_gauge(lat, lon, "72019")
            if gw_gauge:
                gw_val = _fetch_latest_value(gw_gauge["site_no"], "72019")
                row["usgs_gw_site_no"]   = gw_gauge["site_no"]
                row["usgs_gw_name"]      = gw_gauge["station_nm"]
                row["usgs_gw_dist_km"]   = gw_gauge["dist_km"]
                row["usgs_gw_depth_ft"]  = gw_val
            else:
                row["usgs_gw_site_no"]  = None
                row["usgs_gw_name"]     = None
                row["usgs_gw_dist_km"]  = None
                row["usgs_gw_depth_ft"] = None
        else:
            for k in ("usgs_streamflow_site_no","usgs_streamflow_name",
                      "usgs_streamflow_dist_km","usgs_streamflow_cfs",
                      "usgs_gw_site_no","usgs_gw_name","usgs_gw_dist_km","usgs_gw_depth_ft"):
                row[k] = None

        enriched.append(row)

    return enriched
