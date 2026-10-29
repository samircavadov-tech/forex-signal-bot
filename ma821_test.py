"""SMA 8 × SMA 21 kəsişməsinin hərtərəfli sınağı (MT5 real broker məlumatı, istifadəçinin 5 cütü).

Giriş: SMA8 SMA21-i yuxarı kəsir → BUY, aşağı → SELL (şamın bağlanışında).
Filtrlər: yox | AO işarəsi | trend (qiymət SMA200-ün eyni tərəfində) | Alligator (Lips×Teeth, 5 şam)
Çıxış: TP/SL ATR(14) ilə. Bir şamda həm SL, həm TP mümkündürsə — ehtiyatla SL. Spred çıxılır.
Öyrənmə: hər qrafikin ilk 60%-i, yoxlama: son 40%-i.

İstifadə:  python ma821_test.py
"""
import itertools
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
from alligator_test import PAIRS, load
from indicators import atr

TFS = {"M15": 50000, "M30": 40000, "H1": 20000, "H4": 16000, "D1": 4500}
EXITS = [(1, 1), (1.5, 1), (2, 1), (3, 1), (1, 2)]
FILTERS = ["yox", "AO", "trend", "Alligator", "AO+trend"]
TRAIN_FRAC = 0.6


def candidates(df, sym):
    c = df.close
    med = (df.high + df.low) / 2
    sma8, sma21, sma200 = c.rolling(8).mean(), c.rolling(21).mean(), c.rolling(200).mean()
    ema = lambda s, n: s.ewm(span=n, adjust=False).mean()
    teeth, lips = ema(med, 8).shift(5), ema(med, 5).shift(3)
    ao = med.rolling(5).mean() - med.rolling(34).mean()
    up = ((sma8 > sma21) & (sma8.shift() <= sma21.shift())).to_numpy()
    dn = ((sma8 < sma21) & (sma8.shift() >= sma21.shift())).to_numpy()
    side = np.where(up, 1, np.where(dn, -1, 0))
    idx = np.flatnonzero(side != 0)
    idx = idx[idx > 210]
    s = side[idx]
    pick = lambda u, d: np.where(s == 1, np.asarray(u)[idx], np.asarray(d)[idx])
    rec = lambda x: x.rolling(5).max().fillna(0).astype(bool).to_numpy()
    lips_up = (lips > teeth) & (lips.shift() <= teeth.shift())
    lips_dn = (lips < teeth) & (lips.shift() >= teeth.shift())
    f = pd.DataFrame({"side": s, "pos": idx / len(df), "time": df.index[idx]})
    f["yox"] = True
    f["AO"] = pick(ao > 0, ao < 0)
    f["trend"] = pick(c > sma200, c < sma200)
    f["Alligator"] = pick(rec(lips_up), rec(lips_dn))
    f["AO+trend"] = f["AO"] & f["trend"]

    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    a = atr(df, 14).to_numpy()
    pip = 0.01 if sym.endswith("JPY") else 0.0001
    spread = config.INVESTAZ[sym][0] * pip
    for tpm, slm in EXITS:
        res = np.full(len(idx), np.nan)
        for k, (i, sd) in enumerate(zip(idx, s)):
            if np.isnan(a[i]) or a[i] <= 0:
                continue
            e, risk = close[i], a[i] * slm
            sl, tp = e - sd * risk, e + sd * a[i] * tpm
            h, l = hi[i + 1:i + 3001], lo[i + 1:i + 3001]
            hs = (l <= sl) if sd == 1 else (h >= sl)
            ht = (h >= tp) if sd == 1 else (l <= tp)
            js = hs.argmax() if hs.any() else 10**9
            jt = ht.argmax() if ht.any() else 10**9
            if js == jt == 10**9:
                continue
            res[k] = (-1.0 if js <= jt else tpm / slm) - spread / risk
        f[f"R {tpm}:{slm}"] = res
    return f


def stats(r):
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return len(r), np.nan, np.nan
    return len(r), r.mean(), (r > 0).mean() * 100


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    mt5_data.connect()
    data = {}
    try:
        for tf, bars in TFS.items():
            parts = []
            for sym in PAIRS:
                df = load(sym, tf, bars)
                if df is not None and len(df) > 1000:
                    parts.append(candidates(df, sym).assign(cüt=sym))
            data[tf] = pd.concat(parts, ignore_index=True)
            print(f"{tf}: {data[tf].time.min():%Y-%m-%d} → {data[tf].time.max():%Y-%m-%d}, "
                  f"{len(data[tf])} kəsişmə", flush=True)
    finally:
        mt5_data.shutdown()

    rows = []
    for tf, flt, (tpm, slm) in itertools.product(TFS, FILTERS, EXITS):
        f = data[tf]
        m = f[flt].to_numpy(bool)
        r = f[f"R {tpm}:{slm}"].to_numpy()
        tr, te = m & (f.pos < TRAIN_FRAC).to_numpy(), m & (f.pos >= TRAIN_FRAC).to_numpy()
        n1, r1, w1 = stats(r[tr])
        n2, r2, w2 = stats(r[te])
        rows.append(dict(qrafik=tf, filtr=flt, çıxış=f"{tpm}:{slm}", öyr_n=n1, öyr_R=r1, öyr_qazanc=w1,
                         yox_n=n2, yox_R=r2, yox_qazanc=w2))
    res = pd.DataFrame(rows).round({"öyr_R": 3, "öyr_qazanc": 1, "yox_R": 3, "yox_qazanc": 1})
    res.to_csv("ma821_results.csv", index=False)

    print("\nFİLTRSİZ 8/21 kəsişməsi, TP=SL (1:1) — düz istiqamət faizi və nəticə:")
    print(res[(res.filtr == "yox") & (res.çıxış == "1:1")].to_string(index=False))
    ok = res[(res.öyr_n >= 40) & (res.yox_n >= 20)]
    print(f"\nVariant: {len(res)} | öyrənmədə müsbət: {(ok.öyr_R > 0).sum()} | yoxlamada müsbət: {(ok.yox_R > 0).sum()} | "
          f"hər ikisində: {((ok.öyr_R > 0) & (ok.yox_R > 0)).sum()} | korrelyasiya: {ok[['öyr_R', 'yox_R']].corr().iloc[0, 1]:.2f}")
    print("\nÖYRƏNMƏDƏ ən yaxşı 10 və onların YOXLAMA nəticəsi:")
    print(ok.sort_values("öyr_R", ascending=False).head(10).to_string(index=False))
    print("\nHər iki dövrdə müsbət olanlar:")
    both = ok[(ok.öyr_R > 0) & (ok.yox_R > 0)].sort_values("yox_R", ascending=False)
    print(both.head(12).to_string(index=False) if len(both) else "yoxdur")


if __name__ == "__main__":
    main()
