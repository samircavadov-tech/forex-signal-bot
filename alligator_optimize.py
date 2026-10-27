"""Alligator + MA 10/50 + AO: optimal variant axtarışı, öyrənmə (ilk 60%) / yoxlama (son 40%) bölgüsü ilə.

Giriş həmişə MA10 × MA50 kəsişməsidir; filtrlər və çıxış dəyişdirilir.
İstifadə:  python alligator_optimize.py
"""
import itertools
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
from alligator_test import PAIRS, load
from indicators import atr

TFS = {"M15": 50000, "M30": 40000, "H1": 20000, "H4": 6000}
EXITS = [(1, 1), (1.5, 1), (2, 1), (3, 1), (1, 2)]          # (TP×ATR, SL×ATR)
AO_MODES = ["yox", "rəng 1", "rəng 3", "rəng 5", "işarə"]
ALLI_MODES = ["yox", "kəsişmə 3", "kəsişmə 5", "kəsişmə 10", "düzülüş"]
TRAIN_FRAC = 0.6


def candidates(df, sym):
    c = df.close
    med = (df.high + df.low) / 2
    ema = lambda s, n: s.ewm(span=n, adjust=False).mean()
    jaws, teeth, lips = ema(med, 13).shift(8), ema(med, 8).shift(5), ema(med, 5).shift(3)
    ma10, ma50 = c.rolling(10).mean(), c.rolling(50).mean()
    ao = med.rolling(5).mean() - med.rolling(34).mean()
    up = ((ma10 > ma50) & (ma10.shift() <= ma50.shift())).to_numpy()
    dn = ((ma10 < ma50) & (ma10.shift() >= ma50.shift())).to_numpy()
    side = np.where(up, 1, np.where(dn, -1, 0))
    idx = np.flatnonzero(side != 0)
    idx = idx[idx > 60]
    s = side[idx]

    ao_up = ((ao > ao.shift()) & (ao.shift() <= ao.shift(2)))
    ao_dn = ((ao < ao.shift()) & (ao.shift() >= ao.shift(2)))
    al_up = ((lips > teeth) & (lips.shift() <= teeth.shift()))
    al_dn = ((lips < teeth) & (lips.shift() >= teeth.shift()))
    rec = lambda x, w: x.rolling(w).max().fillna(0).astype(bool).to_numpy()[idx]
    pick = lambda u, d: np.where(s == 1, u, d)
    feat = pd.DataFrame({"side": s, "pos": idx / len(df)})
    for w in (1, 3, 5):
        feat[f"rəng {w}"] = pick(rec(ao_up, w), rec(ao_dn, w))
    feat["işarə"] = pick((ao > 0).to_numpy()[idx], (ao < 0).to_numpy()[idx])
    for w in (3, 5, 10):
        feat[f"kəsişmə {w}"] = pick(rec(al_up, w), rec(al_dn, w))
    feat["düzülüş"] = pick(((lips > teeth) & (teeth > jaws)).to_numpy()[idx],
                           ((lips < teeth) & (teeth < jaws)).to_numpy()[idx])
    feat["yox"] = True

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
        feat[f"R {tpm}:{slm}"] = res
    return feat


def stats(r):
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return len(r), np.nan, np.nan, np.nan
    g, l = r[r > 0].sum(), -r[r < 0].sum()
    return len(r), r.mean(), (g / l if l else np.inf), (r > 0).mean() * 100


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
    finally:
        mt5_data.shutdown()

    rows = []
    for tf, ao_m, al_m, (tpm, slm) in itertools.product(TFS, AO_MODES, ALLI_MODES, EXITS):
        f = data[tf]
        m = f[ao_m].to_numpy(bool) & f[al_m].to_numpy(bool)
        r = f[f"R {tpm}:{slm}"].to_numpy()
        tr, te = m & (f.pos < TRAIN_FRAC).to_numpy(), m & (f.pos >= TRAIN_FRAC).to_numpy()
        n1, r1, pf1, w1 = stats(r[tr])
        n2, r2, pf2, w2 = stats(r[te])
        rows.append(dict(tf=tf, AO=ao_m, Alligator=al_m, çıxış=f"{tpm}:{slm}",
                         öyr_n=n1, öyr_R=r1, öyr_PF=pf1, öyr_qazanc=w1, yox_n=n2, yox_R=r2, yox_PF=pf2, yox_qazanc=w2))
    res = pd.DataFrame(rows)
    res.to_csv("alligator_optimize_results.csv", index=False)
    ok = res[(res.öyr_n >= 40) & (res.yox_n >= 20)].copy()
    fmt = ok.round({"öyr_R": 3, "öyr_PF": 2, "öyr_qazanc": 1, "yox_R": 3, "yox_PF": 2, "yox_qazanc": 1})
    print(f"Variant sayı: {len(res)} | kifayət qədər ticarəti olan: {len(ok)}")
    print(f"Öyrənmədə müsbət: {(ok.öyr_R > 0).sum()} | yoxlamada müsbət: {(ok.yox_R > 0).sum()} | "
          f"hər ikisində müsbət: {((ok.öyr_R > 0) & (ok.yox_R > 0)).sum()}")
    print(f"Öyrənmə ilə yoxlama arasında korrelyasiya: {ok[['öyr_R', 'yox_R']].corr().iloc[0, 1]:.2f}")
    print("\nÖYRƏNMƏDƏ ən yaxşı 10 variant və onların YOXLAMA nəticəsi (R/ticarət):")
    print(fmt.sort_values("öyr_R", ascending=False).head(10).to_string(index=False))
    print("\nHər iki dövrdə müsbət olanlar (yoxlamaya görə):")
    both = fmt[(fmt.öyr_R > 0) & (fmt.yox_R > 0)].sort_values("yox_R", ascending=False)
    print(both.head(10).to_string(index=False) if len(both) else "yoxdur")
    print("\nOrijinal qayda (rəng 3 + kəsişmə 3), hər qrafik, çıxış 1:1:")
    print(fmt[(fmt.AO == "rəng 3") & (fmt.Alligator == "kəsişmə 3") & (fmt.çıxış == "1:1")].to_string(index=False))


if __name__ == "__main__":
    main()
