"""İstifadəçinin dəqiq ssenarisi: 500 AZN, 0.01 lot, D1 SMA 8 × SMA 21/30, TP 25 pips, SL yox,
11.04.2025 – bu gün, InvestAZ cütləri, yalnız svopu MÜSBƏT olan istiqamətdə ticarət.
Hər siqnal yeni ticarət açır. MT5 real broker məlumatı. Nəticə AZN ilə (1 USD = 1.70 AZN).

İstifadə:  python investaz_tp25.py      → ekrana cədvəl + investaz_tp25_trades.csv
"""
import sys

import numpy as np
import pandas as pd

from investaz_test import SPECS, load, notional_usd, pip_value_usd
from strategy import ma_cross_signals

START = pd.Timestamp("2025-04-11")
BALANCE_AZN = 500.0
USD_AZN = 1.70
LOT = 0.01
TP = 25
# yalnız svopu müsbət olan istiqamət: +1 BUY, -1 SELL
ALLOWED = {s: (1 if SPECS[s][1] > 0 else -1) for s in SPECS}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    data = load()
    trades, daily_pnl, margin_used = [], {}, {}
    for sym in SPECS:
        df = data[sym]
        pip = 0.01 if sym.endswith("JPY") else 0.0001
        digits = 3 if sym.endswith("JPY") else 5
        spread, sw_long, sw_short, mrate = SPECS[sym]
        side = ALLOWED[sym]
        swap_night = (sw_long if side == 1 else sw_short) * LOT          # $ / gecə
        pv = (pip_value_usd(sym, data) * LOT).to_numpy()                  # $ / pips
        notional = (notional_usd(sym, data) * LOT).to_numpy()
        sig = ma_cross_signals(df)
        hi, lo, close, idx = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy(), df.index
        nights = idx.to_series().diff().dt.days.fillna(1).to_numpy()
        for i in np.flatnonzero((sig == side) & (idx >= START)):
            entry = close[i]
            tp = entry + side * TP * pip
            j, swap, worst = i + 1, 0.0, 0.0
            pnl_day = {idx[i]: -spread * pv[i]}
            exit_px = None
            prev = entry
            while j < len(df):
                swap += swap_night * nights[j]
                worst = min(worst, ((lo[j] - entry) if side == 1 else (entry - hi[j])) / pip)
                hit = hi[j] >= tp if side == 1 else lo[j] <= tp
                px = tp if hit else close[j]
                pnl_day[idx[j]] = pnl_day.get(idx[j], 0) + side * (px - prev) / pip * pv[j] + swap_night * nights[j]
                for d in (idx[j],):
                    margin_used[d] = margin_used.get(d, 0) + mrate * notional[j]
                prev = px
                if hit:
                    exit_px = tp
                    break
                j += 1
            closed = exit_px is not None
            last = min(j, len(df) - 1)
            px = exit_px if closed else close[-1]
            pips = side * (px - entry) / pip - spread
            profit_usd = pips * pv[last] + swap
            for d, v in pnl_day.items():
                daily_pnl[d] = daily_pnl.get(d, 0) + v
            trades.append({
                "Cüt": sym, "Növ": "BUY" if side == 1 else "SELL",
                "Açılış": idx[i].strftime("%d.%m.%Y"), "Açılış qiyməti": round(entry, digits),
                "TP": round(tp, digits),
                "Bağlanış": idx[last].strftime("%d.%m.%Y") if closed else "AÇIQDIR",
                "Bağlanış qiyməti": round(px, digits),
                "Gün": (idx[last] - idx[i]).days,
                "Pips": round(pips, 1),
                "Svop AZN": round(swap * USD_AZN, 2),
                "Ən pis üzən AZN": round(worst * pv[i] * USD_AZN, 2),
                "Mənfəət AZN": round(profit_usd * USD_AZN, 2),
                "_t": idx[i],
            })

    t = pd.DataFrame(trades).sort_values("_t").drop(columns="_t").reset_index(drop=True)
    t.index += 1
    closed = t[t["Bağlanış"] != "AÇIQDIR"]
    t["Balans AZN (bağlananlar)"] = (BALANCE_AZN + closed["Mənfəət AZN"].cumsum()).reindex(t.index).ffill().fillna(BALANCE_AZN).round(2)
    t.to_csv("investaz_tp25_trades.csv", encoding="utf-8-sig")

    pnl = pd.Series(daily_pnl).sort_index()
    equity = BALANCE_AZN + pnl.cumsum() * USD_AZN
    marg = pd.Series(margin_used).reindex(equity.index).fillna(0) * USD_AZN
    level = (equity / marg.replace(0, np.nan) * 100)

    print(t.to_string())
    print(f"\nDövr: {START:%d.%m.%Y} – {data['EURUSD'].index[-1]:%d.%m.%Y}")
    print(f"Ticarət: {len(t)} | bağlanan (TP): {len(closed)} | açıq: {len(t) - len(closed)}")
    print(f"Bağlananların mənfəəti: {closed['Mənfəət AZN'].sum():.2f} AZN | açıqların üzən nəticəsi: "
          f"{t[t['Bağlanış'] == 'AÇIQDIR']['Mənfəət AZN'].sum():.2f} AZN")
    print(f"Son balans (bağlananlar): {BALANCE_AZN + closed['Mənfəət AZN'].sum():.2f} AZN | "
          f"son kapital (açıqlar daxil): {BALANCE_AZN + t['Mənfəət AZN'].sum():.2f} AZN")
    print(f"Ən aşağı kapital: {equity.min():.2f} AZN ({equity.idxmin():%d.%m.%Y}) | "
          f"ən aşağı marja səviyyəsi: {level.min():.0f}% | ən çox eyni anda açıq marja: {marg.max():.2f} AZN")


if __name__ == "__main__":
    main()
