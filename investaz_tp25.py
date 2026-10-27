"""İstifadəçi ssenarisi: 500 AZN, 0.01 lot, D1 SMA 8 × SMA 21/30, SL yox, InvestAZ cütləri,
yalnız svopu MÜSBƏT olan istiqamətdə ticarət. MT5 real broker məlumatı. Nəticə AZN ilə (1 USD = 1.70 AZN).

İstifadə:
  python investaz_tp25.py                     # TP 25, hər siqnal yeni ticarət
  python investaz_tp25.py --tp 50 --one       # TP 50, eyni anda yalnız 1 ticarət (bütün cütlər üzrə)
"""
import argparse
import sys

import numpy as np
import pandas as pd

from investaz_test import SPECS, load, notional_usd, pip_value_usd
from strategy import ma_cross_signals

START = pd.Timestamp("2025-04-11")
BALANCE_AZN = 500.0
USD_AZN = 1.70
LOT = 0.01
# yalnız svopu müsbət olan istiqamət: +1 BUY, -1 SELL
ALLOWED = {s: (1 if SPECS[s][1] > 0 else -1) for s in SPECS}


def simulate(sym, i, data, tp_pips):
    """Bir ticarəti TP-yə qədər izləyir. Qaytarır: sətir, gündəlik $ nəticə, gündəlik marja $, çıxış tarixi."""
    df = data[sym]
    pip = 0.01 if sym.endswith("JPY") else 0.0001
    digits = 3 if sym.endswith("JPY") else 5
    spread, sw_long, sw_short, mrate = SPECS[sym]
    side = ALLOWED[sym]
    swap_night = (sw_long if side == 1 else sw_short) * LOT
    pv = (pip_value_usd(sym, data) * LOT).to_numpy()
    notional = (notional_usd(sym, data) * LOT).to_numpy()
    hi, lo, close, idx = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy(), df.index
    nights = idx.to_series().diff().dt.days.fillna(1).to_numpy()

    entry = close[i]
    tp = entry + side * tp_pips * pip
    pnl = {idx[i]: -spread * pv[i]}
    margin = {idx[i]: mrate * notional[i]}
    j, swap, worst, prev, exit_px = i + 1, 0.0, 0.0, entry, None
    while j < len(df):
        swap += swap_night * nights[j]
        worst = min(worst, ((lo[j] - entry) if side == 1 else (entry - hi[j])) / pip)
        hit = hi[j] >= tp if side == 1 else lo[j] <= tp
        px = tp if hit else close[j]
        pnl[idx[j]] = side * (px - prev) / pip * pv[j] + swap_night * nights[j]
        margin[idx[j]] = mrate * notional[j]
        prev = px
        if hit:
            exit_px = tp
            break
        j += 1
    closed = exit_px is not None
    last = min(j, len(df) - 1)
    px = exit_px if closed else close[-1]
    pips = side * (px - entry) / pip - spread
    row = {
        "Cüt": sym, "Növ": "BUY" if side == 1 else "SELL",
        "Açılış": idx[i].strftime("%d.%m.%Y"), "Açılış qiyməti": round(entry, digits),
        "TP": round(tp, digits),
        "Bağlanış": idx[last].strftime("%d.%m.%Y") if closed else "AÇIQDIR",
        "Gün": (idx[last] - idx[i]).days,
        "Pips": round(pips, 1),
        "Svop AZN": round(swap * USD_AZN, 2),
        "Ən pis üzən AZN": round(worst * pv[i] * USD_AZN, 2),
        "Mənfəət AZN": round((pips * pv[last] + swap) * USD_AZN, 2),
        "_open": idx[i],
    }
    return row, pnl, margin, (idx[last] if closed else pd.Timestamp.max)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    ap = argparse.ArgumentParser()
    ap.add_argument("--tp", type=int, default=25)
    ap.add_argument("--one", action="store_true", help="eyni anda yalnız 1 ticarət (bütün cütlər üzrə)")
    ap.add_argument("--one-per-pair", action="store_true", help="hər cütdə eyni anda yalnız 1 ticarət")
    args = ap.parse_args()

    data = load()
    candidates = []                                    # (tarix, cüt, indeks)
    for sym in SPECS:
        df = data[sym]
        sig = ma_cross_signals(df)
        for i in np.flatnonzero((sig == ALLOWED[sym]) & (df.index >= START)):
            candidates.append((df.index[i], sym, i))
    candidates.sort()

    trades, daily_pnl, daily_margin, skipped = [], {}, {}, []
    busy_until = {}                                    # açar: "ALL" və ya cüt
    for date, sym, i in candidates:
        key = "ALL" if args.one else sym if args.one_per_pair else None
        if key and date < busy_until.get(key, pd.Timestamp.min):   # ticarət hələ bağlanmayıb — keç
            skipped.append(f"{date:%d.%m.%Y} {sym}")
            continue
        row, pnl, margin, exit_date = simulate(sym, i, data, args.tp)
        trades.append(row)
        if key:
            busy_until[key] = exit_date
        for d, v in pnl.items():
            daily_pnl[d] = daily_pnl.get(d, 0) + v
        for d, v in margin.items():
            daily_margin[d] = daily_margin.get(d, 0) + v

    t = pd.DataFrame(trades).sort_values("_open").drop(columns="_open").reset_index(drop=True)
    t.index += 1
    closed = t[t["Bağlanış"] != "AÇIQDIR"]
    t["Balans AZN"] = (BALANCE_AZN + closed["Mənfəət AZN"].cumsum()).reindex(t.index).ffill().fillna(BALANCE_AZN).round(2)
    out = f"investaz_tp{args.tp}{'_one' if args.one else '_perpair' if args.one_per_pair else ''}_trades.csv"
    t.to_csv(out, encoding="utf-8-sig")

    pnl = pd.Series(daily_pnl).sort_index()
    equity = BALANCE_AZN + pnl.cumsum() * USD_AZN
    marg = pd.Series(daily_margin).reindex(equity.index).fillna(0) * USD_AZN
    level = equity / marg.replace(0, np.nan) * 100

    print(t.to_string())
    print(f"\nTP {args.tp} | {'eyni anda 1 ticarət' if args.one else 'hər cütdə 1 ticarət' if args.one_per_pair else 'hər siqnal yeni ticarət'} | "
          f"{START:%d.%m.%Y} – {data['EURUSD'].index[-1]:%d.%m.%Y}")
    print(f"Ticarət: {len(t)} | bağlanan: {len(closed)} | açıq: {len(t) - len(closed)} | buraxılan siqnal: {len(skipped)}")
    print(f"Bağlananların mənfəəti: {closed['Mənfəət AZN'].sum():.2f} AZN | açıqların üzən nəticəsi: "
          f"{t[t['Bağlanış'] == 'AÇIQDIR']['Mənfəət AZN'].sum():.2f} AZN")
    print(f"Son balans: {BALANCE_AZN + closed['Mənfəət AZN'].sum():.2f} AZN | "
          f"son kapital (açıqlar daxil): {BALANCE_AZN + t['Mənfəət AZN'].sum():.2f} AZN")
    print(f"Ən aşağı kapital: {equity.min():.2f} AZN ({equity.idxmin():%d.%m.%Y}) | "
          f"ən aşağı marja səviyyəsi: {level.min():.0f}% | ən çox marja: {marg.max():.2f} AZN")
    print(f"Fayl: {out}")


if __name__ == "__main__":
    main()
