"""SMA 8 × SMA 21 kəsişməsi, sabit TP 10 pips (100 punkt).
A) TP 10 + SL 10 pips   B) TP 10, SL yox (TP-yə qədər gözlə, hər cütdə eyni anda 1 ticarət)
Filtr: yox | trend (qiymət SMA200-ün eyni tərəfində). MT5 real broker məlumatı, istifadəçinin 5 cütü,
spred cədvəldən. Bir şamda həm SL, həm TP mümkündürsə — ehtiyatla SL.

İstifadə:  python ma821_fixed.py
"""
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
from alligator_test import PAIRS, load
from investaz_test import pip_value_usd as _unused  # noqa: F401  (eyni pips dəyəri qaydası)

TFS = {"M15": 50000, "M30": 40000, "H1": 20000, "H4": 16000, "D1": 4500}
TP = 10
SL = 10


def side_and_trend(df):
    c = df.close
    s8, s21, s200 = c.rolling(8).mean(), c.rolling(21).mean(), c.rolling(200).mean()
    up = (s8 > s21) & (s8.shift() <= s21.shift())
    dn = (s8 < s21) & (s8.shift() >= s21.shift())
    side = np.where(up, 1, np.where(dn, -1, 0))
    trend_ok = np.where(side == 1, c > s200, np.where(side == -1, c < s200, False)) & s200.notna().to_numpy()
    return side, trend_ok


def run(df, sym, use_trend, with_sl):
    pip = 0.01 if sym.endswith("JPY") else 0.0001
    spread = config.INVESTAZ[sym][0]
    side, trend_ok = side_and_trend(df)
    hi, lo, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    out, busy = [], -1
    for i in np.flatnonzero(side != 0):
        if i < 210 or (use_trend and not trend_ok[i]):
            continue
        if not with_sl and i <= busy:
            continue
        sd, e = side[i], close[i]
        tp = e + sd * TP * pip
        h, l = hi[i + 1:], lo[i + 1:]
        ht = (h >= tp) if sd == 1 else (l <= tp)
        jt = ht.argmax() if ht.any() else None
        if with_sl:
            sl = e - sd * SL * pip
            hs = (l <= sl) if sd == 1 else (h >= sl)
            js = hs.argmax() if hs.any() else None
            if js is None and jt is None:
                continue
            win = js is None or (jt is not None and jt < js)
            out.append(dict(pips=(TP if win else -SL) - spread, bars=(jt if win else js) + 1, worst=0))
        else:
            end = jt if jt is not None else len(h) - 1
            worst = ((l[:end + 1].min() - e) if sd == 1 else (e - h[:end + 1].max())) / pip
            res = TP if jt is not None else sd * (close[-1] - e) / pip
            out.append(dict(pips=res - spread, bars=end + 1, worst=min(worst, 0), open=jt is None))
            busy = i + 1 + end if jt is not None else len(df)
    return pd.DataFrame(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    mt5_data.connect()
    rows = []
    try:
        for tf, bars in TFS.items():
            for sym in PAIRS:
                df = load(sym, tf, bars)
                if df is None or len(df) < 1000:
                    continue
                years = (df.index[-1] - df.index[0]).days / 365.25
                for use_trend in (False, True):
                    for with_sl in (True, False):
                        t = run(df, sym, use_trend, with_sl)
                        if t.empty:
                            continue
                        rows.append(dict(qrafik=tf, filtr="trend" if use_trend else "yox",
                                         variant="TP10+SL10" if with_sl else "TP10, SL yox", cüt=sym, il=years,
                                         n=len(t), qazanc=(t.pips > 0).mean() * 100, net=t.pips.sum(),
                                         worst=t.worst.min(), açıq=int(t.get("open", pd.Series(dtype=bool)).sum()),
                                         müddət=t.bars.mean()))
    finally:
        mt5_data.shutdown()
    r = pd.DataFrame(rows)
    g = r.groupby(["qrafik", "filtr", "variant"]).agg(
        il=("il", "max"), ticarət=("n", "sum"), qazanc_pct=("qazanc", "mean"), net_pips=("net", "sum"),
        müsbət_cüt=("net", lambda x: f"{(x > 0).sum()}/{len(x)}"), ən_pis_üzən=("worst", "min"),
        açıq_qalan=("açıq", "sum"), orta_şam=("müddət", "mean"))
    g["pips/ticarət"] = g.net_pips / g.ticarət
    g["AZN/il (0.01 lot)"] = g.net_pips * 0.1 * config.USD_AZN / g.il      # ~0.10$/pips, 0.01 lot
    print(g.round(1).to_string())


if __name__ == "__main__":
    main()
