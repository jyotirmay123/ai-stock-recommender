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
import requests

from ai_analyst import ai_enhanced_signal
from constants import STOCKS, get_mult
from indicators import add_indicators, score_stock

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
# CURRENCY RATE FETCHERS  (plain — no Streamlit cache)
# ─────────────────────────────────────────────
def _eur_rate() -> float:
    try:    return 1.0 / yf.Ticker("EURUSD=X").fast_info["last_price"]
    except: return 0.92  # noqa: E731

def _inr_eur_rate() -> float:
    try:    return 1.0 / yf.Ticker("EURINR=X").fast_info["last_price"]
    except: return 1.0 / 87.5  # noqa: E731

# ─────────────────────────────────────────────
# NEWS FETCH  (lightweight — no Streamlit cache)
# ─────────────────────────────────────────────
def _fetch_headlines(sym: str) -> list[str]:
    """Return up to 5 recent news headlines for a ticker."""
    try:
        raw = yf.Ticker(sym).news
        if not raw:
            return []
        titles = []
        for item in raw[:5]:
            content = item.get("content", item)
            title   = content.get("title") or item.get("title", "")
            if title:
                titles.append(title)
        return titles
    except Exception:
        return []


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
                df         = add_indicators(df)
                scored     = score_stock(df, "Balanced")
                mult       = get_mult(sym, eur_r, inr_r)
                res = {
                    "symbol": sym,
                    "name":   name,
                    "market": market,
                    "score":  scored["score"],
                    "rec":    scored["recommendation"],
                    "rsi":    scored["rsi"],
                    "price":  float(scored["close"]),
                    "eur":    float(scored["close"]) * mult,
                }
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
                # AI reasoning for top-3 per market (avoids excess API calls)
                try:
                    if top5.index(r) < 3:
                        headlines = _fetch_headlines(r["symbol"])
                        ai = ai_enhanced_signal(
                            symbol        = r["symbol"],
                            name          = r["name"],
                            rule_score    = r["score"],
                            rule_signal   = r["rec"],
                            rsi           = float(r["rsi"]) if not pd.isna(r["rsi"]) else None,
                            macd_status   = "MACD above signal" if r["score"] > 0 else "MACD below signal",
                            sma20_pos     = "Above SMA20" if r["score"] > 0 else "Below SMA20",
                            sma50_pos     = "Above SMA50" if r["score"] > 1 else "Below SMA50",
                            bollinger_pos = "Inside bands",
                            volume_status = "Normal volume",
                            pct_chg_1m    = None,
                            pct_chg_6m    = None,
                            news_headlines = headlines,
                        )
                        if ai:
                            sig_emoji = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(ai["signal"], "")
                            lines.append(
                                f"    <i>🤖 AI ({ai.get('provider','AI')}): {sig_emoji} {ai['signal']} "
                                f"({ai['confidence']}%) — {ai['reasoning']}</i>"
                            )
                except Exception:
                    pass  # AI enrichment is best-effort; never block Telegram send
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
