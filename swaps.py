"""Svop məlumatı: MT5-dən oxunub swaps.json-a yazılır, siqnal mesajı oradan götürür.
Buludda (GitHub) MT5 yoxdur, ona görə swaps.json repoda saxlanılır.

Yeniləmək:  python swaps.py          # MT5-dən oxu, swaps.json-a yaz
            python swaps.py --push   # + GitHub-a yüklə (bulud versiyası da yenilənsin)
"""
import json
import os
import subprocess
import sys
from datetime import date

import config

SWAPS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swaps.json")
DAYS = ["Bazar", "Bazar ertəsi", "Çərşənbə axşamı", "Çərşənbə", "Cümə axşamı", "Cümə", "Şənbə"]


def load():
    try:
        with open(SWAPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def update_from_mt5():
    """MT5-ə qoşulmuş halda çağırılır. 1 lot üçün gecəlik svopu hesab valyutasında yazır."""
    import MetaTrader5 as mt5
    import mt5_data

    account = mt5.account_info()
    data = {"broker": account.server if account else "?", "currency": account.currency if account else "USD",
            "updated": date.today().isoformat(), "symbols": {}}
    for symbol in config.SYMBOLS:
        info = mt5.symbol_info(mt5_data.broker_symbol(symbol))
        if not info:
            continue
        entry = {"triple_day": info.swap_rollover3days}
        if info.swap_mode == mt5.SYMBOL_SWAP_MODE_POINTS and info.trade_tick_size:
            per_point = info.trade_tick_value * info.point / info.trade_tick_size
            entry["long"] = round(info.swap_long * per_point, 2)
            entry["short"] = round(info.swap_short * per_point, 2)
            entry["unit"] = data["currency"]
        else:   # digər rejimlər (faiz və s.) — xam dəyər
            entry["long"], entry["short"], entry["unit"] = info.swap_long, info.swap_short, f"(rejim {info.swap_mode})"
        data["symbols"][symbol] = entry
    with open(SWAPS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    return data


def format_lines(symbol: str, side: str) -> list:
    data = load()
    s = data and data["symbols"].get(symbol)
    if not s:
        return []

    def line(name, value):
        mark = "✅ müsbət" if value > 0 else "❌ mənfi" if value < 0 else "➖ sıfır"
        arrow = "  ◀ siqnal" if name == side else ""
        return f"{name}: <code>{value:+.2f} {s['unit']}</code> {mark}{arrow}"

    return [
        f"<b>Svop</b> (1 lot, 1 gecə, {data['broker']}, {data['updated']}):",
        line("BUY", s["long"]),
        line("SELL", s["short"]),
        f"{DAYS[s['triple_day']]} günü svop 3 qat tutulur.",
    ]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import mt5_data
    mt5_data.connect()
    try:
        result = update_from_mt5()
    finally:
        mt5_data.shutdown()
    for sym, v in result["symbols"].items():
        print(f"{sym:8} BUY {v['long']:+8.2f}   SELL {v['short']:+8.2f}  {v['unit']}")
    if "--push" in sys.argv:
        repo = os.path.dirname(SWAPS_FILE)
        subprocess.run(["git", "add", "swaps.json"], cwd=repo, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode:
            subprocess.run(["git", "commit", "-m", f"Svoplar yeniləndi {result['updated']}"], cwd=repo, check=True)
            subprocess.run(["git", "push"], cwd=repo, check=True)
            print("GitHub-a yükləndi ✅")
        else:
            print("Dəyişiklik yoxdur.")
