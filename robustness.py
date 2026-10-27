"""D1 SMA kəsişmə strategiyasının dayanıqlıq yoxlaması: yaxın parametrlər də qazanc verirmi?

Şəbəkə: sürətli SMA × (orta, yavaş) SMA × TP × SL, 7 valyuta cütü, Yahoo D1 2004–2026.
Hər kombinasiya üçün: cəmi pips, 3 dövrün neçəsi müsbət, 7 cütün neçəsi müsbət.

İstifadə:  python robustness.py
"""
import itertools
import sys

import numpy as np
import pandas as pd

import research as R
from strategy import ma_cross_signals, pip_size

FAST = [5, 8, 10, 13]
SLOW_PAIRS = [(21, 30), (20, 50), (21, 55)]
TPS = [60, 80, 100, 150]
SLS = [20, 30, 40, 50]
PERIODS = [("2004", "2014"), ("2015", "2020"), ("2021", "2026")]


def simulate(df, sym, sig, tp_pips, sl_pips):
    pip = pip_size(sym)
    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    cost = R.SPREAD[sym]
    out, i, n = [], 0, len(df)
    idx = np.flatnonzero(sig != 0)
    for i in idx:
        if out and i <= out[-1][2]:
            continue                                   # hər cütdə eyni anda 1 ticarət
        side, entry = sig[i], close[i]
        tp, sl = entry + side * tp_pips * pip, entry - side * sl_pips * pip
        h, l = hi[i + 1:], lo[i + 1:]
        hit_sl = (l <= sl) if side == 1 else (h >= sl)
        hit_tp = (h >= tp) if side == 1 else (l <= tp)
        j_sl = hit_sl.argmax() if hit_sl.any() else n
        j_tp = hit_tp.argmax() if hit_tp.any() else n
        if j_sl == j_tp == n:
            break
        res = -sl_pips if j_sl <= j_tp else tp_pips
        out.append((df.index[i], res - cost, i + 1 + min(j_sl, j_tp)))
    return pd.DataFrame(out, columns=["time", "pips", "exit"])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    data = {s: d for s, d in R.load_daily().items() if s != "XAUUSD"}
    rows = []
    for fast, (mid, slow) in itertools.product(FAST, SLOW_PAIRS):
        sigs = {s: ma_cross_signals(df, fast, mid, slow) for s, df in data.items()}
        for tp, sl in itertools.product(TPS, SLS):
            trades = pd.concat([simulate(df, s, sigs[s], tp, sl).assign(sym=s) for s, df in data.items()])
            per = [trades[(trades.time >= a) & (trades.time < str(int(b) + 1))].pips.sum() for a, b in PERIODS]
            pair = trades.groupby("sym").pips.sum()
            rows.append(dict(sma=f"{fast}/{mid}/{slow}", tp=tp, sl=sl, ticarət=len(trades),
                             net_pips=round(trades.pips.sum()), pips_ticarət=round(trades.pips.mean(), 1),
                             müsbət_dövr=sum(p > 0 for p in per), müsbət_cüt=int((pair > 0).sum()),
                             qazanc_pct=round((trades.pips > 0).mean() * 100, 1)))
    res = pd.DataFrame(rows)
    res.to_csv("robustness_results.csv", index=False)
    print(f"Cəmi kombinasiya: {len(res)} | müsbət: {(res.net_pips > 0).sum()} | "
          f"3/3 dövr və ≥6/7 cüt müsbət: {((res.müsbət_dövr == 3) & (res.müsbət_cüt >= 6)).sum()}")
    print("\nSMA üzrə orta (bütün TP/SL):")
    print(res.groupby("sma").agg(net_orta=("net_pips", "mean"), müsbət=("net_pips", lambda x: f"{(x > 0).sum()}/{len(x)}"),
                                 möhkəm=("müsbət_dövr", lambda x: (x == 3).sum())).to_string())
    print("\nTP × SL üzrə orta net pips (bütün SMA):")
    print(res.pivot_table(index="sl", columns="tp", values="net_pips", aggfunc="mean").round(0).to_string())
    print("\nSMA 8/21/30 üçün TP × SL (net pips):")
    print(res[res.sma == "8/21/30"].pivot_table(index="sl", columns="tp", values="net_pips").to_string())
    print("\nƏn möhkəm 10 (3/3 dövr, cüt sayına və pips/ticarətə görə):")
    print(res[res.müsbət_dövr == 3].sort_values(["müsbət_cüt", "pips_ticarət"], ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
