import logging

import requests

import config

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
    lines = [
        f"{icon[sig.side]} <b>{sig.side} {sig.symbol}</b>",
        f"Qiymət: <code>{sig.price}</code>",
        f"Stop-loss: <code>{sig.sl}</code>",
        f"Take-profit: <code>{sig.tp}</code>",
        f"Güc: {sig.strength}/{len(sig.biases)} timeframe razıdır",
        f"Səbəb: {sig.trigger}",
        "",
        "<b>Timeframe analizi:</b>",
    ]
    for b in sig.biases:
        lines.append(f"{icon[b.direction]} {b.tf}: {b.score:+d}  RSI {b.rsi:.0f}  ({' '.join(b.details)})")
    lines.append(f"\n🕐 Şam: {sig.bar_time:%Y-%m-%d %H:%M}")
    return "\n".join(lines)
