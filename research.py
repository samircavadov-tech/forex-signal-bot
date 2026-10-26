"""Məşhur strategiyaların standart parametrlərlə sınağı (parametr tənzimləmə YOXDUR).

Gündəlik strategiyalar: Yahoo D1 (2004–), hər cüt eyni riskə (10% illik volatillik) gətirilir,
portfel = cütlərin ortası. Xərc: hər mövqe dəyişikliyində spred.
London breakout: MT5 H1 (~3 il), nəticə R ilə.

İstifadə:  python research.py
"""
import sys

import numpy as np
import pandas as pd
import yfinance as yf

import config

START = "2004-01-01"
TICKERS = {s: ("GC=F" if s == "XAUUSD" else s + "=X") for s in config.SYMBOLS}
SPREAD = {"EURUSD": 1.0, "GBPUSD": 1.5, "USDJPY": 1.5, "USDCHF": 2.0, "AUDUSD": 1.5,
          "USDCAD": 2.0, "NZDUSD": 2.5, "XAUUSD": 3.0}          # pips (qızıl: 0.1$ = 1 pip)
PERIODS = [("2004", "2010"), ("2011", "2016"), ("2017", "2021"), ("2022", "2026")]
TARGET_VOL = 0.10


# ---------- gündəlik strategiyalar: mövqe (-1..1) günün bağlanışında qərar verilir ----------
def sma(x, n):
    return x.rolling(n).mean()


def rsi(c, n):
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l)


def tsmom(df):
    sig = np.sign(df.close / df.close.shift(252) - 1)
    month_end = df.index.to_series().dt.to_period("M") != df.index.to_series().shift(-1).dt.to_period("M")
    return sig.where(month_end).ffill()


def ma_cross(df):
    return np.sign(sma(df.close, 50) - sma(df.close, 200))


def donchian(entry, exit_):
    def f(df):
        hi_e, lo_e = df.high.rolling(entry).max().shift(), df.low.rolling(entry).min().shift()
        hi_x, lo_x = df.high.rolling(exit_).max().shift(), df.low.rolling(exit_).min().shift()
        pos, out = 0, []
        for c, he, le, hx, lx in zip(df.close, hi_e, lo_e, hi_x, lo_x):
            if pos == 1 and c < lx or pos == -1 and c > hx:
                pos = 0
            if pos == 0:
                pos = 1 if c > he else -1 if c < le else 0
            out.append(pos)
        return pd.Series(out, index=df.index, dtype=float)
    return f


def rsi2(df):
    c, r, s200, s5 = df.close, rsi(df.close, 2), sma(df.close, 200), sma(df.close, 5)
    pos, out = 0, []
    for ci, ri, a, b in zip(c, r, s200, s5):
        if pos == 1 and ci > b or pos == -1 and ci < b:
            pos = 0
        if pos == 0 and not np.isnan(a):
            pos = 1 if ci > a and ri < 10 else -1 if ci < a and ri > 90 else 0
        out.append(pos)
    return pd.Series(out, index=df.index, dtype=float)


DAILY = {
    "1. Time-series momentum 12m": tsmom,
    "2. Donchian 20/10": donchian(20, 10),
    "3. Donchian 55/20": donchian(55, 20),
    "4. MA 50/200 kəsişmə": ma_cross,
    "5. RSI(2) mean reversion": rsi2,
}


def load_daily():
    data = {}
    for s, t in TICKERS.items():
        df = yf.download(t, start=START, interval="1d", progress=False, auto_adjust=False, multi_level_index=False)
        df = df.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
        df = df[(df.close > 0) & (df.high >= df.low)]
        data[s] = df
    return data


def daily_returns(strategy, data):
    """Hər cüt üçün volatilliyə görə ölçülmüş günlük xalis gəlir."""
    out = {}
    for s, df in data.items():
        ret = df.close.pct_change()
        vol = ret.rolling(60).std() * np.sqrt(252)
        w = (strategy(df).fillna(0) * TARGET_VOL / vol).clip(-3, 3).shift(1).fillna(0)
        pip = 0.1 if s == "XAUUSD" else 0.01 if "JPY" in s else 0.0001
        cost = w.diff().abs().fillna(0) * SPREAD[s] * pip / df.close
        out[s] = (w * ret - cost).fillna(0)
    return pd.DataFrame(out).fillna(0)


def metrics(r):
    r = r[r.index >= "2005-01-01"]
    if r.std() == 0:
        return dict(sharpe=0.0, annual=0.0, maxdd=0.0)
    sharpe = r.mean() / r.std() * np.sqrt(252)
    eq = (1 + r).cumprod()
    return dict(sharpe=round(sharpe, 2), annual=round(r.mean() * 252 * 100, 1),
                maxdd=round(((eq.cummax() - eq) / eq.cummax()).max() * 100, 1))


# ---------- London breakout (H1, MT5) ----------
def london_breakout():
    import MetaTrader5 as mt5
    import mt5_data
    from strategy import pip_size
    mt5_data.connect()
    rows = []
    try:
        for s in config.SYMBOLS:
            r = pd.DataFrame(mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 20000))
            r["time"] = pd.to_datetime(r.time, unit="s")
            r = r.set_index("time")
            point = 0.01 if s == "XAUUSD" else 0.001 if "JPY" in s else 0.00001
            for day, g in r.groupby(r.index.date):
                asia = g[(g.index.hour >= 2) & (g.index.hour < 9)]          # server ~ 00–07 UTC
                trade = g[(g.index.hour >= 9) & (g.index.hour < 21)]
                if len(asia) < 6 or trade.empty:
                    continue
                hi, lo = asia.high.max(), asia.low.min()
                rng = hi - lo
                if rng <= 0:
                    continue
                res = None
                for t, b in trade.iterrows():
                    if res is None:
                        if b.high > hi and b.low < lo:
                            break                                         # aydın deyil — keç
                        if b.high > hi:
                            res = [1, hi, lo, hi + rng]
                        elif b.low < lo:
                            res = [-1, lo, hi, lo - rng]
                        else:
                            continue
                    side, entry, sl, tp = res
                    if (side == 1 and b.low <= sl) or (side == -1 and b.high >= sl):
                        rows.append((s, t, -1.0 - b.spread * point / rng)); break
                    if (side == 1 and b.high >= tp) or (side == -1 and b.low <= tp):
                        rows.append((s, t, 1.0 - b.spread * point / rng)); break
                else:
                    if res:
                        side, entry = res[0], res[1]
                        rows.append((s, trade.index[-1], side * (trade.close.iloc[-1] - entry) / rng
                                     - trade.spread.iloc[-1] * point / rng))
    finally:
        mt5_data.shutdown()
    return pd.DataFrame(rows, columns=["symbol", "time", "R"])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 220)
    data = load_daily()
    print("Məlumat:", {s: f"{d.index[0]:%Y}-{d.index[-1]:%Y}" for s, d in data.items()})

    summary, per_pair, per_period = [], {}, {}
    for name, strat in DAILY.items():
        r = daily_returns(strat, data)
        port = r.mean(axis=1)
        summary.append({"Strategiya": name, **metrics(port),
                        "Müsbət illər": f"{(port.groupby(port.index.year).sum() > 0).sum()}/{port.index.year.nunique()}"})
        per_pair[name] = {s: metrics(r[s])["sharpe"] for s in r}
        per_period[name] = {f"{a}–{b}": metrics(port[a:b])["sharpe"] if len(port[a:b]) else np.nan
                            for a, b in PERIODS}

    print("\nGÜNDƏLİK STRATEGİYALAR — portfel (8 cüt, 2005–2026):")
    print("Sharpe: 0 = heç nə, 0.5 = yaxşı, 1+ = əla. annual = 10% vol hədəfi ilə illik gəlir %, maxdd = ən böyük geriləmə %")
    print(pd.DataFrame(summary).to_string(index=False))
    print("\nSharpe dövrlər üzrə (sabitlik):")
    print(pd.DataFrame(per_period).T.to_string())
    print("\nSharpe cütlər üzrə (2005–2026):")
    print(pd.DataFrame(per_pair).T.to_string())

    lb = london_breakout()
    print("\nLONDON BREAKOUT (H1, MT5):", f"{lb.time.min():%Y-%m-%d} — {lb.time.max():%Y-%m-%d}")
    g = lb.groupby("symbol").R
    t = pd.DataFrame({"siqnal": g.count(), "net R": g.sum().round(1), "qazanc %": (g.apply(lambda x: (x > 0).mean() * 100)).round(1)})
    t.loc["CƏMİ"] = [len(lb), round(lb.R.sum(), 1), round((lb.R > 0).mean() * 100, 1)]
    print(t.to_string())
    print("İllər üzrə net R:", lb.groupby(lb.time.dt.year).R.sum().round(1).to_dict())


if __name__ == "__main__":
    main()
