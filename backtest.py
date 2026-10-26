"""Strategiyanın keçmiş məlumatlar üzərində sınağı (MT5 tarixçəsi).

İstifadə:  python backtest.py            # son 2 il
           python backtest.py --years 1

Qaydalar canlı botla eynidir (strategy.py). Hər siqnal üçün sonrakı H1 şamlarında
əvvəlcə SL-ə, yoxsa TP-yə çatıldığı yoxlanılır. Bir şamda hər ikisi mümkündürsə,
ehtiyatla ZƏRƏR sayılır. Spred (MT5 tarixçəsindən) və svop (swaps.json) çıxılır.
"""
import argparse
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
import swaps
from indicators import add_indicators
from strategy import TF_DURATION, pip_size

BARS = {"H1": 20000, "H4": 6000, "D1": 1500, "W1": 300, "MN1": 120}


def load(symbol):
    import MetaTrader5 as mt5
    frames = {}
    for tf in config.TIMEFRAMES:
        rates = mt5.copy_rates_from_pos(mt5_data.broker_symbol(symbol), mt5_data.TF_MAP[tf], 0, BARS[tf])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        frames[tf] = add_indicators(df.set_index("time").iloc[:-1])
    return frames


def bias(df):
    """strategy.tf_bias-ın vektor variantı: hər şam üçün -4..+4 bal və istiqamət."""
    votes = [
        (df["close"] > df["ema_slow"]).where(df["ema_slow"].notna()),
        (df["ema_fast"] > df["ema_mid"]).where(df["ema_mid"].notna()),
        (df["macd_hist"] > 0).where(df["macd_hist"].notna()),
        (df["rsi"] > 50).where(df["rsi"].notna()),
    ]
    score = sum(v.map({True: 1, False: -1}).fillna(0) for v in votes).astype(int)
    return np.where(score >= 2, 1, np.where(score <= -2, -1, 0))


def signals(frames):
    """Hər H1 şamı üçün siqnal: +1 BUY, -1 SELL, 0 yoxdur."""
    h1 = frames["H1"].copy()
    h1["close_time"] = h1.index + TF_DURATION["H1"]
    dirs = {}
    for tf, df in frames.items():
        b = pd.DataFrame({"dir": bias(df)}, index=df.index)
        b["close_time"] = df.index + TF_DURATION[tf]
        merged = pd.merge_asof(h1[["close_time"]].reset_index(), b.sort_values("close_time"),
                               on="close_time", direction="backward")
        dirs[tf] = merged["dir"].fillna(0).to_numpy()

    p, c = h1.shift(1), h1
    up = ((p.ema_fast <= p.ema_mid) & (c.ema_fast > c.ema_mid)) | ((p.macd <= p.macd_signal) & (c.macd > c.macd_signal))
    dn = ((p.ema_fast >= p.ema_mid) & (c.ema_fast < c.ema_mid)) | ((p.macd >= p.macd_signal) & (c.macd < c.macd_signal))
    buy = up & c.rsi.between(*config.RSI_BUY_RANGE)
    sell = ~buy & dn & c.rsi.between(*config.RSI_SELL_RANGE)
    side = np.where(buy, 1, np.where(sell, -1, 0))

    for tf in config.FILTER_TFS:
        side = np.where(dirs[tf] == side, side, 0)
    strength = sum((dirs[tf] == side).astype(int) for tf in config.TIMEFRAMES)
    side = np.where(strength >= config.MIN_STRENGTH, side, 0)
    h1["side"], h1["strength"] = side, strength
    return h1


def simulate(symbol, h1, start, swap_info):
    pip = pip_size(symbol)
    hi, lo, close = h1.high.to_numpy(), h1.low.to_numpy(), h1.close.to_numpy()
    spread = h1.spread.to_numpy() * {"XAUUSD": 0.01}.get(symbol, 0.001 if "JPY" in symbol else 0.00001)
    times = h1.index
    trades = []
    for i in np.flatnonzero((h1.side.to_numpy() != 0) & (times >= start)):
        side, entry, atr = h1.side.iat[i], close[i], h1.atr.iat[i]
        sl = entry - side * atr * config.SL_ATR_MULT
        tp = entry + side * atr * config.TP_ATR_MULT
        result = None
        for j in range(i + 1, len(h1)):
            hit_sl = lo[j] <= sl if side == 1 else hi[j] >= sl
            hit_tp = hi[j] >= tp if side == 1 else lo[j] <= tp
            if hit_sl or hit_tp:
                result = ("SL", sl) if hit_sl else ("TP", tp)
                break
        if result is None:
            continue    # hələ açıqdır
        exit_price = result[1]
        gross = side * (exit_price - entry) / pip
        cost = spread[i] / pip
        nights = max(0, (times[j].normalize() - times[i].normalize()).days)
        swap_usd = 0.0
        if swap_info:
            swap_usd = (swap_info["long"] if side == 1 else swap_info["short"]) * nights
        risk = atr * config.SL_ATR_MULT / pip
        trades.append({
            "symbol": symbol, "time": times[i], "side": "BUY" if side == 1 else "SELL",
            "result": result[0], "pips": gross - cost, "R": (gross - cost) / risk,
            "hours": j - i, "nights": nights, "swap_usd": swap_usd,
        })
    return trades


def max_losing_streak(results):
    best = cur = 0
    for r in results:
        cur = cur + 1 if r == "SL" else 0
        best = max(best, cur)
    return best


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--csv", default="backtest_trades.csv")
    args = ap.parse_args()

    mt5_data.connect()
    sw = (swaps.load() or {}).get("symbols", {})
    all_trades = []
    try:
        for symbol in config.SYMBOLS:
            frames = load(symbol)
            h1 = signals(frames)
            start = h1.index[-1] - pd.Timedelta(days=365 * args.years)
            all_trades += simulate(symbol, h1, start, sw.get(symbol))
    finally:
        mt5_data.shutdown()

    t = pd.DataFrame(all_trades).sort_values("time")
    t.to_csv(args.csv, index=False)
    rows = []
    for name, g in list(t.groupby("symbol")) + [("CƏMİ", t)]:
        wins = (g.result == "TP").sum()
        gain, loss = g.R[g.R > 0].sum(), -g.R[g.R < 0].sum()
        rows.append({
            "Cüt": name, "Siqnal": len(g), "Qazanc %": round(100 * wins / len(g), 1),
            "Net R": round(g.R.sum(), 1), "Net pips": round(g.pips.sum()),
            "Profit factor": round(gain / loss, 2) if loss else float("inf"),
            "Max ardıcıl itki": max_losing_streak(g.result),
            "Orta müddət (saat)": round(g.hours.mean()),
            "Svop $/1 lot": round(g.swap_usd.sum()),
        })
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nDövr: {t.time.min():%Y-%m-%d} — {t.time.max():%Y-%m-%d}")
    t["year"] = t.time.dt.year
    print("\nİllər üzrə (Net R):", t.groupby("year").R.sum().round(1).to_dict())
    print("Aylar üzrə: müsbət ay", (t.groupby(t.time.dt.to_period("M")).R.sum() > 0).sum(),
          "/", t.time.dt.to_period("M").nunique())
    eq = t.R.cumsum()
    print("Ən böyük geriləmə (R):", round((eq.cummax() - eq).max(), 1))


if __name__ == "__main__":
    main()
