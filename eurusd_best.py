"""EURUSD üçün internetdə ən çox tövsiyə olunan strategiyaların sınağı (standart parametrlər, tənzimləmə YOXDUR).

Məlumat: MT5 D1 (2009–2026) və H4 (~10 il). 0.01 lot sabit, nəticə pips və AZN ilə.
Xərc: hər giriş/çıxışda spred 0.6 + 0.2 sürüşmə pips. Svop iki variantda: yox / bugünkü (alış −13.5, satış +2.91 punkt).
Öyrənmə/yoxlama ayrımı yoxdur (parametr seçilmir), amma nəticə iki dövr üzrə ayrıca göstərilir: 2009–2017 və 2018–2026.

İstifadə:  python eurusd_best.py
"""
import sys

import numpy as np
import pandas as pd

import config
import mt5_data
from alligator_test import load
from indicators import atr
from strategy import alligator_signals

PIP = 0.0001
COST = 0.6 + 0.2                    # pips, bir dövrə (giriş + çıxış)
SWAP_LONG, SWAP_SHORT = -13.5, 2.91  # punkt/lot/gecə → 0.01 lotda pips ekvivalenti: /10
AZN_PER_PIP = 0.10 * config.USD_AZN  # 0.01 lot
SPLIT = "2018-01-01"


# ---------- mövqe əsaslı strategiyalar (D1): pos[t] şamın bağlanışında qərar, t+1-də nəticə ----------
def sma(x, n):
    return x.rolling(n).mean()


def rsi(c, n):
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def hold(entry_long, exit_long, entry_short, exit_short):
    """Giriş/çıxış şərtlərindən mövqe seriyası (+1/0/−1)."""
    pos, p = [], 0
    for el, xl, es, xs in zip(entry_long, exit_long, entry_short, exit_short):
        if p == 1 and xl:
            p = 0
        elif p == -1 and xs:
            p = 0
        if p == 0:
            p = 1 if el else -1 if es else 0
        pos.append(p)
    return np.array(pos)


def donchian(df, n_in, n_out):
    c, h, l = df.close, df.high, df.low
    up, dn = h.rolling(n_in).max().shift(), l.rolling(n_in).min().shift()
    xl, xs = l.rolling(n_out).min().shift(), h.rolling(n_out).max().shift()
    return hold(c > up, c < xl, c < dn, c > xs)


def ma_always(df, f, s, ema=False):
    c = df.close
    a, b = (c.ewm(span=f).mean(), c.ewm(span=s).mean()) if ema else (sma(c, f), sma(c, s))
    return np.where(a > b, 1, -1) * b.notna()


def tsmom(df, n=252):
    r = df.close / df.close.shift(n) - 1
    return np.sign(r).fillna(0).to_numpy()


def macd(df):
    c = df.close
    m = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    return np.where(m > m.ewm(span=9).mean(), 1, -1)


def rsi2(df):
    c = df.close
    r, s200, s5 = rsi(c, 2), sma(c, 200), sma(c, 5)
    return hold((r < 10) & (c > s200), c > s5, (r > 90) & (c < s200), c < s5)


def bollinger(df):
    c = df.close
    m, sd = sma(c, 20), c.rolling(20).std()
    return hold(c < m - 2 * sd, c >= m, c > m + 2 * sd, c <= m)


def short_trend(df):
    """Yalnız SELL (müsbət svop): qiymət SMA200-dən aşağı olanda satışda qal."""
    c = df.close
    return np.where(c < sma(c, 200), -1, 0)


def short_always(df):
    return -np.ones(len(df))


def position_pnl(df, pos, swap):
    pos = pd.Series(pos, index=df.index).fillna(0)
    held = pos.shift().fillna(0)
    move = df.close.diff().fillna(0) / PIP
    nights = df.index.to_series().diff().dt.days.fillna(0)
    sw = np.where(held > 0, SWAP_LONG, np.where(held < 0, SWAP_SHORT, 0)) / 10 * nights * swap
    cost = pos.diff().abs().fillna(0) * COST / 2
    trades = int((pos.diff().fillna(0) != 0).sum() / 2)
    return held * move + sw - cost, trades


# ---------- ticarət əsaslı strategiyalar ----------
def trade_pnl(df, entries, exits_fn, swap):
    """entries: (i, side). exits_fn(i, side) → (j, exit_price). Eyni anda 1 ticarət. Gündəlik P&L qaytarır."""
    daily = pd.Series(0.0, index=df.index)
    busy, n = -1, 0
    for i, side in entries:
        if i <= busy or i >= len(df) - 1:
            continue
        j, px = exits_fn(i, side)
        e = df.close.iloc[i]
        pips = side * (px - e) / PIP - COST
        nights = (df.index[j] - df.index[i]).days
        pips += (SWAP_LONG if side == 1 else SWAP_SHORT) / 10 * nights * swap
        daily.iloc[j] += pips
        busy, n = j, n + 1
    return daily, n


def ma821_tp10_sell(df, swap):
    c = df.close
    f, m = sma(c, 8), sma(c, 21)
    dn = (f < m) & (f.shift() >= m.shift())
    hi, lo = df.high.to_numpy(), df.low.to_numpy()

    def ex(i, side):
        tp = df.close.iloc[i] - 10 * PIP
        hit = np.flatnonzero(lo[i + 1:] <= tp)
        return (i + 1 + hit[0], tp) if len(hit) else (len(df) - 1, df.close.iloc[-1])
    return trade_pnl(df, [(i, -1) for i in np.flatnonzero(dn.to_numpy())], ex, swap)


def alligator_h4(df, swap):
    sig = alligator_signals(df)
    a = atr(df, 14).to_numpy()
    hi, lo, cl = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()

    def ex(i, side):
        sl, tp = cl[i] - side * a[i], cl[i] + side * 3 * a[i]
        for j in range(i + 1, len(df)):
            if (lo[j] <= sl) if side == 1 else (hi[j] >= sl):
                return j, sl                       # bir şamda hər ikisi — ehtiyatla SL
            if (hi[j] >= tp) if side == 1 else (lo[j] <= tp):
                return j, tp
        return len(df) - 1, cl[-1]
    return trade_pnl(df, [(i, int(s)) for i, s in enumerate(sig) if s != 0 and not np.isnan(a[i])], ex, swap)


def metrics(daily, trades):
    eq = daily.cumsum()
    dd = (eq - eq.cummax()).min()
    yearly = daily.groupby(daily.index.year).sum()
    years = (daily.index[-1] - daily.index[0]).days / 365.25
    a, b = daily[daily.index < SPLIT], daily[daily.index >= SPLIT]
    ya, yb = (a.index[-1] - a.index[0]).days / 365.25, (b.index[-1] - b.index[0]).days / 365.25
    return dict(ticarət=trades, pips_il=daily.sum() / years, il_2009_17=a.sum() / ya, il_2018_26=b.sum() / yb,
                müsbət_il=f"{(yearly > 0).sum()}/{len(yearly)}", max_düşmə_pips=dd,
                AZN_il=daily.sum() / years * AZN_PER_PIP, max_düşmə_AZN=dd * AZN_PER_PIP)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    mt5_data.connect()
    try:
        d1 = load("EURUSD", "D1", 4500)
        h4 = load("EURUSD", "H4", 16000)
    finally:
        mt5_data.shutdown()
    d1 = d1[d1.index >= "2009-01-01"]
    print(f"D1: {d1.index[0]:%Y-%m-%d} → {d1.index[-1]:%Y-%m-%d} | H4: {h4.index[0]:%Y-%m-%d} → {h4.index[-1]:%Y-%m-%d}\n")
    pos_strats = {
        "Turtle (Donchian 20/10)": lambda: donchian(d1, 20, 10),
        "Turtle (Donchian 55/20)": lambda: donchian(d1, 55, 20),
        "EMA 50/200 trend": lambda: ma_always(d1, 50, 200, ema=True),
        "SMA 8/21 (həmişə bazarda)": lambda: ma_always(d1, 8, 21),
        "MACD 12/26/9": lambda: macd(d1),
        "12 aylıq momentum": lambda: tsmom(d1),
        "RSI(2) Connors": lambda: rsi2(d1),
        "Bollinger 20/2 geri dönüş": lambda: bollinger(d1),
        "Yalnız SELL, SMA200 altında": lambda: short_trend(d1),
        "Həmişə SELL (svop üçün)": lambda: short_always(d1),
    }
    rows = []
    for swap in (0, 1):
        for name, f in pos_strats.items():
            daily, n = position_pnl(d1, f(), swap)
            rows.append(dict(strategiya=name, qrafik="D1", svop="var" if swap else "yox", **metrics(daily, n)))
        daily, n = ma821_tp10_sell(d1, swap)
        rows.append(dict(strategiya="8×21 SELL, TP 10, SL yox", qrafik="D1", svop="var" if swap else "yox",
                         **metrics(daily, n)))
        daily, n = alligator_h4(h4, swap)
        rows.append(dict(strategiya="Alligator (bizim)", qrafik="H4", svop="var" if swap else "yox",
                         **metrics(daily, n)))
    r = pd.DataFrame(rows).round(1)
    r.to_csv("eurusd_best.csv", index=False)
    for sw in ("yox", "var"):
        print(f"===== Svop: {sw} =====")
        print(r[r.svop == sw].drop(columns="svop").sort_values("AZN_il", ascending=False).to_string(index=False))
        print()


if __name__ == "__main__":
    main()
