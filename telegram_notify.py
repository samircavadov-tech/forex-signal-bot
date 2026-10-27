import logging
from datetime import datetime, timedelta, timezone

import requests

import config
import news
import swaps
from strategy import pip_size

BAKU = timezone(timedelta(hours=4))   # Bakıda yay/qış vaxtı yoxdur

API = "https://api.telegram.org/bot{token}/{method}"
log = logging.getLogger(__name__)


def send(text: str) -> bool:
    """TELEGRAM_CHAT_ID vergüllə ayrılmış bir neçə ID ola bilər. Hamısına çatarsa True."""
    chat_ids = [c.strip() for c in str(config.TELEGRAM_CHAT_ID).split(",") if c.strip()]
    if not config.TELEGRAM_BOT_TOKEN or not chat_ids:
        log.warning("Telegram tənzimlənməyib (config.py) — mesaj göndərilmədi.")
        return False
    ok = True
    for chat_id in chat_ids:
        try:
            r = requests.post(
                API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage"),
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if not r.ok:
                log.error("Telegram xətası (%s): %s", chat_id, r.text)
            ok &= r.ok
        except requests.RequestException as e:
            log.error("Telegram-a qoşulmaq olmadı (%s): %s", chat_id, e)
            ok = False
    return ok


def find_chat_ids():
    """Bota son yazılmış mesajlardan chat ID-ləri qaytarır."""
    r = requests.get(API.format(token=config.TELEGRAM_BOT_TOKEN, method="getUpdates"), timeout=15)
    r.raise_for_status()
    ids = {}
    for upd in r.json().get("result", []):
        chat = (upd.get("message") or upd.get("channel_post") or {}).get("chat")
        if chat:
            ids[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    return ids


def format_signal(sig) -> str:
    icon = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}
    pip = pip_size(sig.symbol)

    def dist(a, b):
        d = abs(a - b)
        return f"{d:.2f}$" if sig.symbol == "XAUUSD" else f"{d / pip:.0f} pips"
    lines = [
        "⏱ <b>SAATLIQ SİQNAL (H1)</b>",
        "Strategiya: <b>Trend təsdiqi</b>",
        "Qayda: EMA + MACD + RSI kəsişməsi, 5 timeframe təsdiqi",
        "Etibarlılıq: ⭐ zəif — sınaqda (2 il) qazanc göstərmədi",
        "",
        f"{icon[sig.side]} <b>{sig.side} {sig.symbol}</b>",
        f"Qiymət: <code>{sig.price}</code>",
        f"Stop-loss: <code>{sig.sl}</code>  ({dist(sig.price, sig.sl)})",
        f"Take-profit: <code>{sig.tp}</code>  ({dist(sig.tp, sig.price)})",
        f"Güc: {sig.strength}/{len(sig.biases)} timeframe razıdır",
        f"Səbəb: {sig.trigger}",
        "",
    ]
    if sig.note:
        lines[-1:-1] = [f"⚠️ {sig.note}"]
    swap = swaps.format_lines(sig.symbol, sig.side)
    if swap:
        lines += swap + [""]
    lines += news.signal_lines(sig.symbol, datetime.now(timezone.utc)) + [""]
    lines += [
        "<b>Timeframe analizi:</b>",
    ]
    for b in sig.biases:
        lines.append(f"{icon[b.direction]} {b.tf}: {b.score:+d}  RSI {b.rsi:.0f}  ({' '.join(b.details)})")
    lines.append(f"\n🕐 {datetime.now(BAKU):%Y-%m-%d %H:%M} (Bakı vaxtı)")
    return "\n".join(lines)
