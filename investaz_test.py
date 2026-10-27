"""InvestAZ şərtləri ilə D1 SMA 8/21/30 strategiyasının sınağı (MT5 real broker məlumatı).

Qayda: D1-də SMA 8 həm SMA 21-i, həm SMA 30-u kəsəndə giriş (bağlanışda), TP 100 pips.
Variantlar: SL-siz (TP-yə qədər gözlə) və SL 30. Hər cütdə eyni anda 1 ticarət.
Xərclər: InvestAZ spredi (girişdə), svop hər gecə (təqvim günü; çərşənbə 3x ≈ həftədə 7 gecə).
Svop vahidi: 1 lot üçün bir gecəlik $ qəbul olunub. Marja: cədvəldəki faiz (1:50 = 2%).

İstifadə:  python investaz_test.py
"""
import sys

import numpy as np
import pandas as pd

import mt5_data
from strategy import ma_cross_signals

# cüt: (spred pips, svop alış $, svop satış $, marja faizi)
SPECS = {
    "EURUSD": (0.6, -13.50, 2.91, 0.02),
    "GBPUSD": (1.6, -7.48, 1.83, 0.02),
    "AUDJPY": (1.8, 2.11, -9.42, 0.05),
    "EURGBP": (1.8, -4.88, 0.88, 0.05),
    "EURAUD": (2.3, -16.03, 2.93, 0.05),
}
TP = 100
START = "2009-08-01"
LOT = 0.01


def load():
    import MetaTrader5 as mt5
    mt5_data.connect()
    out = {}
    try:
        for s in list(SPECS) + ["USDJPY", "AUDUSD"]:
            mt5.symbol_select(s, True)
            r = pd.DataFrame(mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 4500))
            r["time"] = pd.to_datetime(r.time, unit="s")
            out[s] = r.set_index("time").iloc[:-1]
    finally:
        mt5_data.shutdown()
    return out


def pip_value_usd(sym, data):
    """1 lot, 1 pips — $ (gündəlik seriya)."""
    idx = data[sym].index
    if sym in ("EURUSD", "GBPUSD"):
        return pd.Series(10.0, index=idx)
    if sym == "AUDJPY":
        return (1000 / data["USDJPY"].close).reindex(idx).ffill()
    if sym == "EURGBP":
        return (10 * data["GBPUSD"].close).reindex(idx).ffill()
    if sym == "EURAUD":
        return (10 * data["AUDUSD"].close).reindex(idx).ffill()


def notional_usd(sym, data):
    idx = data[sym].index
    base = {"EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "EURGBP": "EURUSD", "EURAUD": "EURUSD", "AUDJPY": "AUDUSD"}[sym]
    return (100_000 * data[base].close).reindex(idx).ffill()


def run(sym, data, sl_pips):
    """Ticarətlər + gündəlik $ nəticə seriyası (1 lot üçün, mark-to-market)."""
    df = data[sym]
    pip = 0.01 if sym.endswith("JPY") else 0.0001
    spread, sw_long, sw_short, _ = SPECS[sym]
    pv = pip_value_usd(sym, data).to_numpy()
    sig = ma_cross_signals(df)
    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    days = df.index.to_series().diff().dt.days.fillna(1).to_numpy()   # gecə sayı (həftəsonu daxil)
    daily = np.zeros(len(df))
    in_pos = np.zeros(len(df))
    trades, i = [], 0
    start_i = df.index.searchsorted(pd.Timestamp(START))
    while i < len(df):
        if i < start_i or sig[i] == 0:
            i += 1
            continue
        side, entry = sig[i], close[i]
        tp = entry + side * TP * pip
        sl = entry - side * sl_pips * pip if sl_pips else None
        swap = sw_long if side == 1 else sw_short
        daily[i] -= spread * pv[i]
        worst, sw_total, prev, j, exit_px = 0.0, 0.0, entry, i + 1, None
        while j < len(df):
            sw_total += swap * days[j]
            daily[j] += swap * days[j]
            in_pos[j] = 1
            hit_sl = sl is not None and (lo[j] <= sl if side == 1 else hi[j] >= sl)
            hit_tp = hi[j] >= tp if side == 1 else lo[j] <= tp
            adverse = (lo[j] - entry) / pip if side == 1 else (entry - hi[j]) / pip
            worst = min(worst, adverse)
            if hit_sl or hit_tp:
                exit_px = sl if hit_sl else tp
                daily[j] += side * (exit_px - prev) / pip * pv[j]
                break
            daily[j] += side * (close[j] - prev) / pip * pv[j]
            prev = close[j]
            j += 1
        closed = exit_px is not None
        result_pips = side * ((exit_px if closed else close[-1]) - entry) / pip - spread
        trades.append(dict(cüt=sym, giriş=df.index[i], bağlandı=closed, gün=(df.index[min(j, len(df) - 1)] - df.index[i]).days,
                           pips=result_pips, usd=result_pips * pv[min(j, len(df) - 1)] + sw_total,
                           svop_usd=sw_total, ən_pis_pips=worst, ən_pis_usd=worst * pv[i]))
        i = j + 1 if closed else len(df)
    return pd.DataFrame(trades), pd.Series(daily, index=df.index), pd.Series(in_pos, index=df.index)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    data = load()
    years = (data["EURUSD"].index[-1] - pd.Timestamp(START)).days / 365.25
    print(f"Dövr: {START} → {data['EURUSD'].index[-1].date()} ({years:.1f} il), MT5 real broker məlumatı")

    for name, sl in [("SL-siz (TP-yə qədər gözlə)", None), ("SL 30 pips", 30)]:
        all_t, eq_parts = [], []
        for s in SPECS:
            t, daily, _ = run(s, data, sl)
            all_t.append(t)
            eq_parts.append(daily.rename(s))
        t = pd.concat(all_t)
        eq = pd.concat(eq_parts, axis=1).fillna(0)
        eq = eq[eq.index >= START]
        curve = eq.sum(axis=1).cumsum() * LOT
        dd = (curve.cummax() - curve).max()
        rows = []
        for s, g in t.groupby("cüt"):
            c = g[g.bağlandı]
            rows.append({"cüt": s, "ticarət": len(g), "TP %": round((c.pips > 0).mean() * 100, 1) if len(c) else 0,
                         "açıq": int((~g.bağlandı).sum()), "net pips": round(g.pips.sum()),
                         f"net $ ({LOT} lot)": round(g.usd.sum() * LOT), f"svop $ ({LOT} lot)": round(g.svop_usd.sum() * LOT),
                         "ən uzun gün": int(g.gün.max()), "ən pis üzən pips": round(g.ən_pis_pips.min()),
                         f"ən pis üzən $ ({LOT} lot)": round(g.ən_pis_usd.min() * LOT)})
        r = pd.DataFrame(rows)
        print(f"\n=== {name} ===")
        print(r.to_string(index=False))
        margin = sum(SPECS[s][3] * notional_usd(s, data).iloc[-1] * LOT for s in SPECS)
        print(f"CƏMİ: net {round(curve.iloc[-1])}$ ({LOT} lot hər cütdə), illik ~{round(curve.iloc[-1] / years)}$; "
              f"portfelin ən böyük geriləməsi {round(dd)}$; 5 cüt üçün marja ~{round(margin)}$; "
              f"lazımi minimum kapital ~{round(dd + margin)}$")
        yearly = (eq.sum(axis=1) * LOT).groupby(eq.index.year).sum().round(0)
        print("İllər üzrə $:", yearly.astype(int).to_dict())


if __name__ == "__main__":
    main()
