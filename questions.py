"""Telegram sualları: istifadəçi lot / pips / gün yazır, bot gəliri hesablayıb cavab verir.

Nümunələr:
  (siqnal mesajına Reply)  0.05 lot 30 pips
  EURAUD SELL 0.05 lot 30 pips 10 gün
  GBPUSD 0.1 lot 40 pips
Yalnız TELEGRAM_CHAT_ID-dəki istifadəçilərə cavab verilir.
"""
import logging
import re
import time

import requests

import config
import swaps
from d1_signals import pip_value_usd
from strategy import pip_size

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"
ALL_SYMBOLS = list(dict.fromkeys(config.SYMBOLS + config.D1_SYMBOLS))
# marja faizi: istifadəçinin cədvəli (1:50 = 2%, krosslar 5%); digərləri təxmini
MARGIN_RATE = {"AUDJPY": 0.05, "EURGBP": 0.05, "EURAUD": 0.05}
MAX_AGE_SEC = 30 * 60

HELP = (
    "🧮 <b>Hesablama üçün sual nümunələri</b>\n"
    "• Siqnal mesajına <b>Reply</b> edib yazın: <code>0.05 lot 30 pips</code>\n"
    "• Və ya birbaşa: <code>EURAUD SELL 0.05 lot 30 pips</code>\n"
    "• Svopu da hesablamaq üçün gün əlavə edin: <code>... 10 gün</code>\n"
    "• Siqnalların real nəticəsi: <code>hesabat</code>\n"
    f"Cütlər: {', '.join(ALL_SYMBOLS)}"
)


GREETINGS = ("salam", "slm", "hi", "hello", "hey", "privet", "привет", "sabahınız xeyir", "sabahiniz xeyir",
             "günortanız xeyir", "axşamınız xeyir", "axsaminiz xeyir", "/start")

NOT_CHAT = (
    "ℹ️ <b>Bu bot yazışma üçün nəzərdə tutulmayıb.</b>\n\n"
    "Bot yalnız aşağıdakı xidmətləri göstərir:\n"
    "• 📅 bazar siqnallarının avtomatik göndərilməsi\n"
    "• 📰 gündəlik iqtisadi xəbər xülasəsi və 📆 aylıq hesabat\n"
    "• 🧮 gəlir hesablaması — məsələn: <code>EURAUD SELL 0.05 lot 30 pips</code>\n\n"
    "Anlayışınız üçün təşəkkür edirik."
)


def record_signal(state, text):
    """Göndərilən siqnalı yadda saxlayır (son 24 saat salamlaşma cavabında göstərilir)."""
    now = time.time()
    items = [x for x in state.get("_signals", []) if now - x[0] < 24 * 3600]
    items.append([now, text])
    state["_signals"] = items[-20:]


def welcome(state):
    now = time.time()
    recent = [x for x in state.get("_signals", []) if now - x[0] < 24 * 3600]
    lines = ["👋 <b>Salam! Forex Siqnal Botuna xoş gəlmisiniz.</b>", "",
             "Bot valyuta bazarını avtomatik izləyir və strategiya şərtləri yarandıqda sizə dərhal siqnal göndərir.", ""]
    if recent:
        lines.append("📬 <b>Son 24 saatda göndərilən siqnallar:</b>")
        for ts, text in recent:
            t = time.strftime("%d.%m %H:%M", time.gmtime(ts + 4 * 3600))   # Bakı vaxtı
            lines.append(f"• {t} — {text}")
    else:
        lines.append("📭 <b>Hazırda aktiv siqnal yoxdur.</b> Yeni siqnal yarandıqda bildiriş alacaqsınız.")
    lines += ["", "🧮 Gəliri hesablamaq üçün siqnal mesajına <b>Reply</b> edib yazın, məsələn: <code>0.05 lot 30 pips</code>"]
    return "\n".join(lines)


def is_greeting(low):
    """İlk söz salamlaşmadırsa (məs. "salam", "hi"), və ya çoxsözlü salamla başlayırsa."""
    first = re.split(r"[\s,!.?]+", low.strip())[0]
    return first in GREETINGS or any(low.startswith(g) for g in GREETINGS if " " in g)


def is_calculation(text, replied):
    t = text.lower()
    has_units = re.search(r"\d\s*(lot|pip)", t) is not None   # "lotla", "pipsə" də
    has_symbol = any(s in text.upper().replace("/", "").replace(" ", "") for s in ALL_SYMBOLS)
    has_number = re.search(r"\d", t) is not None
    return has_units or has_symbol or (bool(replied) and has_number)


def _allowed_chats():
    return {c.strip() for c in str(config.TELEGRAM_CHAT_ID).split(",") if c.strip()}


def _reply(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        r = requests.post(API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage"), json=payload, timeout=15)
        if not r.ok:
            log.error("Cavab Telegram tərəfindən rədd edildi (%s): %s", chat_id, r.text[:300])
        return r.ok
    except requests.RequestException as e:
        log.error("Cavab göndərilmədi: %s", e)
        return False


def _num(s):
    return float(s.replace(",", "."))


def parse(text, replied=""):
    """Sualdan cüt, istiqamət, lot, pips, gün, qiymət çıxarır."""
    t = text.lower().replace(",", ".")
    def find_symbol(src):
        flat = src.upper().replace("/", "").replace(" ", "")
        return next((s for s in ALL_SYMBOLS if s in flat), None)
    symbol = find_symbol(text) or find_symbol(replied)
    # istiqamət: əvvəlcə sualdan, sonra Reply edilən mesajdan
    side = None
    for src in (text.upper(), replied.upper()):
        if "SELL" in src or "SATIŞ" in src:
            side = "SELL"
            break
        if "BUY" in src or "ALIŞ" in src:
            side = "BUY"
            break
    lot = re.search(r"(\d+(?:\.\d+)?)\s*lot", t)
    pips = re.search(r"(\d+(?:\.\d+)?)\s*(?:pips|pip|pp|pts|pt)", t)
    days = re.search(r"(\d+)\s*(?:gün|gun|gecə|gece|day)", t)
    # vahidsiz rəqəmlər: kəsr → lot, tam ≥ 5 → pips
    loose = [m for m in re.findall(r"\d+(?:\.\d+)?", t)]
    lot = _num(lot.group(1)) if lot else next((_num(x) for x in loose if "." in x and _num(x) < 100), None)
    pips = _num(pips.group(1)) if pips else next((_num(x) for x in loose if "." not in x and _num(x) >= 5
                                                  and not (days and x == days.group(1))), None)
    price = re.search(r"Qiymət:\s*([\d.]+)", replied)
    return dict(symbol=symbol, side=side, lot=lot or 0.01, pips=pips or config.D1_TP_PIPS,
                days=int(days.group(1)) if days else None, price=float(price.group(1)) if price else None)


def swap_for(symbol):
    if symbol in config.INVESTAZ:
        _, l, s = config.INVESTAZ[symbol]
        return l, s
    sw = (swaps.load() or {}).get("symbols", {}).get(symbol)
    return (sw["long"], sw["short"]) if sw else (None, None)


def answer(q, data):
    sym = q["symbol"]
    if not sym:
        return HELP
    lot, pips, side = q["lot"], q["pips"], q["side"]
    df = data.get_closed_bars(sym, "D1")
    price = q["price"] or (float(df["close"].iloc[-1]) if df is not None else None)
    if price is None:
        return f"❌ {sym} üçün qiymət tapılmadı, bir az sonra yenidən yoxlayın."
    pv1 = pip_value_usd(sym, price, data)
    if not pv1:
        return f"❌ {sym} üçün pips dəyəri hesablanmadı."
    spread = config.INVESTAZ[sym][0] if sym in config.INVESTAZ else config.DEFAULT_SPREAD.get(sym, 2.0)
    net = pips - spread
    usd = net * pv1 * lot
    azn = lambda x: f"{x * config.USD_AZN:+.2f} AZN"
    pip = pip_size(sym)
    digits = 3 if sym.endswith("JPY") else 2 if sym == "XAUUSD" else 5

    lines = [f"🧮 <b>HESABLAMA — {sym}{' ' + side if side else ''}</b>",
             f"Lot: <b>{lot:g}</b> | TP: <b>{pips:g} pips</b>"]
    if side:
        tp = price + (1 if side == "BUY" else -1) * pips * pip
        lines.append(f"Qiymət: <code>{price:.{digits}f}</code> → TP: <code>{tp:.{digits}f}</code>")
    lines += [
        "",
        f"1) Xalis pips: {pips:g} − {spread:g} (spred) = <b>{net:g} pips</b>",
        f"2) 1 pips dəyəri: 1 lot = {pv1:.2f}$ → {lot:g} lot = {pv1 * lot:.4f}$",
        f"3) TP-də gəlir: {net:g} × {pv1 * lot:.4f}$ = <b>{usd:+.2f}$ = {azn(usd)}</b>",
    ]
    long_, short_ = swap_for(sym)
    if long_ is not None:
        lines.append("")
        sides = [side] if side else ["BUY", "SELL"]
        for sd in sides:
            s = long_ if sd == "BUY" else short_
            mark = "✅ müsbət" if s > 0 else "❌ mənfi"
            lines.append(f"💱 Svop {sd}: {s:+.2f}$/lot/gecə {mark} → {lot:g} lotla gecəyə {azn(s * lot)}")
            nights = [q["days"]] if q["days"] else [7, 30]
            for n in nights:
                total_sw = s * lot * n
                lines.append(f"   {n} gün açıq qalsa: svop {azn(total_sw)} → cəmi <b>{azn(usd + total_sw)}</b>")
    # təxmini marja
    base, quote = sym[:3], sym[3:]
    if sym == "XAUUSD":
        notional = 100 * price * lot
    elif base == "USD":
        notional = 100_000 * lot
    elif quote == "USD":
        notional = 100_000 * price * lot
    else:
        rate = data.get_closed_bars(base + "USD", "D1")
        notional = 100_000 * float(rate["close"].iloc[-1]) * lot if rate is not None else None
    if notional:
        m = MARGIN_RATE.get(sym, 0.02)
        lines += ["", f"🏦 Lazımi marja (təxmini, {m * 100:g}%): {notional * m:.2f}$ = {notional * m * config.USD_AZN:.2f} AZN"]
    lines += ["", "ℹ️ Pips dəyəri cari kursla hesablanır; AZN = 1.70 × USD."]
    return "\n".join(lines)


def handle(data, state):
    """Yeni Telegram mesajlarını oxuyur və cavab verir. state['_tg_offset'] yadda saxlanılır."""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    try:
        r = requests.get(API.format(token=config.TELEGRAM_BOT_TOKEN, method="getUpdates"),
                         params={"offset": state.get("_tg_offset", 0), "timeout": 0}, timeout=20)
        updates = r.json().get("result", [])
    except Exception as e:
        log.warning("Telegram mesajları oxunmadı: %s", e)
        return
    allowed = _allowed_chats()
    for u in updates:
        state["_tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        if not text or chat not in allowed:
            continue
        if time.time() - msg.get("date", 0) > MAX_AGE_SEC:    # köhnə mesajlara gecikmiş cavab vermə
            continue
        replied = (msg.get("reply_to_message") or {}).get("text", "")
        try:
            low = text.strip().lower()
            if low in ("/help", "kömək", "komek", "help"):
                out = HELP
            elif low.strip("/ ") in ("hesabat", "report", "portfel", "nəticə", "netice"):
                import tracker
                out = tracker.report(state)
            elif is_calculation(text, replied):
                out = answer(parse(text, replied), data)
            elif is_greeting(low):
                out = welcome(state)
            else:
                out = NOT_CHAT
        except Exception:
            log.exception("Sual cavablandırılmadı: %s", text)
            out = "❌ Hesablama alınmadı. Nümunə: <code>EURAUD SELL 0.05 lot 30 pips</code>"
        ok = _reply(chat, out, msg.get("message_id"))
        log.info("Suala cavab %s: %s", "verildi" if ok else "GÖNDƏRİLMƏDİ", text[:60])
