"""
AI Stock Investment Recommender
================================
Analyses EU, US (S&P 500), Bitcoin, and ANY global ticker using
technical indicators and recommends Buy / Hold / Sell in EUR.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import requests
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AI Stock Investment Recommender",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# STOCK UNIVERSE
# ─────────────────────────────────────────────
STOCKS = {
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
    "₿ Crypto": {
        "BTC-EUR": "Bitcoin",
    },
}

RISK_PARAMS = {
    "Conservative": {"rsi_buy": 35, "rsi_sell": 65, "min_score": 4},
    "Balanced":     {"rsi_buy": 40, "rsi_sell": 60, "min_score": 3},
    "Aggressive":   {"rsi_buy": 45, "rsi_sell": 55, "min_score": 2},
}

# ─────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)   # cache 5 minutes
def get_eur_rate():
    """Return USD → EUR conversion rate."""
    try:
        ticker = yf.Ticker("EURUSD=X")
        rate = ticker.fast_info["last_price"]
        return 1 / rate  # USD per EUR → EUR per USD
    except Exception:
        return 0.92  # fallback

@st.cache_data(ttl=300)
def fetch_stock_data(symbol: str, period: str = "6mo"):
    try:
        df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
        if df is None or (hasattr(df, "empty") and df.empty):
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except Exception as e:
        return None

def check_internet():
    """Quick check if Yahoo Finance is reachable."""
    try:
        import urllib.request
        urllib.request.urlopen("https://finance.yahoo.com", timeout=5)
        return True
    except Exception:
        return False

# ─────────────────────────────────────────────
# SMART TICKER SEARCH
# ─────────────────────────────────────────────
@st.cache_data(ttl=120)
def yahoo_search(query: str, max_results: int = 6) -> list:
    """Call Yahoo Finance search API to find matching tickers for any query."""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {
            "q": query,
            "quotesCount": max_results,
            "newsCount": 0,
            "enableFuzzyQuery": True,
            "quotesQueryId": "tss_match_phrase_query",
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        data = resp.json()
        out  = []
        for q in data.get("quotes", []):
            sym = q.get("symbol", "")
            if not sym:
                continue
            out.append({
                "symbol":   sym,
                "name":     q.get("shortname") or q.get("longname") or sym,
                "type":     q.get("quoteType", ""),
                "exchange": q.get("exchange", ""),
                "sector":   q.get("sector", ""),
            })
        return out
    except Exception:
        return []

# ─────────────────────────────────────────────
# EDUCATIONAL TOOLTIPS
# ─────────────────────────────────────────────
TOOLTIPS: dict[str, str] = {
    # ── Indicators ──────────────────────────
    "RSI": (
        "Relative Strength Index (0–100). "
        "Below 30 → oversold, potential BUY. "
        "Above 70 → overbought, potential SELL. "
        "Between 30–70 → neutral momentum."
    ),
    "MACD": (
        "Moving Average Convergence Divergence. "
        "Tracks the gap between a 12-day and 26-day EMA. "
        "When MACD crosses above its signal line → bullish. "
        "When it crosses below → bearish."
    ),
    "MACD Signal": (
        "9-day EMA of the MACD line. "
        "Used as a trigger: when MACD crosses above this line it's a buy signal; "
        "crossing below is a sell signal."
    ),
    "MACD Hist": (
        "MACD Histogram: the difference between MACD and its signal line. "
        "Positive bars = bullish momentum building; negative bars = bearish."
    ),
    "SMA20": (
        "Simple Moving Average (20 days). "
        "Average closing price over the last 20 trading days (~1 month). "
        "Price above SMA20 suggests short-term uptrend."
    ),
    "SMA50": (
        "Simple Moving Average (50 days). "
        "Medium-term trend indicator (~2.5 months). "
        "Price above SMA50 = medium-term bullish. Below = bearish."
    ),
    "SMA200": (
        "Simple Moving Average (200 days). "
        "The gold-standard long-term trend line (~10 months). "
        "Price above SMA200 = long-term bull market."
    ),
    "EMA": (
        "Exponential Moving Average. "
        "Like an SMA but gives more weight to recent prices, "
        "making it more reactive to new data."
    ),
    "Bollinger Bands": (
        "Price envelope set ±2 standard deviations around a 20-day SMA. "
        "Price touching the lower band → potentially oversold (BUY). "
        "Price touching the upper band → potentially overbought (SELL). "
        "Bands widening = high volatility; narrowing = low volatility."
    ),
    "BB Upper": (
        "Upper Bollinger Band: SMA20 + 2× standard deviation. "
        "Price above this = statistically overbought."
    ),
    "BB Lower": (
        "Lower Bollinger Band: SMA20 − 2× standard deviation. "
        "Price below this = statistically oversold."
    ),
    "Golden Cross": (
        "Golden Cross: the 50-day SMA crosses ABOVE the 200-day SMA. "
        "Considered a strong long-term bullish signal. "
        "Historically precedes sustained uptrends."
    ),
    "Death Cross": (
        "Death Cross: the 50-day SMA crosses BELOW the 200-day SMA. "
        "Considered a strong long-term bearish signal. "
        "Often precedes prolonged downtrends."
    ),
    "Volume": (
        "Number of shares/units traded in a session. "
        "High volume confirms a price move (strong conviction). "
        "Low volume on a price move = weak, potentially unreliable signal."
    ),
    # ── Recommendations ──────────────────────
    "BUY": (
        "BUY signal: Multiple technical indicators suggest the price is "
        "likely to rise. Consider purchasing this asset."
    ),
    "SELL": (
        "SELL signal: Multiple technical indicators suggest the price is "
        "likely to fall. Consider selling or avoiding this asset."
    ),
    "HOLD": (
        "HOLD signal: Mixed or neutral technical signals. "
        "No strong directional bias — best to wait for a clearer signal."
    ),
    "Score": (
        "Composite signal score combining 6 indicators: RSI, MACD crossover, "
        "SMA20, SMA50, Bollinger Bands, and Volume. "
        "Positive = net bullish signals; negative = net bearish. "
        "Range roughly −10 to +10."
    ),
    # ── Stats ────────────────────────────────
    "52W High": (
        "52-Week High: the highest closing price reached in the last 52 weeks (1 year). "
        "Price near the 52W high = strong uptrend or potential resistance."
    ),
    "52W Low": (
        "52-Week Low: the lowest closing price in the last 52 weeks. "
        "Price near the 52W low = potential support or continued weakness."
    ),
    "1M Change": (
        "1-Month Price Change: percentage price difference over the last "
        "~22 trading days. Green = price rose; red = price fell."
    ),
    "6M Change": (
        "6-Month Price Change: percentage price difference over the last "
        "~126 trading days. A key medium-term momentum indicator."
    ),
    "EUR": (
        "Euro (€): all prices are converted to EUR using the live USD/EUR "
        "exchange rate fetched from Yahoo Finance."
    ),
    "USD/EUR": (
        "The current exchange rate: how many Euros you get per 1 US Dollar. "
        "Used to convert USD-priced assets (US stocks, crypto) into EUR."
    ),
    # ── Chart ────────────────────────────────
    "Candlestick": (
        "Each candle represents one trading day. "
        "Green candle = price closed HIGHER than it opened. "
        "Red candle = price closed LOWER than it opened. "
        "The thin wicks show the day's high and low."
    ),
    "Risk Profile": (
        "Controls how sensitive the BUY/SELL scoring is. "
        "Conservative: requires stronger signals before recommending. "
        "Aggressive: acts on weaker signals, accepts more risk."
    ),
}

# Quote-type icons for search results
QTYPE_ICON = {
    "EQUITY":        "📈",
    "ETF":           "🗂️",
    "MUTUALFUND":    "🏦",
    "INDEX":         "📊",
    "CRYPTOCURRENCY":"₿",
    "CURRENCY":      "💱",
    "FUTURE":        "⏳",
    "OPTION":        "⚙️",
}

def tip(term: str, display: str | None = None) -> str:
    """Return an HTML span with a hover tooltip for a financial term."""
    text    = display or term
    tooltip = TOOLTIPS.get(term, "")
    if not tooltip:
        return text
    # Escape single quotes in tooltip text
    safe = tooltip.replace("'", "&#39;").replace('"', "&quot;")
    return (
        f'<span class="tt" data-t="{safe}">{text}</span>'
    )

TOOLTIP_CSS = """
<style>
/* Tooltip host */
.tt {
    border-bottom: 1px dashed #1E88E5;
    cursor: help;
    position: relative;
    display: inline-block;
    color: inherit;
}
/* Tooltip bubble */
.tt::after {
    content: attr(data-t);
    position: absolute;
    bottom: 130%;
    left: 50%;
    transform: translateX(-50%);
    min-width: 240px;
    max-width: 320px;
    background: #1A1F36;
    color: #E8EAF6;
    border: 1px solid #1E88E5;
    border-radius: 8px;
    padding: 9px 13px;
    font-size: 12px;
    line-height: 1.55;
    white-space: normal;
    z-index: 99999;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.18s ease;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
.tt::before {
    content: "";
    position: absolute;
    bottom: 115%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: #1E88E5;
    z-index: 99999;
    opacity: 0;
    transition: opacity 0.18s ease;
}
.tt:hover::after,
.tt:hover::before { opacity: 1; }

/* Suggestion chip */
.sug-chip {
    display: inline-block;
    background: #1A2332;
    border: 1px solid #1E88E5;
    border-radius: 20px;
    padding: 5px 14px;
    margin: 4px 4px 4px 0;
    font-size: 13px;
    cursor: pointer;
    color: #E0E0E0;
    transition: background 0.15s;
}
.sug-chip:hover { background: #1E88E5; color: white; }

/* Signal badge */
.sig-row {
    display: flex;
    align-items: flex-start;
    padding: 5px 0;
    border-bottom: 1px solid #1E1E2E;
    font-size: 13px;
    line-height: 1.5;
}
.sig-label { min-width: 110px; font-weight: 600; color: #90CAF9; }
.sig-value { flex: 1; }
.pts-badge {
    font-size: 11px;
    border-radius: 10px;
    padding: 1px 7px;
    margin-left: 6px;
    font-weight: 700;
}
.pts-pos { background:#0D3B24; color:#00E676; }
.pts-neg { background:#3B0D0D; color:#FF5252; }
.pts-zero{ background:#2A2A2A; color:#aaa; }
</style>
"""

# Suffixes that trade natively in EUR (or close currencies treated as EUR)
EUR_SUFFIXES = {".AS", ".DE", ".PA", ".SW", ".BR", ".MI", ".MC", ".LS",
                ".VI", ".HE", ".CO", ".ST", ".OL"}

def is_eur_symbol(symbol: str) -> bool:
    """Return True if the symbol is likely priced in EUR natively."""
    sym = symbol.upper()
    if sym.endswith("-EUR"):
        return True
    for sfx in EUR_SUFFIXES:
        if sym.endswith(sfx):
            return True
    return False

@st.cache_data(ttl=600)
def resolve_ticker_name(symbol: str) -> str:
    """Try to get a human-readable name from yfinance info."""
    try:
        info = yf.Ticker(symbol).fast_info
        # fast_info doesn't have shortName; fall back to Ticker.info
        full = yf.Ticker(symbol).info
        return (
            full.get("shortName")
            or full.get("longName")
            or symbol.upper()
        )
    except Exception:
        return symbol.upper()

def build_result(sym: str, name: str, market: str,
                 df: pd.DataFrame, eur_rate: float, risk: str) -> dict:
    """Run indicators + scoring on a ready dataframe and return a result dict."""
    s    = score_stock(df, risk)
    mult = 1.0 if is_eur_symbol(sym) else eur_rate
    return {
        "symbol":         sym,
        "name":           name,
        "market":         market,
        "df":             df,
        "is_eur":         is_eur_symbol(sym),
        "mult":           mult,
        "price_eur":      s["close"] * mult,
        "recommendation": s["recommendation"],
        "rec_emoji":      s["rec_emoji"],
        "rec_color":      s["rec_color"],
        "score":          s["score"],
        "rsi":            s["rsi"],
        "high52":         s["high52"] * mult,
        "low52":          s["low52"]  * mult,
        "pct_chg_1m":     s["pct_chg_1m"],
        "pct_chg_6m":     s["pct_chg_6m"],
        "signals":        s["signals"],
    }

@st.cache_data(ttl=300)
def fetch_info(symbol: str):
    try:
        return yf.Ticker(symbol).info
    except Exception:
        return {}

# ─────────────────────────────────────────────
# TECHNICAL INDICATORS
# ─────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_macd(series: pd.Series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return macd, signal, hist

def compute_bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    sma   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    upper = sma + std * sigma
    lower = sma - std * sigma
    return upper, sma, lower

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]
    df["SMA20"]  = close.rolling(20).mean()
    df["SMA50"]  = close.rolling(50).mean()
    df["SMA200"] = close.rolling(200).mean()
    df["EMA12"]  = close.ewm(span=12, adjust=False).mean()
    df["EMA26"]  = close.ewm(span=26, adjust=False).mean()
    df["RSI"]    = compute_rsi(close)
    df["MACD"], df["MACD_Signal"], df["MACD_Hist"] = compute_macd(close)
    df["BB_Upper"], df["BB_Mid"], df["BB_Lower"] = compute_bollinger(close)
    df["Volume_MA20"] = df["Volume"].rolling(20).mean()
    return df

# ─────────────────────────────────────────────
# SCORING ENGINE  (max 10 points)
# ─────────────────────────────────────────────
def score_stock(df: pd.DataFrame, risk: str) -> dict:
    params = RISK_PARAMS[risk]
    last   = df.iloc[-1]
    prev   = df.iloc[-2] if len(df) > 1 else last

    signals = {}
    score   = 0  # positive = bullish, negative = bearish

    # 1. RSI
    rsi = last.get("RSI", np.nan)
    if pd.notna(rsi):
        if rsi < params["rsi_buy"]:
            signals["RSI"] = ("🟢 Oversold", +2)
            score += 2
        elif rsi > params["rsi_sell"]:
            signals["RSI"] = ("🔴 Overbought", -2)
            score -= 2
        else:
            signals["RSI"] = ("🟡 Neutral", 0)

    # 2. MACD crossover
    macd, sig = last.get("MACD", np.nan), last.get("MACD_Signal", np.nan)
    p_macd, p_sig = prev.get("MACD", np.nan), prev.get("MACD_Signal", np.nan)
    if all(pd.notna(x) for x in [macd, sig, p_macd, p_sig]):
        if p_macd < p_sig and macd > sig:
            signals["MACD"] = ("🟢 Bullish crossover", +2)
            score += 2
        elif p_macd > p_sig and macd < sig:
            signals["MACD"] = ("🔴 Bearish crossover", -2)
            score -= 2
        elif macd > sig:
            signals["MACD"] = ("🟢 Above signal", +1)
            score += 1
        else:
            signals["MACD"] = ("🔴 Below signal", -1)
            score -= 1

    # 3. Price vs SMA 20/50
    close  = last["Close"]
    sma20  = last.get("SMA20",  np.nan)
    sma50  = last.get("SMA50",  np.nan)
    sma200 = last.get("SMA200", np.nan)
    if pd.notna(sma20):
        if close > sma20:
            signals["SMA20"] = ("🟢 Above SMA20", +1)
            score += 1
        else:
            signals["SMA20"] = ("🔴 Below SMA20", -1)
            score -= 1
    if pd.notna(sma50):
        if close > sma50:
            signals["SMA50"] = ("🟢 Above SMA50", +1)
            score += 1
        else:
            signals["SMA50"] = ("🔴 Below SMA50", -1)
            score -= 1

    # 4. Golden / Death cross (SMA50 vs SMA200)
    p_sma50  = prev.get("SMA50",  np.nan)
    p_sma200 = prev.get("SMA200", np.nan)
    if all(pd.notna(x) for x in [sma50, sma200, p_sma50, p_sma200]):
        if p_sma50 < p_sma200 and sma50 > sma200:
            signals["Golden Cross"] = ("🟢 Golden Cross!", +2)
            score += 2
        elif p_sma50 > p_sma200 and sma50 < sma200:
            signals["Death Cross"] = ("🔴 Death Cross!", -2)
            score -= 2

    # 5. Bollinger Bands
    bb_up  = last.get("BB_Upper", np.nan)
    bb_low = last.get("BB_Lower", np.nan)
    if pd.notna(bb_up) and pd.notna(bb_low):
        if close < bb_low:
            signals["Bollinger"] = ("🟢 Below lower band", +1)
            score += 1
        elif close > bb_up:
            signals["Bollinger"] = ("🔴 Above upper band", -1)
            score -= 1
        else:
            signals["Bollinger"] = ("🟡 Inside bands", 0)

    # 6. Volume confirmation
    vol    = last.get("Volume",    np.nan)
    vol_ma = last.get("Volume_MA20", np.nan)
    if pd.notna(vol) and pd.notna(vol_ma) and vol_ma > 0:
        if vol > vol_ma * 1.5:
            signals["Volume"] = ("🟢 High volume", +1)
            score += 1
        else:
            signals["Volume"] = ("🟡 Normal volume", 0)

    # Final recommendation
    max_possible = 10
    pct = score / max_possible

    if pct >= 0.3:
        recommendation = "BUY"
        rec_color = "#00C853"
        rec_emoji = "🟢"
    elif pct <= -0.2:
        recommendation = "SELL"
        rec_color = "#D50000"
        rec_emoji = "🔴"
    else:
        recommendation = "HOLD"
        rec_color = "#FF6F00"
        rec_emoji = "🟡"

    # 52-week stats
    high52 = df["Close"].tail(252).max()
    low52  = df["Close"].tail(252).min()
    pct_chg_1m = (close / df["Close"].iloc[-22] - 1) * 100 if len(df) >= 22 else np.nan
    pct_chg_6m = (close / df["Close"].iloc[0]   - 1) * 100

    return {
        "score":          score,
        "recommendation": recommendation,
        "rec_color":      rec_color,
        "rec_emoji":      rec_emoji,
        "signals":        signals,
        "rsi":            rsi,
        "close":          close,
        "high52":         high52,
        "low52":          low52,
        "pct_chg_1m":     pct_chg_1m,
        "pct_chg_6m":     pct_chg_6m,
    }

# ─────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────
def build_chart(df: pd.DataFrame, symbol: str, name: str, eur_rate: float, is_eur: bool):
    mult = 1.0 if is_eur else eur_rate
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.25, 0.20],
        vertical_spacing=0.03,
        subplot_titles=(f"{name} — Price (€)", "RSI", "MACD"),
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"]  * mult,
        high=df["High"]  * mult,
        low=df["Low"]    * mult,
        close=df["Close"] * mult,
        name="Price",
        increasing_line_color="#00C853",
        decreasing_line_color="#D50000",
    ), row=1, col=1)

    for label, col_name, color, dash in [
        ("SMA20",  "SMA20",  "#1E88E5", "solid"),
        ("SMA50",  "SMA50",  "#FFA726", "solid"),
        ("SMA200", "SMA200", "#AB47BC", "dot"),
        ("BB Up",  "BB_Upper","#78909C","dash"),
        ("BB Low", "BB_Lower","#78909C","dash"),
    ]:
        if col_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col_name] * mult,
                name=label, line=dict(color=color, dash=dash, width=1),
                opacity=0.8,
            ), row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=df.index, y=df["RSI"],
        name="RSI", line=dict(color="#26C6DA", width=1.5),
    ), row=2, col=1)
    for lvl, clr in [(70, "#D50000"), (30, "#00C853")]:
        fig.add_hline(y=lvl, line_dash="dash", line_color=clr, row=2, col=1)

    # MACD
    colors = ["#00C853" if v >= 0 else "#D50000" for v in df["MACD_Hist"]]
    fig.add_trace(go.Bar(
        x=df.index, y=df["MACD_Hist"],
        name="MACD Hist", marker_color=colors, opacity=0.6,
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD"],
        name="MACD", line=dict(color="#1E88E5", width=1.2),
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD_Signal"],
        name="Signal", line=dict(color="#FFA726", width=1.2),
    ), row=3, col=1)

    fig.update_layout(
        height=620,
        template="plotly_dark",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.05, x=0),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    fig.update_yaxes(tickprefix="€", row=1, col=1)
    return fig

# ─────────────────────────────────────────────
# SHARED DEEP-DIVE RENDERER
# ─────────────────────────────────────────────
def render_deep_dive(r: dict, eur_rate: float, key_prefix: str = ""):
    """Render the signal panel + candlestick chart for a result dict."""
    sig_col, chart_col = st.columns([1, 3])

    with sig_col:
        # ── Signals with hover tooltips ──────
        rows_html = ""
        for indicator, (label, pts) in r["signals"].items():
            badge_cls = "pts-pos" if pts > 0 else ("pts-neg" if pts < 0 else "pts-zero")
            label_html = tip(indicator)
            rows_html += (
                f"<div class='sig-row'>"
                f"  <span class='sig-label'>{label_html}</span>"
                f"  <span class='sig-value'>{label}"
                f"    <span class='pts-badge {badge_cls}'>{pts:+d}</span>"
                f"  </span>"
                f"</div>"
            )

        score_color = r["rec_color"]
        st.markdown(
            f"<p style='font-weight:600;color:#90CAF9;margin-bottom:6px'>📡 Technical Signals</p>"
            f"{rows_html}"
            f"<div style='margin-top:12px;font-size:13px'>"
            f"  {tip('Score', '📊 Score')}: "
            f"  <b style='color:{score_color};font-size:16px'>{r['score']:+d}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f"<h3 style='color:{r['rec_color']};margin-top:8px'>"
            f"  {r['rec_emoji']} {tip(r['recommendation'])}"
            f"</h3>",
            unsafe_allow_html=True,
        )

        # ── Metrics with built-in Streamlit help tooltips ──
        st.metric("Current Price (€)", f"€{r['price_eur']:,.2f}",
                  help=TOOLTIPS["EUR"])
        if pd.notna(r["pct_chg_1m"]):
            st.metric("1M Return", f"{r['pct_chg_1m']:+.2f}%",
                      help=TOOLTIPS["1M Change"])
        st.metric("6M Return", f"{r['pct_chg_6m']:+.2f}%",
                  help=TOOLTIPS["6M Change"])
        st.metric("52W High", f"€{r['high52']:,.2f}",
                  help=TOOLTIPS["52W High"])
        st.metric("52W Low",  f"€{r['low52']:,.2f}",
                  help=TOOLTIPS["52W Low"])

    with chart_col:
        fig = build_chart(r["df"], r["symbol"], r["name"], eur_rate, r["is_eur"])
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{key_prefix}{r['symbol']}")


# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────
def main():
    # ── Sidebar ──────────────────────────────
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/combo-chart.png", width=64)
        st.title("⚙️ Settings")

        risk = st.selectbox(
            "Risk Profile",
            ["Conservative", "Balanced", "Aggressive"],
            index=1,
            help=TOOLTIPS["Risk Profile"],
        )

        period = st.selectbox(
            "Analysis Period",
            ["3mo", "6mo", "1y", "2y"],
            index=1,
        )

        selected_markets = st.multiselect(
            "Markets",
            list(STOCKS.keys()),
            default=list(STOCKS.keys()),
        )

        refresh = st.button("🔄 Refresh Data", use_container_width=True)
        if refresh:
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        st.caption("Data: Yahoo Finance · Prices in EUR")

    # ── Inject CSS (tooltips + styled elements) ──
    st.markdown(TOOLTIP_CSS, unsafe_allow_html=True)

    # ── Header ───────────────────────────────
    st.markdown("""
    <h1 style='text-align:center; color:#1E88E5;'>
        📈 AI Stock Investment Recommender
    </h1>
    <p style='text-align:center; color:#888; margin-top:-10px;'>
        Real-time technical analysis · Buy / Hold / Sell signals · Prices in €
    </p>
    """, unsafe_allow_html=True)
    st.divider()

    eur_rate = get_eur_rate()
    st.markdown(
        f"<span style='font-size:12px;color:#888'>"
        f"💱 {tip('USD/EUR', '1 USD = €' + str(round(eur_rate, 4)))}"
        f"</span>",
        unsafe_allow_html=True,
    )

    # ── Tabs ─────────────────────────────────
    tab_watch, tab_search, tab_learn = st.tabs([
        "📋 Market Watchlist",
        "🔍 Search Any Ticker",
        "📚 How It Works",
    ])

    # ══════════════════════════════════════════
    # TAB 1 — MARKET WATCHLIST
    # ══════════════════════════════════════════
    with tab_watch:
        # Collect tickers from selected markets
        all_tickers = {}
        for market in selected_markets:
            for sym, name in STOCKS[market].items():
                all_tickers[sym] = {"name": name, "market": market}

        if not all_tickers:
            st.info("Select at least one market in the sidebar to populate the watchlist.")
        else:
            # Run Analysis
            failed_tickers = []
            with st.spinner("🔍 Fetching live market data and running analysis…"):
                results = []
                for sym, meta in all_tickers.items():
                    df = fetch_stock_data(sym, period)
                    if df is None or len(df) < 30:
                        failed_tickers.append(sym)
                        continue
                    df = add_indicators(df)
                    results.append(
                        build_result(sym, meta["name"], meta["market"], df, eur_rate, risk)
                    )

            # Data fetch status
            if not results:
                st.error(
                    "⚠️ **No stock data could be retrieved.** "
                    "Please check your internet connection and click **🔄 Refresh Data**."
                )
            else:
                if failed_tickers:
                    st.warning(
                        f"⚠️ Could not fetch: **{', '.join(failed_tickers)}** — "
                        "may be temporarily unavailable."
                    )

                # KPI row
                buys  = sum(1 for r in results if r["recommendation"] == "BUY")
                holds = sum(1 for r in results if r["recommendation"] == "HOLD")
                sells = sum(1 for r in results if r["recommendation"] == "SELL")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("📊 Stocks Analysed", len(results))
                k2.metric("🟢 BUY Signals",  buys,  help=TOOLTIPS["BUY"])
                k3.metric("🟡 HOLD Signals", holds, help=TOOLTIPS["HOLD"])
                k4.metric("🔴 SELL Signals", sells, help=TOOLTIPS["SELL"])
                st.divider()

                # Summary table
                st.subheader("📋 Full Analysis Summary")
                table_data = []
                for r in sorted(results, key=lambda x: x["score"], reverse=True):
                    chg_1m = f"{r['pct_chg_1m']:+.1f}%" if pd.notna(r["pct_chg_1m"]) else "—"
                    chg_6m = f"{r['pct_chg_6m']:+.1f}%" if pd.notna(r["pct_chg_6m"]) else "—"
                    table_data.append({
                        "Signal":       f"{r['rec_emoji']} {r['recommendation']}",
                        "Name":         r["name"],
                        "Symbol":       r["symbol"],
                        "Market":       r["market"],
                        "Price (€)":    f"€{r['price_eur']:,.2f}",
                        "RSI":          f"{r['rsi']:.1f}" if pd.notna(r["rsi"]) else "—",
                        "Score":        r["score"],
                        "1M Change":    chg_1m,
                        "6M Change":    chg_6m,
                        "52W High (€)": f"€{r['high52']:,.2f}",
                        "52W Low (€)":  f"€{r['low52']:,.2f}",
                    })

                def color_signal(val):
                    if "BUY"  in str(val): return "color:#00C853; font-weight:bold"
                    if "SELL" in str(val): return "color:#D50000; font-weight:bold"
                    if "HOLD" in str(val): return "color:#FFA726; font-weight:bold"
                    return ""

                def color_change(val):
                    try:
                        v = float(str(val).replace("%", ""))
                        return f"color:{'#00C853' if v > 0 else '#D50000'}"
                    except Exception:
                        return ""

                df_table = pd.DataFrame(table_data)
                st.dataframe(
                    df_table.style
                        .applymap(color_signal, subset=["Signal"])
                        .applymap(color_change, subset=["1M Change", "6M Change"]),
                    use_container_width=True,
                    hide_index=True,
                )

                # Top picks
                st.divider()
                buys_list  = [r for r in results if r["recommendation"] == "BUY"]
                sells_list = [r for r in results if r["recommendation"] == "SELL"]
                col_b, col_s = st.columns(2)
                with col_b:
                    st.subheader("🟢 Top BUY Picks")
                    if buys_list:
                        for r in sorted(buys_list, key=lambda x: x["score"], reverse=True)[:5]:
                            st.markdown(f"""
                            <div style='background:#0E2A1E;border:1px solid #00C853;border-radius:8px;padding:10px 14px;margin-bottom:8px;'>
                                <b style='color:#00C853'>{r['name']}</b>
                                <span style='color:#aaa;font-size:12px'> ({r['symbol']})</span><br>
                                <span style='font-size:22px;font-weight:bold;color:white'>€{r['price_eur']:,.2f}</span>
                                &nbsp;&nbsp;
                                <span style='color:#aaa;font-size:13px'>RSI: {r['rsi']:.1f} · Score: {r['score']}</span>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No BUY signals at this time.")
                with col_s:
                    st.subheader("🔴 Top SELL Picks")
                    if sells_list:
                        for r in sorted(sells_list, key=lambda x: x["score"])[:5]:
                            st.markdown(f"""
                            <div style='background:#2A0E0E;border:1px solid #D50000;border-radius:8px;padding:10px 14px;margin-bottom:8px;'>
                                <b style='color:#D50000'>{r['name']}</b>
                                <span style='color:#aaa;font-size:12px'> ({r['symbol']})</span><br>
                                <span style='font-size:22px;font-weight:bold;color:white'>€{r['price_eur']:,.2f}</span>
                                &nbsp;&nbsp;
                                <span style='color:#aaa;font-size:13px'>RSI: {r['rsi']:.1f} · Score: {r['score']}</span>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No SELL signals at this time.")

                # Deep dive
                st.divider()
                st.subheader("🔍 Individual Stock Deep Dive")
                symbol_options = {f"{r['rec_emoji']} {r['name']} ({r['symbol']})": r for r in results}
                chosen_label   = st.selectbox("Select a stock to inspect:", list(symbol_options.keys()), key="watchlist_select")
                chosen         = symbol_options[chosen_label]
                render_deep_dive(chosen, eur_rate)

    # ══════════════════════════════════════════
    # TAB 2 — SEARCH ANY TICKER (smart)
    # ══════════════════════════════════════════
    with tab_search:
        st.markdown(
            "<p style='color:#aaa;margin-bottom:6px'>"
            "Search <b>any</b> global ticker — stocks, ETFs, indices, crypto, forex, futures.<br>"
            "Type a <b>ticker</b> (e.g. <code>AAPL</code>, <code>BTC-EUR</code>) "
            "<b>or a company/asset name</b> (e.g. <code>toyota</code>, <code>gold</code>, "
            "<code>reliance</code>) and the app will find the right symbol for you."
            "</p>",
            unsafe_allow_html=True,
        )

        # ── Session state for search ──────────
        # We persist the last search state so suggestion chips survive reruns
        if "sx_results"    not in st.session_state: st.session_state.sx_results    = []
        if "sx_sug_map"    not in st.session_state: st.session_state.sx_sug_map    = {}
        if "sx_no_sug"     not in st.session_state: st.session_state.sx_no_sug     = []
        if "sx_has_state"  not in st.session_state: st.session_state.sx_has_state  = False
        if "sx_chip_sym"   not in st.session_state: st.session_state.sx_chip_sym   = None

        search_col, btn_col = st.columns([4, 1])
        with search_col:
            raw_input = st.text_input(
                "Search ticker or company name",
                placeholder="e.g.  AAPL  ·  toyota  ·  BTC-EUR  ·  RELIANCE.NS  ·  gold",
                label_visibility="collapsed",
                key="ticker_search_input",
            )
        with btn_col:
            search_clicked = st.button("🔍 Analyse", use_container_width=True, key="search_btn")

        # ── Resolve what to analyse ───────────
        if st.session_state.sx_chip_sym:
            # A suggestion chip was clicked — consume it and run analysis
            active_query   = st.session_state.sx_chip_sym
            st.session_state.sx_chip_sym = None
            run_analysis   = True
        elif search_clicked and raw_input.strip():
            active_query   = raw_input.strip()
            run_analysis   = True
        elif search_clicked and not raw_input.strip():
            st.warning("Please enter at least one ticker symbol or company name.")
            run_analysis   = False
            active_query   = ""
        else:
            active_query   = ""
            run_analysis   = False

        # ── Run analysis ──────────────────────
        if run_analysis:
            raw_tokens  = [t.strip().upper() for t in
                           active_query.replace(",", " ").split() if t.strip()]
            results_tmp = []
            errors_tmp  = []
            sug_tmp     = {}

            with st.spinner(f"Searching and analysing: {', '.join(raw_tokens)}…"):
                for token in raw_tokens:
                    df = fetch_stock_data(token, period)
                    if df is not None and len(df) >= 10:
                        df   = add_indicators(df)
                        name = resolve_ticker_name(token)
                        results_tmp.append(
                            build_result(token, name, "Custom Search", df, eur_rate, risk)
                        )
                    else:
                        errors_tmp.append(token)
                        sugs = yahoo_search(token)
                        if sugs:
                            sug_tmp[token] = sugs

            # Persist results in session state so chips survive the next rerun
            st.session_state.sx_results   = results_tmp
            st.session_state.sx_sug_map   = sug_tmp
            st.session_state.sx_no_sug    = [s for s in errors_tmp if s not in sug_tmp]
            st.session_state.sx_has_state = True

        # ── Always render persisted results ──
        # (chips must be rendered unconditionally so clicks can fire)
        if st.session_state.sx_has_state:

            # Suggestion chips for failed tokens
            for bad_sym, suggestions in st.session_state.sx_sug_map.items():
                st.markdown(
                    f"<div style='background:#1A1228;border:1px solid #7B1FA2;"
                    f"border-radius:8px;padding:12px 16px;margin-bottom:10px;'>"
                    f"<b style='color:#CE93D8'>❓ Could not find <code>{bad_sym}</code> — "
                    f"did you mean one of these?</b><br>"
                    f"<span style='font-size:12px;color:#aaa'>"
                    f"Click a chip to analyse that ticker instantly.</span></div>",
                    unsafe_allow_html=True,
                )
                chip_cols = st.columns(min(len(suggestions), 3))
                for i, sug in enumerate(suggestions):
                    icon  = QTYPE_ICON.get(sug["type"].upper(), "📌")
                    label = f"{icon} {sug['symbol']}  —  {sug['name'][:30]}"
                    if sug["exchange"]:
                        label += f"  [{sug['exchange']}]"
                    with chip_cols[i % len(chip_cols)]:
                        if st.button(label, key=f"sug_{bad_sym}_{sug['symbol']}", use_container_width=True):
                            # Store chip symbol — will be consumed at top of next rerun
                            st.session_state.sx_chip_sym  = sug["symbol"]
                            st.session_state.sx_has_state = False   # clear old state
                            st.rerun()

            # Tokens with no suggestions
            if st.session_state.sx_no_sug:
                st.error(
                    f"❌ No data or suggestions found for: **{', '.join(st.session_state.sx_no_sug)}**. "
                    "Verify the symbol on [finance.yahoo.com](https://finance.yahoo.com)."
                )

            # ── Results from session state ────
            if st.session_state.sx_results:
                cols = st.columns(min(len(st.session_state.sx_results), 3))
                for i, r in enumerate(st.session_state.sx_results):
                    with cols[i % len(cols)]:
                        bg     = "#0E2A1E" if r["recommendation"] == "BUY"  else \
                                 "#2A0E0E" if r["recommendation"] == "SELL" else "#1A1A0E"
                        border = r["rec_color"]
                        chg_1m_str = f"{r['pct_chg_1m']:+.1f}%" if pd.notna(r["pct_chg_1m"]) else "—"
                        chg_col    = "#00C853" if (pd.notna(r["pct_chg_1m"]) and r["pct_chg_1m"] > 0) else "#FF5252"
                        st.markdown(f"""
                        <div style='background:{bg};border:1px solid {border};
                                    border-radius:10px;padding:14px 16px;margin-bottom:12px;'>
                            <div style='font-size:11px;color:#aaa'>{r['symbol']}</div>
                            <div style='font-size:15px;font-weight:700;color:white;margin:3px 0'>{r['name']}</div>
                            <div style='font-size:26px;font-weight:700;color:white'>€{r['price_eur']:,.2f}</div>
                            <div style='margin-top:8px'>
                                <span style='background:{border};color:white;padding:2px 11px;
                                             border-radius:20px;font-weight:700;font-size:13px'>
                                    {r['rec_emoji']} {r['recommendation']}
                                </span>
                                <span style='color:#aaa;font-size:12px;margin-left:8px'>
                                    Score: {r['score']} · RSI: {r['rsi']:.1f}
                                </span>
                            </div>
                            <div style='margin-top:6px;font-size:12px;color:#aaa'>
                                1M: <b style='color:{chg_col}'>{chg_1m_str}</b>
                                &nbsp;·&nbsp; 52W: €{r['low52']:,.0f} – €{r['high52']:,.0f}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                st.divider()
                for r in st.session_state.sx_results:
                    st.subheader(f"🔍 {r['name']} ({r['symbol']})")
                    render_deep_dive(r, eur_rate, key_prefix=r["symbol"])
                    st.divider()

        else:
            # Idle state — show examples
            st.markdown("""
            <div style='text-align:center;padding:36px 20px;color:#555;'>
                <div style='font-size:44px'>🌍</div>
                <div style='font-size:15px;margin-top:8px;color:#666'>
                    Search any stock, ETF, crypto, index or commodity worldwide
                </div>
            </div>
            <div style='display:flex;flex-wrap:wrap;gap:8px;justify-content:center;
                        padding:0 40px 24px 40px;'>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>📈 AAPL — Apple</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>₿ BTC-EUR — Bitcoin</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>📈 RELIANCE.NS — India</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>📈 7203.T — Toyota</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>⏳ GC=F — Gold Futures</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>🗂️ VWCE.DE — MSCI World ETF</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>📊 ^DAX — DAX Index</span>
                <span style='background:#12233A;border:1px solid #1E88E5;border-radius:16px;
                             padding:5px 14px;font-size:13px;color:#90CAF9'>📈 Or just type: toyota</span>
            </div>
            """, unsafe_allow_html=True)

    # ══════════════════════════════════════════
    # TAB 3 — HOW IT WORKS / METHODOLOGY
    # ══════════════════════════════════════════
    with tab_learn:
        st.markdown("""
        <h2 style='color:#1E88E5;margin-bottom:4px'>📚 How the Recommender Works</h2>
        <p style='color:#888'>
            A plain-English guide to every signal, metric, and formula used in this app.
        </p>
        """, unsafe_allow_html=True)
        st.divider()

        # ── OVERVIEW ──────────────────────────
        st.markdown("""
        <h3 style='color:#90CAF9'>🔭 Overview</h3>
        <p style='color:#ccc;line-height:1.7'>
            This app fetches <b>live price data</b> from Yahoo Finance, computes <b>six
            technical indicators</b>, and combines their scores into a single
            <b>composite score</b>.  Based on that score and your chosen
            <b>Risk Profile</b>, each asset receives a <b>BUY / HOLD / SELL</b>
            recommendation.  All prices are displayed in <b>Euros (€)</b> using a
            live USD → EUR exchange rate.
        </p>
        """, unsafe_allow_html=True)

        # ── SCORING SYSTEM ────────────────────
        st.markdown("<h3 style='color:#90CAF9'>🧮 Composite Scoring System</h3>",
                    unsafe_allow_html=True)
        st.markdown("""
        <p style='color:#ccc;line-height:1.7'>
            Each indicator contributes <b>points</b> to a running total.
            Positive points mean <em>bullish</em> evidence; negative points mean
            <em>bearish</em> evidence.  The maximum possible score is
            <b>+10</b> and the minimum is <b>−10</b>.
        </p>
        """, unsafe_allow_html=True)

        score_table = pd.DataFrame([
            {"Indicator":     "RSI",
             "Max Points":    "±2",
             "Bullish (+)":   "RSI < buy threshold (oversold)",
             "Bearish (−)":   "RSI > sell threshold (overbought)"},
            {"Indicator":     "MACD",
             "Max Points":    "±2",
             "Bullish (+)":   "MACD crosses above signal line (crossover +2) or stays above (+1)",
             "Bearish (−)":   "MACD crosses below signal line (crossover −2) or stays below (−1)"},
            {"Indicator":     "SMA 20",
             "Max Points":    "±1",
             "Bullish (+)":   "Price above 20-day moving average",
             "Bearish (−)":   "Price below 20-day moving average"},
            {"Indicator":     "SMA 50",
             "Max Points":    "±1",
             "Bullish (+)":   "Price above 50-day moving average",
             "Bearish (−)":   "Price below 50-day moving average"},
            {"Indicator":     "Bollinger Bands",
             "Max Points":    "±1",
             "Bullish (+)":   "Price below lower band (oversold)",
             "Bearish (−)":   "Price above upper band (overbought)"},
            {"Indicator":     "Volume",
             "Max Points":    "+1",
             "Bullish (+)":   "Volume > 1.5× its 20-day average (strong conviction)",
             "Bearish (−)":   "Normal volume → 0 pts"},
        ])
        st.dataframe(score_table, use_container_width=True, hide_index=True)

        st.markdown("""
        <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;
                    padding:14px 18px;margin:10px 0;color:#ccc;line-height:1.8'>
            <b style='color:#90CAF9'>Recommendation thresholds</b><br>
            <code>score / 10 ≥  0.30</code> → <b style='color:#00C853'>BUY</b><br>
            <code>score / 10 ≤ −0.20</code> → <b style='color:#D50000'>SELL</b><br>
            <code>otherwise       </code> → <b style='color:#FFA726'>HOLD</b>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # ── INDICATORS ───────────────────────
        st.markdown("<h3 style='color:#90CAF9'>📡 Technical Indicators Explained</h3>",
                    unsafe_allow_html=True)

        indicators = [
            ("📈 RSI — Relative Strength Index", "#CE93D8", """
<p>The RSI measures the <b>speed and magnitude of recent price changes</b> on a scale
of 0 to 100.  It is computed over a rolling <b>14-day</b> window.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b style='color:#D50000'>RSI &gt; 70</b> — asset is <em>overbought</em>:
      price rose very fast, a pullback may follow → bearish signal.</li>
  <li><b style='color:#00C853'>RSI &lt; 30</b> — asset is <em>oversold</em>:
      price fell very fast, a bounce may follow → bullish signal.</li>
  <li><b style='color:#FFA726'>30 ≤ RSI ≤ 70</b> — neutral momentum, no strong signal.</li>
</ul>
<p><b>Formula:</b> <code>RSI = 100 − 100 / (1 + RS)</code> where
<code>RS = Average Gain / Average Loss</code> over 14 days.</p>
<p><b>Risk-profile thresholds:</b> Conservative uses 35/65, Balanced 40/60,
Aggressive 45/55 — so aggressive profiles trigger signals earlier.</p>
            """),
            ("📉 MACD — Moving Average Convergence/Divergence", "#80DEEA", """
<p>MACD tracks the <b>momentum and trend direction</b> of a price series by
comparing two exponential moving averages (EMAs).</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b>MACD line</b> = EMA(12 days) − EMA(26 days)</li>
  <li><b>Signal line</b> = EMA(9 days) of the MACD line</li>
  <li><b>Histogram</b> = MACD − Signal (shows divergence visually)</li>
</ul>
<p><b>Signals:</b></p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b style='color:#00C853'>Bullish crossover</b> — MACD crosses <em>above</em>
      the signal line → strong buy signal (+2 pts).</li>
  <li><b style='color:#D50000'>Bearish crossover</b> — MACD crosses <em>below</em>
      the signal line → strong sell signal (−2 pts).</li>
  <li>MACD staying above/below signal = +1/−1 pts (continuation).</li>
</ul>
            """),
            ("📊 SMA — Simple Moving Averages (20 / 50 / 200)", "#A5D6A7", """
<p>A Simple Moving Average smooths price data by averaging the closing prices
over a specified number of days, filtering out daily noise.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b>SMA 20</b> — short-term trend (~1 month): price above SMA20 → bullish momentum.</li>
  <li><b>SMA 50</b> — medium-term trend (~2.5 months): widely watched by institutions.</li>
  <li><b>SMA 200</b> — long-term trend (~10 months): the definitive bull/bear divide.</li>
</ul>
<p><b>Special crossover events:</b></p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b style='color:#00C853'>Golden Cross</b> — SMA50 crosses <em>above</em> SMA200:
      strong long-term bullish signal (+2 pts).</li>
  <li><b style='color:#D50000'>Death Cross</b> — SMA50 crosses <em>below</em> SMA200:
      strong long-term bearish signal (−2 pts).</li>
</ul>
<p>Only SMA20 and SMA50 contribute to the daily score (±1 each).
Golden/Death Cross is tracked separately and adds ±2 when it occurs.</p>
            """),
            ("🎯 Bollinger Bands", "#FFCC80", """
<p>Bollinger Bands place a <b>statistical envelope</b> around price, defined as
SMA20 ± 2 standard deviations.  About 95% of price action falls <em>inside</em>
the bands under normal conditions.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b>Upper Band</b> = SMA20 + 2σ — price here is statistically high (overbought −1 pt).</li>
  <li><b>Middle Band</b> = SMA20 — the baseline.</li>
  <li><b>Lower Band</b> = SMA20 − 2σ — price here is statistically low (oversold +1 pt).</li>
  <li><b>Band width</b> signals volatility: widening = high volatility; narrowing = squeeze
      (often precedes a breakout).</li>
</ul>
            """),
            ("📦 Volume Confirmation", "#EF9A9A", """
<p>Volume is the number of shares/units traded in a session.  It acts as a
<b>confidence multiplier</b> for price moves.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b style='color:#00C853'>High volume</b> — volume &gt; 1.5× its 20-day average:
      the price move has strong market participation behind it (+1 pt).</li>
  <li><b style='color:#FFA726'>Normal volume</b> — move may be less reliable (0 pts).</li>
</ul>
<p>Volume alone is not directional — it is used only to <em>confirm</em> other signals.</p>
            """),
        ]

        for title, color, body in indicators:
            with st.expander(title):
                st.markdown(f"<div style='color:#ccc;line-height:1.7'>{body}</div>",
                            unsafe_allow_html=True)

        st.divider()

        # ── RISK PROFILES ─────────────────────
        st.markdown("<h3 style='color:#90CAF9'>⚖️ Risk Profiles</h3>",
                    unsafe_allow_html=True)
        risk_df = pd.DataFrame([
            {"Profile":       "Conservative",
             "RSI Buy Below": 35,
             "RSI Sell Above": 65,
             "Min Score for BUY": 4,
             "Who it suits": "Capital-preservation focus, dislikes volatility"},
            {"Profile":       "Balanced",
             "RSI Buy Below": 40,
             "RSI Sell Above": 60,
             "Min Score for BUY": 3,
             "Who it suits": "Default — moderate risk/reward balance"},
            {"Profile":       "Aggressive",
             "RSI Buy Below": 45,
             "RSI Sell Above": 55,
             "Min Score for BUY": 2,
             "Who it suits": "Growth-seeking, comfortable with higher drawdowns"},
        ])
        st.dataframe(risk_df, use_container_width=True, hide_index=True)
        st.markdown("""
        <p style='color:#aaa;font-size:13px;margin-top:6px'>
            The Risk Profile adjusts <em>two</em> things: the RSI thresholds at which
            oversold/overbought signals fire, and the minimum composite score required
            to trigger a BUY recommendation.  Higher risk tolerance = earlier, more
            frequent signals.
        </p>
        """, unsafe_allow_html=True)

        st.divider()

        # ── CHART GUIDE ───────────────────────
        st.markdown("<h3 style='color:#90CAF9'>🕯️ Reading the Chart</h3>",
                    unsafe_allow_html=True)
        st.markdown("""
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;'>

          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Panel 1 — Candlestick + Overlays</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li>Each candle = 1 trading day. <b style='color:#00C853'>Green</b> = up day,
                  <b style='color:#D50000'>Red</b> = down day.</li>
              <li>Thin wicks show the intra-day high and low.</li>
              <li><b style='color:#1E88E5'>Blue line</b> = SMA 20</li>
              <li><b style='color:#FFA726'>Orange line</b> = SMA 50</li>
              <li><b style='color:#AB47BC'>Purple dotted</b> = SMA 200</li>
              <li><b style='color:#78909C'>Grey dashed</b> = Bollinger Bands (upper & lower)</li>
            </ul>
          </div>

          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Panel 2 — RSI</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li><b style='color:#26C6DA'>Teal line</b> = RSI (14-day)</li>
              <li><b style='color:#D50000'>Red dashed line at 70</b> = overbought zone</li>
              <li><b style='color:#00C853'>Green dashed line at 30</b> = oversold zone</li>
              <li>RSI entering/leaving these zones is the key signal.</li>
            </ul>
          </div>

          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Panel 3 — MACD</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li><b style='color:#00C853'>Green bars</b> / <b style='color:#D50000'>Red bars</b>
                  = MACD Histogram (momentum strength)</li>
              <li><b style='color:#1E88E5'>Blue line</b> = MACD line</li>
              <li><b style='color:#FFA726'>Orange line</b> = Signal line (9-day EMA of MACD)</li>
              <li>Watch where blue crosses orange — that's the crossover signal.</li>
            </ul>
          </div>

          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>EUR Conversion</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li>European stocks (.AS, .DE, .PA, etc.) are already priced in EUR — no conversion.</li>
              <li>US stocks, Bitcoin, and other USD assets are converted using the live
                  <b>EURUSD=X</b> rate from Yahoo Finance (cached 5 min).</li>
              <li>Fallback rate of 0.92 is used if Yahoo Finance is unreachable.</li>
            </ul>
          </div>

        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # ── GLOSSARY ──────────────────────────
        st.markdown("<h3 style='color:#90CAF9'>📖 Full Glossary</h3>",
                    unsafe_allow_html=True)
        st.markdown(
            "<p style='color:#aaa;font-size:13px'>Hover over any <span style='border-bottom:1px dashed #1E88E5;color:#90CAF9'>blue underlined term</span> in the app for a quick tooltip. Full definitions are listed below.</p>",
            unsafe_allow_html=True,
        )

        glossary_rows = [
            {"Term": k, "Definition": v}
            for k, v in TOOLTIPS.items()
        ]
        gl_df = pd.DataFrame(glossary_rows)
        st.dataframe(gl_df, use_container_width=True, hide_index=True,
                     column_config={"Definition": st.column_config.TextColumn(width="large")})

        st.divider()
        st.markdown("""
        <div style='background:#1A1228;border:1px solid #7B1FA2;border-radius:8px;
                    padding:14px 18px;color:#ccc;font-size:13px;line-height:1.8'>
            <b style='color:#CE93D8'>⚠️ Important Notes</b><br>
            • Technical analysis is <em>probabilistic</em>, not deterministic.
              Past signals do not guarantee future performance.<br>
            • This app uses <b>price-action only</b> — it does not factor in
              earnings, news, macro-economics, or fundamentals.<br>
            • Always combine technical signals with your own research and consult
              a qualified financial advisor before investing.
        </div>
        """, unsafe_allow_html=True)

    # ── Disclaimer ────────────────────────────
    st.divider()
    st.warning(
        "⚠️ **Disclaimer:** This tool is for informational purposes only and does not "
        "constitute financial advice. Always do your own research and consult a qualified "
        "financial advisor before making investment decisions."
    )


if __name__ == "__main__":
    main()
