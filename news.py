"""Fundamental filtr: iqtisadi təqvim (Forex Factory həftəlik təqvimi, pulsuz).

- Siqnal mesajına yaxın saatlardakı vacib xəbərləri əlavə edir.
- NEWS_BLOCK_MINUTES > 0 olarsa, vacib xəbərə yaxın siqnalları dayandırır.
- Hər səhər günün vacib xəbərlərinin siyahısını göndərir.
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

import config

log = logging.getLogger(__name__)

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
BAKU = timezone(timedelta(hours=4))
_events = None


def events() -> list:
    """Bu həftənin xəbərləri (bir proses ərzində bir dəfə yüklənir). Xəta olsa — boş siyahı."""
    global _events
    if _events is None:
        try:
            r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            r.raise_for_status()
            _events = [
                {**e, "time": datetime.fromisoformat(e["date"]).astimezone(timezone.utc)}
                for e in r.json()
            ]
        except Exception as e:
            log.warning("İqtisadi təqvim yüklənmədi: %s", e)
            _events = []
    return _events


def currencies(symbol: str) -> set:
    if symbol.startswith("XAU"):
        return {"USD"}          # qızıla ən çox USD xəbərləri təsir edir
    return {symbol[:3], symbol[3:6]}


def important(symbol: str, start: datetime, end: datetime) -> list:
    cur = currencies(symbol)
    return sorted(
        (e for e in events()
         if e["impact"] in config.NEWS_IMPACT and e["country"] in cur and start <= e["time"] <= end),
        key=lambda e: e["time"],
    )


def blocks_signal(symbol: str, now: datetime) -> list:
    """NEWS_BLOCK_MINUTES aralığında vacib xəbər varsa, onları qaytarır."""
    m = config.NEWS_BLOCK_MINUTES
    if m <= 0:
        return []
    return important(symbol, now - timedelta(minutes=m), now + timedelta(minutes=m))


def _fmt_delta(delta: timedelta) -> str:
    mins = int(abs(delta.total_seconds()) // 60)
    h, m = divmod(mins, 60)
    text = f"{h} saat {m} dəq" if h else f"{m} dəq"
    return f"{text} sonra" if delta.total_seconds() >= 0 else f"{text} əvvəl"


def _fmt_event(e, now=None) -> str:
    t = e["time"].astimezone(BAKU)
    extra = []
    if e.get("forecast"):
        extra.append(f"proqnoz {e['forecast']}")
    if e.get("previous"):
        extra.append(f"əvvəlki {e['previous']}")
    when = f"{t:%H:%M}" + (f" ({_fmt_delta(e['time'] - now)})" if now else "")
    return f"• {e['country']} {e['title']} — {when}" + (f"  [{', '.join(extra)}]" if extra else "")


def signal_lines(symbol: str, now: datetime) -> list:
    """Siqnal mesajı üçün: son 1 saatda olmuş və yaxın N saatda olacaq vacib xəbərlər."""
    if not events():
        return ["📰 İqtisadi təqvim yüklənmədi — xəbərləri özünüz yoxlayın."]
    found = important(symbol, now - timedelta(hours=1), now + timedelta(hours=config.NEWS_WARN_HOURS))
    if not found:
        return [f"📰 Yaxın {config.NEWS_WARN_HOURS} saatda {'/'.join(sorted(currencies(symbol)))} üzrə vacib xəbər yoxdur ✅"]
    return ["⚠️ <b>Diqqət, vacib xəbər:</b>"] + [_fmt_event(e, now) for e in found] + \
           ["Xəbər zamanı qiymət kəskin tərpənə bilər, SL vurula bilər."]


def daily_summary(now: datetime) -> str | None:
    """Növbəti 24 saatın vacib xəbərləri, izlənən valyutalar üzrə (Bakı vaxtı)."""
    if not events():
        return None
    watched = set().union(*(currencies(s) for s in config.SYMBOLS))
    upcoming = sorted(
        (e for e in events() if e["impact"] in config.NEWS_IMPACT and e["country"] in watched
         and now <= e["time"] <= now + timedelta(hours=24)),
        key=lambda e: e["time"],
    )
    head = ("📰 <b>XƏBƏR XÜLASƏSİ</b> (siqnal deyil — məlumat)\n"
            "Növbəti 24 saatın vacib xəbərləri (Bakı vaxtı):")
    if not upcoming:
        return head + "\nYüksək təsirli xəbər yoxdur ✅"
    lines, day = [head], None
    for e in upcoming:
        d = e["time"].astimezone(BAKU).date()
        if d != day:
            day = d
            lines.append(f"\n<b>{d:%d.%m.%Y}</b>")
        lines.append(_fmt_event(e))
    return "\n".join(lines)
