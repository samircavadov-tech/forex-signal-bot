"""Virtual portfel: göndərilən siqnalların real nəticəsini izləyir (forward test).

- Hər siqnal lot qaydası ilə virtual açılır (hesab TRACK_BALANCE_AZN): hər LOT_STEP_AZN üçün 0.01 lot,
  balans LOT_STEP_AZN-dən azdırsa eyni anda ən çox SMALL_MAX_OPEN ticarət (artığı açılmır).
- Hər saat yoxlanılır: TP (və Trend təsdiqi üçün SL) vurulubsa bağlanır, Telegram-a nəticə gedir.
  Bir şamda həm SL, həm TP mümkündürsə — ehtiyatla SL sayılır.
- 60 gündən çox açıq qalan ticarət və 30% kapital düşməsi üçün bir dəfəlik xəbərdarlıq.
- Həftəlik hesabat (şənbə, Bakı vaxtı) və "hesabat" sorğusu.
Məlumat state.json-da saxlanılır (açar: _trades).
"""
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

import config
import swaps
from strategy import pip_size

log = logging.getLogger(__name__)
BAKU = timezone(timedelta(hours=4))


def _swap_night_usd(symbol, side, data=None):
    if symbol in config.INVESTAZ:
        from d1_signals import investaz_swap_usd
        l, s = investaz_swap_usd(symbol, data)
    else:
        sw = (swaps.load() or {}).get("symbols", {}).get(symbol)
        if not sw:
            return 0.0
        l, s = sw["long"], sw["short"]
    return l if side == "BUY" else s          # 1 lot üçün


def _spread(symbol):
    return config.INVESTAZ[symbol][0] if symbol in config.INVESTAZ else config.DEFAULT_SPREAD.get(symbol, 2.0)


def lot_for(bal):
    """Hər LOT_STEP_AZN üçün 0.01 lot, ən azı 0.01."""
    return round(max(1, int(bal // config.LOT_STEP_AZN)) * 0.01, 2)


def plan(state):
    """Lot qaydasına görə: tövsiyə olunan lot, açıq ticarət sayı, limit, yeni ticarət açmaq olarmı."""
    bal = balance(state)
    open_n = sum(1 for t in state.get("_trades", []) if t["status"] == "open")
    limit = config.SMALL_MAX_OPEN if bal < config.LOT_STEP_AZN else None
    return dict(balance=bal, lot=lot_for(bal), open_n=open_n, limit=limit,
                can_open=limit is None or open_n < limit)


def plan_line(state):
    p = plan(state)
    rule = f"(qayda: hər {config.LOT_STEP_AZN:.0f} AZN üçün 0.01 lot)"
    if not p["can_open"]:
        return (f"⛔ <b>Bu siqnalı açmayın</b> — eyni anda ən çox {p['limit']} ticarət "
                f"(balans {p['balance']:.0f} AZN, açıq: {p['open_n']}). Virtual portfelə əlavə edilmədi.")
    count = f"{p['open_n']}/{p['limit']}" if p["limit"] else str(p["open_n"])
    return (f"📏 <b>Lot: {p['lot']:g}</b> — balans {p['balance']:.0f} AZN, açıq ticarət {count} {rule}")


def add(state, strategy, symbol, side, entry, tp, sl, check_from):
    """Yeni virtual ticarət (lot qaydası ilə). check_from — giriş şamının bağlanış vaxtı (UTC, ISO).
    Limit dolubsa ticarət açılmır, False qaytarır."""
    p = plan(state)
    if not p["can_open"]:
        log.info("İzləmə: %s %s %s açılmadı — limit (%d/%d)", strategy, side, symbol, p["open_n"], p["limit"])
        return False
    trades = state.setdefault("_trades", [])
    trades.append(dict(id=len(trades) + 1, strategy=strategy, symbol=symbol, side=side,
                       entry=float(entry), tp=float(tp), sl=float(sl) if sl else None,
                       check_from=str(check_from), status="open", lot=p["lot"]))
    return True


def _lot(t):
    return t.get("lot", config.TRACK_LOT)


def _pnl_azn(t, exit_price, days, data):
    from d1_signals import pip_value_usd
    pip = pip_size(t["symbol"])
    sign = 1 if t["side"] == "BUY" else -1
    pips = sign * (exit_price - t["entry"]) / pip - _spread(t["symbol"])
    pv = pip_value_usd(t["symbol"], exit_price, data) or 0.0
    swap = _swap_night_usd(t["symbol"], t["side"], data) * _lot(t) * max(days, 0)
    return pips, (pips * pv * _lot(t) + swap) * config.USD_AZN, swap * config.USD_AZN


def _days_open(t, until=None):
    until = until or datetime.now(timezone.utc).replace(tzinfo=None)
    return (until - pd.Timestamp(t["check_from"]).to_pydatetime()).days


def update(data, state, send):
    """Açıq ticarətləri yoxlayır; bağlananlar və xəbərdarlıqlar üçün mesaj göndərir."""
    for t in state.get("_trades", []):
        if t["status"] != "open":
            continue
        bars = data.get_closed_bars(t["symbol"], "H1")
        if bars is None:
            continue
        since = bars[bars.index >= pd.Timestamp(t["check_from"])]
        sign = 1 if t["side"] == "BUY" else -1
        for ts, b in since.iterrows():
            hit_sl = t["sl"] is not None and (b.low <= t["sl"] if sign == 1 else b.high >= t["sl"])
            hit_tp = b.high >= t["tp"] if sign == 1 else b.low <= t["tp"]
            if hit_sl or hit_tp:
                exit_price = t["sl"] if hit_sl else t["tp"]
                days = _days_open(t, ts.to_pydatetime() + timedelta(hours=1))
                pips, azn, swap_azn = _pnl_azn(t, exit_price, days, data)
                t.update(status="sl" if hit_sl else "tp", exit=exit_price,
                         closed=str(ts + pd.Timedelta(hours=1)), pips=round(pips, 1),
                         azn=round(azn, 2), swap_azn=round(swap_azn, 2), days=days)
                icon = "❌ <b>STOP-LOSS</b>" if hit_sl else "✅ <b>TAKE-PROFIT</b>"
                send(f"{icon} — {t['strategy']}\n"
                     f"{t['side']} {t['symbol']} (#{t['id']})\n"
                     f"Giriş: <code>{t['entry']}</code> → Çıxış: <code>{exit_price}</code>\n"
                     f"Müddət: {days} gün | Pips (spred çıxılıb): {pips:+.1f}\n"
                     f"Nəticə ({_lot(t):g} lot): <b>{azn:+.2f} AZN</b> (svop {swap_azn:+.2f} AZN daxil)\n\n"
                     f"💼 Virtual balans: <b>{balance(state):.2f} AZN</b>")
                log.info("İzləmə: #%s %s %s %s %+.2f AZN", t["id"], t["symbol"], t["side"], t["status"], azn)
                break
        if t["status"] == "open":
            last = float(bars["close"].iloc[-1])
            days = _days_open(t)
            t["float_pips"], t["float_azn"], _ = [round(x, 2) for x in _pnl_azn(t, last, days, data)]
            t["days"] = days
            if days > config.TRACK_MAX_DAYS and not t.get("warned_days"):
                t["warned_days"] = True
                send(f"⏰ <b>XƏBƏRDARLIQ: ticarət {days} gündür açıqdır</b>\n"
                     f"{t['strategy']}: {t['side']} {t['symbol']} (#{t['id']}), giriş {t['entry']}\n"
                     f"Üzən nəticə: {t['float_azn']:+.2f} AZN\n"
                     f"Qayda: {config.TRACK_MAX_DAYS} gündən çox açıq qalan ticarəti bağlamağı düşünün.")
    # kapital düşməsi
    eq = equity(state)
    limit = config.TRACK_BALANCE_AZN * (1 - config.TRACK_DD_ALERT)
    if eq < limit and not state.get("_dd_warned"):
        state["_dd_warned"] = True
        send(f"🚨 <b>XƏBƏRDARLIQ: kapital {config.TRACK_DD_ALERT * 100:.0f}% düşüb</b>\n"
             f"Virtual kapital: {eq:.2f} AZN (başlanğıc {config.TRACK_BALANCE_AZN:.0f} AZN)\n"
             f"Qayda: bütün açıq ticarətləri bağlamağı düşünün.")
    elif eq >= limit:
        state["_dd_warned"] = False


def balance(state):
    return config.TRACK_BALANCE_AZN + sum(t.get("azn", 0) for t in state.get("_trades", []) if t["status"] != "open")


def equity(state):
    return balance(state) + sum(t.get("float_azn", 0) for t in state.get("_trades", []) if t["status"] == "open")


def report(state, title="📊 <b>PORTFEL HESABATI</b>"):
    trades = state.get("_trades", [])
    now = datetime.now(BAKU)
    p = plan(state)
    limit = f", eyni anda ən çox {p['limit']} ticarət" if p["limit"] else ""
    lines = [title, f"{now:%d.%m.%Y %H:%M} (Bakı vaxtı)",
             f"Lot qaydası: hər {config.LOT_STEP_AZN:.0f} AZN üçün 0.01 → indi <b>{p['lot']:g} lot</b>{limit}", ""]
    if not trades:
        return "\n".join(lines + ["Hələ izlənən siqnal yoxdur. Yeni siqnallar avtomatik əlavə olunacaq."])
    for strat in sorted({t["strategy"] for t in trades}):
        ts = [t for t in trades if t["strategy"] == strat]
        tp = [t for t in ts if t["status"] == "tp"]
        sl = [t for t in ts if t["status"] == "sl"]
        op = [t for t in ts if t["status"] == "open"]
        realized = sum(t["azn"] for t in tp + sl)
        floating = sum(t.get("float_azn", 0) for t in op)
        lines += [f"<b>{strat}</b>",
                  f"Siqnal: {len(ts)} | ✅ TP: {len(tp)} | ❌ SL: {len(sl)} | ⏳ açıq: {len(op)}",
                  f"Bağlananların nəticəsi: <b>{realized:+.2f} AZN</b> | açıqların üzən nəticəsi: {floating:+.2f} AZN"]
        for t in op:
            lines.append(f"   ⏳ #{t['id']} {t['side']} {t['symbol']} {_lot(t):g} lot — "
                         f"{t.get('days', 0)} gün, {t.get('float_azn', 0):+.2f} AZN")
        lines.append("")
    lines += [f"💼 Balans (bağlananlar): <b>{balance(state):.2f} AZN</b>",
              f"📈 Kapital (açıqlar daxil): <b>{equity(state):.2f} AZN</b> (başlanğıc {config.TRACK_BALANCE_AZN:.0f} AZN)"]
    return "\n".join(lines)


def weekly(state, send):
    """Şənbə günü DAILY_SUMMARY_HOUR+3-dən sonra həftədə bir dəfə hesabat."""
    now = datetime.now(BAKU)
    week = f"{now.isocalendar().year}-W{now.isocalendar().week}"
    if now.weekday() != 5 or now.hour < 12 or state.get("_week_report") == week:
        return
    if send(report(state, "📊 <b>HƏFTƏLİK PORTFEL HESABATI</b>")):
        state["_week_report"] = week
        log.info("Həftəlik hesabat göndərildi (%s)", week)
