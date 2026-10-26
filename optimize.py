"""Strategiya parametrlərinin axtarışı: öyrənmə dövründə seçilir, yoxlama dövründə sınanır.

İstifadə:  python optimize.py
"""
import itertools
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
from backtest import bias, load
from strategy import TF_DURATION, pip_size

TRAIN = ("2023-10-01", "2025-06-30")
TEST = ("2025-07-01", "2099-01-01")
SLTP = [(1.5, 3.0), (1.0, 2.0), (2.0, 4.0), (1.5, 2.25), (2.0, 3.0), (1.0, 3.0)]
MIN_TRADES_TRAIN = 150
WINDOW = 2000      # ticarət ən çox bu qədər H1 şamı izlənir (~3 ay)


def adx(df, period=14):
    up, dn = df.high.diff(), -df.low.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    a = 1 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=a, adjust=False).mean()


def asof(h1_close_time, df, values, tf):
    b = pd.DataFrame({"v": values, "close_time": df.index + TF_DURATION[tf]})
    m = pd.merge_asof(pd.DataFrame({"close_time": h1_close_time}), b, on="close_time", direction="backward")
    return m["v"].to_numpy()


def outcomes(h1, idx, side, slm, tpm, pip, point):
    """Hər namizəd şam üçün: xalis nəticə R ilə (spred çıxılıb). Açıq qalanlar NaN."""
    hi, lo, close, atr = h1.high.to_numpy(), h1.low.to_numpy(), h1.close.to_numpy(), h1.atr.to_numpy()
    spread = h1.spread.to_numpy() * point
    res = np.full(len(idx), np.nan)
    for k, (i, s) in enumerate(zip(idx, side)):
        sl = close[i] - s * atr[i] * slm
        tp = close[i] + s * atr[i] * tpm
        w = slice(i + 1, i + 1 + WINDOW)
        if s == 1:
            hit_sl, hit_tp = lo[w] <= sl, hi[w] >= tp
        else:
            hit_sl, hit_tp = hi[w] >= sl, lo[w] <= tp
        never = WINDOW + 1
        j_sl = hit_sl.argmax() if hit_sl.any() else never
        j_tp = hit_tp.argmax() if hit_tp.any() else never
        if j_sl == j_tp == never:
            continue                                   # hələ açıqdır
        gross_r = -1.0 if j_sl <= j_tp else tpm / slm  # eyni şamda hər ikisi → zərər (ehtiyatla)
        res[k] = gross_r - spread[i] / (atr[i] * slm)
    return res


def prepare(symbol):
    frames = load(symbol)
    h1 = frames["H1"]
    ct = h1.index + TF_DURATION["H1"]
    dirs = {tf: asof(ct, df, bias(df), tf) for tf, df in frames.items()}
    p = h1.shift(1)
    ema_up = ((p.ema_fast <= p.ema_mid) & (h1.ema_fast > h1.ema_mid)).to_numpy()
    ema_dn = ((p.ema_fast >= p.ema_mid) & (h1.ema_fast < h1.ema_mid)).to_numpy()
    macd_up = ((p.macd <= p.macd_signal) & (h1.macd > h1.macd_signal)).to_numpy()
    macd_dn = ((p.macd >= p.macd_signal) & (h1.macd < h1.macd_signal)).to_numpy()
    up, dn = ema_up | macd_up, ema_dn | macd_dn
    side = np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0))
    idx = np.flatnonzero(side != 0)
    idx = idx[(h1.index[idx] >= TRAIN[0])]
    s = side[idx]
    pip = pip_size(symbol)
    point = {"XAUUSD": 0.01}.get(symbol, 0.001 if "JPY" in symbol else 0.00001)
    c = pd.DataFrame({
        "symbol": symbol, "time": h1.index[idx], "side": s,
        "ema": np.where(s == 1, ema_up[idx], ema_dn[idx]),
        "macd": np.where(s == 1, macd_up[idx], macd_dn[idx]),
        "rsi": h1.rsi.to_numpy()[idx],
        "adx_h1": adx(h1).to_numpy()[idx],
        "adx_h4": asof(ct, frames["H4"], adx(frames["H4"]).to_numpy(), "H4")[idx],
        "hour": h1.index[idx].hour,
    })
    for tf in config.TIMEFRAMES:
        c["agree_" + tf] = dirs[tf][idx] == s
    c["strength"] = sum(c["agree_" + tf].astype(int) for tf in config.TIMEFRAMES)
    for slm, tpm in SLTP:
        c[f"R_{slm}_{tpm}"] = outcomes(h1, idx, s, slm, tpm, pip, point)
    return c


def stats(r):
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return dict(n=0, R=0.0, pf=0.0, win=0.0)
    gain, loss = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(r), R=r.sum(), pf=gain / loss if loss else np.inf, win=(r > 0).mean() * 100)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    mt5_data.connect()
    try:
        cand = pd.concat([prepare(s) for s in config.SYMBOLS], ignore_index=True)
    finally:
        mt5_data.shutdown()
    train = (cand.time >= TRAIN[0]) & (cand.time <= TRAIN[1])
    test = cand.time >= TEST[0]

    grid = itertools.product(
        ["both", "ema", "macd"],                 # kəsişmə növü
        [3, 4, 5],                               # minimum güc
        [("H4", "D1"), ("H4", "D1", "W1")],      # məcburi filtrlər
        [0, 20, 25],                             # ADX H1 minimum
        [0, 20, 25],                             # ADX H4 minimum
        ["all", "london_ny"],                    # sessiya
        [True, False],                           # RSI aralığı filtri
        SLTP,
    )
    rows = []
    for trig, mins, filt, a1, a4, sess, rsi_f, (slm, tpm) in grid:
        m = np.ones(len(cand), bool)
        if trig != "both":
            m &= cand[trig].to_numpy()
        m &= cand.strength.to_numpy() >= mins
        for tf in filt:
            m &= cand["agree_" + tf].to_numpy()
        m &= cand.adx_h1.to_numpy() >= a1
        m &= cand.adx_h4.to_numpy() >= a4
        if sess == "london_ny":     # server vaxtı (UTC+2/3) ~ 09:00–21:00 = UTC 07:00–18:00
            m &= (cand.hour >= 9).to_numpy() & (cand.hour < 21).to_numpy()
        if rsi_f:
            buy = cand.side.to_numpy() == 1
            r = cand.rsi.to_numpy()
            m &= np.where(buy, (r >= config.RSI_BUY_RANGE[0]) & (r <= config.RSI_BUY_RANGE[1]),
                          (r >= config.RSI_SELL_RANGE[0]) & (r <= config.RSI_SELL_RANGE[1]))
        col = cand[f"R_{slm}_{tpm}"].to_numpy()
        tr, te = stats(col[m & train.to_numpy()]), stats(col[m & test.to_numpy()])
        rows.append(dict(trigger=trig, min_str=mins, filt="+".join(filt), adx_h1=a1, adx_h4=a4, session=sess,
                         rsi=rsi_f, sl=slm, tp=tpm,
                         train_n=tr["n"], train_R=round(tr["R"], 1), train_pf=round(tr["pf"], 2), train_win=round(tr["win"], 1),
                         test_n=te["n"], test_R=round(te["R"], 1), test_pf=round(te["pf"], 2), test_win=round(te["win"], 1)))
    res = pd.DataFrame(rows)
    res.to_csv("optimize_results.csv", index=False)

    is_base = ((res.trigger == "both") & (res.min_str == 3) & (res.filt == "H4+D1") & (res.adx_h1 == 0) &
               (res.adx_h4 == 0) & (res.session == "all") & res.rsi & (res.sl == 1.5) & (res.tp == 3.0))
    pd.set_option("display.width", 250)
    print("İNDİKİ STRATEGİYA:")
    print(res[is_base].to_string(index=False))
    ok = res[res.train_n >= MIN_TRADES_TRAIN].sort_values("train_pf", ascending=False)
    print(f"\nÖYRƏNMƏ dövründə ən yaxşı 15 variant (≥{MIN_TRADES_TRAIN} siqnal) və onların YOXLAMA nəticəsi:")
    print(ok.head(15).to_string(index=False))
    print("\nÖyrənmədə ən yaxşı 50 variantın yoxlamadakı orta PF:", round(ok.head(50).test_pf.mean(), 2),
          "| bütün variantların orta yoxlama PF:", round(res[res.test_n > 50].test_pf.mean(), 2))
    print("Öyrənmə PF ilə yoxlama PF arasında korrelyasiya:",
          round(ok[ok.test_n > 50][["train_pf", "test_pf"]].corr().iloc[0, 1], 2))


if __name__ == "__main__":
    main()
