from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from . import config

# Version sentinel — bump on every push so the UI can prove which build is live.
# If the footer shows an older value than expected, Streamlit Cloud is serving
# stale bytecode; do a full delete+redeploy of the app.
__version__ = "0.3.0"

# Yahoo Finance blocks unauthenticated requests from datacenter IPs (Streamlit
# Cloud, Render, AWS, etc.) with HTTP 401. Routing yfinance through a
# curl_cffi session that impersonates Chrome bypasses most of those blocks.
# Falls back to default requests if curl_cffi isn't available.
try:
    from curl_cffi import requests as _cffi_requests

    _SESSION = _cffi_requests.Session(impersonate="chrome")
except Exception:  # pragma: no cover - graceful fallback for local dev
    _SESSION = None


def load_universe(csv_path: Path) -> list[str]:
    df = pd.read_csv(csv_path)
    return df["symbol"].dropna().astype(str).str.strip().tolist()


def wilder_rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> float:
    """Classic Wilder's RSI. Returns the most recent value, or NaN if insufficient data."""
    if len(close) < period + 1:
        return float("nan")
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def volume_ratio(volume: pd.Series, window: int = config.VOLUME_AVG_WINDOW) -> float:
    """Latest volume / average of the prior `window` sessions (excludes the latest bar)."""
    if len(volume) < window + 1:
        return float("nan")
    latest = float(volume.iloc[-1])
    prior_avg = float(volume.iloc[-(window + 1):-1].mean())
    if prior_avg <= 0:
        return float("nan")
    return latest / prior_avg


def _download_history(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Batch-download OHLCV. Returns a dict keyed by symbol."""
    kwargs = dict(
        tickers=symbols,
        period=config.HISTORY_LOOKBACK,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    if _SESSION is not None:
        kwargs["session"] = _SESSION
    data = yf.download(**kwargs)
    out: dict[str, pd.DataFrame] = {}
    if isinstance(data.columns, pd.MultiIndex):
        for sym in symbols:
            if sym in data.columns.get_level_values(0):
                df = data[sym].dropna(how="all")
                if not df.empty:
                    out[sym] = df
    else:
        if not data.empty and len(symbols) == 1:
            out[symbols[0]] = data.dropna(how="all")
    return out


def _fetch_pe(symbol: str) -> float:
    try:
        ticker = yf.Ticker(symbol, session=_SESSION) if _SESSION is not None else yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception:
        return float("nan")
    pe = info.get("trailingPE")
    if pe is None:
        pe = info.get("forwardPE")
    try:
        return float(pe) if pe is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


SPARKLINE_DAYS = 30
_EMPTY_COLUMNS = ["ticker", "price", "pe", "volume_ratio", "rsi", "sparkline"]


def _compute_indicators(symbol: str, hist: pd.DataFrame) -> dict | None:
    """Cheap, fully local — no API calls. Returns a row without P/E."""
    if hist is None or hist.empty or "Close" not in hist or "Volume" not in hist:
        return None
    close = hist["Close"].dropna()
    volume = hist["Volume"].dropna()
    if close.empty or volume.empty:
        return None

    rsi = wilder_rsi(close)
    vol_ratio = volume_ratio(volume)
    if np.isnan(rsi) or np.isnan(vol_ratio):
        return None

    return {
        "ticker": symbol,
        "price": float(close.iloc[-1]),
        "pe": float("nan"),  # filled in later, only for prefilter survivors
        "volume_ratio": vol_ratio,
        "rsi": rsi,
        "sparkline": close.iloc[-SPARKLINE_DAYS:].tolist(),
    }


def scan(symbols: Iterable[str]) -> pd.DataFrame:
    """Pull history, compute indicators, lazily fetch P/E only for prefilter survivors.

    Pipeline:
      1. Bulk-download OHLCV (batched, with a small inter-batch sleep).
      2. Compute RSI + volume_ratio entirely from OHLCV (no API).
      3. Drop anything below the generous prefilter floors (RSI/volume).
      4. Fetch P/E ONLY for the survivors — typically ~5% of the universe.

    The expensive per-ticker `.info` call is the main rate-limit pressure
    on Yahoo, so step 4 cuts API surface ~20× vs. fetching P/E for everyone.

    The UI applies the user's full filter thresholds on the returned frame,
    so slider changes never trigger a re-fetch within the cache TTL.
    """
    symbols = list(symbols)

    # Phase 1: bulk OHLCV
    histories: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), config.BATCH_SIZE):
        chunk = symbols[i : i + config.BATCH_SIZE]
        histories.update(_download_history(chunk))
        if i + config.BATCH_SIZE < len(symbols):
            time.sleep(config.INTER_BATCH_SLEEP)

    # Phase 2 + 3: compute indicators, drop weak signals
    candidates: list[dict] = []
    for sym in symbols:
        row = _compute_indicators(sym, histories.get(sym))
        if row is None:
            continue
        if row["rsi"] < config.PREFILTER_RSI_MIN:
            continue
        if row["volume_ratio"] < config.PREFILTER_VOLUME_MIN:
            continue
        candidates.append(row)

    if not candidates:
        return pd.DataFrame(columns=_EMPTY_COLUMNS)

    # Phase 4: fetch P/E only for prefilter survivors
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_row = {pool.submit(_fetch_pe, row["ticker"]): row for row in candidates}
        for fut in as_completed(future_to_row):
            row = future_to_row[fut]
            try:
                row["pe"] = fut.result()
            except Exception:
                row["pe"] = float("nan")

    return pd.DataFrame(candidates)


def filter_and_rank(
    df: pd.DataFrame,
    pe_max: float,
    volume_multiplier_min: float,
    rsi_min: float,
    top_n: int,
    require_pe: bool = False,
) -> pd.DataFrame:
    """Apply screening thresholds and return the top N ranked by RSI desc.

    When `require_pe=False` (default), tickers whose P/E lookup failed (NaN)
    still pass the filter — only tickers that actually have P/E data are
    constrained by `pe_max`. This is the realistic mode for cloud-hosted
    deployments where Yahoo's fundamentals endpoint is unreliable.

    When `require_pe=True`, strict mode: any ticker without P/E is dropped.
    """
    if df.empty:
        return df

    has_valid_pe = df["pe"].notna() & (df["pe"] > 0) & (df["pe"] < pe_max)
    if require_pe:
        pe_mask = has_valid_pe
    else:
        # Lax: accept NaN/zero/missing P/E too. Only constrain rows that have it.
        pe_mask = has_valid_pe | df["pe"].isna() | (df["pe"] <= 0)

    mask = pe_mask & (df["volume_ratio"] > volume_multiplier_min) & (df["rsi"] > rsi_min)
    return df[mask].sort_values("rsi", ascending=False).head(top_n).reset_index(drop=True)
