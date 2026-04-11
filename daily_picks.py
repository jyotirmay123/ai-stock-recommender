#!/usr/bin/env python3
"""
daily_picks.py — Standalone daily BUY-picks Telegram sender.
Runs every weekday at 9AM Berlin time via Cowork scheduler.
No Streamlit dependency — reads secrets from .streamlit/secrets.toml or env vars.
"""

import json
import os
import sys
try:
    import tomllib          # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # Python 3.10 fallback (pip install tomli)
    except ModuleNotFoundError:
        tomllib = None      # will be handled gracefully in _load_secrets
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd
import numpy as np
import requests

warnings.filterwarnings("ignore")

BERLIN = ZoneInfo("Europe/Berlin")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_PATH = os.path.join(PROJECT_DIR, "portfolio.json")

# ─────────────────────────────────────────────
# SECRETS
# ─────────────────────────────────────────────
def _load_secrets() -> dict:
    if tomllib is None:
        return {}
    path = os.path.join(PROJECT_DIR, ".streamlit", "secrets.toml")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}

_SECRETS = _load_secrets()

def secret(key: str) -> str:
    return _SECRETS.get(key, "") or os.environ.get(key, "")

# ─────────────────────────────────────────────
# TRACKED BUYS PERSISTENCE
# ─────────────────────────────────────────────
def _load_tracked_buys() -> dict:
    """Return tracked_buys dict from portfolio.json, or {} if missing/unreadable."""
    try:
        with open(PORTFOLIO_PATH, "r") as f:
            return json.load(f).get("tracked_buys", {})
    except Exception:
        return {}


def _save_tracked_buys(tracked: dict) -> None:
    """Persist tracked_buys back into portfolio.json without touching other keys."""
    try:
        try:
            with open(PORTFOLIO_PATH, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data["tracked_buys"] = tracked
        with open(PORTFOLIO_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save tracked buys: {e}")


# ─────────────────────────────────────────────
# STOCK UNIVERSE  (mirrors stock_analyser.py)
# ─────────────────────────────────────────────
STOCKS = {
    "🇪🇺 European": {
        "ASML.AS": "ASML Holding",   "SAP.DE":  "SAP SE",
        "SIE.DE":  "Siemens",        "MC.PA":   "LVMH",
        "TTE.PA":  "TotalEnergies",  "AIR.PA":  "Airbus",
        "SAN.PA":  "Sanofi",         "DTE.DE":  "Deutsche Telekom",
        "ALV.DE":  "Allianz",        "BAS.DE":  "BASF",
    },
    "🇺🇸 US S&P 500": {
        "AAPL":  "Apple",     "MSFT":  "Microsoft",
        "NVDA":  "NVIDIA",    "GOOGL": "Alphabet",
        "AMZN":  "Amazon",   "META":  "Meta",
        "TSLA":  "Tesla",    "JPM":   "JPMorgan",
        "V":     "Visa",     "JNJ":   "J&J",
    },
    "🇮🇳 Indian (NSE)": {
        "RELIANCE.NS":   "Reliance",       "TCS.NS":        "TCS",
        "INFY.NS":       "Infosys",        "HDFCBANK.NS":   "HDFC Bank",
        "ICICIBANK.NS":  "ICICI Bank",     "WIPRO.NS":      "Wipro",
        "BAJFINANCE.NS": "Bajaj Finance",  "SBIN.NS":       "SBI",
        "HINDUNILVR.NS": "HUL",            "ITC.NS":        "ITC",
    },
    "₿ Crypto": {
        "BTC-EUR": "Bitcoin",
    },
}

# ─────────────────────────────────────────────
# CURRENCY
# ─────────────────────────────────────────────
EUR_SUFFIXES = {".AS",".DE",".PA",".SW",".BR",".MI",".MC",
                ".LS",".VI",".HE",".CO",".ST",".OL"}
INR_SUFFIXES = {".NS", ".BO"}

def _eur_rate() -> float:
    try:    return 1.0 / yf.Ticker("EURUSD=X").fast_info["last_price"]
    except: return 0.92

def _inr_eur_rate() -> float:
    try:    return 1.0 / yf.Ticker("EURINR=X").fast_info["last_price"]
    except: return 1.0 / 87.5

def _mult(sym, eur_r, inr_r) -> float:
    s = sym.upper()
    if s.endswith("-EUR") or any(s.endswith(x) for x in EUR_SUFFIXES): return 1.0
    if any(s.endswith(x) for x in INR_SUFFIXES):                        return inr_r
    return eur_r

# ─────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────
def _indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"].squeeze()
    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, 1e-9))
    # MACD
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    macd         = ema12 - ema26
    df["MACD"]   = macd
    df["Signal"] = macd.ewm(span=9).mean()
    # SMAs
    for p in (20, 50, 200): df[f"SMA{p}"] = c.rolling(p).mean()
    # Bollinger
    sma20         = c.rolling(20).mean()
    std20         = c.rolling(20).std()
    df["BB_upper"] = sma20 + 2 * std20
    df["BB_lower"] = sma20 - 2 * std20
    # Volume MA
    if "Volume" in df.columns:
        df["Vol_MA"] = df["Volume"].rolling(20).mean()
    return df

# ─────────────────────────────────────────────
# SCORE
# ─────────────────────────────────────────────
def _score(sym: str, df: pd.DataFrame) -> dict:
    last  = df.iloc[-1]
    prev  = df.iloc[-2] if len(df) > 1 else last
    c     = df["Close"].squeeze()
    score = 0

    rsi  = last.get("RSI", float("nan"))
    if not pd.isna(rsi):
        if rsi < 40:   score += 2
        elif rsi < 30: score += 3
        elif rsi > 60: score -= 2
        elif rsi > 70: score -= 3

    if not pd.isna(last.get("MACD")) and not pd.isna(last.get("Signal")):
        if last["MACD"] > last["Signal"] and prev.get("MACD",0) <= prev.get("Signal",0):
            score += 2
        elif last["MACD"] < last["Signal"] and prev.get("MACD",0) >= prev.get("Signal",0):
            score -= 2
        elif last["MACD"] > last["Signal"]: score += 1
        else:                               score -= 1

    price = float(c.iloc[-1])
    for ma in ("SMA20","SMA50","SMA200"):
        v = last.get(ma, float("nan"))
        if not pd.isna(v):
            if price > v: score += 1
            else:         score -= 1

    p50  = last.get("SMA50",  float("nan"))
    p200 = last.get("SMA200", float("nan"))
    pp50 = prev.get("SMA50",  float("nan"))
    pp200= prev.get("SMA200", float("nan"))
    if not any(pd.isna(x) for x in [p50,p200,pp50,pp200]):
        if p50 > p200 and pp50 <= pp200: score += 2
        elif p50 < p200 and pp50 >= pp200: score -= 2

    bb_u = last.get("BB_upper", float("nan"))
    bb_l = last.get("BB_lower", float("nan"))
    if not pd.isna(bb_u) and not pd.isna(bb_l):
        if price < bb_l: score += 1
        elif price > bb_u: score -= 1

    if "Volume" in df.columns and not pd.isna(last.get("Vol_MA")):
        if float(df["Volume"].iloc[-1]) > 1.5 * float(last["Vol_MA"]):
            score += 1 if score > 0 else -1

    score = max(-10, min(10, score))
    rec   = "BUY" if score >= 3 else ("SELL" if score <= -3 else "HOLD")

    return {
        "symbol": sym,
        "score":  score,
        "rec":    rec,
        "rsi":    rsi,
        "price":  price,
    }

# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
def _send_telegram(text: str) -> bool:
    token   = secret("TELEGRAM_BOT_TOKEN")
    chat_id = secret("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        return r.ok
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    now   = datetime.now(BERLIN)
    eur_r = _eur_rate()
    inr_r = _inr_eur_rate()
    today = now.strftime("%Y-%m-%d")

    print(f"[{now.strftime('%Y-%m-%d %H:%M %Z')}] Running daily BUY picks analysis…")

    tracked = _load_tracked_buys()

    # symbol → full result dict (populated for every ticker, not just BUYs)
    all_results: dict = {}

    lines = [
        "📈 <b>Daily Top BUY Picks — AI Stock Recommender</b>",
        f"📅 {now.strftime('%A, %d %b %Y  %H:%M')} Berlin",
        "",
    ]

    any_buys = False

    for market, tickers in STOCKS.items():
        buys = []
        for sym, name in tickers.items():
            try:
                df = yf.download(sym, period="6mo", auto_adjust=True, progress=False)
                if df is None or len(df) < 30:
                    continue
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df  = _indicators(df)
                res = _score(sym, df)
                mult       = _mult(sym, eur_r, inr_r)
                res["eur"] = res["price"] * mult
                res["name"]   = name
                res["market"] = market
                all_results[sym] = res

                if res["rec"] == "BUY":
                    buys.append(res)
                    # Track: first time we recommend a ticker, record it; subsequent runs update last date
                    if sym not in tracked:
                        tracked[sym] = {
                            "name":  name,
                            "market": market,
                            "first_recommended": today,
                            "last_recommended":  today,
                            "price_at_recommendation": res["eur"],
                            "consecutive_sell_days": 0,
                        }
                    else:
                        tracked[sym]["last_recommended"] = today
                        tracked[sym]["consecutive_sell_days"] = 0
            except Exception as e:
                print(f"  skip {sym}: {e}")

        buys.sort(key=lambda x: x["score"], reverse=True)
        top5 = buys[:5]

        lines.append(f"<b>{market}</b>")
        if top5:
            any_buys = True
            for r in top5:
                star    = "⭐" if r["score"] >= 6 else "✅"
                rsi_str = f"{r['rsi']:.0f}" if not pd.isna(r["rsi"]) else "—"
                lines.append(
                    f"  {star} <code>{r['symbol']}</code> {r['name']}"
                    f"  €{r['eur']:,.2f}  Score: {r['score']:+d}  RSI: {rsi_str}"
                )
        else:
            lines.append("  — No BUY signals today")
        lines.append("")

    # ── Sell alerts for previously recommended tickers ──────────────────────
    sell_alerts: dict = {}  # market label → list of alert dicts
    to_remove: list = []

    for sym, info in tracked.items():
        if sym not in all_results:
            # Not in STOCKS universe this run — leave consecutive count as-is
            continue
        res = all_results[sym]
        if res["rec"] == "SELL":
            info["consecutive_sell_days"] = info.get("consecutive_sell_days", 0) + 1
            market = info.get("market", "Other")
            sell_alerts.setdefault(market, [])
            price_then = info.get("price_at_recommendation") or 0
            price_now  = res["eur"]
            pct_str    = f"{(price_now - price_then) / price_then * 100:+.1f}%" if price_then else "—"
            rsi_str    = f"{res['rsi']:.0f}" if not pd.isna(res["rsi"]) else "—"
            cons_days  = info["consecutive_sell_days"]
            sell_alerts[market].append({
                "symbol":    sym,
                "name":      info["name"],
                "score":     res["score"],
                "rsi":       rsi_str,
                "eur":       price_now,
                "pct":       pct_str,
                "first_rec": info.get("first_recommended", "?"),
                "cons_days": cons_days,
            })
            if cons_days >= 3:
                to_remove.append(sym)
        else:
            info["consecutive_sell_days"] = 0

    for sym in to_remove:
        print(f"  Dropping {sym} from tracked buys — 3 consecutive SELL days.")
        del tracked[sym]

    if sell_alerts:
        lines.append("🔔 <b>Tracked Buys — Now Showing SELL Signal</b>")
        for market in STOCKS:  # preserve market order
            alerts = sell_alerts.get(market, [])
            if not alerts:
                continue
            lines.append(f"<b>{market}</b>")
            for a in alerts:
                drop_note = "  ⚠️ Auto-removed after 3 days" if a["cons_days"] >= 3 else f"  (day {a['cons_days']})"
                lines.append(
                    f"  🔴 <code>{a['symbol']}</code> {a['name']}"
                    f"  €{a['eur']:,.2f}  Score: {a['score']:+d}  RSI: {a['rsi']}"
                    f"  Since rec: {a['pct']}  (first picked: {a['first_rec']}){drop_note}"
                )
            lines.append("")

    _save_tracked_buys(tracked)

    lines.append("⚠️ <i>Informational only. Not financial advice.</i>")
    msg = "\n".join(lines)

    print(msg)
    print()

    ok = _send_telegram(msg)
    if ok:
        print("✅ Sent to Telegram.")
    else:
        print("❌ Telegram delivery failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
