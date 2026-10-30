"""GitHub → Cloudflare Worker sinxronizasiyası.

- /setup: Telegram tokeni və chat ID-ləri Worker-ə ötürülür (ilk dəfə və ya dəyişəndə),
  Worker özü Telegram webhook-unu qurur. Bundan sonra suallara Worker dərhal cavab verir.
- /status: qiymətlər, svoplar, son siqnallar və portfel hesabatı (saatda bir dəfə).
"""
import hashlib
import logging
import time

import requests

import config
import swaps
import tracker

log = logging.getLogger(__name__)


def enabled():
    return bool(config.WORKER_URL and config.STATUS_KEY)


def _post(path, payload):
    r = requests.post(config.WORKER_URL.rstrip("/") + path, json=payload,
                      headers={"X-Status-Key": config.STATUS_KEY}, timeout=30)
    return r


def ensure_setup(state):
    """Token və ya chat ID dəyişibsə Worker-i yenidən qurur (webhook daxil)."""
    fingerprint = hashlib.sha256(f"{config.TELEGRAM_BOT_TOKEN}|{config.TELEGRAM_CHAT_ID}|{config.WORKER_URL}"
                                 .encode()).hexdigest()[:16]
    if state.get("_worker_setup") == fingerprint:
        return False
    chat_ids = [c.strip() for c in str(config.TELEGRAM_CHAT_ID).split(",") if c.strip()]
    r = _post("/setup", {"bot_token": config.TELEGRAM_BOT_TOKEN, "chat_ids": chat_ids})
    result = r.json() if r.ok else {"ok": False, "description": r.text[:200]}
    if result.get("ok"):
        state["_worker_setup"] = fingerprint
        log.info("Worker quruldu, Telegram webhook aktivdir")
        return True
    log.error("Worker qurulmadı: %s", result.get("description"))
    return False


def push_status(data, state, symbols):
    prices = {}
    for s in symbols:
        try:
            df = data.get_closed_bars(s, "D1")
            if df is not None:
                prices[s] = round(float(df["close"].iloc[-1]), 6)
        except Exception:
            pass
    sw = {s: {"long": v["long"], "short": v["short"]}
          for s, v in ((swaps.load() or {}).get("symbols", {})).items()}
    from d1_signals import investaz_swap_usd
    investaz = {}                     # svop punktdan $-a çevrilmiş halda (1 lot, 1 gecə)
    for s, (spread, _, _) in config.INVESTAZ.items():
        try:
            lng, sht = investaz_swap_usd(s, data)
        except Exception:
            _, lng, sht = config.INVESTAZ[s]
        investaz[s] = (spread, round(lng, 2), round(sht, 2))
    payload = {
        "updated": int(time.time()),
        "config": {
            "symbols": symbols,
            "investaz": investaz,
            "default_spread": config.DEFAULT_SPREAD,
            "tp_default": config.D1_TP_PIPS,
            "usd_azn": config.USD_AZN,
            "margin_rate": {"AUDJPY": 0.05, "EURGBP": 0.05, "EURAUD": 0.05},
        },
        "prices": prices,
        "swaps": sw,
        "signals": state.get("_signals", []),
        "report": tracker.report(state),
    }
    r = _post("/status", payload)
    if r.ok:
        log.info("Worker məlumatı yeniləndi (%d qiymət)", len(prices))
    else:
        log.error("Worker məlumatı yenilənmədi: %s %s", r.status_code, r.text[:200])
