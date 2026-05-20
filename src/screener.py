from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from . import config


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
    data = yf.download(
        tickers=symbols,
        period=config.HISTORY_LOOKBACK,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
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
        info = yf.Ticker(symbol).info or {}
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


def _row_for_symbol(symbol: str, hist: pd.DataFrame) -> dict | None:
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

    pe = _fetch_pe(symbol)
    return {
        "ticker": symbol,
        "price": float(close.iloc[-1]),
        "pe": pe,
        "volume_ratio": vol_ratio,
        "rsi": rsi,
        "sparkline": close.iloc[-SPARKLINE_DAYS:].tolist(),
    }


def scan(symbols: Iterable[str]) -> pd.DataFrame:
    """Pull history, compute indicators for every ticker, return one row per usable ticker.

    No filtering or ranking is done here — the UI applies thresholds so changing
    a slider does not trigger a re-fetch.
    """
    symbols = list(symbols)
    histories: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), config.BATCH_SIZE):
        chunk = symbols[i : i + config.BATCH_SIZE]
        histories.update(_download_history(chunk))

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_row_for_symbol, sym, histories.get(sym)): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row is not None:
                rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=["ticker", "price", "pe", "volume_ratio", "rsi", "sparkline"]
        )
    return pd.DataFrame(rows)


def filter_and_rank(
    df: pd.DataFrame,
    pe_max: float,
    volume_multiplier_min: float,
    rsi_min: float,
    top_n: int,
) -> pd.DataFrame:
    """Apply screening thresholds and return the top N ranked by RSI desc."""
    if df.empty:
        return df
    mask = (
        df["pe"].notna()
        & (df["pe"] > 0)
        & (df["pe"] < pe_max)
        & (df["volume_ratio"] > volume_multiplier_min)
        & (df["rsi"] > rsi_min)
    )
    return df[mask].sort_values("rsi", ascending=False).head(top_n).reset_index(drop=True)
