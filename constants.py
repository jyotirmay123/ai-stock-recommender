"""
constants.py — Application-wide constants and pure currency helpers.

No external dependencies beyond the standard library.
Safe to import from both the Streamlit app and the standalone daily_picks.py script.
"""
from __future__ import annotations

# ─────────────────────────────────────────────
# CURRENCY SUFFIX SETS
# ─────────────────────────────────────────────
EUR_SUFFIXES: frozenset[str] = frozenset({
    ".AS", ".DE", ".PA", ".SW", ".BR", ".MI", ".MC",
    ".LS", ".VI", ".HE", ".CO", ".ST", ".OL",
})
INR_SUFFIXES: frozenset[str] = frozenset({".NS", ".BO"})


def is_eur_symbol(symbol: str) -> bool:
    sym = symbol.upper()
    if sym.endswith("-EUR"):
        return True
    return any(sym.endswith(s) for s in EUR_SUFFIXES)


def is_inr_symbol(symbol: str) -> bool:
    return any(symbol.upper().endswith(s) for s in INR_SUFFIXES)


def get_mult(symbol: str, eur_rate: float, inr_eur_rate: float) -> float:
    """Return multiplier to convert the asset's native price to EUR."""
    if is_eur_symbol(symbol):
        return 1.0
    if is_inr_symbol(symbol):
        return inr_eur_rate
    return eur_rate  # USD → EUR


# ─────────────────────────────────────────────
# STOCK UNIVERSE
# ─────────────────────────────────────────────
STOCKS: dict[str, dict[str, str]] = {
    "🇪🇺 European": {
        "ASML.AS":  "ASML Holding",
        "SAP.DE":   "SAP SE",
        "SIE.DE":   "Siemens",
        "MC.PA":    "LVMH",
        "TTE.PA":   "TotalEnergies",
        "AIR.PA":   "Airbus",
        "SAN.PA":   "Sanofi",
        "DTE.DE":   "Deutsche Telekom",
        "ALV.DE":   "Allianz",
        "BAS.DE":   "BASF",
    },
    "🇺🇸 US S&P 500": {
        "AAPL":  "Apple",
        "MSFT":  "Microsoft",
        "NVDA":  "NVIDIA",
        "GOOGL": "Alphabet",
        "AMZN":  "Amazon",
        "META":  "Meta",
        "TSLA":  "Tesla",
        "JPM":   "JPMorgan Chase",
        "V":     "Visa",
        "JNJ":   "Johnson & Johnson",
    },
    "🇮🇳 Indian (NSE)": {
        "RELIANCE.NS":   "Reliance Industries",
        "TCS.NS":        "Tata Consultancy",
        "INFY.NS":       "Infosys",
        "HDFCBANK.NS":   "HDFC Bank",
        "ICICIBANK.NS":  "ICICI Bank",
        "WIPRO.NS":      "Wipro",
        "BAJFINANCE.NS": "Bajaj Finance",
        "SBIN.NS":       "State Bank of India",
        "HINDUNILVR.NS": "Hindustan Unilever",
        "ITC.NS":        "ITC",
    },
    "₿ Crypto": {
        "BTC-EUR": "Bitcoin",
    },
}

# ─────────────────────────────────────────────
# RISK PROFILES
# ─────────────────────────────────────────────
RISK_PARAMS: dict[str, dict[str, int]] = {
    "Conservative": {"rsi_buy": 35, "rsi_sell": 65, "min_score": 4},
    "Balanced":     {"rsi_buy": 40, "rsi_sell": 60, "min_score": 3},
    "Aggressive":   {"rsi_buy": 45, "rsi_sell": 55, "min_score": 2},
}

# ─────────────────────────────────────────────
# NEWS SENTIMENT KEYWORDS
# ─────────────────────────────────────────────
BULLISH_WORDS: frozenset[str] = frozenset({
    "upgrade", "buy", "strong", "growth", "profit", "beat", "surge",
    "rally", "gain", "positive", "outperform", "record", "rise", "expand",
    "bullish", "overweight",
})
BEARISH_WORDS: frozenset[str] = frozenset({
    "downgrade", "sell", "weak", "loss", "miss", "fall", "drop",
    "decline", "negative", "underperform", "cut", "warning", "concern",
    "bearish", "underweight",
})

# ─────────────────────────────────────────────
# UI ICON MAP  (quote type → emoji)
# ─────────────────────────────────────────────
QTYPE_ICON: dict[str, str] = {
    "EQUITY": "📈", "ETF": "🗂️", "MUTUALFUND": "🏦",
    "INDEX": "📊", "CRYPTOCURRENCY": "₿", "CURRENCY": "💱",
    "FUTURE": "⏳", "OPTION": "⚙️",
}
