# Stock Screener — Momentum + Value

## Project
Near-real-time stock screener written in Python. Pulls quotes from yfinance,
computes technical indicators, filters by momentum + value rules, and renders
a ranked leaderboard in a Streamlit dashboard.

Two universes are supported:
- **NSE (India)** — Nifty 500 constituents (tickers suffixed `.NS`)
- **US (Nasdaq)** — Nasdaq 100 constituents (plain tickers)

## Screening rules
A ticker passes when ALL of the following are true:
- P/E ratio (trailing) < 20
- Latest day's volume > 2.0 × 20-day average volume
- RSI(14) > 50

Survivors are ranked by RSI descending and the top 25 are shown.

## Layout
- `app.py` — Streamlit entry point (UI + auto-refresh loop)
- `src/screener.py` — yfinance fetch, indicator math, filter pipeline
- `src/config.py` — thresholds, RSI period, vol window, refresh interval
- `tickers/nifty500.csv` — NSE universe (one symbol per line, with `.NS` suffix)
- `tickers/nasdaq100.csv` — US universe (one symbol per line)
- `requirements.txt` — pinned deps

## Common commands
```
pip install -r requirements.txt
streamlit run app.py            # serves on http://localhost:8501
```

## Rules
- Never hardcode file paths — use `pathlib.Path(__file__).parent` style.
- yfinance is **delayed ~15 min** for free NSE/US data. This is a screener,
  not a tick feed. Do not advertise it as live tick data.
- Be gentle on yfinance: batch tickers with `yf.download(..., group_by='ticker')`
  and cache per-ticker fundamentals (`Ticker.info`) for the refresh window.
- Handle missing/None P/E gracefully (many tickers return NaN or None) —
  exclude them from results rather than crashing.
- RSI uses Wilder's smoothing (the standard).
- Volume ratio = latest close volume / mean(volume of prior 20 sessions).

## Indicator math (canonical)
- **RSI(14)**: Wilder's exponential smoothing of up/down moves over 14 periods.
- **Volume avg**: simple mean of the prior 20 daily volumes (exclude the
  current bar from the average — otherwise the spike gets diluted into itself).
