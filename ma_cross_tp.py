"""SMA 8 həm SMA 21-i, həm SMA 30-u kəsəndə ticarət, TP = 100 pips.

BUY: SMA8 hər iki xəttin üstünə çıxdığı ilk şam (əvvəlki şamda ən azı birinin altında idi)
SELL: əksinə. Giriş — siqnal şamının bağlanışı. Hər cütdə eyni anda 1 ticarət.
Bir şamda həm SL, həm TP mümkündürsə — ehtiyatla ZƏRƏR sayılır. Spred çıxılır.

İstifadə:  python ma_cross_tp.py
"""
import sys

import numpy as np
import pandas as pd

import config
from ma_test import POINT, mt5_frames
from strategy import pip_size

TP_PIPS = 100
SL_VARIANTS = {"SL 30": 30, "SL 50": 50, "SL 100": 100, "SL yox (əks siqnalda bağla)": None}


def signals(df):
    c = df.close
    f, m, s = c.rolling(8).mean(), c.rolling(21).mean(), c.rolling(30).mean()
    above = (f > m) & (f > s)
    below = (f < m) & (f < s)
    buy = above & ~above.shift(1, fill_value=False)
    sell = below & ~below.shift(1, fill_value=False)
    valid = s.notna() & s.shift(1).notna()
    return np.where(buy & valid, 1, np.where(sell & valid, -1, 0))


def simulate(df, sym, sl_pips):
    pip = pip_size(sym)
    sig = signals(df)
    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    spread = (df.spread.to_numpy() * POINT(sym)) / pip
    trades, i, n = [], 0, len(df)
    while i < n:
        if sig[i] == 0:
            i += 1
            continue
        side, entry = sig[i], close[i]
        tp = entry + side * TP_PIPS * pip
        sl = entry - side * sl_pips * pip if sl_pips else None
        result, j = None, i + 1
        while j < n:
            hit_sl = sl is not None and (lo[j] <= sl if side == 1 else hi[j] >= sl)
            hit_tp = hi[j] >= tp if side == 1 else lo[j] <= tp
            if hit_sl:
                result = -sl_pips; break
            if hit_tp:
                result = TP_PIPS; break
            if sl is None and sig[j] == -side:          # əks siqnal: bağla
                result = side * (close[j] - entry) / pip; break
            j += 1
        if result is None:
            break                                       # hələ açıqdır
        trades.append({"time": df.index[i], "pips": result - spread[i], "bars": j - i})
        i = j if sl is None else j + 1                  # əks siqnalda bağlananda həmin siqnalla yenidən gir
    return pd.DataFrame(trades)


def summarize(t):
    if t.empty:
        return dict(ticarət=0)
    gain, loss = t.pips[t.pips > 0].sum(), -t.pips[t.pips < 0].sum()
    eq = t.pips.cumsum()
    streak = cur = 0
    for p in t.pips:
        cur = cur + 1 if p < 0 else 0
        streak = max(streak, cur)
    return dict(ticarət=len(t), qazanc_pct=round((t.pips > 0).mean() * 100, 1),
                net_pips=round(t.pips.sum()), pf=round(gain / loss, 2) if loss else np.inf,
                max_geriləmə_pips=round((eq.cummax() - eq).max()), max_ardıcıl_itki=streak,
                orta_müddət_şam=round(t.bars.mean()))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    rows = []
    for tf, bars in [("H1", 20000), ("H4", 6000), ("D1", 1500)]:
        frames = mt5_frames(tf, bars)
        for sym, df in frames.items():
            for name, sl in SL_VARIANTS.items():
                t = simulate(df, sym, sl)
                s = summarize(t)
                rows.append({"qrafik": tf, "variant": name, "cüt": sym,
                             "dövr": f"{df.index[0]:%Y-%m}…{df.index[-1]:%Y-%m}", **s})
    res = pd.DataFrame(rows)
    res.to_csv("ma_cross_tp_results.csv", index=False)
    total = res.groupby(["qrafik", "variant"]).agg(
        ticarət=("ticarət", "sum"), net_pips=("net_pips", "sum"),
        qazanc_pct=("qazanc_pct", "mean"), müsbət_cüt=("net_pips", lambda x: f"{(x > 0).sum()}/{len(x)}"))
    print("CƏMİ (8 cüt):")
    print(total.to_string())
    print("\nCütlər üzrə net pips:")
    print(res.pivot_table(index=["qrafik", "variant"], columns="cüt", values="net_pips").to_string())
    print("\nDövrlər:", res.groupby("qrafik").dövr.first().to_dict())
    best = res.sort_values("net_pips", ascending=False).head(5)
    print("\nƏn yaxşı 5 nəticə (detallı):")
    print(best.to_string(index=False))


if __name__ == "__main__":
    main()
