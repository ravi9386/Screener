# Momentum + Value Stock Screener

Near-real-time screener for **NSE (Nifty 500)** and **US (Nasdaq 100)** universes.
Pulls quotes from yfinance, computes technical indicators, and shows a ranked
leaderboard in a Streamlit dashboard.

## Screening rules

A ticker passes when **all three** are true (defaults, adjustable in the UI):

- **P/E (trailing)** less than `20`
- **Volume** of the latest session greater than `2.0×` the prior 20-day average
- **RSI(14)** (Wilder's) greater than `50`

Survivors are ranked by RSI descending and the top **N** (default 25) are
displayed. Each row also shows a 30-day price sparkline.

The sidebar exposes sliders for **P/E max**, **Volume multiplier**, **RSI min**,
and **Top N**. Slider changes re-filter the most recent scan **without
re-fetching** — only the underlying scan respects the 60-second cache.

## Local setup

```powershell
git clone https://github.com/ravi9386/Screener.git
cd Screener
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run locally

```powershell
streamlit run app.py
```

The app serves at **http://localhost:8501**. Use the sidebar to switch between
**NSE (Nifty 500)** and **US (Nasdaq 100)**. The leaderboard auto-refreshes
every **60 seconds**; toggle it off or click **Refresh now** for manual
control.

To use a different port:

```powershell
streamlit run app.py --server.port 8600
```

## Deploy to Streamlit Community Cloud (free public hosting)

This repo is preconfigured for Streamlit Cloud — no edits needed.

1. Go to https://share.streamlit.io and sign in with your GitHub account.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Pick the repo `ravi9386/Screener`, branch `main`, main file `app.py`.
4. Click **Deploy**. First build takes 1–2 minutes (installs from
   `requirements.txt`, pins Python via `runtime.txt`).
5. You'll get a public URL like `https://<your-slug>.streamlit.app`. That URL
   is permanent.

### Point a custom domain at the deployed app

Streamlit Cloud lets you map a custom (sub)domain to the app via a CNAME.

1. In your Streamlit Cloud app dashboard → **Settings** → **Custom subdomain**
   (or **Custom domain** depending on UI version).
2. Add e.g. `screener.yourdomain.com`.
3. At your DNS provider (Cloudflare, Namecheap, GoDaddy, etc.), create a
   **CNAME** record:
   ```
   Host:   screener
   Type:   CNAME
   Value:  <your-slug>.streamlit.app
   TTL:    Auto (or 3600)
   ```
4. Wait 5–30 minutes for DNS propagation. Streamlit Cloud auto-provisions a
   TLS cert once propagation completes.

> **Note**: a Streamlit app needs a Python runtime — it CANNOT be hosted on
> GitHub Pages. If your root domain already points at GitHub Pages (e.g. for a
> static site), use a subdomain like `screener.yourdomain.com` for this app.

### Alternative hosts

If you prefer a different platform, the repo also works as-is on:
- **Render.com** — add a `web` service, build `pip install -r requirements.txt`,
  start `streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`.
- **Hugging Face Spaces** — choose Streamlit SDK, point at this repo.
- **Railway / Fly.io / any container host** — `python:3.11-slim` base, install
  `requirements.txt`, run the same start command as Render above.

## Project layout

```
Screener/
├── app.py                  # Streamlit UI + auto-refresh loop
├── requirements.txt
├── runtime.txt             # pins Python 3.11 for Streamlit Cloud
├── .streamlit/
│   └── config.toml         # headless server + dark theme
├── CLAUDE.md
├── README.md
├── src/
│   ├── __init__.py
│   ├── config.py           # thresholds, refresh interval, paths
│   └── screener.py         # yfinance fetch + indicator math + filter
└── tickers/
    ├── nifty500.csv        # NSE universe (.NS-suffixed symbols)
    └── nasdaq100.csv       # US universe
```

## Notes & caveats

- **Not tick data.** Free yfinance feeds are delayed roughly 15 minutes for
  both NSE and US equities. The 60-second refresh cadence is for catching new
  end-of-bar signals, not intraday tick-by-tick action.
- **Rate limits.** A full Nifty 500 scan can take 30–60 seconds. If yfinance
  starts throttling, you'll see fewer matches or warnings in the status banner.
  Bump `REFRESH_SECONDS` in `src/config.py` if this happens.
- **Missing P/E.** Many tickers (loss-making companies, REITs, some new
  listings) return `None` for trailing P/E. Those rows are filtered out rather
  than treated as passes.
- **Nifty 500 list.** The bundled `tickers/nifty500.csv` contains ~586 NSE
  tickers (a buffered superset so renamed/delisted symbols still leave full
  Nifty 500 coverage). Replace it with a fresh dump anytime — only requirement
  is a `symbol` column with `.NS`-suffixed tickers.

## Tuning

Edit `src/config.py` to change thresholds, RSI period, refresh cadence, or the
ranked-result count.
