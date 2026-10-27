"""Üçlü SMA (8 / 21 / 30, Close) strategiyasının sınağı.

A) Düzülüş: 8>21>30 → BUY, 8<21<30 → SELL, qarışıq → bazardan kənar
B) 8/21 kəsişməsi: həmişə bazarda (8>21 BUY, 8<21 SELL)
C) 8/21 kəsişməsi + SMA30 filtri: B, amma yalnız qiymət SMA30-un eyni tərəfindədirsə

H1 və H4: MT5 (~3 il), D1: Yahoo (2004–). Spred hər mövqe dəyişikliyində çıxılır.
İstifadə:  python ma_test.py
"""
import sys

import numpy as np
import pandas as pd

import config
import research as R

FAST, MID, SLOW = 8, 21, 30
POINT = lambda s: 0.01 if s == "XAUUSD" else 0.001 if "JPY" in s else 0.00001
BARS_PER_YEAR = {"H1": 252 * 24, "H4": 252 * 6, "D1": 252}


def positions(df):
    c = df.close
    f, m, s = c.rolling(FAST).mean(), c.rolling(MID).mean(), c.rolling(SLOW).mean()
    a = np.where((f > m) & (m > s), 1, np.where((f < m) & (m < s), -1, 0))
    b = np.where(f > m, 1, -1)
    cc = np.where((f > m) & (c > s), 1, np.where((f < m) & (c < s), -1, 0))
    valid = s.notna().to_numpy()
    return {k: pd.Series(np.where(valid, v, 0), index=df.index, dtype=float)
            for k, v in {"A düzülüş": a, "B 8/21 kəsişmə": b, "C kəsişmə+SMA30": cc}.items()}


def evaluate(df, pos, spread_price, bars_per_year):
    """Gəlir 1x (leverage-siz) mövqe üzrə; ticarətlər ayrıca sayılır."""
    ret = df.close.pct_change().fillna(0)
    p = pos.shift(1).fillna(0)
    cost = p.diff().abs().fillna(0) * spread_price / df.close
    r = p * ret - cost
    # ticarətlər: mövqenin hər dəyişməsi yeni ticarətdir
    trade_id = (p != p.shift()).cumsum()
    trades = r[p != 0].groupby(trade_id[p != 0]).sum()
    sharpe = r.mean() / r.std() * np.sqrt(bars_per_year) if r.std() > 0 else 0
    eq = (1 + r).cumprod()
    return dict(
        sharpe=round(sharpe, 2),
        illik_pct=round(r.mean() * bars_per_year * 100, 1),
        max_geriləmə_pct=round(((eq.cummax() - eq) / eq.cummax()).max() * 100, 1),
        ticarət=len(trades),
        qazanc_pct=round((trades > 0).mean() * 100, 1) if len(trades) else 0,
        orta_qazanc_itki=round(trades[trades > 0].mean() / -trades[trades < 0].mean(), 2) if (trades < 0).any() else np.nan,
    )


def mt5_frames(tf, bars):
    import MetaTrader5 as mt5
    import mt5_data
    out = {}
    mt5_data.connect()
    try:
        for s in config.SYMBOLS:
            r = pd.DataFrame(mt5.copy_rates_from_pos(s, mt5_data.TF_MAP[tf], 0, bars))
            r["time"] = pd.to_datetime(r.time, unit="s")
            out[s] = r.set_index("time").iloc[:-1]
    finally:
        mt5_data.shutdown()
    return out


def run(tf, frames):
    rows = []
    for s, df in frames.items():
        if "spread" in df:
            spread = (df.spread * POINT(s)).median()
        else:
            pip = 0.1 if s == "XAUUSD" else 0.01 if "JPY" in s else 0.0001
            spread = R.SPREAD[s] * pip
        for name, pos in positions(df).items():
            rows.append({"qrafik": tf, "cüt": s, "variant": name, **evaluate(df, pos, spread, BARS_PER_YEAR[tf])})
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 250)
    res = pd.concat([
        run("H1", mt5_frames("H1", 20000)),
        run("H4", mt5_frames("H4", 6000)),
        run("D1", R.load_daily()),
    ])
    res.to_csv("ma_test_results.csv", index=False)
    print("Xülasə (8 cüt üzrə orta):")
    summary = res.groupby(["qrafik", "variant"]).agg(
        sharpe=("sharpe", "mean"), illik_pct=("illik_pct", "mean"), ticarət=("ticarət", "sum"),
        qazanc_pct=("qazanc_pct", "mean"), müsbət_cüt=("sharpe", lambda x: f"{(x > 0).sum()}/{len(x)}"))
    print(summary.round(2).to_string())
    print("\nCütlər üzrə Sharpe:")
    print(res.pivot_table(index=["qrafik", "variant"], columns="cüt", values="sharpe").to_string())


if __name__ == "__main__":
    main()
