"""
indicators.py — Technical indicator computation and scoring engine.

No Streamlit dependency — safe to import from both the Streamlit app
and the standalone daily_picks.py script.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from constants import RISK_PARAMS, get_mult


# ─────────────────────────────────────────────
# BASE INDICATORS
# ─────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12  = series.ewm(span=12, adjust=False).mean()
    ema26  = series.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def compute_bollinger(
    series: pd.Series, period: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    sma   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    return sma + std * sigma, sma, sma - std * sigma


# ─────────────────────────────────────────────
# ADVANCED INDICATORS
# ─────────────────────────────────────────────

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — measures daily volatility."""
    h, l, pc = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_stochastic(
    df: pd.DataFrame, k: int = 14, d: int = 3
) -> tuple[pd.Series, pd.Series]:
    """Stochastic %K and %D oscillator."""
    low_min  = df["Low"].rolling(k).min()
    high_max = df["High"].rolling(k).max()
    pct_k    = 100 * (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    return pct_k, pct_k.rolling(d).mean()


def find_support_resistance(
    close: pd.Series,
    window: int = 5,
    n_levels: int = 4,
) -> tuple[list[float], list[float]]:
    """Return (support_levels, resistance_levels) nearest the current price."""
    w         = window * 2 + 1
    local_min = close == close.rolling(w, center=True).min()
    local_max = close == close.rolling(w, center=True).max()

    def _cluster(levels: list[float]) -> list[float]:
        out: list[float] = []
        for lv in sorted(levels):
            if not out or abs(lv - out[-1]) / max(out[-1], 1e-9) > 0.005:
                out.append(lv)
        return out

    supports    = _cluster(sorted(close[local_min].dropna().unique()))
    resistances = _cluster(sorted(close[local_max].dropna().unique(), reverse=True))
    current     = float(close.iloc[-1])
    sup = sorted(supports,    key=lambda x: abs(x - current))[:n_levels]
    res = sorted(resistances, key=lambda x: abs(x - current))[:n_levels]
    return sorted(sup), sorted(res, reverse=True)


def compute_fibonacci_levels(high: float, low: float) -> dict[str, float]:
    """Classic Fibonacci retracement levels between swing high and low."""
    diff = high - low
    return {
        "Fib 100%":  high,
        "Fib 78.6%": high - 0.214 * diff,
        "Fib 61.8%": high - 0.382 * diff,
        "Fib 50%":   high - 0.500 * diff,
        "Fib 38.2%": high - 0.618 * diff,
        "Fib 23.6%": high - 0.764 * diff,
        "Fib 0%":    low,
    }


def compute_pivot_points(df: pd.DataFrame) -> dict[str, float]:
    """Classic floor-trader pivot points from the last completed session."""
    prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    p = (h + l + c) / 3
    return {
        "PP":  p,
        "R1":  2 * p - l,  "R2": p + (h - l),
        "S1":  2 * p - h,  "S2": p - (h - l),
    }


# ─────────────────────────────────────────────
# INDICATOR PIPELINE
# ─────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute and attach all technical indicators to a price DataFrame."""
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
    df["Volume_MA20"]              = df["Volume"].rolling(20).mean()
    df["ATR"]                      = compute_atr(df)
    df["Stoch_K"], df["Stoch_D"]   = compute_stochastic(df)
    return df


# ─────────────────────────────────────────────
# SCORING ENGINE  (max ±10 pts)
# ─────────────────────────────────────────────

def score_stock(df: pd.DataFrame, risk: str) -> dict:
    """
    Score the last row of an indicator-enriched DataFrame.

    Returns a dict with: score, recommendation, rec_color, rec_emoji,
    signals, rsi, close, high52, low52, pct_chg_1m, pct_chg_6m.
    """
    params = RISK_PARAMS[risk]
    last   = df.iloc[-1]
    prev   = df.iloc[-2] if len(df) > 1 else last
    signals: dict = {}
    score = 0

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


def build_result(
    sym: str,
    name: str,
    market: str,
    df: pd.DataFrame,
    eur_rate: float,
    inr_eur_rate: float,
    risk: str,
) -> dict:
    """Combine scored stock data into a flat result dict used by the UI."""
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
