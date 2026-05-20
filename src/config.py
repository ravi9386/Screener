from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TICKERS_DIR = ROOT / "tickers"

UNIVERSES = {
    "NSE (Nifty 500)": TICKERS_DIR / "nifty500.csv",
    "US (Nasdaq 100)": TICKERS_DIR / "nasdaq100.csv",
}

RSI_PERIOD = 14
VOLUME_AVG_WINDOW = 20
HISTORY_LOOKBACK = "3mo"

PE_MAX = 20.0
VOLUME_MULTIPLIER_MIN = 2.0
RSI_MIN = 50.0

TOP_N = 25
REFRESH_SECONDS = 60
BATCH_SIZE = 100

# Pre-filter thresholds applied INSIDE scan() before the expensive per-ticker
# P/E lookup. Anything outside these floors is dropped without hitting Yahoo's
# fundamentals endpoint. Keep these generous — they only exist to avoid
# wasting API budget on obviously uninteresting tickers.
PREFILTER_RSI_MIN = 30.0
PREFILTER_VOLUME_MIN = 1.0
INTER_BATCH_SLEEP = 0.5
