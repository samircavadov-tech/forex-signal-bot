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

# --- D1 strategiyası: SMA 8 × SMA 21/30, TP 50 pips (d1_signals.py) ---
D1_SYMBOLS = ["EURUSD", "GBPUSD", "AUDJPY", "EURGBP", "EURAUD",            # InvestAZ cütləri
              "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"]
D1_TP_PIPS = 50
USD_AZN = 1.70

# Virtual portfel (tracker.py): siqnalların real nəticəsinin izlənməsi
TRACK_BALANCE_AZN = 500.0
TRACK_LOT = 0.01
TRACK_MAX_DAYS = 60          # bundan çox açıq qalan ticarət üçün xəbərdarlıq
TRACK_DD_ALERT = 0.30        # kapital bu qədər düşəndə xəbərdarlıq

# InvestAZ şərtləri (istifadəçinin cədvəli): spred pips, svop alış $, svop satış $ (1 lot, 1 gecə)
INVESTAZ = {
    "EURUSD": (0.6, -13.50, 2.91),
    "GBPUSD": (1.6, -7.48, 1.83),
    "AUDJPY": (1.8, 2.11, -9.42),
    "EURGBP": (1.8, -4.88, 0.88),
    "EURAUD": (2.3, -16.03, 2.93),
}
# InvestAZ-da olmayan cütlər üçün təxmini spred, pips
DEFAULT_SPREAD = {"USDJPY": 1.5, "USDCHF": 2.0, "AUDUSD": 1.5, "USDCAD": 2.0, "NZDUSD": 2.5, "XAUUSD": 3.0}

# --- Fundamental filtr: iqtisadi təqvim ---
NEWS_IMPACT = {"High"}          # hansı təsir səviyyəsi nəzərə alınsın ("High", "Medium")
NEWS_WARN_HOURS = 4             # siqnal mesajında neçə saat irəlidəki xəbərlər göstərilsin
NEWS_BLOCK_MINUTES = 0          # 0 = yalnız xəbərdarlıq; məs. 60 = xəbərdən 60 dəq əvvəl/sonra siqnal verilmir
DAILY_SUMMARY_HOUR = 9          # hər iş günü bu saatda (Bakı vaxtı) günün xəbərləri göndərilir

# Neçə saniyədən bir yoxlanılsın
CHECK_INTERVAL_SEC = 30
