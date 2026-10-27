"""SL-siz, yalnız TP 100 pips: ticarət TP-yə çatana qədər açıq qalır.

(a) hər cütdə eyni anda 1 ticarət   (b) hər siqnalda yeni ticarət (köhnələr açıq qalsa da)
Ölçülür: neçə ticarət TP-yə çatıb, nə qədər çəkib, ən böyük ÜZƏN zərər (pips və $/1 lot),
indi açıq qalan ticarətlər və svop xərci.

İstifadə:  python no_sl_test.py
"""
import sys

import numpy as np
import pandas as pd

import research as R
import swaps
from ma_cross_tp import signals
from ma_test import POINT, mt5_frames
from strategy import pip_size

TP = 100


def pip_value_usd(sym, price):
    """1 lot üçün 1 pipsin dəyəri, $."""
    if sym.endswith("USD"):
        return 10.0
    return 10.0 / price if "JPY" not in sym else 1000.0 / price


def run(df, sym, many, bars_per_day):
    pip = pip_size(sym)
    sig = signals(df)
    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    spread = df.spread.to_numpy() * POINT(sym) / pip
    sw = (swaps.load() or {}).get("symbols", {}).get(sym, {})
    trades, busy_until = [], -1
    for i in np.flatnonzero(sig != 0):
        if not many and i <= busy_until:
            continue
        side, entry = sig[i], close[i]
        tp = entry + side * TP * pip
        fut_hi, fut_lo = hi[i + 1:], lo[i + 1:]
        hit = (fut_hi >= tp) if side == 1 else (fut_lo <= tp)
        j = i + 1 + hit.argmax() if hit.any() else None
        end = j if j is not None else len(df) - 1
        worst = (lo[i + 1:end + 1].min() - entry) / pip if side == 1 else (entry - hi[i + 1:end + 1].max()) / pip
        days = (end - i) / bars_per_day
        swap_usd = (sw.get("long" if side == 1 else "short", 0.0)) * days * 7 / 5
        pv = pip_value_usd(sym, entry)
        trades.append(dict(time=df.index[i], closed=j is not None, days=days, worst_pips=min(worst, 0),
                           worst_usd=min(worst, 0) * pv,
                           result_pips=(TP if j is not None else side * (close[-1] - entry) / pip) - spread[i],
                           swap_usd=swap_usd, pip_usd=pv))
        busy_until = end
    return pd.DataFrame(trades)


def report(name, frames, bars_per_day, many):
    rows = []
    for sym, df in frames.items():
        if sym == "XAUUSD":
            continue
        t = run(df, sym, many, bars_per_day)
        if t.empty:
            continue
        c, o = t[t.closed], t[~t.closed]
        rows.append({
            "cüt": sym, "siqnal": len(t), "TP-yə çatdı": len(c), "hələ açıq": len(o),
            "orta gün": round(c.days.mean(), 1), "ən uzun gün": round(c.days.max()),
            "ən böyük üzən zərər pips": round(t.worst_pips.min()),
            "ən böyük üzən zərər $/lot": round(t.worst_usd.min()),
            "açıqların indiki nəticəsi pips": round(o.result_pips.sum()),
            "bağlananların qazancı pips": round(c.result_pips.sum()),
            "svop $/lot": round(t.swap_usd.sum()),
        })
    r = pd.DataFrame(rows)
    print(f"\n=== {name} ===")
    print(r.to_string(index=False))
    return r


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    h1 = mt5_frames("H1", 20000)
    d1 = R.load_daily()
    for s, df in d1.items():
        df["spread"] = R.SPREAD.get(s, 2) * 10
    for many in (False, True):
        mode = "hər siqnalda yeni ticarət" if many else "hər cütdə 1 ticarət"
        report(f"H1 (2023–2026), {mode}", h1, 24, many)
        report(f"D1 (2004–2026), {mode}", d1, 1, many)


if __name__ == "__main__":
    main()
