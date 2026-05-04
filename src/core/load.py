"""
core/load.py — append-only GeoJSON + CSV writer with dedup on article_id.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_existing_ids(csv_path: Path) -> set:
    """Return set of article_ids already in the CSV."""
    if not csv_path.exists():
        return set()
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {row["article_id"] for row in reader if row.get("article_id")}
    except Exception as e:
        logger.warning("Could not read existing CSV %s: %s", csv_path, e)
        return set()


def _rows_to_features(rows: List[dict]) -> List[dict]:
    """Convert flat dicts to GeoJSON Feature objects.

    Rows with null lat/lon are included as null-geometry features so they
    appear in GeoJSON tooling (QGIS, Tippecanoe, etc.) without crashing it.
    They are clearly marked with geocoded=False in properties.
    """
    features = []
    for r in rows:
        lat = r.get("lat")
        lon = r.get("lon")
        props = {k: v for k, v in r.items() if k not in ("lat", "lon")}
        if lat is not None and lon is not None:
            geometry = {"type": "Point", "coordinates": [lon, lat]}
        else:
            geometry = None  # valid GeoJSON null geometry
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": props,
        })
    return features


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def write_outputs(
    rows: List[dict],
    wire: str,
    data_dir,
) -> Tuple[int, int]:
    """
    Append new rows to data/<wire>.geojson and data/<wire>.csv.
    Deduplicates on article_id.

    Returns (new_rows_written, total_rows_in_file).
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    geojson_path = data_dir / "{}.geojson".format(wire)
    csv_path     = data_dir / "{}.csv".format(wire)

    # --- dedup ---
    existing_ids = _load_existing_ids(csv_path)
    new_rows = [r for r in rows if r.get("article_id") not in existing_ids]
    logger.debug("[%s] dedup: %d rows in, %d new", wire, len(rows), len(new_rows))

    if not new_rows:
        logger.info("[%s] no new rows to write", wire)
        return 0, len(existing_ids)

    run_at = datetime.now(timezone.utc).isoformat()
    for r in new_rows:
        r["run_at"] = run_at

    # --- CSV (append) ---
    all_keys = list(new_rows[0].keys())
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
        logger.debug("[%s] wrote %d rows to %s", wire, len(new_rows), csv_path)
    except Exception as e:
        logger.error("[%s] CSV write failed: %s", wire, e)

    # --- GeoJSON (rewrite full file) ---
    if geojson_path.exists():
        try:
            with open(geojson_path, encoding="utf-8") as f:
                existing_fc = json.load(f)
            existing_features = existing_fc.get("features", [])
        except Exception as e:
            logger.warning("[%s] Could not load existing GeoJSON: %s", wire, e)
            existing_features = []
    else:
        existing_features = []

    new_features = _rows_to_features(new_rows)
    all_features = existing_features + new_features

    fc = {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "wire":           wire,
            "last_updated":   run_at,
            "total_features": len(all_features),
        },
    }
    try:
        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump(fc, f, indent=2)
        logger.debug("[%s] wrote GeoJSON with %d features", wire, len(all_features))
    except Exception as e:
        logger.error("[%s] GeoJSON write failed: %s", wire, e)

    total = len(existing_ids) + len(new_rows)
    logger.info("[%s] wrote %d new rows (total %d)", wire, len(new_rows), total)
    return len(new_rows), total
