"""Proqramın bütün tənzimləmələri burdadır."""
import os

# --- Telegram ---
# Token və chat ID koda yazılmır (GitHub-a düşməsin):
#  - kompüterdə: secrets_local.py faylında saxlanılır (git-ə əlavə edilmir)
#  - GitHub-da: repo Settings -> Secrets bölməsindən mühit dəyişəni kimi gəlir
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
try:
    from secrets_local import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  # noqa: F811
except ImportError:
    pass

# --- MetaTrader 5 ---
# Boş qalsa, açıq olan MT5 terminalına qoşulur.
MT5_PATH = ""        # məs: r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_LOGIN = 0        # 0 = terminalda artıq daxil olunmuş hesab
MT5_PASSWORD = ""
MT5_SERVER = ""

# Bəzi brokerlər simvola şəkilçi əlavə edir (məs. "EURUSDm", "EURUSD.r").
SYMBOL_SUFFIX = ""

# --- İzlənən cütlər ---
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"]

# --- Zaman çərçivələri ---
# ENTRY_TF: siqnalın (giriş nöqtəsinin) axtarıldığı qrafik.
# FILTER_TFS: siqnalla eyni istiqamətdə OLMALI olan böyük qrafiklər.
# Qalanları (W1, MN1) yalnız siqnal gücünə təsir edir.
TIMEFRAMES = ["H1", "H4", "D1", "W1", "MN1"]
ENTRY_TF = "H1"
FILTER_TFS = ["H4", "D1"]

# --- İndikator parametrləri ---
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ATR_PERIOD = 14

# BUY üçün RSI bu aralıqda olmalıdır (çox alınmış bazarda alış etməmək üçün)
RSI_BUY_RANGE = (45, 70)
RSI_SELL_RANGE = (30, 55)

# Stop-loss və take-profit = ATR(H1) * əmsal
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0

# Minimum siqnal gücü (5 timeframe-dən neçəsi siqnalla razıdır)
MIN_STRENGTH = 3

# Neçə saniyədən bir yoxlanılsın
CHECK_INTERVAL_SEC = 30
