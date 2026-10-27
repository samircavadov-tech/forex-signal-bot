"""Dürüst sınaq: "yalnız svopu müsbət istiqamət" qaydası, amma istiqamət HƏR GÜN o vaxtkı
mərkəzi bank faizlərinə görə seçilir (BUGÜNKÜ svop cədvəli 2009-a tətbiq edilmir).
Svop da o vaxtkı faiz fərqindən hesablanır: (fərq − 1% broker əlavəsi) × nominal / 365.

İstifadə:  python carry_honest.py
"""
import sys

import numpy as np
import pandas as pd

import research as R
from investaz_test import SPECS, load, notional_usd, pip_value_usd
from strategy import ma_cross_signals

START = pd.Timestamp("2009-08-01")
BALANCE_AZN, USD_AZN, LOT = 500.0, 1.70, 0.01
MARKUP = 1.0          # broker svop əlavəsi, illik %
MIN_DIFF = 0.25       # faiz fərqi bundan kiçikdirsə ticarət yoxdur


def rate_diff_series(sym, idx, rates):
    """Hər gün üçün baza − kotirovka faizi (əvvəlki ayın sonu)."""
    def at(cur):
        r = rates[cur]
        r = r.reindex(pd.period_range(r.index.min(), idx.to_period("M").max(), freq="M")).ffill()
        return r.shift(1).reindex(idx.to_period("M")).to_numpy()
    return at(sym[:3]) - at(sym[3:])


def run(data, rates, tp_pips, fixed_today=False):
    trades, pnl_all = [], {}
    for sym in SPECS:
        df = data[sym]
        idx = df.index
        pip = 0.01 if sym.endswith("JPY") else 0.0001
        spread = SPECS[sym][0]
        diff = rate_diff_series(sym, idx, rates)
        pv = (pip_value_usd(sym, data) * LOT).to_numpy()
        notional = (notional_usd(sym, data) * LOT).to_numpy()
        sig = ma_cross_signals(df)
        hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
        nights = idx.to_series().diff().dt.days.fillna(1).to_numpy()
        busy = -1
        for i in np.flatnonzero((sig != 0) & (idx >= START)):
            if i <= busy:
                continue
            if fixed_today:
                allowed = 1 if SPECS[sym][1] > 0 else -1
            else:
                if np.isnan(diff[i]) or abs(diff[i]) < MIN_DIFF:
                    continue
                allowed = 1 if diff[i] > 0 else -1
            side = sig[i]
            if side != allowed:
                continue
            entry, tp = close[i], close[i] + side * tp_pips * pip
            pnl = {idx[i]: -spread * pv[i]}
            j, prev, exit_px, swap = i + 1, entry, None, 0.0
            while j < len(df):
                d = diff[j] if not np.isnan(diff[j]) else diff[i]
                sw = (side * d - MARKUP) / 100 * notional[j] / 365 * nights[j]
                swap += sw
                hit = hi[j] >= tp if side == 1 else lo[j] <= tp
                px = tp if hit else close[j]
                pnl[idx[j]] = side * (px - prev) / pip * pv[j] + sw
                prev = px
                if hit:
                    exit_px = tp
                    break
                j += 1
            busy = j if exit_px is not None else len(df)
            for k, v in pnl.items():
                pnl_all[k] = pnl_all.get(k, 0) + v
            trades.append(dict(cüt=sym, növ="BUY" if side == 1 else "SELL", açılış=idx[i],
                               bağlandı=exit_px is not None, gün=(idx[min(j, len(df) - 1)] - idx[i]).days,
                               svop_azn=swap * USD_AZN))
    t = pd.DataFrame(trades)
    pnl = pd.Series(pnl_all).sort_index() * USD_AZN
    equity = BALANCE_AZN + pnl.cumsum()
    return t, equity, pnl


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    data = load()
    rates = R.load_rates()
    rows = []
    for tp in [25, 50, 75, 100, 150]:
        for label, fixed in [("BUGÜNKÜ svopa görə (gələcəyi bilir)", True), ("O vaxtkı faizə görə (dürüst)", False)]:
            t, eq, pnl = run(data, rates, tp, fixed)
            yearly = pnl.groupby(pnl.index.year).sum()
            rows.append({"TP": tp, "istiqamət seçimi": label, "ticarət": len(t),
                         "açıq": int((~t.bağlandı).sum()) if len(t) else 0,
                         "son kapital AZN": round(eq.iloc[-1]), "ən aşağı kapital AZN": round(eq.min()),
                         "mənfi illər": f"{(yearly < 0).sum()}/{len(yearly)}",
                         "svop AZN": round(t.svop_azn.sum()) if len(t) else 0,
                         "ən uzun gün": int(t.gün.max()) if len(t) else 0})
    print(pd.DataFrame(rows).to_string(index=False))
    # dürüst variantda cütlər və istiqamətlər
    t, eq, _ = run(data, rates, 50, False)
    print("\nTP 50, dürüst: cüt × istiqamət üzrə ticarət sayı")
    print(t.groupby(["cüt", "növ"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()
