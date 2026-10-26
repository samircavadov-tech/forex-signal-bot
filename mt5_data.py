import logging

import MetaTrader5 as mt5
import pandas as pd

import config

log = logging.getLogger(__name__)

TF_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1, "MN1": mt5.TIMEFRAME_MN1,
}
# Böyük qrafiklərdə serverdə olmayan qədər şam istəmək MT5-i ilişdirir.
BARS = {"W1": 300, "MN1": 120}
DEFAULT_BARS = 400


def connect():
    kwargs = {"timeout": 30000}
    if config.MT5_PATH:
        kwargs["path"] = config.MT5_PATH
    if config.MT5_LOGIN:
        kwargs.update(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER)
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MetaTrader 5-ə qoşulmaq olmadı: {mt5.last_error()}")
    info = mt5.account_info()
    log.info("MT5 qoşuldu: %s (%s)", info.server if info else "?", info.login if info else "?")


def shutdown():
    mt5.shutdown()


def broker_symbol(symbol: str) -> str:
    return symbol + config.SYMBOL_SUFFIX


def prepare_symbol(symbol: str) -> bool:
    name = broker_symbol(symbol)
    if not mt5.symbol_select(name, True):
        log.error("Simvol tapılmadı: %s (SYMBOL_SUFFIX-i yoxlayın)", name)
        return False
    return True


def digits(symbol: str) -> int:
    info = mt5.symbol_info(broker_symbol(symbol))
    return info.digits if info else 5


def get_closed_bars(symbol: str, tf: str) -> pd.DataFrame | None:
    """Yalnız BAĞLANMIŞ şamları qaytarır (cari, hələ formalaşan şam atılır)."""
    rates = mt5.copy_rates_from_pos(broker_symbol(symbol), TF_MAP[tf], 0, BARS.get(tf, DEFAULT_BARS))
    if rates is None or len(rates) < 3:
        log.warning("%s %s üçün məlumat yoxdur: %s", symbol, tf, mt5.last_error())
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.set_index("time").iloc[:-1]
