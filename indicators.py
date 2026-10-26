import pandas as pd

import config


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    df["ema_fast"] = ema(c, config.EMA_FAST)
    df["ema_mid"] = ema(c, config.EMA_MID)
    df["ema_slow"] = ema(c, config.EMA_SLOW)
    df["rsi"] = rsi(c, config.RSI_PERIOD)
    macd_line = ema(c, config.MACD_FAST) - ema(c, config.MACD_SLOW)
    df["macd"] = macd_line
    df["macd_signal"] = macd_line.ewm(span=config.MACD_SIGNAL, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["atr"] = atr(df, config.ATR_PERIOD)
    return df
