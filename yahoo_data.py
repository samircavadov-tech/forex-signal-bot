"""Yahoo Finance məlumat mənbəyi (MT5 olmadan, buludda işləmək üçün).
mt5_data.py ilə eyni funksiyaları təqdim edir."""
import logging
import time

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# Yahoo-da adı fərqli olan simvollar (spot qızıl yoxdur — qızıl fyuçersi istifadə olunur)
TICKERS = {"XAUUSD": "GC=F"}
PRICE_NOTES = {"XAUUSD": "Qiymət qızıl fyuçersindəndir (spotdan fərqlidir) — "
                         "SL/TP-ni brokerdəki qiymətə məsafə ilə tətbiq edin."}

# tf -> (yahoo interval, period, şamın müddəti)
SOURCES = {
    "H1": ("1h", "200d", pd.Timedelta(hours=1)),
    "H4": ("1h", "200d", pd.Timedelta(hours=4)),     # 1h-dən yığılır
    "D1": ("1d", "5y", pd.Timedelta(days=1)),
    "W1": ("1wk", "10y", pd.Timedelta(weeks=1)),
    "MN1": ("1mo", "max", pd.offsets.MonthBegin(1)),
}
CACHE_TTL = 60
_cache = {}


def connect():
    log.info("Məlumat mənbəyi: Yahoo Finance")


def shutdown():
    pass


def prepare_symbol(symbol: str) -> bool:
    return True


def digits(symbol: str) -> int:
    if symbol == "XAUUSD":
        return 2
    return 3 if "JPY" in symbol else 5


def _download(symbol: str, interval: str, period: str) -> pd.DataFrame | None:
    key = (symbol, interval)
    if key in _cache and time.time() - _cache[key][0] < CACHE_TTL:
        return _cache[key][1]
    ticker = TICKERS.get(symbol, symbol + "=X")
    df = yf.download(ticker, interval=interval, period=period, progress=False,
                     auto_adjust=False, multi_level_index=False)
    if df is None or df.empty:
        return None
    df = df.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    _cache[key] = (time.time(), df)
    return df


def get_closed_bars(symbol: str, tf: str) -> pd.DataFrame | None:
    """Yalnız BAĞLANMIŞ şamları qaytarır (vaxtlar UTC)."""
    interval, period, duration = SOURCES[tf]
    df = _download(symbol, interval, period)
    if df is None:
        log.warning("%s %s üçün məlumat yoxdur", symbol, tf)
        return None
    if tf == "H4":
        df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    closed = df[df.index + duration <= now]
    return closed if len(closed) >= 3 else None
