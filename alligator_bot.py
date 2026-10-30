"""Alligator (H4) strategiyası: MA10 × MA50 kəsişməsi + Lips/Teeth kəsişməsi (5 şam) + AO işarəsi.
SL = 1×ATR(14), TP = 3×ATR(14). Hər yeni bağlanmış H4 şamında yoxlanılır.

Sınaq (alligator_optimize.py, MT5, 2016–2026, 5 cüt): 1079 ticarət, +0.125 R/ticarət,
11 ilin 9-u müsbət; 2016–2022 müstəqil yoxlamada da müsbət. Svop daxil deyil.
"""
import logging
from datetime import datetime, timezone

import pandas as pd

import config
import news
import telegram_notify as tg
from d1_signals import pip_value_usd, swap_lines
from indicators import atr
from strategy import alligator_signals, pip_size

log = logging.getLogger(__name__)
LOTS = [0.01, 0.1, 1.0]


def _azn(usd):
    return f"{usd * config.USD_AZN:+.2f} AZN"


def format_message(symbol, side, price, sl, tp, bar_time, digits, data, sample=False):
    pip = pip_size(symbol)
    sl_pips, tp_pips = abs(price - sl) / pip, abs(tp - price) / pip
    spread = config.INVESTAZ[symbol][0] if symbol in config.INVESTAZ else config.DEFAULT_SPREAD.get(symbol, 2.0)
    pv = pip_value_usd(symbol, price, data)
    icon = "🟢" if side == "BUY" else "🔴"
    lines = []
    if sample:
        lines += ["🧪 <b>NÜMUNƏ MESAJ</b> — real siqnal deyil, formatı yoxlamaq üçündür", ""]
    lines += [
        "🐊 <b>H4 SİQNAL</b>",
        "Strategiya: <b>Alligator (H4)</b>",
        "Qayda: MA 10 × MA 50 kəsişməsi + Alligator (Lips × Teeth) + AO işarəsi",
        "Etibarlılıq: ⭐⭐ — 10 illik sınaqda müsbət (11 ilin 9-u), ticarətlərin ~30%-i TP-yə çatır",
        "",
        f"{icon} <b>{side} {symbol}</b>" + ("  📌 <i>seçdiyiniz cüt</i>" if symbol in config.INVESTAZ else ""),
        f"Qiymət: <code>{price:.{digits}f}</code>",
        f"Take-profit: <code>{tp:.{digits}f}</code>  ({tp_pips:.0f} pips = 3 × ATR)",
        f"Stop-loss: <code>{sl:.{digits}f}</code>  ({sl_pips:.0f} pips = 1 × ATR) — <b>mütləq qoyun</b>",
        "Risk/qazanc: 1 : 3",
        "",
    ]
    if pv:
        lines.append(f"💰 <b>Nəticə</b> (spred {spread:g} pips çıxılıb):")
        for lot in LOTS:
            win = (tp_pips - spread) * pv * lot
            loss = -(sl_pips + spread) * pv * lot
            lines.append(f"   {lot:g} lot: TP <b>{_azn(win)}</b> | SL {_azn(loss)}")
        risk_azn = config.TRACK_BALANCE_AZN * config.ALLIGATOR_RISK_PCT / 100
        lot_suggest = risk_azn / config.USD_AZN / ((sl_pips + spread) * pv)
        lines.append(f"   📏 {config.TRACK_BALANCE_AZN:.0f} AZN hesab, {config.ALLIGATOR_RISK_PCT:g}% risk üçün: "
                     f"~<b>{max(lot_suggest, 0.01):.2f} lot</b>")
        lines.append("")
    lines += swap_lines(symbol, side, data)
    lines += ["", "⚠️ 8–10 ardıcıl itki bu strategiya üçün normaldır — qazanc nadir, amma 3 dəfə böyük olur.", ""]
    lines += news.signal_lines(symbol, datetime.now(timezone.utc))
    lines.append(f"\n🕐 H4 şamı: {bar_time:%d.%m.%Y %H:%M} UTC")
    return "\n".join(lines)


def levels(df, side):
    a = float(atr(df, 14).iloc[-1])
    price = float(df["close"].iloc[-1])
    sign = 1 if side == "BUY" else -1
    return price, price - sign * config.ALLIGATOR_SL_ATR * a, price + sign * config.ALLIGATOR_TP_ATR * a


def check(data, symbol, state, notify=True):
    """Yeni bağlanmış H4 şamında siqnal varsa göndərir. state açarı: _alli_<symbol>."""
    if symbol not in config.ALLIGATOR_SYMBOLS:
        return
    df = data.get_closed_bars(symbol, "H4")
    if df is None or len(df) < 80:
        return
    key = f"_alli_{symbol}"
    bar = str(df.index[-1])
    if state.get(key) == bar:
        return
    state[key] = bar
    sig = alligator_signals(df)[-1]
    if sig == 0 or not notify:
        return
    side = "BUY" if sig == 1 else "SELL"
    digits = data.digits(symbol)
    price, sl, tp = [round(x, digits) for x in levels(df, side)]
    log.info("ALLIGATOR SİQNAL: %s %s @ %s SL %s TP %s (şam %s)", side, symbol, price, sl, tp, bar)
    tg.send(format_message(symbol, side, price, sl, tp, df.index[-1], digits, data))
    import questions
    import tracker
    questions.record_signal(state, f"Alligator (H4): {side} {symbol}")
    tracker.add(state, "Alligator (H4)", symbol, side, price, tp, sl, df.index[-1] + pd.Timedelta(hours=4))
