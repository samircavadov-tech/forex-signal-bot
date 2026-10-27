"""Alligator + MA 10/50 + Awesome Oscillator kombinasiyasının sınağı (MT5 real broker məlumatı).

BUY: MA10 MA50-ni yuxarı kəsir + AO rəngi qırmızıdan göyə dəyişir + Alligator qatlanır
     (Lips Teeth-i yuxarı kəsir); üç şərt WINDOW şam ərzində təsdiqlənməlidir. SELL — əksinə.
Alligator: EMA, Median Price, Jaws 13/8, Teeth 8/5, Lips 5/3 (istifadəçinin parametrləri).
Çıxış: A) TP=SL=1×ATR  B) TP=2×ATR, SL=1×ATR  C) əks MA kəsişməsi (SL yox).
Bir şamda həm SL, həm TP mümkündürsə — ehtiyatla SL. Spred istifadəçinin cədvəlindən.

İstifadə:  python alligator_test.py
"""
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
from indicators import atr

PAIRS = list(config.INVESTAZ)
TIMEFRAMES = {"M1": 50000, "M5": 50000, "H1": 20000, "H4": 6000}
WINDOW = 3


def load(sym, tf, bars):
    import MetaTrader5 as mt5
    tfc = mt5_data.TF_MAP[tf]
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, tfc, 0, bars)
    if r is None:
        return None
    df = pd.DataFrame(r)
    df["time"] = pd.to_datetime(df.time, unit="s")
    return df.set_index("time").iloc[:-1]


def signals(df):
    c = df.close
    med = (df.high + df.low) / 2
    ema = lambda s, n: s.ewm(span=n, adjust=False).mean()
    jaws, teeth, lips = ema(med, 13).shift(8), ema(med, 8).shift(5), ema(med, 5).shift(3)
    ma10, ma50 = c.rolling(10).mean(), c.rolling(50).mean()
    ao = med.rolling(5).mean() - med.rolling(34).mean()

    cross_up = (ma10 > ma50) & (ma10.shift() <= ma50.shift())
    cross_dn = (ma10 < ma50) & (ma10.shift() >= ma50.shift())
    ao_up = (ao > ao.shift()) & (ao.shift() <= ao.shift(2))        # qırmızı → göy
    ao_dn = (ao < ao.shift()) & (ao.shift() >= ao.shift(2))        # göy → qırmızı
    all_up = (lips > teeth) & (lips.shift() <= teeth.shift())      # Lips Teeth-i yuxarı kəsir
    all_dn = (lips < teeth) & (lips.shift() >= teeth.shift())

    recent = lambda s: s.rolling(WINDOW).max().fillna(0).astype(bool)
    buy = cross_up & recent(ao_up) & recent(all_up)
    sell = cross_dn & recent(ao_dn) & recent(all_dn)
    full = np.where(buy, 1, np.where(sell, -1, 0))
    only_ma = np.where(cross_up, 1, np.where(cross_dn, -1, 0))
    return full, only_ma, np.where(cross_up, 1, np.where(cross_dn, -1, 0))


def simulate(df, sig, opp_sig, spread_price, mode):
    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    a = atr(df, 14).to_numpy()
    out = []
    busy = -1
    for i in np.flatnonzero(sig != 0):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0 or i + 1 >= len(df):
            continue
        side, entry, risk = sig[i], close[i], a[i]
        if mode == "C":
            j = next((k for k in range(i + 1, len(df)) if opp_sig[k] == -side), None)
            if j is None:
                break
            r = side * (close[j] - entry) / risk
        else:
            tp_mult = 1.0 if mode == "A" else 2.0
            sl, tp = entry - side * risk, entry + side * tp_mult * risk
            h, l = hi[i + 1:], lo[i + 1:]
            hit_sl = (l <= sl) if side == 1 else (h >= sl)
            hit_tp = (h >= tp) if side == 1 else (l <= tp)
            js = hit_sl.argmax() if hit_sl.any() else 10**9
            jt = hit_tp.argmax() if hit_tp.any() else 10**9
            if js == jt == 10**9:
                break
            j = i + 1 + min(js, jt)
            r = -1.0 if js <= jt else tp_mult
        out.append((r - spread_price / risk, r > 0))
        busy = j
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 220)
    mt5_data.connect()
    rows = []
    try:
        for tf, bars in TIMEFRAMES.items():
            for sym in PAIRS:
                df = load(sym, tf, bars)
                if df is None or len(df) < 500:
                    print(f"{sym} {tf}: məlumat yoxdur")
                    continue
                pip = 0.01 if sym.endswith("JPY") else 0.0001
                spread = config.INVESTAZ[sym][0] * pip
                full, only_ma, opp = signals(df)
                for name, sig in [("Kombinasiya (3 şərt)", full), ("Yalnız MA 10/50 kəsişməsi", only_ma)]:
                    for mode in "ABC":
                        res = simulate(df, sig, opp, spread, mode)
                        if not res:
                            continue
                        r = np.array([x[0] for x in res])
                        rows.append(dict(tf=tf, cüt=sym, strategiya=name, çıxış=mode, ticarət=len(r),
                                         düz_istiqamət_pct=round(100 * np.mean([x[1] for x in res]), 1),
                                         xalis_qazanc_pct=round(100 * (r > 0).mean(), 1),
                                         net_R=round(r.sum(), 1), R_ticarət=round(r.mean(), 3),
                                         dövr=f"{df.index[0]:%Y-%m-%d}…{df.index[-1]:%Y-%m-%d}"))
    finally:
        mt5_data.shutdown()
    res = pd.DataFrame(rows)
    res.to_csv("alligator_results.csv", index=False)
    summ = res.groupby(["tf", "strategiya", "çıxış"]).apply(lambda g: pd.Series({
        "ticarət": g.ticarət.sum(),
        "düz istiqamət %": round(np.average(g.düz_istiqamət_pct, weights=g.ticarət), 1),
        "spreddən sonra qazanc %": round(np.average(g.xalis_qazanc_pct, weights=g.ticarət), 1),
        "net R": round(g.net_R.sum(), 1),
        "müsbət cüt": f"{(g.net_R > 0).sum()}/{len(g)}",
    }), include_groups=False)
    print(summ.to_string())
    print("\nDövrlər:", res.groupby("tf").dövr.first().to_dict())


if __name__ == "__main__":
    main()
