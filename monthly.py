"""Aylıq trend hesabatı — sınaqlarda ən sabit nəticəni verən strategiya:
qızılda 12 aylıq trend (time-series momentum). 2005–2026 sınağında xərclərlə Sharpe ≈ 0.55,
4 dövrün hamısında müsbət (research.py). Ayda bir dəfə yoxlanılır.

Valyutalar üçün trend + carry vəziyyəti yalnız MƏLUMAT kimi göstərilir (sınaqda üstünlük yoxdur).
"""
import logging

import numpy as np
import pandas as pd
import yfinance as yf

import config
import swaps

log = logging.getLogger(__name__)

GOLD_TICKER = "GC=F"
TARGET_VOL = 0.10          # hesabın illik volatilliyi hədəfi (10%)
EXAMPLE_EQUITY = 10_000    # lot nümunəsi üçün hesab ölçüsü, $
GOLD_CONTRACT = 100        # 1 lot qızıl = 100 unsiya
MONTHS_AZ = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "İyun", "İyul",
             "Avqust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]


def _daily(ticker):
    df = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=False, multi_level_index=False)
    return df.rename(columns=str.lower)["close"].dropna()


def trend(close: pd.Series):
    """12 aylıq (252 iş günü) dəyişmə, % və istiqamət."""
    change = close.iloc[-1] / close.iloc[-253] - 1
    return change * 100, (1 if change > 0 else -1)


def gold_section(prev_side):
    close = _daily(GOLD_TICKER)
    change, side = trend(close)
    vol = close.pct_change().tail(60).std() * np.sqrt(252)
    lots = TARGET_VOL * EXAMPLE_EQUITY / (vol * close.iloc[-1] * GOLD_CONTRACT)
    action = "🟢 BUY — saxla / al" if side == 1 else "🔴 SELL — sat / çıx"
    changed = prev_side is not None and prev_side != side
    lines = [
        "🥇 <b>QIZIL (XAUUSD) — əsas strategiya</b>",
        f"12 aylıq dəyişmə: <b>{change:+.1f}%</b>",
        f"Tövsiyə: <b>{action}</b>" + ("  ⚠️ <b>İSTİQAMƏT DƏYİŞDİ!</b>" if changed else ""),
        f"Lot (hər {EXAMPLE_EQUITY:,}$ hesab üçün, 10% illik risk): ~<b>{lots:.2f}</b>",
        f"Qızılın son 60 günlük volatilliyi: {vol * 100:.0f}% illik",
        "Mövqe ay boyu saxlanılır, növbəti hesabatda yenidən yoxlanılır.",
    ]
    return lines, side


def fx_section():
    sw = (swaps.load() or {}).get("symbols", {})
    lines = ["", "💱 <b>Valyutalar</b> (yalnız məlumat — sınaqda sabit üstünlük yoxdur):"]
    for s in config.SYMBOLS:
        if s == "XAUUSD":
            continue
        try:
            change, side = trend(_daily(s + "=X"))
        except Exception as e:
            log.warning("%s trend hesablanmadı: %s", s, e)
            continue
        t = "↑" if side == 1 else "↓"
        info = sw.get(s)
        carry = ""
        if info:
            best = "BUY" if info["long"] > info["short"] else "SELL"
            carry = f"  svop üstün: {best}"
        lines.append(f"{s}: trend {t} {change:+.1f}%{carry}")
    return lines


def report(state: dict, now_baku) -> str:
    gold_lines, side = gold_section(state.get("_gold_side"))
    state["_gold_side"] = side
    head = (f"📆 <b>AYLIQ HESABAT — {MONTHS_AZ[now_baku.month - 1]} {now_baku.year}</b>\n"
            "Strategiya: <b>Qızıl trendi</b>\n"
            "Qayda: qızılın 12 aylıq dəyişməsi (ayda 1 dəfə)\n"
            "Etibarlılıq: ⭐⭐ yaxşı — 22 illik sınaqda müsbət")
    return "\n".join([head, ""] + gold_lines + fx_section() +
                     ["", "Strategiya: 12 aylıq trend (time-series momentum). Keçmiş nəticə zəmanət deyil."])
