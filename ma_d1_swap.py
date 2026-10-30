"""D1: SMA 8×21 və SMA 8×21×30 ("Samir") kəsişməsi, TP 5 və 10 pips, SL yox.
Yalnız svopu müsbət olan istiqamət (bugünkü cədvələ görə), hər cütdə eyni anda 1 ticarət.
Spred çıxılır, müsbət svop gəlirə əlavə olunur (gecə sayı ≈ təqvim günü). 0.01 lot, MT5 məlumatı.

İstifadə:  python ma_d1_swap.py
"""
import sys

import numpy as np
import pandas as pd

import config
from investaz_test import load, pip_value_usd
from strategy import ma_cross_signals

PAIRS = list(config.INVESTAZ)
LOT = 0.01
START_RECENT = "2025-04-11"


def cross821(df):
    c = df.close
    f, m = c.rolling(8).mean(), c.rolling(21).mean()
    up = (f > m) & (f.shift() <= m.shift())
    dn = (f < m) & (f.shift() >= m.shift())
    return np.where(up, 1, np.where(dn, -1, 0))


def pos_side(sym):
    _, long_sw, short_sw = config.INVESTAZ[sym]
    return (1, long_sw) if long_sw > 0 else (-1, short_sw)


def run(df, sym, sig, tp_pips, pv):
    pip = 0.01 if sym.endswith("JPY") else 0.0001
    spread = config.INVESTAZ[sym][0]
    side, swap_lot = pos_side(sym)
    hi, lo, close, t = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy(), df.index
    out, busy = [], -1
    for i in np.flatnonzero(sig == side):
        if i <= busy or i < 40:
            continue
        e = close[i]
        tp = e + side * tp_pips * pip
        h, l = hi[i + 1:], lo[i + 1:]
        hit = (h >= tp) if side == 1 else (l <= tp)
        j = hit.argmax() if hit.any() else None
        end = j if j is not None else len(h) - 1
        worst = ((l[:end + 1].min() - e) if side == 1 else (e - h[:end + 1].max())) / pip - spread
        pips = (tp_pips if j is not None else side * (close[-1] - e) / pip) - spread
        days = (t[i + 1 + end] - t[i]).days
        v = pv.iloc[i] * LOT
        out.append(dict(time=t[i], pips=pips, usd=pips * v, swap=swap_lot * LOT * days, days=days,
                        worst_usd=min(worst, 0) * v, open=j is None))
        busy = i + 1 + end if j is not None else len(df)
    return pd.DataFrame(out)


def summary(t, years):
    tot = t.usd + t.swap
    return dict(ticarət=len(t), TP_çatan=int((~t.open).sum()), açıq=int(t.open.sum()),
                orta_gün=round(t.days.mean(), 1), max_gün=int(t.days.max()),
                pips_AZN=round(t.usd.sum() * config.USD_AZN), svop_AZN=round(t.swap.sum() * config.USD_AZN),
                cəmi_AZN=round(tot.sum() * config.USD_AZN),
                AZN_il=round(tot.sum() * config.USD_AZN / years),
                ən_pis_üzən_AZN=round(t.worst_usd.min() * config.USD_AZN))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    data = load()
    rows = []
    for sym in PAIRS:
        df = data[sym]
        pv = pip_value_usd(sym, data)
        for name, sig in (("8×21", cross821(df)), ("8×21×30", ma_cross_signals(df, 8, 21, 30))):
            for tp in (5, 10):
                t = run(df, sym, sig, tp, pv)
                if t.empty:
                    continue
                for period, sub in (("tam", t), ("11.04.2025+", t[t.time >= START_RECENT])):
                    if sub.empty:
                        continue
                    start = df.index[40] if period == "tam" else pd.Timestamp(START_RECENT)
                    years = (df.index[-1] - start).days / 365.25
                    rows.append(dict(dövr=period, strategiya=name, TP=tp, cüt=sym,
                                     istiqamət="BUY" if pos_side(sym)[0] == 1 else "SELL",
                                     başlanğıc=f"{start:%Y}", **summary(sub, years)))
    r = pd.DataFrame(rows)
    r.to_csv("ma_d1_swap.csv", index=False)
    for period in ("tam", "11.04.2025+"):
        print(f"\n===== DÖVR: {period} =====")
        print(r[r.dövr == period].drop(columns="dövr").to_string(index=False))


if __name__ == "__main__":
    main()
