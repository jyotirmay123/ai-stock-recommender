"""
AI Stock Investment Recommender
================================
Real-time technical analysis + news · BUY / HOLD / SELL signals · All prices in €
Supports EU, US, Indian (NSE) and Bitcoin with live currency conversion.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import json as _json
import warnings

BERLIN = ZoneInfo("Europe/Berlin")


def now_berlin() -> datetime:
    """Current datetime in Europe/Berlin timezone."""
    return datetime.now(BERLIN)
warnings.filterwarnings("ignore")

from portfolio_manager import (
    load_portfolio, save_portfolio,
    parse_screenshot_with_ai,
    portfolio_summary,
    generate_portfolio_recommendations,
    apply_recommendation, disapprove_recommendation,
    format_portfolio_telegram,
    _get_secret as _pf_get_secret,
)
from ai_analyst import ai_enhanced_signal, build_indicator_context

# ─────────────────────────────────────────────
# PAGE CONFIG
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

RISK_PARAMS = {
    "Conservative": {"rsi_buy": 35, "rsi_sell": 65, "min_score": 4},
    "Balanced":     {"rsi_buy": 40, "rsi_sell": 60, "min_score": 3},
    "Aggressive":   {"rsi_buy": 45, "rsi_sell": 55, "min_score": 2},
}

# ─────────────────────────────────────────────
# CURRENCY HELPERS
# ─────────────────────────────────────────────
EUR_SUFFIXES = {".AS", ".DE", ".PA", ".SW", ".BR", ".MI", ".MC",
                ".LS", ".VI", ".HE", ".CO", ".ST", ".OL"}
INR_SUFFIXES = {".NS", ".BO"}


def is_eur_symbol(symbol: str) -> bool:
    sym = symbol.upper()
    if sym.endswith("-EUR"):
        return True
    return any(sym.endswith(s) for s in EUR_SUFFIXES)


def is_inr_symbol(symbol: str) -> bool:
    return any(symbol.upper().endswith(s) for s in INR_SUFFIXES)


@st.cache_data(ttl=300)
def get_eur_rate() -> float:
    """Live USD → EUR rate."""
    try:
        return 1.0 / yf.Ticker("EURUSD=X").fast_info["last_price"]
    except Exception:
        return 0.92


@st.cache_data(ttl=300)
def get_inr_eur_rate() -> float:
    """Live INR → EUR rate."""
    try:
        rate = yf.Ticker("EURINR=X").fast_info["last_price"]  # EUR/INR ≈ 87
        return 1.0 / rate
    except Exception:
        return 1.0 / 87.5


def get_mult(symbol: str, eur_rate: float, inr_eur_rate: float) -> float:
    """Return multiplier to convert native price to EUR."""
    if is_eur_symbol(symbol):
        return 1.0
    if is_inr_symbol(symbol):
        return inr_eur_rate
    return eur_rate  # USD → EUR


# ─────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_stock_data(symbol: str, period: str = "6mo"):
    try:
        df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
        if df is None or (hasattr(df, "empty") and df.empty):
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except Exception:
        return None


@st.cache_data(ttl=120)
def yahoo_search(query: str, max_results: int = 6) -> list:
    """Fuzzy-search Yahoo Finance for matching tickers."""
    try:
        url    = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": query, "quotesCount": max_results,
                  "newsCount": 0, "enableFuzzyQuery": True}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp   = requests.get(url, params=params, headers=headers, timeout=6)
        out    = []
        for q in resp.json().get("quotes", []):
            sym = q.get("symbol", "")
            if sym:
                out.append({
                    "symbol":   sym,
                    "name":     q.get("shortname") or q.get("longname") or sym,
                    "type":     q.get("quoteType", ""),
                    "exchange": q.get("exchange", ""),
                })
        return out
    except Exception:
        return []


@st.cache_data(ttl=600)
def resolve_ticker_name(symbol: str) -> str:
    try:
        info = yf.Ticker(symbol).info
        return info.get("shortName") or info.get("longName") or symbol.upper()
    except Exception:
        return symbol.upper()


# ─────────────────────────────────────────────
# NEWS & SENTIMENT
# ─────────────────────────────────────────────
BULLISH_WORDS = {
    "upgrade", "buy", "strong", "growth", "profit", "beat", "surge",
    "rally", "gain", "positive", "outperform", "record", "rise", "expand",
    "bullish", "overweight",
}
BEARISH_WORDS = {
    "downgrade", "sell", "weak", "loss", "miss", "fall", "drop",
    "decline", "negative", "underperform", "cut", "warning", "concern",
    "bearish", "underweight",
}


@st.cache_data(ttl=1800)
def fetch_news(symbol: str) -> list:
    """Fetch up to 5 recent headlines from Yahoo Finance."""
    try:
        raw = yf.Ticker(symbol).news
        if not raw:
            return []
        articles = []
        for item in raw[:5]:
            content   = item.get("content", item)
            title     = content.get("title") or item.get("title", "")
            url       = ""
            if isinstance(content.get("canonicalUrl"), dict):
                url = content["canonicalUrl"].get("url", "")
            url       = url or item.get("link", "")
            publisher = ""
            if isinstance(content.get("provider"), dict):
                publisher = content["provider"].get("displayName", "")
            publisher = publisher or item.get("publisher", "")
            pub_date  = ""
            raw_date  = content.get("pubDate") or ""
            if raw_date:
                pub_date = str(raw_date)[:10]
            elif item.get("providerPublishTime"):
                pub_date = datetime.fromtimestamp(
                    item["providerPublishTime"]
                ).strftime("%Y-%m-%d")
            if title:
                articles.append({"title": title, "url": url,
                                  "publisher": publisher, "date": pub_date})
        return articles
    except Exception:
        return []


def news_sentiment(articles: list) -> int:
    """Return +1 positive, 0 neutral, -1 negative based on headline keywords."""
    score = 0
    for a in articles:
        t      = a.get("title", "").lower()
        score += sum(1 for w in BULLISH_WORDS if w in t)
        score -= sum(1 for w in BEARISH_WORDS if w in t)
    if score >= 2:  return  1
    if score <= -2: return -1
    return 0


# ─────────────────────────────────────────────
# PORTFOLIO LIVE PRICE HELPER
# ─────────────────────────────────────────────
@st.cache_data(ttl=120)
def get_live_prices(symbols: tuple) -> dict:
    """Fetch last trade price for each symbol. Uses fast_info for speed."""
    prices = {}
    for sym in symbols:
        try:
            prices[sym] = yf.Ticker(sym).fast_info["last_price"]
        except Exception:
            prices[sym] = None
    return prices


# ─────────────────────────────────────────────
# AI SIGNAL WRAPPER  (cached per ticker per hour)
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_ai_signal(
    symbol: str,
    name: str,
    rule_score: int,
    rule_signal: str,
    rsi_val: float | None,
    macd_status: str,
    sma20_pos: str,
    sma50_pos: str,
    bollinger_pos: str,
    volume_status: str,
    pct_chg_1m: float | None,
    pct_chg_6m: float | None,
    headlines_tuple: tuple,
) -> dict | None:
    """Streamlit-cached wrapper around ai_enhanced_signal."""
    return ai_enhanced_signal(
        symbol=symbol, name=name,
        rule_score=rule_score, rule_signal=rule_signal,
        rsi=rsi_val, macd_status=macd_status,
        sma20_pos=sma20_pos, sma50_pos=sma50_pos,
        bollinger_pos=bollinger_pos, volume_status=volume_status,
        pct_chg_1m=pct_chg_1m, pct_chg_6m=pct_chg_6m,
        news_headlines=list(headlines_tuple),
    )


# ─────────────────────────────────────────────
# EDUCATIONAL TOOLTIPS
# ─────────────────────────────────────────────
TOOLTIPS: dict = {
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
    "52W High": (
        "52-Week High: the highest closing price reached in the last 52 weeks. "
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
        "Euro (€): all prices are converted to EUR using live exchange rates "
        "fetched from Yahoo Finance."
    ),
    "USD/EUR": (
        "The current exchange rate: how many Euros you get per 1 US Dollar. "
        "Used to convert USD-priced assets (US stocks, crypto) into EUR."
    ),
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
    "News Sentiment": (
        "Keyword-based sentiment of recent news headlines. "
        "🟢 Positive: more bullish words found in headlines. "
        "🔴 Negative: more bearish words found. "
        "🟡 Neutral: mixed or no strong signals."
    ),
}

QTYPE_ICON = {
    "EQUITY": "📈", "ETF": "🗂️", "MUTUALFUND": "🏦",
    "INDEX": "📊", "CRYPTOCURRENCY": "₿", "CURRENCY": "💱",
    "FUTURE": "⏳", "OPTION": "⚙️",
}


def tip(term: str, display: str | None = None) -> str:
    """Wrap a financial term in a hover-tooltip HTML span."""
    text    = display or term
    tooltip = TOOLTIPS.get(term, "")
    if not tooltip:
        return text
    safe = tooltip.replace("'", "&#39;").replace('"', "&quot;")
    return f'<span class="tt" data-t="{safe}">{text}</span>'


TOOLTIP_CSS = """
<style>
.tt {
    border-bottom: 1px dashed #1E88E5;
    cursor: help;
    position: relative;
    display: inline-block;
    color: inherit;
}
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
.tt:hover::after, .tt:hover::before { opacity: 1; }
.sig-row {
    display: flex;
    align-items: flex-start;
    padding: 5px 0;
    border-bottom: 1px solid #1E1E2E;
    font-size: 13px;
    line-height: 1.5;
}
.sig-label { min-width: 110px; font-weight: 600; color: #90CAF9; }
.sig-value  { flex: 1; }
.pts-badge {
    font-size: 11px;
    border-radius: 10px;
    padding: 1px 7px;
    margin-left: 6px;
    font-weight: 700;
}
.pts-pos  { background: #0D3B24; color: #00E676; }
.pts-neg  { background: #3B0D0D; color: #FF5252; }
.pts-zero { background: #2A2A2A; color: #aaa; }
</style>
"""

# ─────────────────────────────────────────────
# TECHNICAL INDICATORS
# ─────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series):
    ema12  = series.ewm(span=12, adjust=False).mean()
    ema26  = series.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def compute_bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    sma   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    return sma + std * sigma, sma, sma - std * sigma


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["SMA20"]  = c.rolling(20).mean()
    df["SMA50"]  = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200).mean()
    df["EMA12"]  = c.ewm(span=12, adjust=False).mean()
    df["EMA26"]  = c.ewm(span=26, adjust=False).mean()
    df["RSI"]    = compute_rsi(c)
    df["MACD"], df["MACD_Signal"], df["MACD_Hist"] = compute_macd(c)
    df["BB_Upper"], df["BB_Mid"], df["BB_Lower"]   = compute_bollinger(c)
    df["Volume_MA20"] = df["Volume"].rolling(20).mean()
    return df


# ─────────────────────────────────────────────
# SCORING ENGINE  (max ±10 pts)
# ─────────────────────────────────────────────
def score_stock(df: pd.DataFrame, risk: str) -> dict:
    params = RISK_PARAMS[risk]
    last   = df.iloc[-1]
    prev   = df.iloc[-2] if len(df) > 1 else last
    signals, score = {}, 0

    # 1 — RSI
    rsi = last.get("RSI", np.nan)
    if pd.notna(rsi):
        if rsi < params["rsi_buy"]:
            signals["RSI"] = ("🟢 Oversold", +2);    score += 2
        elif rsi > params["rsi_sell"]:
            signals["RSI"] = ("🔴 Overbought", -2);  score -= 2
        else:
            signals["RSI"] = ("🟡 Neutral", 0)

    # 2 — MACD crossover
    macd,   sig   = last.get("MACD", np.nan),  last.get("MACD_Signal", np.nan)
    p_macd, p_sig = prev.get("MACD", np.nan),  prev.get("MACD_Signal", np.nan)
    if all(pd.notna(x) for x in [macd, sig, p_macd, p_sig]):
        if p_macd < p_sig and macd > sig:
            signals["MACD"] = ("🟢 Bullish crossover", +2); score += 2
        elif p_macd > p_sig and macd < sig:
            signals["MACD"] = ("🔴 Bearish crossover", -2); score -= 2
        elif macd > sig:
            signals["MACD"] = ("🟢 Above signal", +1);      score += 1
        else:
            signals["MACD"] = ("🔴 Below signal", -1);      score -= 1

    # 3 — Price vs SMA 20 / 50
    close = last["Close"]
    sma20, sma50, sma200 = (
        last.get("SMA20",  np.nan),
        last.get("SMA50",  np.nan),
        last.get("SMA200", np.nan),
    )
    if pd.notna(sma20):
        if close > sma20:
            signals["SMA20"] = ("🟢 Above SMA20", +1); score += 1
        else:
            signals["SMA20"] = ("🔴 Below SMA20", -1); score -= 1
    if pd.notna(sma50):
        if close > sma50:
            signals["SMA50"] = ("🟢 Above SMA50", +1); score += 1
        else:
            signals["SMA50"] = ("🔴 Below SMA50", -1); score -= 1

    # 4 — Golden / Death Cross (SMA50 vs SMA200)
    p_sma50, p_sma200 = prev.get("SMA50", np.nan), prev.get("SMA200", np.nan)
    if all(pd.notna(x) for x in [sma50, sma200, p_sma50, p_sma200]):
        if p_sma50 < p_sma200 and sma50 > sma200:
            signals["Golden Cross"] = ("🟢 Golden Cross!", +2); score += 2
        elif p_sma50 > p_sma200 and sma50 < sma200:
            signals["Death Cross"]  = ("🔴 Death Cross!", -2);  score -= 2

    # 5 — Bollinger Bands
    bb_up, bb_low = last.get("BB_Upper", np.nan), last.get("BB_Lower", np.nan)
    if pd.notna(bb_up) and pd.notna(bb_low):
        if close < bb_low:
            signals["Bollinger"] = ("🟢 Below lower band", +1); score += 1
        elif close > bb_up:
            signals["Bollinger"] = ("🔴 Above upper band", -1); score -= 1
        else:
            signals["Bollinger"] = ("🟡 Inside bands", 0)

    # 6 — Volume confirmation
    vol, vol_ma = last.get("Volume", np.nan), last.get("Volume_MA20", np.nan)
    if pd.notna(vol) and pd.notna(vol_ma) and vol_ma > 0:
        if vol > vol_ma * 1.5:
            signals["Volume"] = ("🟢 High volume", +1); score += 1
        else:
            signals["Volume"] = ("🟡 Normal volume", 0)

    pct = score / 10
    if pct >= 0.3:
        rec, rec_color, rec_emoji = "BUY",  "#00C853", "🟢"
    elif pct <= -0.2:
        rec, rec_color, rec_emoji = "SELL", "#D50000", "🔴"
    else:
        rec, rec_color, rec_emoji = "HOLD", "#FF6F00", "🟡"

    high52     = df["Close"].tail(252).max()
    low52      = df["Close"].tail(252).min()
    pct_chg_1m = (close / df["Close"].iloc[-22] - 1) * 100 if len(df) >= 22 else np.nan
    pct_chg_6m = (close / df["Close"].iloc[0]   - 1) * 100

    return dict(
        score=score, recommendation=rec, rec_color=rec_color, rec_emoji=rec_emoji,
        signals=signals, rsi=rsi, close=close,
        high52=high52, low52=low52, pct_chg_1m=pct_chg_1m, pct_chg_6m=pct_chg_6m,
    )


def build_result(sym: str, name: str, market: str, df: pd.DataFrame,
                 eur_rate: float, inr_eur_rate: float, risk: str) -> dict:
    s    = score_stock(df, risk)
    mult = get_mult(sym, eur_rate, inr_eur_rate)
    return dict(
        symbol=sym, name=name, market=market, df=df, mult=mult,
        price_eur      = s["close"]  * mult,
        recommendation = s["recommendation"],
        rec_emoji      = s["rec_emoji"],
        rec_color      = s["rec_color"],
        score          = s["score"],
        rsi            = s["rsi"],
        high52         = s["high52"] * mult,
        low52          = s["low52"]  * mult,
        pct_chg_1m     = s["pct_chg_1m"],
        pct_chg_6m     = s["pct_chg_6m"],
        signals        = s["signals"],
    )


# ─────────────────────────────────────────────
# CHART  — visible SMA200, clean layout, no overlap
# ─────────────────────────────────────────────
def build_chart(df: pd.DataFrame, symbol: str, name: str, mult: float) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.22, 0.23],
        vertical_spacing=0.07,
    )

    # ── Panel 1: Candlestick ─────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open =df["Open"]  * mult, high=df["High"]  * mult,
        low  =df["Low"]   * mult, close=df["Close"] * mult,
        name="Price",
        increasing_line_color="#26A69A",
        decreasing_line_color="#EF5350",
        showlegend=False,
    ), row=1, col=1)

    # ── Moving averages (SMA200 = thick purple, always distinct) ──
    for label, col, color, width in [
        ("SMA 20",  "SMA20",  "#42A5F5", 1.2),
        ("SMA 50",  "SMA50",  "#FFA726", 1.2),
        ("SMA 200", "SMA200", "#CE93D8", 2.2),   # thick purple — clearly visible
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col] * mult,
                name=label, line=dict(color=color, width=width),
                opacity=0.9,
            ), row=1, col=1)

    # ── Bollinger Bands: shaded channel, not cluttered lines ──────
    if "BB_Upper" in df.columns and "BB_Lower" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"] * mult,
            name="BB ±2σ",
            line=dict(color="#78909C", dash="dot", width=1),
            opacity=0.6,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"] * mult,
            line=dict(color="#78909C", dash="dot", width=1),
            fill="tonexty", fillcolor="rgba(120,144,156,0.07)",
            opacity=0.6, showlegend=False,
        ), row=1, col=1)

    # ── Panel 2: RSI ─────────────────────────
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"],
            name="RSI", line=dict(color="#26C6DA", width=1.5),
            showlegend=False,
        ), row=2, col=1)
        for lvl, clr in [
            (70, "rgba(239,83,80,0.45)"),
            (50, "rgba(160,160,160,0.2)"),
            (30, "rgba(38,166,154,0.45)"),
        ]:
            fig.add_hline(y=lvl, line_dash="dot", line_color=clr, row=2, col=1)

    # ── Panel 3: MACD ────────────────────────
    if "MACD_Hist" in df.columns:
        hist_colors = ["#26A69A" if v >= 0 else "#EF5350"
                       for v in df["MACD_Hist"].fillna(0)]
        fig.add_trace(go.Bar(
            x=df.index, y=df["MACD_Hist"],
            name="Hist", marker_color=hist_colors, opacity=0.55,
            showlegend=False,
        ), row=3, col=1)
    if "MACD" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"],
            name="MACD", line=dict(color="#42A5F5", width=1.3),
            showlegend=False,
        ), row=3, col=1)
    if "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"],
            name="Signal", line=dict(color="#FFA726", width=1.3),
            showlegend=False,
        ), row=3, col=1)

    # ── Layout ───────────────────────────────
    fig.update_layout(
        height=660,
        template="plotly_dark",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h",
            yanchor="top", y=1.01,
            xanchor="left", x=0,
            font=dict(size=11),
            bgcolor="rgba(14,17,23,0.7)",
            bordercolor="rgba(255,255,255,0.08)",
            borderwidth=1,
        ),
        margin=dict(l=10, r=10, t=8, b=8),
        hoverlabel=dict(bgcolor="#1A1F36", font_size=12),
    )
    fig.update_yaxes(
        tickprefix="€", tickformat=",.0f",
        gridcolor="rgba(255,255,255,0.05)", row=1, col=1,
    )
    fig.update_yaxes(
        title_text="RSI", title_standoff=4,
        title_font=dict(size=10, color="#888"),
        range=[0, 100],
        gridcolor="rgba(255,255,255,0.05)", row=2, col=1,
    )
    fig.update_yaxes(
        title_text="MACD", title_standoff=4,
        title_font=dict(size=10, color="#888"),
        gridcolor="rgba(255,255,255,0.05)", row=3, col=1,
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.04)")
    return fig


# ─────────────────────────────────────────────
# DEEP-DIVE RENDERER
# ─────────────────────────────────────────────
def render_deep_dive(r: dict, key_prefix: str = ""):
    """Render signal panel + fixed chart + news + AI insight for one result."""
    # Fetch news early so headlines are available for AI analysis
    news = fetch_news(r["symbol"])
    headlines = [a["title"] for a in news if a.get("title")]

    sig_col, chart_col = st.columns([1, 3])

    with sig_col:
        rows_html = ""
        for indicator, (label, pts) in r["signals"].items():
            badge_cls = "pts-pos" if pts > 0 else ("pts-neg" if pts < 0 else "pts-zero")
            rows_html += (
                f"<div class='sig-row'>"
                f"  <span class='sig-label'>{tip(indicator)}</span>"
                f"  <span class='sig-value'>{label}"
                f"    <span class='pts-badge {badge_cls}'>{pts:+d}</span>"
                f"  </span>"
                f"</div>"
            )
        st.markdown(
            f"<p style='font-weight:600;color:#90CAF9;margin-bottom:6px'>📡 Technical Signals</p>"
            f"{rows_html}"
            f"<div style='margin-top:12px;font-size:13px'>"
            f"  {tip('Score', '📊 Score')}: "
            f"  <b style='color:{r['rec_color']};font-size:16px'>{r['score']:+d}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<h3 style='color:{r['rec_color']};margin-top:8px'>"
            f"  {r['rec_emoji']} {tip(r['recommendation'])}</h3>",
            unsafe_allow_html=True,
        )
        st.metric("Current Price (€)", f"€{r['price_eur']:,.2f}", help=TOOLTIPS["EUR"])
        if pd.notna(r["pct_chg_1m"]):
            st.metric("1M Return", f"{r['pct_chg_1m']:+.2f}%", help=TOOLTIPS["1M Change"])
        st.metric("6M Return", f"{r['pct_chg_6m']:+.2f}%",  help=TOOLTIPS["6M Change"])
        st.metric("52W High",  f"€{r['high52']:,.2f}",       help=TOOLTIPS["52W High"])
        st.metric("52W Low",   f"€{r['low52']:,.2f}",        help=TOOLTIPS["52W Low"])

        # ── AI-Enhanced Analysis ──────────────
        ind_ctx = build_indicator_context(r["signals"])
        rsi_val = float(r["rsi"]) if pd.notna(r["rsi"]) else None
        p1m     = float(r["pct_chg_1m"]) if pd.notna(r["pct_chg_1m"]) else None
        p6m     = float(r["pct_chg_6m"]) if pd.notna(r["pct_chg_6m"]) else None

        ai = get_ai_signal(
            symbol        = r["symbol"],
            name          = r["name"],
            rule_score    = r["score"],
            rule_signal   = r["recommendation"],
            rsi_val       = rsi_val,
            macd_status   = ind_ctx["macd_status"],
            sma20_pos     = ind_ctx["sma20_pos"],
            sma50_pos     = ind_ctx["sma50_pos"],
            bollinger_pos = ind_ctx["bollinger_pos"],
            volume_status = ind_ctx["volume_status"],
            pct_chg_1m    = p1m,
            pct_chg_6m    = p6m,
            headlines_tuple = tuple(headlines),
        )
        if ai:
            sig_color  = {"BUY": "#00C853", "SELL": "#FF5252", "HOLD": "#FFB74D"}.get(
                ai["signal"], "#aaa"
            )
            sig_emoji  = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(ai["signal"], "")
            conf_bar   = int(ai["confidence"])
            conf_color = (
                "#00C853" if conf_bar >= 70
                else ("#FFB74D" if conf_bar >= 45 else "#FF5252")
            )
            st.markdown(
                f"<div style='margin-top:14px;background:#0D1B2A;border:1px solid #1E88E5;"
                f"border-radius:8px;padding:12px;'>"
                f"<p style='font-size:11px;color:#90CAF9;font-weight:600;margin:0 0 6px'>🤖 AI Analysis</p>"
                f"<div style='font-size:15px;font-weight:700;color:{sig_color}'>"
                f"  {sig_emoji} {ai['signal']}"
                f"  <span style='font-size:11px;color:{conf_color};margin-left:6px'>"
                f"  {conf_bar}% confidence</span>"
                f"</div>"
                f"<p style='font-size:11px;color:#ccc;margin:8px 0 4px;line-height:1.5'>"
                f"{ai['reasoning']}</p>"
                f"<p style='font-size:9px;color:#555;margin:0'>via {ai.get('provider','AI')}</p>"
                f"</div>",
                unsafe_allow_html=True,
            )

    with chart_col:
        fig = build_chart(r["df"], r["symbol"], r["name"], r["mult"])
        st.plotly_chart(fig, use_container_width=True,
                        key=f"chart_{key_prefix}{r['symbol']}")

    # ── Latest news ──────────────────────────
    if news:
        sent       = news_sentiment(news)
        sent_label = ("🟢 Positive" if sent > 0
                      else ("🔴 Negative" if sent < 0 else "🟡 Neutral"))
        with st.expander(f"📰 Latest News  ·  Sentiment: {sent_label}", expanded=False):
            for a in news:
                meta = " · ".join(filter(None, [a.get("publisher"), a.get("date")]))
                line = f"• [{a['title']}]({a['url']})" if a["url"] else f"• {a['title']}"
                if meta:
                    line += f"\n  *{meta}*"
                st.markdown(line)
    else:
        st.caption("📰 No recent news available for this ticker.")


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
def send_telegram_message(text: str) -> bool:
    """POST a message to the configured Telegram bot."""
    try:
        token   = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID",   "")
    except Exception:
        return False
    if not token or not chat_id:
        return False
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.ok
    except Exception:
        return False


def format_telegram_picks(results_by_market: dict) -> str:
    lines = [
        "📈 <b>AI Stock Recommender — Top BUY Picks</b>",
        f"📅 {now_berlin().strftime('%Y-%m-%d %H:%M')} Berlin",
        "",
    ]
    for market, mkt_results in results_by_market.items():
        buys = sorted(
            [r for r in mkt_results if r["recommendation"] == "BUY"],
            key=lambda x: x["score"], reverse=True,
        )
        lines.append(f"<b>{market}</b>")
        if buys:
            for r in buys[:5]:
                rsi_str = f"{r['rsi']:.0f}" if pd.notna(r["rsi"]) else "—"
                lines.append(
                    f"  • <code>{r['symbol']}</code> {r['name']}"
                    f" — €{r['price_eur']:,.2f}"
                    f" | Score: {r['score']:+d} | RSI: {rsi_str}"
                )
        else:
            lines.append("  • No BUY signals at this time")
        lines.append("")

    # ── Tracked buys that are now showing SELL signals ────────────────────
    try:
        tracked = load_portfolio().get("tracked_buys", {})
    except Exception:
        tracked = {}

    # Flatten all results into a quick lookup by symbol
    all_results: dict = {}
    for mkt_results in results_by_market.values():
        for r in mkt_results:
            all_results[r["symbol"]] = r

    sell_alerts: dict = {}
    for sym, info in tracked.items():
        if sym not in all_results:
            continue
        r = all_results[sym]
        if r["recommendation"] != "SELL":
            continue
        market = info.get("market", "Other")
        sell_alerts.setdefault(market, [])
        price_then = info.get("price_at_recommendation") or 0
        price_now  = r["price_eur"]
        pct_str    = f"{(price_now - price_then) / price_then * 100:+.1f}%" if price_then else "—"
        rsi_str    = f"{r['rsi']:.0f}" if pd.notna(r["rsi"]) else "—"
        cons_days  = info.get("consecutive_sell_days", 0)
        sell_alerts[market].append({
            "symbol":    sym,
            "name":      info["name"],
            "score":     r["score"],
            "rsi":       rsi_str,
            "eur":       price_now,
            "pct":       pct_str,
            "first_rec": info.get("first_recommended", "?"),
            "cons_days": cons_days,
        })

    if sell_alerts:
        lines.append("🔔 <b>Tracked Buys — Now Showing SELL Signal</b>")
        for market in results_by_market:
            alerts = sell_alerts.get(market, [])
            if not alerts:
                continue
            lines.append(f"<b>{market}</b>")
            for a in alerts:
                day_note = f"  (sell day {a['cons_days']})" if a["cons_days"] else ""
                lines.append(
                    f"  🔴 <code>{a['symbol']}</code> {a['name']}"
                    f" — €{a['eur']:,.2f}"
                    f" | Score: {a['score']:+d} | RSI: {a['rsi']}"
                    f" | Since rec: {a['pct']}{day_note}"
                )
            lines.append("")

    lines.append("⚠️ <i>For informational purposes only. Not financial advice.</i>")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# AUTHENTICATION
# ─────────────────────────────────────────────
def check_auth():
    """Password-gate the app. Open access if APP_PASSWORD is not configured."""
    try:
        app_pwd = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        app_pwd = ""  # no secrets file → dev mode, open access

    if not app_pwd:
        return
    if st.session_state.get("authenticated"):
        return

    st.markdown("""
    <div style='max-width:400px;margin:80px auto;padding:36px;
                background:#1A1F36;border:1px solid #1E88E5;
                border-radius:12px;text-align:center;'>
        <div style='font-size:48px'>🔒</div>
        <h2 style='color:#1E88E5;margin:12px 0 4px'>Secure Access</h2>
        <p style='color:#aaa;font-size:13px;margin:0'>
            Enter your password to access the analyser.
        </p>
    </div>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        pwd = st.text_input(
            "Password", type="password",
            key="auth_input", label_visibility="collapsed",
            placeholder="Enter password…",
        )
        if st.button("Sign In →", use_container_width=True, type="primary"):
            if pwd == app_pwd:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()


# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────
def main():
    check_auth()

    # ── Sidebar ──────────────────────────────
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/combo-chart.png", width=64)
        st.title("⚙️ Settings")

        risk = st.selectbox(
            "Risk Profile", ["Conservative", "Balanced", "Aggressive"],
            index=1, help=TOOLTIPS["Risk Profile"],
        )
        period = st.selectbox(
            "Analysis Period", ["3mo", "6mo", "1y", "2y"], index=1,
        )
        selected_markets = st.multiselect(
            "Markets", list(STOCKS.keys()), default=list(STOCKS.keys()),
        )

        refresh = st.button("🔄 Refresh Data", use_container_width=True)
        if refresh:
            st.cache_data.clear()
            st.rerun()

        # ── Telegram ─────────────────────────
        st.divider()
        try:
            tg_token   = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
            tg_chat_id = st.secrets.get("TELEGRAM_CHAT_ID",   "")
        except Exception:
            tg_token = tg_chat_id = ""

        if tg_token and tg_chat_id:
            if st.button("📨 Send Watchlist Picks to Telegram", use_container_width=True):
                st.session_state["trigger_telegram"] = True
            if st.button("💼 Send Portfolio Report to Telegram", use_container_width=True):
                st.session_state["trigger_portfolio_telegram"] = True
        else:
            with st.expander("📨 Telegram Setup"):
                st.markdown("""
**To enable Telegram alerts:**

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy your token.
2. Start your bot, then open:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   and copy your `chat_id`.
3. Add to `.streamlit/secrets.toml`:
```toml
TELEGRAM_BOT_TOKEN = "your_token"
TELEGRAM_CHAT_ID   = "your_chat_id"
```
                """)

        st.divider()
        st.caption(f"Last updated: {now_berlin().strftime('%Y-%m-%d %H:%M')} Berlin")
        st.caption("Data: Yahoo Finance · Prices in EUR")

    # ── Global CSS ───────────────────────────
    st.markdown(TOOLTIP_CSS, unsafe_allow_html=True)

    # ── Header ───────────────────────────────
    st.markdown("""
    <h1 style='text-align:center;color:#1E88E5;'>
        📈 AI Stock Investment Recommender
    </h1>
    <p style='text-align:center;color:#888;margin-top:-10px;'>
        Real-time technical analysis · Buy / Hold / Sell signals · News · Prices in €
    </p>
    """, unsafe_allow_html=True)
    st.divider()

    eur_rate     = get_eur_rate()
    inr_eur_rate = get_inr_eur_rate()

    st.markdown(
        f"<span style='font-size:12px;color:#888'>"
        f"💱 {tip('USD/EUR', '1 USD = €' + str(round(eur_rate, 4)))}"
        f"</span>",
        unsafe_allow_html=True,
    )

    # ── Portfolio session state (load once) ──
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = load_portfolio()
    if "pf_recs" not in st.session_state:
        st.session_state.pf_recs = []
    if "pf_approving" not in st.session_state:
        st.session_state.pf_approving = None  # rec id currently showing approval form

    # ── Tabs ─────────────────────────────────
    tab_watch, tab_search, tab_portfolio, tab_learn = st.tabs([
        "📋 Market Watchlist",
        "🔍 Search Any Ticker",
        "💼 My Portfolio",
        "📚 How It Works",
    ])

    # ══════════════════════════════════════════
    # TAB 1 — MARKET WATCHLIST
    # ══════════════════════════════════════════
    with tab_watch:
        all_tickers = {}
        for market in selected_markets:
            for sym, name in STOCKS[market].items():
                all_tickers[sym] = {"name": name, "market": market}

        if not all_tickers:
            st.info("Select at least one market in the sidebar.")
        else:
            failed_tickers = []
            with st.spinner("🔍 Fetching live data and running analysis…"):
                results = []
                for sym, meta in all_tickers.items():
                    df = fetch_stock_data(sym, period)
                    if df is None or len(df) < 30:
                        failed_tickers.append(sym)
                        continue
                    df = add_indicators(df)
                    results.append(
                        build_result(sym, meta["name"], meta["market"],
                                     df, eur_rate, inr_eur_rate, risk)
                    )

            # ── Telegram trigger ─────────────
            if st.session_state.pop("trigger_telegram", False):
                rbm = {m: [r for r in results if r["market"] == m]
                       for m in selected_markets}
                msg = format_telegram_picks(rbm)
                if send_telegram_message(msg):
                    st.success("✅ Top picks sent to Telegram!")
                else:
                    st.error("❌ Telegram failed — check token and chat_id in secrets.toml.")

            if st.session_state.pop("trigger_portfolio_telegram", False):
                pf      = st.session_state.get("portfolio", {})
                pf_recs = st.session_state.get("pf_recs", [])
                msg     = format_portfolio_telegram(pf, pf_recs, inr_eur_rate)
                if send_telegram_message(msg):
                    st.success("✅ Portfolio report sent to Telegram!")
                else:
                    st.error("❌ Telegram failed — check token and chat_id in secrets.toml.")

            if not results:
                st.error("⚠️ No data retrieved. Check internet connection and refresh.")
            else:
                if failed_tickers:
                    st.warning(f"⚠️ Could not fetch: {', '.join(failed_tickers)}")

                # ── KPI row ──────────────────
                buys  = [r for r in results if r["recommendation"] == "BUY"]
                holds = [r for r in results if r["recommendation"] == "HOLD"]
                sells = [r for r in results if r["recommendation"] == "SELL"]
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("📊 Stocks Analysed", len(results))
                k2.metric("🟢 BUY Signals",  len(buys),  help=TOOLTIPS["BUY"])
                k3.metric("🟡 HOLD Signals", len(holds), help=TOOLTIPS["HOLD"])
                k4.metric("🔴 SELL Signals", len(sells), help=TOOLTIPS["SELL"])
                st.divider()

                # ── Top BUY Picks per Market ─
                st.subheader("⭐ Top BUY Picks by Market")
                st.caption("⭐ = strong signal (score ≥ 5)  ·  ✅ = BUY signal  ·  Up to 5 per market")

                results_by_market = {
                    m: [r for r in results if r["market"] == m]
                    for m in selected_markets
                }
                num_cols     = min(len(selected_markets), 4)
                market_cols  = st.columns(num_cols) if num_cols > 0 else []

                for col_idx, market in enumerate(selected_markets):
                    mkt_buys = sorted(
                        [r for r in results_by_market.get(market, [])
                         if r["recommendation"] == "BUY"],
                        key=lambda x: x["score"], reverse=True,
                    )[:5]

                    with market_cols[col_idx % num_cols]:
                        st.markdown(
                            f"<h4 style='color:#90CAF9;margin-bottom:6px'>{market}</h4>",
                            unsafe_allow_html=True,
                        )
                        if mkt_buys:
                            for r in mkt_buys:
                                star    = "⭐" if r["score"] >= 5 else "✅"
                                rsi_str = f"{r['rsi']:.0f}" if pd.notna(r["rsi"]) else "—"
                                chg_str = (f"{r['pct_chg_1m']:+.1f}%"
                                           if pd.notna(r["pct_chg_1m"]) else "—")
                                chg_col = ("#00C853"
                                           if (pd.notna(r["pct_chg_1m"])
                                               and r["pct_chg_1m"] > 0)
                                           else "#FF5252")
                                st.markdown(f"""
                                <div style='background:#091A0F;border:1px solid #1B5E20;
                                            border-radius:8px;padding:10px 12px;
                                            margin-bottom:6px;'>
                                    <div style='font-size:11px;color:#aaa'>
                                        {r["symbol"]} &nbsp;{star}
                                    </div>
                                    <div style='font-size:13px;font-weight:700;color:white'>
                                        {r["name"]}
                                    </div>
                                    <div style='font-size:19px;font-weight:700;color:white'>
                                        €{r["price_eur"]:,.2f}
                                    </div>
                                    <div style='font-size:11px;color:#aaa;margin-top:3px'>
                                        Score: <b style='color:#00C853'>{r["score"]:+d}</b>
                                        &nbsp;·&nbsp;RSI: {rsi_str}
                                        &nbsp;·&nbsp;1M: <b style='color:{chg_col}'>{chg_str}</b>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                        else:
                            st.markdown(
                                "<div style='color:#555;font-size:13px;padding:8px 0'>"
                                "No BUY signals at this time.</div>",
                                unsafe_allow_html=True,
                            )

                st.divider()

                # ── Tracked Buys — Live Signal Status ───────
                tracked_pf   = load_portfolio()
                tracked_buys = tracked_pf.get("tracked_buys", {})

                if tracked_buys:
                    st.subheader("🎯 Tracked Buy Recommendations — Live Signals")
                    st.caption(
                        "Tickers previously recommended as top BUY picks. "
                        "Auto-removed after 3 consecutive SELL days."
                    )

                    # Quick lookup from already-fetched results
                    results_by_sym = {r["symbol"]: r for r in results}

                    # Fetch any tracked ticker whose market wasn't selected
                    for sym, info in tracked_buys.items():
                        if sym not in results_by_sym:
                            df_t = fetch_stock_data(sym, period)
                            if df_t is not None and len(df_t) >= 30:
                                df_t = add_indicators(df_t)
                                results_by_sym[sym] = build_result(
                                    sym, info["name"], info.get("market", "Other"),
                                    df_t, eur_rate, inr_eur_rate, risk,
                                )

                    # Auto-remove tickers with 3+ consecutive SELL days
                    to_drop = [
                        sym for sym, info in tracked_buys.items()
                        if info.get("consecutive_sell_days", 0) >= 3
                    ]
                    if to_drop:
                        for sym in to_drop:
                            del tracked_pf["tracked_buys"][sym]
                            del tracked_buys[sym]
                        save_portfolio(tracked_pf)
                        st.session_state.portfolio = tracked_pf
                        st.toast(
                            f"Removed {', '.join(to_drop)} after 3 consecutive SELL days.",
                            icon="🗑️",
                        )

                    if tracked_buys:
                        num_tracked = len(tracked_buys)
                        t_cols = st.columns(min(num_tracked, 4))
                        for idx, (sym, info) in enumerate(tracked_buys.items()):
                            r = results_by_sym.get(sym)
                            with t_cols[idx % min(num_tracked, 4)]:
                                if r:
                                    rec = r["recommendation"]
                                    if rec == "BUY":
                                        border_col, bg_col, rec_col = "#1B5E20", "#091A0F", "#00C853"
                                    elif rec == "SELL":
                                        border_col, bg_col, rec_col = "#B71C1C", "#1A0909", "#FF5252"
                                    else:
                                        border_col, bg_col, rec_col = "#FF9800", "#191200", "#FFB74D"
                                    rec_emoji  = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(rec, "")
                                    rsi_str    = f"{r['rsi']:.0f}" if pd.notna(r["rsi"]) else "—"
                                    price_then = info.get("price_at_recommendation") or 0
                                    price_now  = r["price_eur"]
                                    if price_then:
                                        pct_val = (price_now - price_then) / price_then * 100
                                        pct_str = f"{pct_val:+.1f}%"
                                        pct_col = "#00C853" if pct_val >= 0 else "#FF5252"
                                    else:
                                        pct_str = "no entry price"
                                        pct_col = "#666"
                                    cons_days  = info.get("consecutive_sell_days", 0)
                                    sell_note  = (
                                        f"<br><span style='color:#FF5252;font-size:10px'>⚠️ SELL day {cons_days}/3 — auto-removes at 3</span>"
                                        if cons_days > 0 else ""
                                    )
                                    first_rec  = info.get("first_recommended", "?")
                                    card = (
                                        f"<div style='background:{bg_col};border:1px solid {border_col};"
                                        f"border-radius:8px;padding:12px;margin-bottom:8px;min-height:148px;'>"
                                        f"<div style='font-size:10px;color:#777'>{sym} &nbsp;·&nbsp; since {first_rec}</div>"
                                        f"<div style='font-size:14px;font-weight:700;color:white;margin-top:3px'>{info['name']}</div>"
                                        f"<div style='font-size:22px;font-weight:700;color:white;margin:4px 0'>€{price_now:,.2f}</div>"
                                        f"<div style='display:inline-block;background:{border_col};color:white;"
                                        f"font-size:12px;font-weight:700;padding:2px 8px;border-radius:4px;margin-bottom:6px'>"
                                        f"{rec_emoji} {rec}</div>"
                                        f"<div style='font-size:11px;color:#aaa;border-top:1px solid {border_col};padding-top:6px;margin-top:2px'>"
                                        f"Score: <b style='color:{rec_col}'>{r['score']:+d}</b>"
                                        f" &nbsp;·&nbsp; RSI: {rsi_str}"
                                        f" &nbsp;·&nbsp; P/L: <span style='color:{pct_col}'>{pct_str}</span>"
                                        f"{sell_note}</div></div>"
                                    )
                                    st.markdown(card, unsafe_allow_html=True)
                                else:
                                    card = (
                                        f"<div style='background:#111;border:1px solid #333;"
                                        f"border-radius:8px;padding:12px;margin-bottom:8px;min-height:148px;'>"
                                        f"<div style='font-size:10px;color:#777'>{sym}</div>"
                                        f"<div style='font-size:14px;font-weight:700;color:white;margin-top:3px'>{info['name']}</div>"
                                        f"<div style='font-size:12px;color:#555;margin-top:8px'>Data unavailable</div>"
                                        f"</div>"
                                    )
                                    st.markdown(card, unsafe_allow_html=True)
                    else:
                        st.info(
                            "All tracked picks have been removed after 3 consecutive SELL days. "
                            "New buys will appear here when recommended."
                        )

                    st.divider()

                # ── Full summary table ───────
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
                        .map(color_signal, subset=["Signal"])
                        .map(color_change, subset=["1M Change", "6M Change"]),
                    use_container_width=True, hide_index=True,
                )
                st.divider()

                # ── Individual deep dive ─────
                st.subheader("🔍 Individual Deep Dive")
                symbol_options = {
                    f"{r['rec_emoji']} {r['name']} ({r['symbol']})": r
                    for r in results
                }
                chosen = symbol_options[
                    st.selectbox("Select a stock:",
                                 list(symbol_options.keys()), key="watchlist_select")
                ]
                render_deep_dive(chosen)

    # ══════════════════════════════════════════
    # TAB 2 — SEARCH ANY TICKER
    # ══════════════════════════════════════════
    with tab_search:
        st.markdown(
            "<p style='color:#aaa;margin-bottom:6px'>"
            "Search <b>any</b> global ticker — stocks, ETFs, indices, crypto, forex, futures.<br>"
            "Type a <b>ticker</b> (e.g. <code>AAPL</code>) "
            "<b>or a company name</b> (e.g. <code>toyota</code>) "
            "and the app will find the right symbol for you."
            "</p>",
            unsafe_allow_html=True,
        )

        # ── Session state ─────────────────────
        for k, v in [("sx_results", []), ("sx_sug_map", {}), ("sx_no_sug", []),
                     ("sx_has_state", False), ("sx_chip_sym", None)]:
            if k not in st.session_state:
                st.session_state[k] = v

        search_col, btn_col = st.columns([4, 1])
        with search_col:
            raw_input = st.text_input(
                "Ticker",
                placeholder="e.g.  AAPL  ·  toyota  ·  BTC-EUR  ·  RELIANCE.NS  ·  gold",
                label_visibility="collapsed",
                key="ticker_search_input",
            )
        with btn_col:
            search_clicked = st.button("🔍 Analyse", use_container_width=True, key="search_btn")

        if st.session_state.sx_chip_sym:
            active_query = st.session_state.sx_chip_sym
            st.session_state.sx_chip_sym = None
            run_analysis = True
        elif search_clicked and raw_input.strip():
            active_query = raw_input.strip()
            run_analysis = True
        elif search_clicked:
            st.warning("Please enter a ticker symbol or company name.")
            active_query = ""; run_analysis = False
        else:
            active_query = ""; run_analysis = False

        if run_analysis:
            tokens = [t.strip().upper()
                      for t in active_query.replace(",", " ").split() if t.strip()]
            results_tmp, errors_tmp, sug_tmp = [], [], {}
            with st.spinner(f"Analysing: {', '.join(tokens)}…"):
                for token in tokens:
                    df = fetch_stock_data(token, period)
                    if df is not None and len(df) >= 10:
                        df   = add_indicators(df)
                        name = resolve_ticker_name(token)
                        results_tmp.append(
                            build_result(token, name, "Custom Search",
                                         df, eur_rate, inr_eur_rate, risk)
                        )
                    else:
                        errors_tmp.append(token)
                        sugs = yahoo_search(token)
                        if sugs:
                            sug_tmp[token] = sugs

            st.session_state.sx_results   = results_tmp
            st.session_state.sx_sug_map   = sug_tmp
            st.session_state.sx_no_sug    = [s for s in errors_tmp if s not in sug_tmp]
            st.session_state.sx_has_state = True

        if st.session_state.sx_has_state:
            for bad_sym, suggestions in st.session_state.sx_sug_map.items():
                st.markdown(
                    f"<div style='background:#1A1228;border:1px solid #7B1FA2;"
                    f"border-radius:8px;padding:12px 16px;margin-bottom:10px;'>"
                    f"<b style='color:#CE93D8'>❓ Could not find <code>{bad_sym}</code>"
                    f" — did you mean one of these?</b><br>"
                    f"<span style='font-size:12px;color:#aaa'>"
                    f"Click a chip to analyse that ticker instantly.</span></div>",
                    unsafe_allow_html=True,
                )
                chip_cols = st.columns(min(len(suggestions), 3))
                for i, sug in enumerate(suggestions):
                    icon  = QTYPE_ICON.get(sug["type"].upper(), "📌")
                    label = f"{icon} {sug['symbol']}  —  {sug['name'][:28]}"
                    if sug["exchange"]:
                        label += f"  [{sug['exchange']}]"
                    with chip_cols[i % len(chip_cols)]:
                        if st.button(label, key=f"sug_{bad_sym}_{sug['symbol']}",
                                     use_container_width=True):
                            st.session_state.sx_chip_sym  = sug["symbol"]
                            st.session_state.sx_has_state = False
                            st.rerun()

            if st.session_state.sx_no_sug:
                st.error(
                    f"❌ No data or suggestions for: "
                    f"**{', '.join(st.session_state.sx_no_sug)}**. "
                    "Verify on [finance.yahoo.com](https://finance.yahoo.com)."
                )

            if st.session_state.sx_results:
                cols = st.columns(min(len(st.session_state.sx_results), 3))
                for i, r in enumerate(st.session_state.sx_results):
                    with cols[i % len(cols)]:
                        bg     = "#0E2A1E" if r["recommendation"] == "BUY"  else \
                                 "#2A0E0E" if r["recommendation"] == "SELL" else "#1A1A0E"
                        chg_1m_str = (f"{r['pct_chg_1m']:+.1f}%"
                                      if pd.notna(r["pct_chg_1m"]) else "—")
                        chg_col    = ("#00C853"
                                      if (pd.notna(r["pct_chg_1m"]) and r["pct_chg_1m"] > 0)
                                      else "#FF5252")
                        st.markdown(f"""
                        <div style='background:{bg};border:1px solid {r["rec_color"]};
                                    border-radius:10px;padding:14px 16px;margin-bottom:12px;'>
                            <div style='font-size:11px;color:#aaa'>{r["symbol"]}</div>
                            <div style='font-size:15px;font-weight:700;color:white'>{r["name"]}</div>
                            <div style='font-size:26px;font-weight:700;color:white'>
                                €{r["price_eur"]:,.2f}
                            </div>
                            <div style='margin-top:8px'>
                                <span style='background:{r["rec_color"]};color:white;
                                             padding:2px 11px;border-radius:20px;
                                             font-weight:700;font-size:13px'>
                                    {r["rec_emoji"]} {r["recommendation"]}
                                </span>
                                <span style='color:#aaa;font-size:12px;margin-left:8px'>
                                    Score: {r["score"]} · RSI: {r["rsi"]:.1f}
                                </span>
                            </div>
                            <div style='margin-top:6px;font-size:12px;color:#aaa'>
                                1M: <b style='color:{chg_col}'>{chg_1m_str}</b>
                                &nbsp;·&nbsp;52W: €{r["low52"]:,.0f}–€{r["high52"]:,.0f}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                st.divider()
                for r in st.session_state.sx_results:
                    st.subheader(f"🔍 {r['name']} ({r['symbol']})")
                    render_deep_dive(r, key_prefix=r["symbol"])
                    st.divider()

        else:
            examples = [
                "📈 AAPL — Apple", "₿ BTC-EUR — Bitcoin",
                "📈 RELIANCE.NS — India", "📈 7203.T — Toyota",
                "⏳ GC=F — Gold Futures", "🗂️ VWCE.DE — MSCI World ETF",
                "📊 ^DAX — DAX Index", "📈 Or just type: toyota",
            ]
            chips_html = "".join([
                f"<span style='background:#12233A;border:1px solid #1E88E5;"
                f"border-radius:16px;padding:5px 14px;font-size:13px;color:#90CAF9'>{e}</span>"
                for e in examples
            ])
            st.markdown(f"""
            <div style='text-align:center;padding:36px 20px 12px;'>
                <div style='font-size:44px'>🌍</div>
                <div style='font-size:15px;margin-top:8px;color:#666'>
                    Search any stock, ETF, crypto, index or commodity worldwide
                </div>
            </div>
            <div style='display:flex;flex-wrap:wrap;gap:8px;justify-content:center;
                        padding:0 40px 24px;'>
                {chips_html}
            </div>
            """, unsafe_allow_html=True)

    # ══════════════════════════════════════════
    # TAB 3 — MY PORTFOLIO
    # ══════════════════════════════════════════
    with tab_portfolio:
        pf = st.session_state.portfolio

        # ── Header + Budget ────────────────────
        hdr_c1, hdr_c2, hdr_c3 = st.columns([3, 2, 2])
        with hdr_c1:
            st.markdown(
                "<h3 style='margin-bottom:2px'>💼 My Portfolio</h3>"
                "<p style='color:#888;font-size:13px;margin-top:0'>Track holdings across India (INR) "
                "and EU/US (EUR) · Personalised buy/sell recommendations · Approval workflow</p>",
                unsafe_allow_html=True,
            )
        with hdr_c2:
            new_budget = st.number_input(
                "Monthly budget (EUR)", min_value=0, step=50,
                value=int(pf.get("settings", {}).get("monthly_budget_eur") or 625),
                key="pf_budget_input",
                help="How much you plan to invest each month. Used to size new-position suggestions.",
            )
        with hdr_c3:
            st.write("")
            st.write("")
            if st.button("💾 Save Budget", key="pf_save_budget", use_container_width=True):
                pf.setdefault("settings", {})["monthly_budget_eur"] = new_budget
                st.session_state.portfolio = pf
                save_portfolio(pf)
                st.success("Budget saved!")

        # ── Import / Export ────────────────────
        with st.expander("📂 Import / Export Portfolio JSON  (use this to backup or restore)"):
            imp_c, exp_c = st.columns(2)
            with exp_c:
                pf_json_str = _json.dumps(pf, indent=2, default=str)
                st.download_button(
                    "⬇️ Export portfolio.json",
                    data=pf_json_str, file_name="portfolio.json",
                    mime="application/json", use_container_width=True,
                    help="Save your portfolio state to a local file.",
                )
            with imp_c:
                uploaded_pf = st.file_uploader(
                    "⬆️ Restore from file", type="json",
                    key="pf_json_import", label_visibility="visible",
                )
                if uploaded_pf is not None:
                    try:
                        new_pf = _json.loads(uploaded_pf.read())
                        st.session_state.portfolio = new_pf
                        save_portfolio(new_pf)
                        st.success("✅ Portfolio restored! Refreshing…")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Could not parse JSON: {ex}")

        st.divider()

        # ═══════════════════════════════════════
        # INDIA BLOCK
        # ═══════════════════════════════════════
        st.markdown(
            "<h4 style='color:#FF9800;margin-bottom:4px'>🇮🇳 Indian Holdings (INR)</h4>",
            unsafe_allow_html=True,
        )
        india_block    = pf.setdefault("india",  {"currency": "INR", "holdings": {}})
        india_holdings = india_block.setdefault("holdings", {})
        india_syms     = tuple(india_holdings.keys())
        india_live     = get_live_prices(india_syms) if india_syms else {}

        if india_holdings:
            india_sum = portfolio_summary(india_holdings, india_live)
            india_rows = india_sum["rows"]

            # Holdings table
            tbl_data = []
            for row in india_rows:
                lp     = row["live_price"]
                lp_str = f"₹{lp:,.2f}" if lp is not None else "N/A"
                pl_col = "#00C853" if row["pl"] >= 0 else "#FF5252"
                tbl_data.append({
                    "Symbol":        row["symbol"],
                    "Name":          row["name"],
                    "Qty":           f"{row['qty']:.0f}",
                    "Avg Price (₹)": f"₹{row['avg_price']:,.2f}",
                    "Live Price":    lp_str,
                    "Invested (₹)":  f"₹{row['invested']:,.0f}",
                    "Current (₹)":   f"₹{row['current']:,.0f}" if lp else "—",
                    "P&L":           f"₹{row['pl']:+,.0f}" if lp else "—",
                    "P&L %":         f"{row['pl_pct']:+.1f}%" if lp else "—",
                })
            df_india = pd.DataFrame(tbl_data)

            def _color_pl(val):
                try:
                    v = float(str(val).replace("₹","").replace("€","").replace("%","").replace(",","").replace("+",""))
                    return f"color:{'#00C853' if v >= 0 else '#FF5252'}"
                except Exception:
                    return ""

            st.dataframe(
                df_india.style.map(_color_pl, subset=["P&L", "P&L %"]),
                use_container_width=True, hide_index=True,
            )

            # Totals
            ti = india_sum["total_invested"]
            tc = india_sum["total_current"]
            tpl = india_sum["total_pl"]
            tpp = india_sum["total_pl_pct"]
            tc1, tc2, tc3, tc4 = st.columns(4)
            tc1.metric("Invested (₹)", f"₹{ti:,.0f}")
            tc2.metric("Current Value (₹)", f"₹{tc:,.0f}")
            tc3.metric("Total P&L (₹)", f"₹{tpl:+,.0f}", delta=f"{tpp:+.1f}%")
            tc4.metric("In EUR (≈)", f"€{tc * inr_eur_rate:,.0f}")
        else:
            st.info("No Indian holdings yet. Upload a screenshot or add manually below.")

        # ── India screenshot upload ────────────
        with st.expander("📸 Upload AngelOne / Zerodha / Groww Screenshot to auto-import"):
            # Detect which AI provider is configured
            _ai_provider = (
                "🟣 Anthropic (Claude Haiku)" if _pf_get_secret("ANTHROPIC_API_KEY") else
                "🔵 Google Gemini Flash (free)" if _pf_get_secret("GEMINI_API_KEY") else
                "🟠 Groq / Llama Vision (free)" if _pf_get_secret("GROQ_API_KEY") else
                None
            )
            if not _ai_provider:
                st.warning(
                    "**No AI key configured.** Add one to `.streamlit/secrets.toml`:\n\n"
                    "- `ANTHROPIC_API_KEY` (you likely have this)\n"
                    "- `GEMINI_API_KEY` (free — [aistudio.google.com/apikey](https://aistudio.google.com/apikey))\n"
                    "- `GROQ_API_KEY` (free — [console.groq.com](https://console.groq.com))"
                )
            else:
                st.caption(f"Active AI provider: {_ai_provider}")
                india_img = st.file_uploader(
                    "Upload portfolio screenshot (PNG/JPG)",
                    type=["png", "jpg", "jpeg", "webp"],
                    key="india_screenshot",
                )
                if india_img and st.button("🔍 Parse Screenshot with AI", key="parse_india"):
                    with st.spinner(f"Parsing with {_ai_provider} — extracting holdings…"):
                        try:
                            parsed = parse_screenshot_with_ai(india_img.read(), "india")
                            if parsed:
                                new_holdings = {}
                                for h in parsed:
                                    sym = h["symbol"].upper()
                                    new_holdings[sym] = {
                                        "name":      h["name"],
                                        "qty":       h["qty"],
                                        "avg_price": h["avg_price"],
                                    }
                                india_block["holdings"]    = new_holdings
                                india_block["last_updated"] = now_berlin().strftime("%Y-%m-%d")
                                india_block["source"]       = "gemini_screenshot"
                                pf["india"]                 = india_block
                                st.session_state.portfolio  = pf
                                save_portfolio(pf)
                                st.success(f"✅ Imported {len(new_holdings)} holdings from screenshot!")
                                st.rerun()
                            else:
                                st.error("Gemini returned no holdings. Try a clearer screenshot.")
                        except RuntimeError as ex:
                            st.error(str(ex))

        # ── India manual add/edit ──────────────
        with st.expander("✏️ Add / Edit / Remove a holding manually"):
            with st.form("india_add_form"):
                st.markdown("**Add or update a holding** (existing symbol = update qty & price)")
                fa1, fa2, fa3, fa4 = st.columns([2, 3, 2, 2])
                sym_in  = fa1.text_input("Symbol (.NS)", placeholder="TCS.NS")
                name_in = fa2.text_input("Name", placeholder="Tata Consultancy Services")
                qty_in  = fa3.number_input("Qty", min_value=0.0, step=1.0)
                atp_in  = fa4.number_input("Avg Price (₹)", min_value=0.0, step=0.01)
                add_sub = st.form_submit_button("➕ Save Holding", use_container_width=True)

            if add_sub and sym_in.strip():
                sym_clean = sym_in.strip().upper()
                if not sym_clean.endswith((".NS", ".BO")):
                    sym_clean += ".NS"
                india_holdings[sym_clean] = {
                    "name":      name_in.strip() or sym_clean,
                    "qty":       qty_in,
                    "avg_price": atp_in,
                }
                india_block["last_updated"] = now_berlin().strftime("%Y-%m-%d")
                pf["india"] = india_block
                st.session_state.portfolio = pf
                save_portfolio(pf)
                st.success(f"✅ Saved {sym_clean}!")
                st.rerun()

            if india_holdings:
                st.markdown("**Remove a holding**")
                del_sym = st.selectbox(
                    "Select to remove", ["— select —"] + list(india_holdings.keys()),
                    key="india_del_sym",
                )
                if del_sym != "— select —" and st.button("🗑️ Remove", key="india_del_btn"):
                    del india_holdings[del_sym]
                    pf["india"] = india_block
                    st.session_state.portfolio = pf
                    save_portfolio(pf)
                    st.success(f"Removed {del_sym}.")
                    st.rerun()

        st.divider()

        # ═══════════════════════════════════════
        # EU / US BLOCK
        # ═══════════════════════════════════════
        last_eu = pf.get("eu_us", {}).get("last_updated")
        eu_header_note = f"  <span style='color:#888;font-size:12px'>(last updated {last_eu})</span>" if last_eu else "  <span style='color:#888;font-size:12px'>(no data yet)</span>"
        st.markdown(
            f"<h4 style='color:#42A5F5;margin-bottom:4px'>🌍 EU / US Holdings (EUR){eu_header_note}</h4>",
            unsafe_allow_html=True,
        )
        eu_block    = pf.setdefault("eu_us", {"currency": "EUR", "holdings": {}})
        eu_holdings = eu_block.setdefault("holdings", {})
        eu_syms     = tuple(eu_holdings.keys())
        eu_live     = get_live_prices(eu_syms) if eu_syms else {}

        if eu_holdings:
            eu_sum  = portfolio_summary(eu_holdings, eu_live)
            eu_rows = eu_sum["rows"]

            eu_tbl = []
            for row in eu_rows:
                lp     = row["live_price"]
                # convert to EUR if needed
                from portfolio_manager import _detect_market as _dm
                if lp is not None:
                    sym_up = row["symbol"].upper()
                    if not any(sym_up.endswith(s) for s in (".AS",".DE",".PA",".MI",".SW",".LS",".ST",".OL",".CO",".HE",".BR",".VI")):
                        lp_eur = lp * eur_rate      # USD → EUR
                    else:
                        lp_eur = lp
                else:
                    lp_eur = None

                avg_eur = row["avg_price"]
                if "currency" in eu_holdings.get(row["symbol"], {}):
                    c = eu_holdings[row["symbol"]]["currency"].upper()
                    if c == "USD":
                        avg_eur = avg_eur * eur_rate
                    elif c == "GBP":
                        avg_eur = avg_eur * eur_rate * 1.17  # approx GBP→EUR

                pl_eur = (lp_eur - avg_eur) * row["qty"] if lp_eur else None
                pl_pct = ((lp_eur - avg_eur) / avg_eur * 100) if (lp_eur and avg_eur) else None

                lp_str  = f"€{lp_eur:,.2f}"  if lp_eur  is not None else "N/A"
                pl_str  = f"€{pl_eur:+,.0f}" if pl_eur  is not None else "—"
                pct_str = f"{pl_pct:+.1f}%"  if pl_pct  is not None else "—"

                eu_tbl.append({
                    "Symbol":        row["symbol"],
                    "Name":          row["name"],
                    "Qty":           f"{row['qty']:.4f}",
                    "Avg Price (€)": f"€{avg_eur:,.2f}",
                    "Live Price":    lp_str,
                    "Invested (€)":  f"€{avg_eur * row['qty']:,.0f}",
                    "Current (€)":   f"€{lp_eur * row['qty']:,.0f}" if lp_eur else "—",
                    "P&L":           pl_str,
                    "P&L %":         pct_str,
                })

            df_eu = pd.DataFrame(eu_tbl)
            st.dataframe(
                df_eu.style.map(_color_pl, subset=["P&L", "P&L %"]),
                use_container_width=True, hide_index=True,
            )

            ti2 = eu_sum["total_invested"]
            tc2v = eu_sum["total_current"]
            tpl2 = eu_sum["total_pl"]
            tpp2 = eu_sum["total_pl_pct"]
            ek1, ek2, ek3 = st.columns(3)
            ek1.metric("Invested (€)", f"€{ti2:,.0f}")
            ek2.metric("Current Value (€)", f"€{tc2v:,.0f}")
            ek3.metric("Total P&L (€)", f"€{tpl2:+,.0f}", delta=f"{tpp2:+.1f}%")
        else:
            st.info("No EU/US holdings yet. Upload a Trading212 screenshot or add manually below.")

        # ── EU/US screenshot upload ────────────
        with st.expander("📸 Upload Trading212 / eToro / DEGIRO Screenshot to auto-import"):
            _ai_provider_eu = (
                "🟣 Anthropic (Claude Haiku)" if _pf_get_secret("ANTHROPIC_API_KEY") else
                "🔵 Google Gemini Flash (free)" if _pf_get_secret("GEMINI_API_KEY") else
                "🟠 Groq / Llama Vision (free)" if _pf_get_secret("GROQ_API_KEY") else
                None
            )
            if not _ai_provider_eu:
                st.warning(
                    "**No AI key configured.** Add one to `.streamlit/secrets.toml`:\n\n"
                    "- `ANTHROPIC_API_KEY` (you likely have this)\n"
                    "- `GEMINI_API_KEY` (free — [aistudio.google.com/apikey](https://aistudio.google.com/apikey))\n"
                    "- `GROQ_API_KEY` (free — [console.groq.com](https://console.groq.com))"
                )
            else:
                st.caption(f"Active AI provider: {_ai_provider_eu}")
                eu_img = st.file_uploader(
                    "Upload portfolio screenshot (PNG/JPG)",
                    type=["png", "jpg", "jpeg", "webp"],
                    key="eu_screenshot",
                )
                if eu_img and st.button("🔍 Parse Screenshot with AI", key="parse_eu"):
                    with st.spinner(f"Parsing with {_ai_provider_eu} — extracting holdings…"):
                        try:
                            parsed_eu = parse_screenshot_with_ai(eu_img.read(), "eu_us")
                            if parsed_eu:
                                new_eu = {}
                                for h in parsed_eu:
                                    sym = h["symbol"].upper()
                                    new_eu[sym] = {
                                        "name":      h["name"],
                                        "qty":       h["qty"],
                                        "avg_price": h["avg_price"],
                                        "currency":  h.get("currency", "EUR"),
                                    }
                                eu_block["holdings"]     = new_eu
                                eu_block["last_updated"] = now_berlin().strftime("%Y-%m-%d")
                                eu_block["source"]       = "gemini_screenshot"
                                pf["eu_us"]              = eu_block
                                st.session_state.portfolio = pf
                                save_portfolio(pf)
                                st.success(f"✅ Imported {len(new_eu)} EU/US holdings!")
                                st.rerun()
                            else:
                                st.error("No holdings parsed. Try a clearer screenshot.")
                        except RuntimeError as ex:
                            st.error(str(ex))

        # ── EU/US manual add ──────────────────
        with st.expander("✏️ Add / Edit / Remove a holding manually"):
            with st.form("eu_add_form"):
                st.markdown("**Add or update** (existing symbol = overwrite)")
                fb1, fb2, fb3, fb4, fb5 = st.columns([2, 3, 1, 2, 1])
                sym_eu   = fb1.text_input("Symbol", placeholder="AAPL or SAP.DE")
                name_eu  = fb2.text_input("Name", placeholder="Apple Inc")
                qty_eu   = fb3.number_input("Qty", min_value=0.0, step=0.0001, format="%.4f")
                avg_eu   = fb4.number_input("Avg Price", min_value=0.0, step=0.01)
                cur_eu   = fb5.selectbox("Currency", ["EUR", "USD", "GBP"])
                eu_sub   = st.form_submit_button("➕ Save Holding", use_container_width=True)

            if eu_sub and sym_eu.strip():
                sym_clean_eu = sym_eu.strip().upper()
                eu_holdings[sym_clean_eu] = {
                    "name":      name_eu.strip() or sym_clean_eu,
                    "qty":       qty_eu,
                    "avg_price": avg_eu,
                    "currency":  cur_eu,
                }
                eu_block["last_updated"] = now_berlin().strftime("%Y-%m-%d")
                pf["eu_us"] = eu_block
                st.session_state.portfolio = pf
                save_portfolio(pf)
                st.success(f"✅ Saved {sym_clean_eu}!")
                st.rerun()

            if eu_holdings:
                st.markdown("**Remove a holding**")
                del_eu = st.selectbox(
                    "Select to remove", ["— select —"] + list(eu_holdings.keys()),
                    key="eu_del_sym",
                )
                if del_eu != "— select —" and st.button("🗑️ Remove", key="eu_del_btn"):
                    del eu_holdings[del_eu]
                    pf["eu_us"] = eu_block
                    st.session_state.portfolio = pf
                    save_portfolio(pf)
                    st.success(f"Removed {del_eu}.")
                    st.rerun()

        st.divider()

        # ═══════════════════════════════════════
        # RECOMMENDATIONS
        # ═══════════════════════════════════════
        st.subheader("🎯 Personalised Recommendations")
        st.caption(
            "Based on technical analysis of YOUR holdings + top watchlist signals. "
            f"Budget: €{int(pf.get('settings', {}).get('monthly_budget_eur') or 625)}/month."
        )

        gen_col, _ = st.columns([2, 4])
        with gen_col:
            gen_clicked = st.button(
                "🔄 Generate Fresh Recommendations",
                type="primary", use_container_width=True, key="pf_gen_recs",
            )

        if gen_clicked:
            all_held = {}
            for mkt_key, blk in [("india", india_block), ("eu_us", eu_block)]:
                for sym, h in blk.get("holdings", {}).items():
                    all_held[sym] = (h.get("name", sym), mkt_key)

            pf_analysis = []
            with st.spinner("Analysing your holdings + top watchlist signals…"):
                # Held symbols first
                for sym, (name, mkt) in all_held.items():
                    df_s = fetch_stock_data(sym, period)
                    if df_s is not None and len(df_s) >= 15:
                        df_s = add_indicators(df_s)
                        pf_analysis.append(
                            build_result(sym, name, mkt, df_s, eur_rate, inr_eur_rate, risk)
                        )
                # Watchlist symbols for new-position ideas
                held_upper = {s.upper() for s in all_held}
                for mkt in selected_markets:
                    for sym, name in STOCKS[mkt].items():
                        if sym.upper() not in held_upper:
                            df_s = fetch_stock_data(sym, period)
                            if df_s is not None and len(df_s) >= 15:
                                df_s = add_indicators(df_s)
                                pf_analysis.append(
                                    build_result(sym, name, mkt, df_s, eur_rate, inr_eur_rate, risk)
                                )

            fresh_recs = generate_portfolio_recommendations(
                pf, pf_analysis, inr_eur_rate, eur_rate
            )
            st.session_state.pf_recs = fresh_recs
            st.success(f"Generated {len(fresh_recs)} recommendation(s).")

        # ── Show pending recommendations ──────
        pending = [r for r in st.session_state.pf_recs if r["status"] == "pending"]

        if not st.session_state.pf_recs:
            st.info("Click **Generate Fresh Recommendations** above to analyse your portfolio.")
        elif not pending:
            st.success("✅ All recommendations actioned! Regenerate to get fresh signals.")
        else:
            # Group by action type
            sells    = [r for r in pending if r["action"] == "SELL"]
            buy_more = [r for r in pending if r["action"] == "BUY MORE"]
            buy_new  = [r for r in pending if r["action"] == "BUY NEW"]
            holds    = [r for r in pending if r["action"] == "HOLD"]

            def _rec_card(r, key_suffix):
                """Render one recommendation card with Approve / Skip buttons."""
                action   = r["action"]
                bg_color = (
                    "#2A0A0A" if action == "SELL"              else
                    "#0A2A0A" if action in ("BUY MORE","BUY NEW") else
                    "#1A1A2A"
                )
                border   = (
                    "#D50000" if action == "SELL"              else
                    "#00C853" if action in ("BUY MORE","BUY NEW") else
                    "#FFA726"
                )
                emoji    = "🔴" if action == "SELL" else "🟢" if "BUY" in action else "🟡"
                mkt_flag = "🇮🇳" if r["market"] == "india" else "🌍"
                pl_col   = "#00C853" if r["pl_pct"] >= 0 else "#FF5252"
                currency = "₹" if r["market"] == "india" else "€"
                native_price = (
                    r["price_eur"] / inr_eur_rate if r["market"] == "india" else r["price_eur"]
                )
                # Pre-compute values that can't go inside f-string format specs
                rsi_str = f"{r['rsi']:.0f}" if r.get("rsi") is not None else "—"
                qty_sug_str = f"{r['qty_suggested']:.0f}" if r.get("qty_suggested") is not None else "0"

                st.markdown(f"""
                <div style='background:{bg_color};border:1px solid {border};
                            border-radius:10px;padding:12px 16px;margin-bottom:4px;'>
                    <div style='display:flex;justify-content:space-between;align-items:center'>
                        <div>
                            <span style='font-size:14px;font-weight:700;color:white'>
                                {emoji} {action} — {mkt_flag} <code style='color:#90CAF9'>{r['symbol']}</code>
                                {r['name']}
                            </span><br>
                            <span style='font-size:12px;color:#aaa'>{r['reason']}</span>
                        </div>
                        <div style='text-align:right'>
                            <div style='font-size:15px;font-weight:700;color:white'>
                                {currency}{native_price:,.2f}
                            </div>
                            <div style='font-size:11px;color:{pl_col}'>
                                P&L: {r['pl_pct']:+.1f}%
                            </div>
                        </div>
                    </div>
                    <div style='font-size:11px;color:#777;margin-top:6px'>
                        Suggested: {qty_sug_str} shares · ≈ €{r['amount_eur']:,.0f}
                        · Score: {r['score']:+d} · RSI: {rsi_str}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                ap_col, sk_col, _ = st.columns([1, 1, 3])

                with ap_col:
                    if st.button(f"✅ Approve", key=f"ap_{key_suffix}",
                                 use_container_width=True):
                        st.session_state.pf_approving = r["id"]
                        st.rerun()

                with sk_col:
                    if st.button(f"❌ Skip", key=f"sk_{key_suffix}",
                                 use_container_width=True):
                        # Use session_state directly to avoid Python closure/scoping issue
                        updated = disapprove_recommendation(
                            st.session_state.portfolio, r, "user_skipped"
                        )
                        st.session_state.portfolio = updated
                        save_portfolio(updated)
                        for rec in st.session_state.pf_recs:
                            if rec["id"] == r["id"]:
                                rec["status"] = "disapproved"
                        st.rerun()

                # Approval form (shows inline when this rec is being approved)
                if st.session_state.pf_approving == r["id"]:
                    with st.form(f"approve_form_{key_suffix}"):
                        st.markdown(f"**Confirm execution for {r['symbol']}**")
                        native_label = "₹" if r["market"] == "india" else "€"
                        af1, af2 = st.columns(2)
                        qty_exec   = af1.number_input(
                            "Qty executed", min_value=0.0, step=1.0,
                            value=float(r["qty_suggested"]), key=f"qty_{key_suffix}",
                        )
                        price_exec = af2.number_input(
                            f"Price ({native_label})", min_value=0.0, step=0.01,
                            value=float(native_price), key=f"prc_{key_suffix}",
                        )
                        confirm = st.form_submit_button("✅ Confirm & Update Portfolio",
                                                        use_container_width=True)
                        cancel  = st.form_submit_button("Cancel")

                    if confirm:
                        # Use session_state directly to avoid Python scoping issue
                        updated_pf = apply_recommendation(
                            st.session_state.portfolio, r, qty_exec, price_exec
                        )
                        st.session_state.portfolio = updated_pf
                        save_portfolio(updated_pf)
                        for rec in st.session_state.pf_recs:
                            if rec["id"] == r["id"]:
                                rec["status"] = "approved"
                        st.session_state.pf_approving = None
                        st.success(f"✅ Portfolio updated with {r['symbol']} {r['action']}!")
                        st.rerun()
                    if cancel:
                        st.session_state.pf_approving = None
                        st.rerun()

            if sells:
                st.markdown("#### 🔴 Sell / Exit")
                for i, r in enumerate(sells):
                    _rec_card(r, f"sell_{i}")
                st.write("")

            if buy_more:
                st.markdown("#### 🟢 Add to Existing Positions")
                for i, r in enumerate(buy_more):
                    _rec_card(r, f"bm_{i}")
                st.write("")

            if buy_new:
                total_alloc = sum(r["amount_eur"] for r in buy_new)
                budget_rem  = int(pf.get("settings", {}).get("monthly_budget_eur") or 625)
                st.markdown(
                    f"#### 🆕 New Positions — Monthly Budget  "
                    f"<span style='font-size:13px;color:#aaa'>€{total_alloc:,.0f} / €{budget_rem}</span>",
                    unsafe_allow_html=True,
                )
                for i, r in enumerate(buy_new):
                    _rec_card(r, f"bn_{i}")
                st.write("")

            if holds and st.checkbox("Show HOLD signals", value=False, key="show_holds"):
                st.markdown("#### 🟡 Hold")
                for i, r in enumerate(holds):
                    _rec_card(r, f"hld_{i}")

        st.divider()

        # ═══════════════════════════════════════
        # RECOMMENDATION HISTORY
        # ═══════════════════════════════════════
        st.subheader("📜 Recommendation History")
        log = pf.get("recommendations_log", [])

        if not log:
            st.caption("No history yet. Approve or skip recommendations to build a log.")
        else:
            log_rows = []
            for entry in reversed(log[-50:]):  # most recent 50
                log_rows.append({
                    "Date":     entry.get("date", "")[:10],
                    "Symbol":   entry.get("symbol", ""),
                    "Action":   entry.get("action", ""),
                    "Status":   entry.get("status", ""),
                    "Qty":      entry.get("qty_executed") or entry.get("qty_suggested", ""),
                    "Reason":   entry.get("reason", ""),
                })
            df_log = pd.DataFrame(log_rows)

            def _color_action(val):
                if "SELL"  in str(val): return "color:#FF5252;font-weight:bold"
                if "BUY"   in str(val): return "color:#00C853;font-weight:bold"
                return "color:#FFA726"

            def _color_status(val):
                if val == "approved":    return "color:#00C853"
                if val == "disapproved": return "color:#FF5252"
                return ""

            st.dataframe(
                df_log.style
                    .map(_color_action,  subset=["Action"])
                    .map(_color_status,  subset=["Status"]),
                use_container_width=True, hide_index=True,
            )

            if st.button("🗑️ Clear History", key="clear_history"):
                pf["recommendations_log"] = []
                st.session_state.portfolio = pf
                save_portfolio(pf)
                st.success("History cleared.")
                st.rerun()

    # ══════════════════════════════════════════
    # TAB 4 — HOW IT WORKS
    # ══════════════════════════════════════════
    with tab_learn:
        st.markdown("""
        <h2 style='color:#1E88E5;margin-bottom:4px'>📚 How the Recommender Works</h2>
        <p style='color:#888'>
            A plain-English guide to every signal, metric, and formula used in this app.
        </p>
        """, unsafe_allow_html=True)
        st.divider()

        st.markdown("""
        <h3 style='color:#90CAF9'>🔭 Overview</h3>
        <p style='color:#ccc;line-height:1.7'>
            This app fetches <b>live price data</b> from Yahoo Finance, computes <b>six
            technical indicators</b> and checks <b>recent news sentiment</b>, combining
            their evidence into a single <b>composite score</b>.  Based on that score
            and your chosen <b>Risk Profile</b>, each asset receives a
            <b>BUY / HOLD / SELL</b> recommendation.  All prices are shown in
            <b>Euros (€)</b> using live exchange rates.
        </p>
        """, unsafe_allow_html=True)

        st.markdown("<h3 style='color:#90CAF9'>🧮 Composite Scoring System</h3>",
                    unsafe_allow_html=True)
        st.markdown("""
        <p style='color:#ccc;line-height:1.7'>
            Each indicator contributes <b>points</b> to a running total (max ±10).
            Positive = bullish; negative = bearish.
        </p>
        """, unsafe_allow_html=True)

        score_df = pd.DataFrame([
            {"Indicator": "RSI",            "Max Pts": "±2",
             "Bullish (+)": "RSI < buy threshold (oversold)",
             "Bearish (−)": "RSI > sell threshold (overbought)"},
            {"Indicator": "MACD",           "Max Pts": "±2",
             "Bullish (+)": "Bullish crossover (+2) or MACD above signal (+1)",
             "Bearish (−)": "Bearish crossover (−2) or MACD below signal (−1)"},
            {"Indicator": "SMA 20",         "Max Pts": "±1",
             "Bullish (+)": "Price above 20-day SMA",
             "Bearish (−)": "Price below 20-day SMA"},
            {"Indicator": "SMA 50",         "Max Pts": "±1",
             "Bullish (+)": "Price above 50-day SMA",
             "Bearish (−)": "Price below 50-day SMA"},
            {"Indicator": "Bollinger Bands","Max Pts": "±1",
             "Bullish (+)": "Price below lower band (oversold)",
             "Bearish (−)": "Price above upper band (overbought)"},
            {"Indicator": "Volume",         "Max Pts": "+1",
             "Bullish (+)": "Volume > 1.5× 20-day average",
             "Bearish (−)": "Normal volume = 0 pts"},
        ])
        st.dataframe(score_df, use_container_width=True, hide_index=True)

        st.markdown("""
        <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;
                    padding:14px 18px;margin:10px 0;color:#ccc;line-height:1.9;'>
            <b style='color:#90CAF9'>Recommendation thresholds:</b><br>
            <code>score / 10 ≥  0.30</code> → <b style='color:#00C853'>🟢 BUY</b><br>
            <code>score / 10 ≤ −0.20</code> → <b style='color:#D50000'>🔴 SELL</b><br>
            <code>otherwise</code>           → <b style='color:#FFA726'>🟡 HOLD</b>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

        st.markdown("<h3 style='color:#90CAF9'>📡 Indicators Explained</h3>",
                    unsafe_allow_html=True)

        indicators_detail = [
            ("📈 RSI — Relative Strength Index", """
<p>Measures <b>speed and magnitude of recent price changes</b> on a 0–100 scale over 14 days.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b style='color:#D50000'>RSI &gt; 70</b> — overbought: may pull back → bearish (−2 pts).</li>
  <li><b style='color:#00C853'>RSI &lt; 30</b> — oversold: may bounce → bullish (+2 pts).</li>
  <li><b style='color:#FFA726'>30–70</b> — neutral (0 pts).</li>
</ul>
<p><b>Formula:</b> RSI = 100 − 100/(1 + RS), where RS = Avg Gain / Avg Loss over 14 days.</p>
<p>Thresholds shift with Risk Profile: Conservative 35/65, Balanced 40/60, Aggressive 45/55.</p>
            """),
            ("📉 MACD — Moving Average Convergence/Divergence", """
<p>Tracks momentum by comparing two EMAs:</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b>MACD line</b> = EMA(12 days) − EMA(26 days)</li>
  <li><b>Signal line</b> = EMA(9 days) of MACD</li>
  <li><b>Histogram</b> = MACD − Signal (visualises divergence)</li>
</ul>
<p>MACD crossing <em>above</em> signal = bullish crossover (+2 pts). Staying above = +1 pt.
   Crossing <em>below</em> = bearish crossover (−2 pts). Staying below = −1 pt.</p>
            """),
            ("📊 SMA 20 / 50 / 200 — Simple Moving Averages", """
<p>Average closing price over N trading days — removes daily noise.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li><b>SMA 20</b> (~1 month) — short-term trend. <b style='color:#42A5F5'>Blue line</b> on chart.</li>
  <li><b>SMA 50</b> (~2.5 months) — medium-term. <b style='color:#FFA726'>Orange line</b> on chart.</li>
  <li><b>SMA 200</b> (~10 months) — long-term bull/bear divide. <b style='color:#CE93D8'>Thick purple line</b>.</li>
</ul>
<p><b>Golden Cross</b>: SMA50 crosses above SMA200 → +2 pts (strong long-term bullish).<br>
   <b>Death Cross</b>: SMA50 crosses below SMA200 → −2 pts (strong long-term bearish).</p>
            """),
            ("🎯 Bollinger Bands", """
<p>Statistical price channel: SMA20 ± 2 standard deviations (~95% of price within).</p>
<ul style='color:#ccc;line-height:1.8'>
  <li>Price <em>below lower band</em> = statistically cheap → +1 pt.</li>
  <li>Price <em>above upper band</em> = statistically expensive → −1 pt.</li>
  <li>Inside bands = neutral (0 pts).</li>
  <li>Band <em>widening</em> = rising volatility. <em>Narrowing</em> = squeeze, potential breakout.</li>
</ul>
<p>Shown on chart as <b style='color:#78909C'>grey dotted shaded channel</b>.</p>
            """),
            ("📦 Volume Confirmation", """
<p>Shares/units traded — acts as a <b>confidence multiplier</b> for price moves.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li>Volume &gt; 1.5× its 20-day average → strong participation → +1 pt.</li>
  <li>Normal volume → 0 pts (move may be less reliable).</li>
</ul>
            """),
            ("📰 News Sentiment", """
<p>Keyword scan of the 5 most recent Yahoo Finance headlines for this ticker.</p>
<ul style='color:#ccc;line-height:1.8'>
  <li>Counts bullish words (upgrade, beat, surge, outperform…) vs bearish (downgrade, miss, cut…).</li>
  <li>Returns 🟢 Positive / 🟡 Neutral / 🔴 Negative label in the news expander.</li>
  <li>News sentiment is shown as context only — it does <em>not</em> change the composite score,
      keeping the technical scoring objective and consistent.</li>
</ul>
            """),
        ]

        for title, body in indicators_detail:
            with st.expander(title):
                st.markdown(f"<div style='color:#ccc;line-height:1.7'>{body}</div>",
                            unsafe_allow_html=True)

        st.divider()

        st.markdown("<h3 style='color:#90CAF9'>⚖️ Risk Profiles</h3>",
                    unsafe_allow_html=True)
        risk_df = pd.DataFrame([
            {"Profile": "Conservative",       "RSI Buy <": 35, "RSI Sell >": 65,
             "Min Score (BUY)": 4, "Best for": "Capital preservation, low volatility"},
            {"Profile": "Balanced (default)", "RSI Buy <": 40, "RSI Sell >": 60,
             "Min Score (BUY)": 3, "Best for": "Moderate risk / reward balance"},
            {"Profile": "Aggressive",         "RSI Buy <": 45, "RSI Sell >": 55,
             "Min Score (BUY)": 2, "Best for": "Growth-seeking, higher drawdown tolerance"},
        ])
        st.dataframe(risk_df, use_container_width=True, hide_index=True)
        st.divider()

        st.markdown("<h3 style='color:#90CAF9'>🕯️ Reading the Chart</h3>",
                    unsafe_allow_html=True)
        st.markdown("""
        <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;'>
          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Panel 1 — Price + Overlays</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li><b style='color:#26A69A'>Green</b>/<b style='color:#EF5350'>Red</b> candles = up / down days; wicks = intra-day range</li>
              <li><b style='color:#42A5F5'>Blue</b> line = SMA 20</li>
              <li><b style='color:#FFA726'>Orange</b> line = SMA 50</li>
              <li><b style='color:#CE93D8'>Thick purple</b> = SMA 200</li>
              <li><b style='color:#78909C'>Grey dotted channel</b> = Bollinger Bands ±2σ</li>
            </ul>
          </div>
          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Panel 2 — RSI</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li><b style='color:#26C6DA'>Teal line</b> = RSI (14-day)</li>
              <li><b style='color:#EF5350'>Red dotted at 70</b> = overbought zone</li>
              <li><b style='color:#26A69A'>Green dotted at 30</b> = oversold zone</li>
              <li>Grey dotted at 50 = momentum midpoint</li>
            </ul>
          </div>
          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Panel 3 — MACD</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li><b style='color:#26A69A'>Green</b>/<b style='color:#EF5350'>Red</b> bars = histogram (momentum strength)</li>
              <li><b style='color:#42A5F5'>Blue</b> = MACD line</li>
              <li><b style='color:#FFA726'>Orange</b> = Signal line</li>
              <li>Blue crossing above orange = bullish crossover signal</li>
            </ul>
          </div>
          <div style='background:#12233A;border:1px solid #1E88E5;border-radius:8px;padding:14px;'>
            <b style='color:#90CAF9'>Currency Conversion</b>
            <ul style='color:#ccc;font-size:13px;line-height:1.8;margin-top:6px'>
              <li>EU stocks (.AS .DE .PA…) — priced natively in EUR, no conversion</li>
              <li>US stocks, Bitcoin — converted via live <b>EURUSD=X</b> rate</li>
              <li>Indian stocks (.NS .BO) — converted via live <b>EURINR=X</b> rate</li>
              <li>Both rates cached 5 min; fallbacks used if unreachable</li>
            </ul>
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

        st.markdown("<h3 style='color:#90CAF9'>📖 Full Glossary</h3>",
                    unsafe_allow_html=True)
        st.caption("Hover over any blue underlined term in the app for a quick inline tooltip.")
        gl_df = pd.DataFrame([{"Term": k, "Definition": v} for k, v in TOOLTIPS.items()])
        st.dataframe(gl_df, use_container_width=True, hide_index=True,
                     column_config={"Definition": st.column_config.TextColumn(width="large")})
        st.divider()

        st.markdown("""
        <div style='background:#1A1228;border:1px solid #7B1FA2;border-radius:8px;
                    padding:14px 18px;color:#ccc;font-size:13px;line-height:1.8;'>
            <b style='color:#CE93D8'>⚠️ Important Notes</b><br>
            • Technical analysis is <em>probabilistic</em> — past signals do not guarantee future returns.<br>
            • This app uses <b>price-action + basic news keywords only</b> — no earnings, macro, or fundamentals.<br>
            • Always combine with your own research. Consult a qualified financial advisor before investing.
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
