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

import config
import telegram_notify as tg
from indicators import add_indicators
from strategy import analyze

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


def check_symbol(data, symbol, last_bar, notify_first=True):
    """Giriş qrafikində yeni bağlanmış şam varsa analiz edir, siqnal varsa göndərir."""
    entry = data.get_closed_bars(symbol, config.ENTRY_TF)
    if entry is None:
        return
    bar = str(entry.index[-1])
    if last_bar.get(symbol) == bar:
        return
    first_pass = symbol not in last_bar
    last_bar[symbol] = bar
    frames = load_frames(data, symbol)
    if not frames:
        return
    sig, _ = analyze(symbol, frames, data.digits(symbol))
    if sig and (notify_first or not first_pass):
        log.info("SİQNAL: %s %s @ %s", sig.side, symbol, sig.price)
        tg.send(tg.format_signal(sig))


def run(data, symbols):
    last_bar = {}      # symbol -> sonuncu yoxlanılmış giriş şamının vaxtı
    tg.send("🤖 Forex siqnal botu işə düşdü.\nİzlənir: " + ", ".join(symbols))
    while True:
        for symbol in symbols:
            try:
                check_symbol(data, symbol, last_bar, notify_first=False)
            except Exception:
                log.exception("%s analiz edilərkən xəta", symbol)
        time.sleep(config.CHECK_INTERVAL_SEC)


def run_cloud(data, symbols):
    """Bir keçid: state.json-da yoxlanılmış şamları yadda saxlayır ki, eyni siqnal iki dəfə gəlməsin."""
    last_bar = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            last_bar = json.load(f)
    errors = 0
    for symbol in symbols:
        try:
            check_symbol(data, symbol, last_bar)
        except Exception:
            errors += 1
            log.exception("%s analiz edilərkən xəta", symbol)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(last_bar, f, indent=1)
    log.info("Yoxlama bitdi: %d cüt, %d xəta", len(symbols), errors)
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
    try:
        symbols = [s for s in config.SYMBOLS if data.prepare_symbol(s)]
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
