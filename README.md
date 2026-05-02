# QuantAgri — Spectral Velocity Engine

> Agricultural futures intelligence powered by **Ollama Cloud** (qwen2.5), **Planetary Computer** (Sentinel-2), and **GitHub Actions**.

No database. No Docker. No server. Flat files + free APIs.

## What It Produces

| Output | Cadence | Location |
|---|---|---|
| NDVI/LSWI spectral indices | Nightly | `data/ndvi/` |
| Trading signals (all commodities) | Nightly | `data/signals/latest.json` |
| Weekly Intelligence Newsletter | Every Monday 07:00 UTC | `data/newsletter/` |
| Monthly Podcast Script | 1st of each month | `data/podcast/` |

## Architecture

```
Planetary Computer (Sentinel-2 L2A)
        │  scripts/pc_pipeline.py
        ▼
data/ndvi/{commodity}_{region}_{date}.json
        │  scripts/generate_signals.py
        ▼
data/signals/latest.json
        │  scripts/newsletter.py (weekly)
        │  scripts/podcast.py    (monthly)
        ▼
data/newsletter/YYYY-MM-DD.md
data/podcast/YYYY-MM.md
        │
        ▼
index.html  ←  GitHub Pages dashboard
```

## Setup

### 1. Fork and clone

```bash
git clone https://github.com/YOUR_USERNAME/quantagri.git
cd quantagri
```

### 2. Add GitHub Secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Where to get it |
|---|---|
| `OLLAMA_API_KEY` | ollama.com → Settings → API Keys |

### 3. Enable GitHub Pages

**Settings → Pages → Source: Deploy from branch → main → / (root)**

Dashboard live at: `https://YOUR_USERNAME.github.io/quantagri`

### 4. Trigger first run

**Actions → QuantAgri Nightly → Run workflow**

### 5. Local development

```bash
pip install -r requirements.txt
cp .env.example .env          # add your OLLAMA_API_KEY
python scripts/pc_pipeline.py
python scripts/generate_signals.py
python scripts/newsletter.py
python scripts/podcast.py
```

## Commodity Nodes

| Commodity | Regions |
|---|---|
| Soybeans | Iowa US · Mato Grosso BR · Illinois US · Buenos Aires AR |
| Corn | Iowa US · Mato Grosso BR · Heilongjiang CN |
| Wheat | Kansas US · Rostov RU · Saskatchewan CA · Grand Est FR |
| Sugar | São Paulo BR · Uttar Pradesh IN |
| Cotton | Texas US · Xinjiang CN |

## License

MIT
