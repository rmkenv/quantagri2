"""
heat/sensor_join.py — fetch Open-Meteo forecast at a geocoded point and
compute WBGT (Wet Bulb Globe Temperature). Appends sensor fields to each row.

Formula:  WBGT = 0.7*Tnwb + 0.2*Tg + 0.1*Tdb   (Liljegren et al. 2008)
Tnwb via Stull 2011 empirical approximation.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import logging
import math
import requests
from typing import List, Optional

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WBGT flag thresholds in °F (US Army TB MED 507)
FLAGS = [
    ("black_plus", 90),
    ("black",      88),
    ("red",        85),
    ("yellow",     80),
    ("green",       0),
]


# ---------------------------------------------------------------------------
# physics helpers
# ---------------------------------------------------------------------------

def _stull_wet_bulb(T_c: float, rh: float) -> float:
    """Natural wet bulb temperature (°C) via Stull 2011."""
    return (
        T_c * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(T_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def _globe_temp(T_c: float, wind_ms: float, solar_wm2: float) -> float:
    """Simplified globe temperature (°C), Liljegren et al. 2008."""
    # Clamp wind to avoid div/zero
    wind_ms = max(wind_ms, 0.1)
    return T_c + 0.0212 * solar_wm2 - 2.6 * wind_ms + 0.5


def _wbgt_c(T_c: float, rh: float, wind_ms: float, solar_wm2: float) -> float:
    Tnwb = _stull_wet_bulb(T_c, rh)
    Tg   = _globe_temp(T_c, wind_ms, solar_wm2)
    return 0.7 * Tnwb + 0.2 * Tg + 0.1 * T_c


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _wbgt_flag(wbgt_f: float) -> str:
    for flag, threshold in FLAGS:
        if wbgt_f >= threshold:
            return flag
    return "green"


# ---------------------------------------------------------------------------
# Open-Meteo fetch
# ---------------------------------------------------------------------------

def _fetch_current(lat: float, lon: float) -> Optional[dict]:
    """Fetch current-hour Open-Meteo variables at lat/lon."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relativehumidity_2m,windspeed_10m,shortwave_radiation",
        "forecast_days": 1,
        "timezone": "auto",
    }
    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        # Return last available hour (most recent complete)
        h = data["hourly"]
        idx = -1
        return {
            "T_c":        h["temperature_2m"][idx],
            "rh":         h["relativehumidity_2m"][idx],
            "wind_ms":    h["windspeed_10m"][idx] / 3.6,  # km/h → m/s
            "solar_wm2":  h["shortwave_radiation"][idx],
            "obs_time":   h["time"][idx],
        }
    except Exception as e:
        logger.warning(f"Open-Meteo error at ({lat},{lon}): {e}")
        return None


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def join_sensor(rows: List[dict]) -> List[dict]:
    """
    For each geocoded row, fetch Open-Meteo and append WBGT fields.
    Rows without sensor data are kept but with null sensor fields.
    """
    enriched = []
    for row in rows:
        lat = row.get("lat")
        lon = row.get("lon")
        obs = _fetch_current(lat, lon) if (lat and lon) else None

        if obs:
            wbgt_c = _wbgt_c(obs["T_c"], obs["rh"], obs["wind_ms"], obs["solar_wm2"])
            wbgt_f = _c_to_f(wbgt_c)
            row["sensor_obs_time"]  = obs["obs_time"]
            row["sensor_temp_f"]    = round(_c_to_f(obs["T_c"]), 1)
            row["sensor_rh_pct"]    = obs["rh"]
            row["sensor_wind_mph"]  = round(obs["wind_ms"] * 2.237, 1)
            row["sensor_solar_wm2"] = obs["solar_wm2"]
            row["wbgt_f"]           = round(wbgt_f, 1)
            row["wbgt_flag"]        = _wbgt_flag(wbgt_f)
        else:
            for k in ("sensor_obs_time","sensor_temp_f","sensor_rh_pct",
                      "sensor_wind_mph","sensor_solar_wm2","wbgt_f","wbgt_flag"):
                row[k] = None

        enriched.append(row)

    return enriched
