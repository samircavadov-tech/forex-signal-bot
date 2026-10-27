"""Forex siqnal botu.

İstifadə:
  python main.py                 # davamlı izləmə (MT5), siqnal gələndə Telegram-a göndərir
  python main.py --once          # bütün cütlərin cari analizini bir dəfə ekrana çıxarır
  python main.py --cloud         # bir dəfə yoxla, yeni siqnal varsa göndər (GitHub üçün)
  python main.py --source yahoo  # MT5 əvəzinə Yahoo Finance məlumatı
  python main.py --test          # Telegram-a test mesajı göndərir
  python main.py --chatid        # Telegram chat ID-nizi tapır
"""
import argparse
import importlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import config
import d1_signals
import news
import questions
import swaps
import telegram_notify as tg
from indicators import add_indicators
from strategy import analyze, frames_as_of

sys.stdout.reconfigure(encoding="utf-8")  # Windows konsolunda emoji/Azərbaycan hərfləri üçün

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("signals.log", encoding="utf-8")],
)
log = logging.getLogger("bot")

STATE_FILE = "state.json"


def load_frames(data, symbol):
    frames = {}
    for tf in config.TIMEFRAMES:
        df = data.get_closed_bars(symbol, tf)
        if df is not None:
            frames[tf] = add_indicators(df)
    return frames if config.ENTRY_TF in frames else None


def print_overview(data, symbols):
    for symbol in symbols:
        frames = load_frames(data, symbol)
        if not frames:
            continue
        sig, biases = analyze(symbol, frames, data.digits(symbol))
        summary = "  ".join(f"{b.tf}:{b.direction}({b.score:+d})" for b in biases)
        print(f"{symbol:8} {summary}")
        if sig:
            print("   >>> " + tg.format_signal(sig).replace("\n", "\n       "))


MAX_CATCHUP = 3   # GitHub bir neçə saatı buraxsa, bu qədər köhnə şam da yoxlanılır


def all_symbols(symbols):
    """Saatlıq strategiyanın cütləri + D1 strategiyasının əlavə cütləri."""
    return list(symbols) + [s for s in config.D1_SYMBOLS if s not in symbols]


def check_symbol(data, symbol, last_bar, notify_first=True):
    """Giriş qrafikində yeni bağlanmış şam(lar) varsa analiz edir, siqnal varsa göndərir."""
    entry = data.get_closed_bars(symbol, config.ENTRY_TF)
    if entry is None:
        return
    prev = last_bar.get(symbol)
    if prev is None:
        new_bars = list(entry.index[-1:])
    else:
        new_bars = [t for t in entry.index[-MAX_CATCHUP:] if str(t) > prev]
    if not new_bars:
        return
    frames = load_frames(data, symbol)
    if not frames:
        return
    last_bar[symbol] = str(entry.index[-1])
    if prev is None and not notify_first:
        return
    for bar in new_bars:
        sig, _ = analyze(symbol, frames_as_of(frames, bar), data.digits(symbol))
        if sig:
            blocking = news.blocks_signal(symbol, datetime.now(timezone.utc))
            if blocking:
                log.info("Siqnal %s %s xəbərə görə buraxıldı: %s", sig.side, symbol,
                         ", ".join(e["country"] + " " + e["title"] for e in blocking))
                continue
            sig.note = getattr(data, "PRICE_NOTES", {}).get(symbol, "")
            log.info("SİQNAL: %s %s @ %s (şam %s)", sig.side, symbol, sig.price, bar)
            tg.send(tg.format_signal(sig))
            questions.record_signal(last_bar, f"Trend təsdiqi (H1): {sig.side} {symbol}")


def run(data, symbols):
    last_bar = {}      # symbol -> sonuncu yoxlanılmış giriş şamının vaxtı
    tg.send("🤖 Forex siqnal botu işə düşdü.\nİzlənir: " + ", ".join(symbols))
    while True:
        for symbol in all_symbols(symbols):
            try:
                if symbol in symbols:
                    check_symbol(data, symbol, last_bar, notify_first=False)
                d1_signals.check(data, symbol, last_bar, notify=f"_d1_{symbol}" in last_bar)
            except Exception:
                log.exception("%s analiz edilərkən xəta", symbol)
        time.sleep(config.CHECK_INTERVAL_SEC)


def send_daily_summary(state):
    """İş günləri DAILY_SUMMARY_HOUR-dan (Bakı vaxtı) sonra gündə bir dəfə günün xəbərlərini göndərir."""
    now = datetime.now(timezone.utc)
    baku = now.astimezone(news.BAKU)
    today = baku.date().isoformat()
    if baku.weekday() >= 5 or baku.hour < config.DAILY_SUMMARY_HOUR or state.get("_summary_day") == today:
        return
    text = news.daily_summary(now)
    if text and tg.send(text):
        state["_summary_day"] = today
        log.info("Gündəlik xəbər xülasəsi göndərildi")


def send_monthly_report(state):
    """Hər ayın ilk iş günü DAILY_SUMMARY_HOUR-dan sonra bir dəfə aylıq hesabat göndərir."""
    import monthly
    baku = datetime.now(timezone.utc).astimezone(news.BAKU)
    month = f"{baku:%Y-%m}"
    if baku.weekday() >= 5 or baku.hour < config.DAILY_SUMMARY_HOUR or state.get("_month") == month:
        return
    try:
        text = monthly.report(state, baku)
    except Exception:
        log.exception("Aylıq hesabat hazırlanmadı")
        return
    if tg.send(text):
        state["_month"] = month
        log.info("Aylıq hesabat göndərildi (%s)", month)


def run_cloud(data, symbols):
    """Bir keçid: state.json-da yoxlanılmış şamları yadda saxlayır ki, eyni siqnal iki dəfə gəlməsin."""
    last_bar = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            last_bar = json.load(f)
    questions.handle(data, last_bar)                  # Telegram sualları — hər işləmədə

    # Bot ~5 dəqiqədən bir işə düşür; siqnal analizi isə saatda bir dəfə (şam bağlanandan 5 dəq sonra)
    now = datetime.now(timezone.utc)
    hour_key = f"{now:%Y-%m-%d %H}"
    errors = 0
    if now.minute >= 5 and last_bar.get("_analyzed_hour") != hour_key:
        for symbol in all_symbols(symbols):
            try:
                if symbol in symbols:
                    check_symbol(data, symbol, last_bar)
                d1_signals.check(data, symbol, last_bar)
            except Exception:
                errors += 1
                log.exception("%s analiz edilərkən xəta", symbol)
        if errors < len(symbols):
            last_bar["_analyzed_hour"] = hour_key
        send_daily_summary(last_bar)
        send_monthly_report(last_bar)
        log.info("Yoxlama bitdi: %d cüt, %d xəta", len(all_symbols(symbols)), errors)
    else:
        log.info("Bu saat artıq analiz edilib — yalnız suallar yoxlanıldı")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(last_bar, f, indent=1)
    if errors == len(symbols):
        sys.exit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--cloud", action="store_true")
    p.add_argument("--source", choices=["mt5", "yahoo"], default=None)
    p.add_argument("--test", action="store_true")
    p.add_argument("--chatid", action="store_true")
    args = p.parse_args()

    if args.chatid:
        ids = tg.find_chat_ids()
        print(ids or "Heç bir mesaj tapılmadı — əvvəlcə bota Telegram-da istənilən mesaj yazın.")
        return
    if args.test:
        print("Göndərildi ✅" if tg.send("✅ Test mesajı: bot işləyir.") else "Göndərilmədi ❌ (loga baxın)")
        return

    source = args.source or ("yahoo" if args.cloud else "mt5")
    data = importlib.import_module("mt5_data" if source == "mt5" else "yahoo_data")
    data.connect()
    if source == "mt5":
        try:
            swaps.update_from_mt5()
        except Exception:
            log.exception("Svoplar yenilənmədi")
    try:
        symbols = [s for s in config.SYMBOLS if data.prepare_symbol(s)]
        for s in config.D1_SYMBOLS:
            data.prepare_symbol(s)
        if args.once:
            print_overview(data, symbols)
        elif args.cloud:
            run_cloud(data, symbols)
        else:
            run(data, symbols)
    except KeyboardInterrupt:
        log.info("Dayandırıldı.")
    finally:
        data.shutdown()


if __name__ == "__main__":
    main()
