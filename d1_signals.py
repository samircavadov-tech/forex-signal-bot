"""D1 strategiyası: SMA 8 həm SMA 21-i, həm SMA 30-u kəsəndə siqnal, TP 100 pips.

DİQQƏT: Yahoo D1 məlumatında (2004–2026) +10 859 pips görünürdü, amma real broker (MT5)
məlumatında eyni qayda ≈ sıfır/mənfi nəticə verir — Yahoo gündəlik diapazonu ~10% dar göstərir
və dar SL az vurulur (robustness.py müqayisəsi). Üstünlük TƏSDİQLƏNMƏYİB.
Qızılda işləmədiyi üçün qızıl daxil deyil.
"""
import logging
from datetime import datetime, timezone

import config
import news
import swaps
import telegram_notify as tg
from strategy import ma_cross_signals, pip_size

log = logging.getLogger(__name__)


def format_message(symbol, side, price, bar_time, digits):
    pip = pip_size(symbol)
    sign = 1 if side == "BUY" else -1
    tp = round(price + sign * config.D1_TP_PIPS * pip, digits)
    sl = round(price - sign * config.D1_SL_PIPS * pip, digits)
    icon = "🟢" if side == "BUY" else "🔴"
    cross = "yuxarı" if side == "BUY" else "aşağı"
    lines = [
        "📅 <b>GÜNDƏLİK SİQNAL (D1)</b>",
        "Strategiya: SMA 8 × SMA 21 və SMA 30 kəsişməsi, TP 100 pips",
        "Etibarlılıq: ⭐ zəif — real broker məlumatı ilə sınaqda qazanc təsdiqlənmədi",
        "",
        f"{icon} <b>{side} {symbol}</b>",
        f"Qiymət: <code>{price:.{digits}f}</code>",
        f"Take-profit: <code>{tp:.{digits}f}</code>  ({config.D1_TP_PIPS} pips)",
        f"Stop-loss (tövsiyə): <code>{sl:.{digits}f}</code>  ({config.D1_SL_PIPS} pips)",
        f"Səbəb: gündəlik qrafikdə SMA 8 həm SMA 21-i, həm SMA 30-u {cross} kəsdi",
        "",
        "📊 Sınaq (MT5, 2004–2026): nəticə təxminən sıfır. Ticarətlərin ~21–25%-i TP-yə çatır.",
        f"⚠️ SL-siz ticarət edirsinizsə: hər {config.D1_NO_SL_EQUITY_PER_001:,}$ hesab üçün ən çox 0.01 lot "
        "(tarixdə üzən zərər 10 000 pipsə çatıb).",
        "",
    ]
    lines += swaps.format_lines(symbol, side)
    lines += [""] + news.signal_lines(symbol, datetime.now(timezone.utc))
    lines.append(f"\n🕐 Gün şamı: {bar_time:%d.%m.%Y}")
    return "\n".join(lines)


def check(data, symbol, state, notify=True):
    """Yeni bağlanmış D1 şamında siqnal varsa göndərir. state açarı: _d1_<symbol>."""
    if symbol not in config.D1_SYMBOLS:
        return
    df = data.get_closed_bars(symbol, "D1")
    if df is None or len(df) < 32:
        return
    key = f"_d1_{symbol}"
    bar = str(df.index[-1])
    if state.get(key) == bar:
        return
    state[key] = bar
    side = ma_cross_signals(df)[-1]
    if side == 0 or not notify:
        return
    side = "BUY" if side == 1 else "SELL"
    price = float(df["close"].iloc[-1])
    log.info("D1 SİQNAL: %s %s @ %s (gün %s)", side, symbol, price, bar)
    tg.send(format_message(symbol, side, price, df.index[-1], data.digits(symbol)))
