from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from src import config
from src import screener as screener_module
from src.screener import filter_and_rank, load_universe, scan

st.set_page_config(
    page_title="Momentum + Value Screener",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

st.title("Momentum + Value Screener")
st.caption("Ranked by RSI desc. Sliders re-filter the latest scan without re-fetching.")

with st.sidebar:
    st.header("Universe")
    universe_name = st.selectbox("Market", list(config.UNIVERSES.keys()))

    st.header("Thresholds")
    pe_max = st.slider("P/E max", min_value=5.0, max_value=50.0, value=float(config.PE_MAX), step=0.5)
    vol_min = st.slider(
        "Volume multiplier min (× 20d avg)",
        min_value=1.0,
        max_value=10.0,
        value=float(config.VOLUME_MULTIPLIER_MIN),
        step=0.1,
    )
    rsi_min = st.slider("RSI min", min_value=30.0, max_value=90.0, value=float(config.RSI_MIN), step=1.0)
    top_n = st.slider("Show top", min_value=5, max_value=100, value=config.TOP_N, step=5)
    require_pe = st.toggle(
        "Strict P/E (drop tickers with no P/E data)",
        value=False,
        help=(
            "Yahoo Finance's fundamentals endpoint is unreliable on cloud hosts. "
            "Leave OFF to let tickers without P/E data still appear (P/E filter "
            "only applies when data is available). Turn ON for strict screening."
        ),
    )

    st.header("Refresh")
    auto_refresh = st.toggle("Auto-refresh every 60s", value=True)
    if st.button("Refresh now"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.caption(
        "yfinance data is delayed (~15 min for NSE / free US data). "
        "This is a screener, not a tick feed."
    )

universe_path = config.UNIVERSES[universe_name]
symbols = load_universe(universe_path)
st.write(f"Scanning **{len(symbols)}** tickers from **{universe_name}**.")

status_slot = st.empty()
table_slot = st.empty()
footer_slot = st.empty()


@st.cache_data(ttl=config.REFRESH_SECONDS, show_spinner=False)
def cached_scan(universe_key: str, symbol_tuple: tuple[str, ...]) -> pd.DataFrame:
    return scan(list(symbol_tuple))


def render_once() -> None:
    with status_slot:
        st.info(f"Scanning {universe_name}… first run typically takes 20–60s.")
    started = time.time()
    raw = cached_scan(universe_name, tuple(symbols))
    elapsed = time.time() - started

    try:
        df = filter_and_rank(
            raw,
            pe_max=pe_max,
            volume_multiplier_min=vol_min,
            rsi_min=rsi_min,
            top_n=top_n,
            require_pe=require_pe,
        )
    except TypeError:
        # Streamlit Cloud is serving a stale cached version of src.screener
        # that doesn't have the require_pe kwarg yet. Fall back to the old
        # signature so the dashboard stays alive while you delete + redeploy.
        st.error(
            "⚠️ Streamlit Cloud is running stale bytecode for src/screener.py. "
            "Click **Manage app → ⋯ → Delete app**, then re-deploy from the same "
            "repo. The build shown in the footer below is the live one."
        )
        df = filter_and_rank(
            raw,
            pe_max=pe_max,
            volume_multiplier_min=vol_min,
            rsi_min=rsi_min,
            top_n=top_n,
        )

    with status_slot:
        if raw.empty:
            st.warning("yfinance returned no usable rows this cycle. It may be throttling.")
        elif df.empty:
            st.warning(
                f"Scanned {len(raw)} tickers in {elapsed:.1f}s — none passed the current filters. "
                f"Try loosening thresholds in the sidebar."
            )
        else:
            st.success(
                f"{len(df)} match(es) from {len(raw)} scanned tickers in {elapsed:.1f}s "
                f"— last updated {datetime.now().strftime('%H:%M:%S')}"
            )

    if not df.empty:
        display = df.copy()
        display.insert(0, "rank", range(1, len(display) + 1))
        display["price"] = display["price"].round(2)
        # P/E may be NaN when Yahoo's fundamentals endpoint refuses the request.
        # Keep it as a float column so column_config can format it; Streamlit
        # renders NaN as a blank cell, which reads cleanly as "no data".
        display["pe"] = display["pe"].round(2)
        display["volume_ratio"] = display["volume_ratio"].round(2)
        display["rsi"] = display["rsi"].round(2)
        display = display[["rank", "ticker", "price", "pe", "volume_ratio", "rsi", "sparkline"]]
        display.columns = ["Rank", "Ticker", "Price", "P/E", "Vol Ratio", "RSI", "30d Price"]
        pe_coverage = df["pe"].notna().sum()

        with table_slot:
            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "30d Price": st.column_config.LineChartColumn(
                        "30d Price",
                        help="Last ~30 daily closes",
                        width="medium",
                    ),
                    "RSI": st.column_config.ProgressColumn(
                        "RSI",
                        help=f"Wilder's RSI({config.RSI_PERIOD})",
                        min_value=0,
                        max_value=100,
                        format="%.2f",
                    ),
                    "Vol Ratio": st.column_config.NumberColumn(
                        "Vol Ratio",
                        help=f"Latest volume / {config.VOLUME_AVG_WINDOW}-day average",
                        format="%.2fx",
                    ),
                    "Price": st.column_config.NumberColumn("Price", format="%.2f"),
                    "P/E": st.column_config.NumberColumn(
                        "P/E",
                        help="Trailing P/E from Yahoo. Blank = unavailable (Yahoo blocks fundamentals on cloud IPs).",
                        format="%.2f",
                    ),
                },
            )
        if pe_coverage < len(df):
            st.caption(
                f"ℹ️ P/E available for {pe_coverage}/{len(df)} matches — Yahoo's fundamentals "
                f"endpoint is unreliable on cloud hosts. Toggle **Strict P/E** in the sidebar "
                f"to drop tickers without P/E data."
            )
    else:
        table_slot.empty()


render_once()
_screener_version = getattr(screener_module, "__version__", "pre-0.3.0 (STALE)")
footer_slot.caption(
    f"Build v{_screener_version}  •  Auto-refresh: {'ON' if auto_refresh else 'OFF'}  •  "
    f"Cache TTL: {config.REFRESH_SECONDS}s  •  Sliders re-filter instantly — only the scan itself respects the cache."
)

if auto_refresh:
    time.sleep(config.REFRESH_SECONDS)
    st.rerun()
