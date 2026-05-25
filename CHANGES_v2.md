# QuantAgri v2 — Change Log & Migration Guide

## What changed and why

### 1. LSWI now uses B8A + B11 (true SWIR-based leaf water index)

**File:** `scripts/pc_pipeline.py`  
**Why:** v1 used `(B3 − B8) / (B3 + B8)` which is NDWI (Gao 1996), sensitive to chlorophyll
as well as water — not a clean hydric signal. v2 uses `(B8A − B11) / (B8A + B11)` (Xiao et al. 2002
LSWI), which responds directly to leaf water potential and is the correct index for detecting
moisture stress ahead of visible canopy decline. Both B8A and B11 are native 20 m resolution,
so no resampling artefacts. **RESOLUTION changed from 60 m → 20 m** to match B8A/B11 native.

```python
# v1 (wrong)
lswi = ((b8 - b3) / (b8 + b3 + eps)).clip(-1.0, 1.0)

# v2 (correct)
b8a  = stack.sel(band="B8A").astype("float32") / 10000.0
b11  = stack.sel(band="B11").astype("float32") / 10000.0
lswi = ((b8a - b11) / (b8a + b11 + eps)).clip(-1.0, 1.0)
```

---

### 2. MODIS baseline z-score normalization

**New files:** `scripts/build_modis_baseline.py`, `scripts/compute_zscore.py`  
**Why:** Raw velocity values are not comparable across regions or years — a value of +0.08 in
a wet June means something different than +0.08 in a dry June. Z-scoring against the 2000–2015
MODIS MOD13Q1 climatological distribution converts raw derivatives into anomaly signals.
A z-score of −1.5 means "1.5 standard deviations below the historical mean for this region
and time of year" — physically interpretable and cross-region comparable.

**Run once (or annually):**
```bash
python scripts/build_modis_baseline.py
```

**Run each season:**
```bash
python scripts/compute_zscore.py --years 2024
```

---

### 3. Expanded region coverage

**File:** `scripts/config.py`  
**New nodes added:**

| Commodity | New regions |
|---|---|
| Corn | Illinois, Indiana, Minnesota, Nebraska, Ohio |
| Soybeans | Indiana, Minnesota, Nebraska |
| Wheat | Oklahoma, Colorado |

This brings the US corn analysis from 1 region (Iowa) to 6 regions, enabling pooled
cross-region correlations with n = 54+ season-observations.

---

### 4. Tightened phenological gate windows

**File:** `scripts/config.py` → `PHENO_GATES`  
**Why:** v1 used Jun–Jul for soybeans — too early. Soybean yield is set during R1–R6
(reproductive stages), which falls in **Aug–Sep** in the US Corn Belt.

| Crop | v1 window | v2 window | Reason |
|---|---|---|---|
| Corn | Jun–Jul | Jun–Jul–Aug (DOY 155–218) | Extended to capture R1–R4 |
| **Soybeans** | **Jun–Jul** | **Aug–Sep (DOY 210–265)** | **Fixed: R1–R6 is yield-critical** |
| Wheat (US) | Apr–May | Apr–May–Jun (DOY 110–155) | Extended to heading/soft dough |
| Cotton | Jun–Jul | Jun–Jul–Aug (DOY 170–240) | Boll development window |

---

### 5. Central finite difference velocity (was np.gradient)

**File:** `scripts/pc_pipeline.py` → `central_diff()`  
**Why:** `np.gradient` uses forward differencing at array edges, which artificially inflates
velocity at the first and last composite — exactly the positions where the seasonal signal
transitions. Central differences are more accurate for interior points and use first-order
differences only at genuine boundaries.

---

### 6. Yield trend detrending + LOOCV validation

**New file:** `scripts/correlation_analysis.py`  
**Why:** Raw yield correlation is confounded by the secular technology trend (~1–2 bu/ac/yr
for corn). Detrending isolates the weather/spectral signal. LOOCV provides honest small-n
validation: train on n−1 seasons, predict the held-out season, report mean absolute error.

```bash
python scripts/correlation_analysis.py \
  --yields data/official_yields.csv \
  --years 2016 2017 2018 2019 2020 2021 2022 2023 2024
```

---

### 7. Historical backfill via workflow_dispatch

**File:** `.github/workflows/nightly.yml`  
**How:** Go to Actions → QuantAgri v2 Pipeline → Run workflow → enter years in
`backfill_years` field (e.g. `2016 2017 2018 2019 2020 2021 2022 2023`). The workflow
runs `pc_pipeline.py --years ...` followed by `compute_zscore.py --years ...` for all
specified years, then commits results to `data/`.

---

### 8. Signal prompt uses z-scores

**File:** `scripts/generate_signals.py`  
The LLM prompt now receives `vel_zscore`, `lswi_zscore`, and `dominant_quadrant` from the
z-score file, giving the model physically interpretable anomaly context rather than raw
spectral values it cannot benchmark.

---

## Migration steps for existing deployment

1. **Delete** `data/ndvi/*.json` (v1 used B3 not B11 — LSWI values are wrong)
2. **Run** `python scripts/build_modis_baseline.py` (once, ~30 min with PC access)
3. **Run** `python scripts/pc_pipeline.py --years 2016 2017 2018 2019 2020 2021 2022 2023 2024`
4. **Run** `python scripts/compute_zscore.py --years 2016 2017 2018 2019 2020 2021 2022 2023 2024`
5. Commit `data/baseline/` and `data/signals/*_zscore.json` to repo
6. From now on the daily cron handles steps 3–4 for the current year automatically

## No changes required to

- `scripts/fetch_prices.py`
- `scripts/newsletter.py`
- `scripts/rs_newsletter.py`
- `scripts/podcast.py`
- `scripts/fetch_rs_news.py`
- `scripts/ollama_client.py`
- `src/` directory (drought/fire/heat/water modules)
