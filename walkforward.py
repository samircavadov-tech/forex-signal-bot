"""Bütün variantların walk-forward sınağı: hər il üçün son 5 ilin ən yaxşısı seçilir
və NÖVBƏTİ il üzrə (görmədiyi məlumatda) sınanır. Bu, "optimallaşdırma" prosesinin
özünün real gəlirini göstərir.

İstifadə:  python walkforward.py
"""
import sys

import numpy as np
import pandas as pd

import research as R

LOOKBACK_YEARS = 5
FIRST_TEST_YEAR = 2010


def tsmom_n(n):
    def f(df):
        sig = np.sign(df.close / df.close.shift(n) - 1)
        return sig.where(R.month_end_mask(df)).ffill()
    return f


def ma(fast, slow):
    return lambda df: np.sign(R.sma(df.close, fast) - R.sma(df.close, slow))


def rate_mom(k):
    def f(df):
        m = df[f"rate_mom{k}"]
        return pd.Series(np.where(m > 0.1, 1, np.where(m < -0.1, -1, 0)), index=df.index, dtype=float)
    return f


def agree(a, b):
    """a siqnalı, yalnız b ilə eyni istiqamətdədirsə."""
    def f(df):
        x, y = a(df).fillna(0), b(df).fillna(0)
        return x.where(x == y, 0.0)
    return f


def average(*fs):
    return lambda df: sum(f(df).fillna(0) for f in fs) / len(fs)


VARIANTS = {
    # texniki
    "T trend 1 ay": tsmom_n(21),
    "T trend 3 ay": tsmom_n(63),
    "T trend 6 ay": tsmom_n(126),
    "T trend 12 ay": tsmom_n(252),
    "T MA 50/200": ma(50, 200),
    "T MA 20/100": ma(20, 100),
    "T Donchian 20/10": R.donchian(20, 10),
    "T Donchian 55/20": R.donchian(55, 20),
    "T RSI(2)": R.rsi2,
    # fundamental
    "F carry": R.carry,
    "F faiz meyli 6 ay": rate_mom(6),
    "F faiz meyli 12 ay": rate_mom(12),
    # birləşmələr
    "C carry+trend12 orta": R.carry_mom,
    "C trend12 & faiz meyli": agree(tsmom_n(252), rate_mom(6)),
    "C trend3 & faiz meyli": agree(tsmom_n(63), rate_mom(6)),
    "C carry & faiz meyli": agree(R.carry, rate_mom(6)),
    "C hamısı orta (trend12+carry+meyl)": average(tsmom_n(252), R.carry, rate_mom(6)),
}


def sharpe(r):
    r = r.dropna()
    return r.mean() / r.std() * np.sqrt(252) if len(r) > 20 and r.std() > 0 else 0.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    data = R.load_daily()
    R.attach_rates(data, R.load_rates())

    # hər variant × hər aktiv üçün günlük xalis gəlir
    rets = {name: R.daily_returns(f, data) for name, f in VARIANTS.items()}
    assets = list(data)
    years = range(FIRST_TEST_YEAR, pd.Timestamp.now().year + 1)

    # 1) Tam dövr (məlumat üçün — seçim üçün DEYİL)
    full = pd.DataFrame({n: {a: round(sharpe(r[a]["2005":]), 2) for a in assets} | {"PORTFEL": round(sharpe(r.mean(axis=1)["2005":]), 2)}
                         for n, r in rets.items()}).T
    print("Bütün variantlar, 2005–2026 Sharpe (yalnız məlumat, seçim üçün istifadə olunmur):")
    print(full.to_string())

    # 2) Walk-forward: A) hər aktiv üçün ayrıca ən yaxşı variant; B) bütün portfel üçün bir variant
    oos_a, oos_b, picks_a, picks_b = [], [], {}, {}
    for y in years:
        train = slice(f"{y - LOOKBACK_YEARS}", f"{y - 1}")
        test = slice(f"{y}", f"{y}")
        # A
        year_ret = []
        picks_a[y] = {}
        for a in assets:
            scores = {n: sharpe(r[a][train]) for n, r in rets.items()}
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                year_ret.append(rets[best][a][test])
                picks_a[y][a] = best
            else:
                year_ret.append(rets[best][a][test] * 0)
                picks_a[y][a] = "— (heç biri)"
        oos_a.append(pd.concat(year_ret, axis=1).mean(axis=1))
        # B
        scores = {n: sharpe(r.mean(axis=1)[train]) for n, r in rets.items()}
        best = max(scores, key=scores.get)
        picks_b[y] = best
        oos_b.append(rets[best].mean(axis=1)[test] * (1 if scores[best] > 0 else 0))
    oos_a, oos_b = pd.concat(oos_a), pd.concat(oos_b)

    # müqayisə üçün: seçimsiz bütün variantların ortası və qızıl trend 12 ay
    ens = sum(r.mean(axis=1) for r in rets.values()) / len(rets)
    gold12 = rets["T trend 12 ay"]["XAUUSD"]
    start = f"{FIRST_TEST_YEAR}"

    def row(name, r):
        r = r[start:]
        m = R.metrics(r)
        yr = r.groupby(r.index.year).sum()
        return {"Yanaşma": name, "Sharpe": round(sharpe(r), 2), "İllik %": m["annual"], "Max geriləmə %": m["maxdd"],
                "Müsbət illər": f"{(yr > 0).sum()}/{len(yr)}"}

    print(f"\nWALK-FORWARD NƏTİCƏSİ ({FIRST_TEST_YEAR}–indi, hər il görülməmiş məlumatda):")
    print(pd.DataFrame([
        row("A) Hər aktiv üçün son 5 ilin ən yaxşısı", oos_a),
        row("B) Portfel üçün son 5 ilin ən yaxşısı", oos_b),
        row("C) Seçimsiz: bütün variantların ortası", ens),
        row("D) Yalnız qızıl, trend 12 ay", gold12),
    ]).to_string(index=False))

    print("\nB) hər il seçilən variant:", picks_b)
    print("\nA) son il üçün seçimlər:", picks_a[max(years)])
    by_year = pd.DataFrame({"A": oos_a.groupby(oos_a.index.year).sum(), "B": oos_b.groupby(oos_b.index.year).sum(),
                            "C": ens[start:].groupby(ens[start:].index.year).sum(),
                            "D qızıl": gold12[start:].groupby(gold12[start:].index.year).sum()}) * 100
    print("\nİllər üzrə gəlir % (10% vol hədəfi ilə):")
    print(by_year.round(1).to_string())


if __name__ == "__main__":
    main()
