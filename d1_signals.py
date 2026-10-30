"""D1 strategiyası: SMA 8 həm SMA 21-i, həm SMA 30-u kəsəndə siqnal, TP 50 pips, SL yox.

Bütün D1_SYMBOLS cütləri üzrə. InvestAZ cütlərində svop istifadəçinin InvestAZ cədvəlindən,
digərlərində MT5 (swaps.json) məlumatından göstərilir. Mesajda TP-də gözlənilən gəlir AZN ilə.

Sınaq qeydləri: investaz_tp25.py, carry_honest.py (17 il, dürüst istiqamət seçimi ilə TP 50:
500 → 1129 AZN, amma kapital bir dəfə 107 AZN-ə düşüb — SL-siz risk böyükdür).
Yahoo D1 diapazonu ~10% dar olduğundan SL-li nəticələr Yahoo-da şişirdilmiş görünür (robustness.py).
"""
import logging
from datetime import datetime, timezone

import pandas as pd

import config
import news
import swaps
import telegram_notify as tg
from strategy import ma_cross_signals, pip_size

log = logging.getLogger(__name__)
LOTS = [0.01, 0.1, 1.0]


def _last_close(data, symbol):
    df = data.get_closed_bars(symbol, "D1")
    return float(df["close"].iloc[-1]) if df is not None else None


def pip_value_usd(symbol, price, data):
    """1 lot üçün 1 pipsin $ dəyəri."""
    if symbol == "XAUUSD":
        return 10.0                                    # 100 unsiya × 0.1$
    if symbol.endswith("USD"):
        return 10.0
    if symbol.startswith("USD"):                       # USDJPY, USDCHF, USDCAD
        return (1000.0 if symbol.endswith("JPY") else 10.0) / price
    quote = symbol[3:]                                 # kross: kotirovka valyutası → USD
    if quote == "JPY":
        usdjpy = _last_close(data, "USDJPY")
        return 1000.0 / usdjpy if usdjpy else None
    rate = _last_close(data, quote + "USD")            # GBPUSD, AUDUSD
    return 10.0 * rate if rate else None


def _fmt_azn(usd):
    return f"{usd * config.USD_AZN:+.2f} AZN"


def investaz_swap_usd(symbol, data, price=None):
    """InvestAZ svopu punktla verilir → 1 lot, 1 gecə üçün $ (1 punkt = pips dəyəri / 10)."""
    _, long_pt, short_pt = config.INVESTAZ[symbol]
    pv = pip_value_usd(symbol, price or _last_close(data, symbol), data) if data else None
    if not pv:
        return long_pt, short_pt          # məlumat yoxdursa — USD-kotirovkalı cütlər kimi
    return long_pt * pv / 10, short_pt * pv / 10


def swap_lines(symbol, side, data=None):
    if symbol in config.INVESTAZ:
        long_, short_ = investaz_swap_usd(symbol, data)
        mine, other = (long_, short_) if side == "BUY" else (short_, long_)
        other_side = "SELL" if side == "BUY" else "BUY"
        mark = "✅ <b>MÜSBƏT</b>" if mine > 0 else "❌ <b>MƏNFİ</b>"
        return [
            f"💱 <b>Svop</b>: {side} {mine:+.2f}$/lot/gecə — {mark}",
            f"   0.01 lotla gecəyə {_fmt_azn(mine * 0.01)} (çərşənbə 3 qat)",
            f"   ({other_side}: {other:+.2f}$/lot)",
        ]
    return swaps.format_lines(symbol, side)


def format_message(symbol, side, price, bar_time, digits, data, sample=False):
    pip = pip_size(symbol)
    sign = 1 if side == "BUY" else -1
    tp = round(price + sign * config.D1_TP_PIPS * pip, digits)
    icon = "🟢" if side == "BUY" else "🔴"
    cross = "yuxarı" if side == "BUY" else "aşağı"
    investaz = symbol in config.INVESTAZ
    spread = config.INVESTAZ[symbol][0] if investaz else config.DEFAULT_SPREAD.get(symbol, 2.0)
    pv = pip_value_usd(symbol, price, data)
    net_pips = config.D1_TP_PIPS - spread
    tp_dist = f"{config.D1_TP_PIPS * pip:.2f}$" if symbol == "XAUUSD" else f"{config.D1_TP_PIPS} pips"

    lines = []
    if sample:
        lines += ["🧪 <b>NÜMUNƏ MESAJ</b> — real siqnal deyil, formatı yoxlamaq üçündür", ""]
    lines += [
        "📅 <b>GÜNDƏLİK SİQNAL (D1)</b>",
        "Strategiya: <b>Samir</b>",
        f"Qayda: SMA 8 × SMA 21 və SMA 30 kəsişməsi, TP {config.D1_TP_PIPS} pips, SL yox",
        "Etibarlılıq: ⭐ risklidir — 17 illik sınaqda kapital bir dəfə 80% düşüb",
        "",
        f"{icon} <b>{side} {symbol}</b>" + ("  📌 <i>seçdiyiniz cüt</i>" if investaz else ""),
        f"Qiymət: <code>{price:.{digits}f}</code>",
        f"Take-profit: <code>{tp:.{digits}f}</code>  ({tp_dist})",
        f"Səbəb: gündəlik qrafikdə SMA 8 həm SMA 21-i, həm SMA 30-u {cross} kəsdi",
        "",
    ]
    if pv:
        lines.append(f"💰 <b>Gözlənilən gəlir</b> (TP-də, spred {spread:g} pips çıxılıb):")
        for lot in LOTS:
            usd = net_pips * pv * lot
            lines.append(f"   {lot:g} lot: <b>{_fmt_azn(usd)}</b>  ({usd:+.2f}$)")
        lines.append("")
    lines += swap_lines(symbol, side, data)
    lines += [
        "",
        "🛡 Qorumalar: kapital 30% düşsə hamısını bağla; 60 gündən çox açıq qalanı bağla; "
        "500 AZN üçün eyni anda 2–3 cütdən çox açma.",
        "",
    ]
    lines += news.signal_lines(symbol, datetime.now(timezone.utc))
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
    tg.send(format_message(symbol, side, price, df.index[-1], data.digits(symbol), data))
    import questions
    import tracker
    questions.record_signal(state, f"Samir (D1): {side} {symbol}")
    sign = 1 if side == "BUY" else -1
    tp = round(price + sign * config.D1_TP_PIPS * pip_size(symbol), data.digits(symbol))
    tracker.add(state, "Samir (D1)", symbol, side, round(price, data.digits(symbol)), tp, None,
                df.index[-1] + pd.Timedelta(days=1))
