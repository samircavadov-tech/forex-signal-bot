"""Çox-timeframe analiz və BUY/SELL siqnal məntiqi."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config


TF_DURATION = {
    "H1": pd.Timedelta(hours=1), "H4": pd.Timedelta(hours=4), "D1": pd.Timedelta(days=1),
    "W1": pd.Timedelta(weeks=1), "MN1": pd.offsets.MonthBegin(1),
}


def frames_as_of(frames: dict, entry_bar: pd.Timestamp) -> dict:
    """Keçmiş bir giriş şamı üçün: o şam bağlananda artıq bağlanmış olan şamları saxlayır."""
    close_time = entry_bar + TF_DURATION[config.ENTRY_TF]
    return {tf: df[df.index + TF_DURATION[tf] <= close_time] for tf, df in frames.items()}


def pip_size(symbol: str) -> float:
    if symbol == "XAUUSD":
        return 0.1
    return 0.01 if "JPY" in symbol else 0.0001


@dataclass
class TFBias:
    tf: str
    score: int          # -4 .. +4
    direction: str      # "BUY", "SELL", "NEUTRAL"
    rsi: float
    details: list = field(default_factory=list)


@dataclass
class Signal:
    symbol: str
    side: str           # "BUY" / "SELL"
    price: float
    sl: float
    tp: float
    strength: int       # razı olan TF sayı
    trigger: str
    bar_time: pd.Timestamp
    biases: list
    note: str = ""


def tf_bias(tf: str, df: pd.DataFrame) -> TFBias:
    """Son bağlanmış şam üzrə trend istiqaməti."""
    row = df.iloc[-1]
    score, details = 0, []

    def vote(cond, name):
        nonlocal score
        if pd.isna(cond):
            return
        score += 1 if cond else -1
        details.append(f"{name}{'↑' if cond else '↓'}")

    vote(row["close"] > row["ema_slow"] if pd.notna(row["ema_slow"]) else float("nan"), "EMA200")
    vote(row["ema_fast"] > row["ema_mid"] if pd.notna(row["ema_mid"]) else float("nan"), "EMA20/50")
    vote(row["macd_hist"] > 0 if pd.notna(row["macd_hist"]) else float("nan"), "MACD")
    vote(row["rsi"] > 50 if pd.notna(row["rsi"]) else float("nan"), "RSI")

    direction = "BUY" if score >= 2 else "SELL" if score <= -2 else "NEUTRAL"
    return TFBias(tf, score, direction, float(row["rsi"]) if pd.notna(row["rsi"]) else float("nan"), details)


def entry_trigger(df: pd.DataFrame):
    """Giriş qrafikində son bağlanmış şamda təzə kəsişmə varmı?"""
    cur, prev = df.iloc[-1], df.iloc[-2]
    triggers = {"BUY": [], "SELL": []}

    if prev["ema_fast"] <= prev["ema_mid"] and cur["ema_fast"] > cur["ema_mid"]:
        triggers["BUY"].append("EMA20 EMA50-ni yuxarı kəsdi")
    if prev["ema_fast"] >= prev["ema_mid"] and cur["ema_fast"] < cur["ema_mid"]:
        triggers["SELL"].append("EMA20 EMA50-ni aşağı kəsdi")
    if prev["macd"] <= prev["macd_signal"] and cur["macd"] > cur["macd_signal"]:
        triggers["BUY"].append("MACD siqnal xəttini yuxarı kəsdi")
    if prev["macd"] >= prev["macd_signal"] and cur["macd"] < cur["macd_signal"]:
        triggers["SELL"].append("MACD siqnal xəttini aşağı kəsdi")

    r = cur["rsi"]
    if triggers["BUY"] and config.RSI_BUY_RANGE[0] <= r <= config.RSI_BUY_RANGE[1]:
        return "BUY", ", ".join(triggers["BUY"])
    if triggers["SELL"] and config.RSI_SELL_RANGE[0] <= r <= config.RSI_SELL_RANGE[1]:
        return "SELL", ", ".join(triggers["SELL"])
    return None, None


def analyze(symbol: str, frames: dict, digits: int):
    """frames: {tf: indikatorlu DataFrame (yalnız bağlanmış şamlar)}.
    Qaytarır: (Signal və ya None, biases siyahısı)."""
    biases = [tf_bias(tf, frames[tf]) for tf in config.TIMEFRAMES if tf in frames]
    entry_df = frames[config.ENTRY_TF]
    side, trigger = entry_trigger(entry_df)
    if not side:
        return None, biases

    by_tf = {b.tf: b for b in biases}
    if any(by_tf[tf].direction != side for tf in config.FILTER_TFS if tf in by_tf):
        return None, biases

    strength = sum(1 for b in biases if b.direction == side)
    if strength < config.MIN_STRENGTH:
        return None, biases

    last = entry_df.iloc[-1]
    price, a = float(last["close"]), float(last["atr"])
    sign = 1 if side == "BUY" else -1
    sl = round(price - sign * a * config.SL_ATR_MULT, digits)
    tp = round(price + sign * a * config.TP_ATR_MULT, digits)
    return Signal(symbol, side, round(price, digits), sl, tp, strength, trigger,
                  entry_df.index[-1], biases), biases


def ma_cross_signals(df: pd.DataFrame, fast=8, mid=21, slow=30) -> np.ndarray:
    """SMA fast həm mid-i, həm slow-u kəsdiyi ilk şam: +1 BUY, -1 SELL, 0 yox."""
    c = df["close"]
    f, m, s = c.rolling(fast).mean(), c.rolling(mid).mean(), c.rolling(slow).mean()
    above = (f > m) & (f > s)
    below = (f < m) & (f < s)
    buy = above & ~above.shift(1, fill_value=False)
    sell = below & ~below.shift(1, fill_value=False)
    valid = s.notna() & s.shift(1).notna()
    return np.where(buy & valid, 1, np.where(sell & valid, -1, 0))
