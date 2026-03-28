"""
Portfolio Manager
=================
Handles portfolio state (load/save), screenshot OCR via Gemini Flash API,
recommendation generation, and Telegram formatting for personal holdings.
"""

import json
import os
import base64
import io
import uuid
import requests
from datetime import datetime
import streamlit as st

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")

_EMPTY_PORTFOLIO = {
    "india": {
        "currency": "INR",
        "last_updated": None,
        "source": None,
        "holdings": {},
    },
    "eu_us": {
        "currency": "EUR",
        "last_updated": None,
        "source": None,
        "holdings": {},
    },
    "settings": {
        "monthly_budget_eur": 625,
        "monthly_budget_inr": None,
    },
    "recommendations_log": [],
}

# ─────────────────────────────────────────────
# LOAD / SAVE
# ─────────────────────────────────────────────
def load_portfolio() -> dict:
    """Load portfolio from JSON file. Returns default structure if not found."""
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
        # Ensure all keys exist (handle older file versions)
        for key in _EMPTY_PORTFOLIO:
            if key not in data:
                data[key] = _EMPTY_PORTFOLIO[key]
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(_EMPTY_PORTFOLIO))


def save_portfolio(data: dict) -> bool:
    """Persist portfolio to JSON file. Returns True on success."""
    try:
        with open(PORTFOLIO_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except Exception as e:
        st.error(f"❌ Could not save portfolio: {e}")
        return False


# ─────────────────────────────────────────────
# MULTI-PROVIDER AI SCREENSHOT PARSING
# ─────────────────────────────────────────────
# Supported providers (auto-detected from secrets, tried in order):
#   1. Anthropic  — ANTHROPIC_API_KEY  — claude-haiku-4-5 (you likely have this)
#   2. Google     — GEMINI_API_KEY     — gemini-1.5-flash  (free tier, 1500 req/day)
#   3. Groq       — GROQ_API_KEY       — llama-3.2-11b-vision (free tier, fast)
# ─────────────────────────────────────────────

INDIA_PROMPT = """
You are a stock-data extractor. Analyse this screenshot from an Indian stock broker app
(AngelOne / Zerodha / Groww / Upstox / Kite).

Extract EVERY holding visible and return ONLY a valid JSON array with this exact format:
[
  {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "qty": 15, "avg_price": 3352.65},
  ...
]

Rules:
- Append .NS to every NSE stock symbol (e.g. TCS → TCS.NS, NIFTYBEES → NIFTYBEES.NS)
- Append .BO for BSE-only symbols if the exchange shown is BSE
- qty  = number of shares / units held (the quantity column)
- avg_price = Average Trade Price (ATP) or average buy price shown (in INR)
- If a field is unclear, make your best guess
- Return ONLY the JSON array. No markdown, no explanation, no extra text.
"""

EU_US_PROMPT = """
You are a stock-data extractor. Analyse this screenshot from a European or US brokerage app
(Trading 212 / eToro / Degiro / Interactive Brokers / Revolut / Robinhood / Schwab).

Extract EVERY holding visible and return ONLY a valid JSON array with this exact format:
[
  {"symbol": "AAPL",   "name": "Apple Inc", "qty": 5,  "avg_price": 150.50, "currency": "USD"},
  {"symbol": "SAP.DE", "name": "SAP SE",    "qty": 3,  "avg_price": 182.00, "currency": "EUR"}
]

Rules:
- Use standard Yahoo Finance ticker symbols
- For European stocks include the exchange suffix (.DE .AS .PA .MI .SW .LS .ST .OL etc.)
- For US stocks use plain symbol (AAPL, MSFT, NVDA, etc.)
- qty = number of shares / fractional shares held
- avg_price = your average cost per share in the listed currency
- currency = EUR, USD, or GBP as shown
- Return ONLY the JSON array. No markdown, no explanation, no extra text.
"""


def _get_secret(key: str) -> str:
    """Read from Streamlit secrets or environment variable."""
    try:
        val = st.secrets.get(key, "")
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(key, "")


def _detect_mime(image_bytes: bytes) -> str:
    if image_bytes[:4] == b"\x89PNG":
        return "image/png"
    if image_bytes[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"


def _compress_image(image_bytes: bytes, max_px: int = 1024, quality: int = 82) -> bytes:
    """
    Resize + JPEG-compress an image so it stays within API payload limits.
    Groq and some other providers reject large base64 payloads (>1 MB raw).
    Returns compressed JPEG bytes. Falls back to original on any error.
    """
    try:
        from PIL import Image  # always available — Streamlit depends on Pillow
        img = Image.open(io.BytesIO(image_bytes))
        # Flatten transparency
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        # Downscale if either dimension exceeds max_px
        w, h = img.size
        if max(w, h) > max_px:
            ratio = max_px / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return image_bytes  # give up silently, try with original


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        # find the part that starts with '[' or '{'
        for part in parts:
            stripped = part.lstrip("json").strip()
            if stripped.startswith("[") or stripped.startswith("{"):
                return stripped
    return t


def _parse_holdings_json(raw_text: str, market_type: str) -> list[dict]:
    """Parse LLM JSON response into normalised holdings list."""
    clean = _strip_fences(raw_text)
    try:
        data = json.loads(clean)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
        result = []
        for h in data:
            sym = str(h.get("symbol", "")).strip().upper()
            if not sym:
                continue
            result.append({
                "symbol":    sym,
                "name":      str(h.get("name", sym)),
                "qty":       float(h.get("qty", 0)),
                "avg_price": float(h.get("avg_price", 0)),
                "currency":  str(h.get("currency",
                                       "INR" if market_type == "india" else "EUR")),
            })
        return result
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(
            f"Could not parse AI JSON output:\n{raw_text[:400]}\nError: {e}"
        )


# ── Provider 1: Anthropic (Claude Haiku) ──────────────────────────────────
def _ocr_anthropic(image_bytes: bytes, mime: str, prompt: str, api_key: str) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model":      "claude-haiku-4-5-20251001",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        json=payload, headers=headers, timeout=40,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


# ── Provider 2: Google Gemini Flash (free tier) ────────────────────────────
def _ocr_gemini(image_bytes: bytes, mime: str, prompt: str, api_key: str) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-1.5-flash:generateContent",
        params={"key": api_key}, json=payload, timeout=40,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


# ── Provider 3: Groq (free tier) ──────────────────────────────────────────
# Model priority: Llama 4 Scout (best free vision) → Llama 4 Maverick → Llama 3.2 90b
_GROQ_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",   # Llama 4, native multimodal, free
    "meta-llama/llama-4-maverick-17b-128e-instruct", # Llama 4, larger, free
    "llama-3.2-90b-vision-preview",                 # Llama 3.2, fallback
    "llama-3.2-11b-vision-preview",                 # Llama 3.2, smallest fallback
]

def _groq_list_vision_models(api_key: str) -> list[str]:
    """Ask Groq which models are currently available, filter for vision-capable ones."""
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if not resp.ok:
            return _GROQ_VISION_MODELS
        ids = {m["id"] for m in resp.json().get("data", [])}
        # Return our preferred list filtered to what's actually available
        available = [m for m in _GROQ_VISION_MODELS if m in ids]
        return available if available else _GROQ_VISION_MODELS
    except Exception:
        return _GROQ_VISION_MODELS


def _ocr_groq(image_bytes: bytes, mime: str, prompt: str, api_key: str) -> str:
    # Compress to ≤800px JPEG — Groq has strict payload limits
    compressed = _compress_image(image_bytes, max_px=800, quality=80)
    b64        = base64.b64encode(compressed).decode()
    data_url   = f"data:image/jpeg;base64,{b64}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    models_to_try = _groq_list_vision_models(api_key)
    last_error    = ""

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            "max_tokens":  2048,
            "temperature": 0.1,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload, headers=headers, timeout=45,
        )
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"]

        # Capture the actual Groq error message for useful feedback
        try:
            groq_msg = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            groq_msg = resp.text[:200]
        last_error = f"[{model}] HTTP {resp.status_code}: {groq_msg}"

        if resp.status_code == 429:   # rate-limited — stop immediately
            break
        # 400/404/503 → try next model

    raise RuntimeError(f"Groq vision failed. Last error: {last_error}")


# ── Main entry point ──────────────────────────────────────────────────────
def parse_screenshot_with_ai(image_bytes: bytes, market_type: str) -> list[dict]:
    """
    Parse a broker portfolio screenshot using the first configured AI provider.
    Priority: Anthropic → Google Gemini → Groq (all free or near-free).
    market_type: 'india' | 'eu_us'
    Returns normalised list of {symbol, name, qty, avg_price, currency}.
    Raises RuntimeError with setup instructions if no key is configured.
    """
    anthropic_key = _get_secret("ANTHROPIC_API_KEY")
    gemini_key    = _get_secret("GEMINI_API_KEY")
    groq_key      = _get_secret("GROQ_API_KEY")

    if not any([anthropic_key, gemini_key, groq_key]):
        raise RuntimeError(
            "No AI API key found. Add **one** of these to `.streamlit/secrets.toml`:\n\n"
            "**Option A — Anthropic** (you likely have this):\n"
            "```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```\n\n"
            "**Option B — Google Gemini Flash** (free, 1500 req/day):\n"
            "Get key at https://aistudio.google.com/apikey\n"
            "```toml\nGEMINI_API_KEY = \"AIza...\"\n```\n\n"
            "**Option C — Groq** (free, very fast):\n"
            "Get key at https://console.groq.com\n"
            "```toml\nGROQ_API_KEY = \"gsk_...\"\n```"
        )

    prompt = INDIA_PROMPT if market_type == "india" else EU_US_PROMPT
    mime   = _detect_mime(image_bytes)
    errors = []

    if anthropic_key:
        try:
            text = _ocr_anthropic(image_bytes, mime, prompt, anthropic_key)
            return _parse_holdings_json(text, market_type)
        except Exception as e:
            errors.append(f"Anthropic: {e}")

    if gemini_key:
        try:
            text = _ocr_gemini(image_bytes, mime, prompt, gemini_key)
            return _parse_holdings_json(text, market_type)
        except Exception as e:
            errors.append(f"Gemini: {e}")

    if groq_key:
        try:
            text = _ocr_groq(image_bytes, mime, prompt, groq_key)
            return _parse_holdings_json(text, market_type)
        except Exception as e:
            errors.append(f"Groq: {e}")

    raise RuntimeError("All AI providers failed:\n" + "\n".join(errors))


# Backward-compatible alias (used in stock_analyser.py)
def parse_screenshot_with_gemini(image_bytes: bytes, market_type: str) -> list[dict]:
    return parse_screenshot_with_ai(image_bytes, market_type)


# ─────────────────────────────────────────────
# PORTFOLIO VALUE HELPERS
# ─────────────────────────────────────────────
def portfolio_summary(holdings: dict, live_prices: dict) -> dict:
    """
    Compute invested, current value, total P&L for a block of holdings.
    live_prices: {symbol: current_price_in_native_currency}
    Returns dict with per-holding rows + totals.
    """
    rows   = []
    total_invested = 0.0
    total_current  = 0.0

    for sym, h in holdings.items():
        qty       = float(h.get("qty", 0))
        avg_price = float(h.get("avg_price", 0))
        live      = live_prices.get(sym)

        invested  = qty * avg_price
        current   = qty * live if live is not None else invested
        pl        = current - invested
        pl_pct    = (pl / invested * 100) if invested else 0.0

        rows.append({
            "symbol":    sym,
            "name":      h.get("name", sym),
            "qty":       qty,
            "avg_price": avg_price,
            "live_price": live,
            "invested":  invested,
            "current":   current,
            "pl":        pl,
            "pl_pct":    pl_pct,
        })
        total_invested += invested
        total_current  += current

    rows.sort(key=lambda x: x["pl_pct"])  # worst performers first
    return {
        "rows": rows,
        "total_invested": total_invested,
        "total_current":  total_current,
        "total_pl":       total_current - total_invested,
        "total_pl_pct":   ((total_current - total_invested) / total_invested * 100)
                          if total_invested else 0.0,
    }


# ─────────────────────────────────────────────
# RECOMMENDATION ENGINE (PORTFOLIO-AWARE)
# ─────────────────────────────────────────────
def generate_portfolio_recommendations(
    portfolio:        dict,
    analysis_results: list,  # list of build_result() dicts from stock_analyser
    inr_eur_rate:     float,
    eur_rate:         float,
) -> list[dict]:
    """
    For each held symbol, check technical signal and suggest SELL/HOLD/BUY MORE.
    For top watchlist BUYs NOT held, suggest allocation from monthly budget.
    Returns list of recommendation dicts.
    """
    monthly_eur = float(portfolio.get("settings", {}).get("monthly_budget_eur") or 625)
    monthly_inr = portfolio.get("settings", {}).get("monthly_budget_inr")
    if monthly_inr is None:
        monthly_inr = monthly_eur / inr_eur_rate

    # Build quick lookup: symbol → analysis result
    analysis_map = {r["symbol"].upper(): r for r in analysis_results}

    recs = []

    # ── 1. Existing holdings ───────────────────
    for market_key, block in [("india", portfolio.get("india", {})),
                               ("eu_us", portfolio.get("eu_us", {}))]:
        holdings = block.get("holdings", {})
        for sym, h in holdings.items():
            ar = analysis_map.get(sym.upper())
            if ar is None:
                continue  # no data available right now

            rec     = ar["recommendation"]   # BUY / HOLD / SELL
            score   = ar["score"]
            rsi     = ar.get("rsi")
            price   = ar.get("price_eur", 0)
            qty     = float(h.get("qty", 0))
            avg_p   = float(h.get("avg_price", 0))

            # Convert avg_price to EUR for unified P&L
            if market_key == "india":
                avg_p_eur = avg_p * inr_eur_rate
            elif sym.upper().endswith((".AS",".DE",".PA",".MI",".SW")):
                avg_p_eur = avg_p
            else:
                avg_p_eur = avg_p * eur_rate

            pl_pct = ((price - avg_p_eur) / avg_p_eur * 100) if avg_p_eur else 0

            if rec == "SELL":
                if pl_pct < -15:
                    action      = "SELL"
                    reason      = f"Stop-loss: down {pl_pct:+.1f}% · Score {score:+d}"
                    urgency     = "HIGH"
                elif pl_pct > 20:
                    action      = "SELL"
                    reason      = f"Take profits: up {pl_pct:+.1f}% · Score {score:+d}"
                    urgency     = "MEDIUM"
                else:
                    action      = "SELL"
                    reason      = f"Bearish signal · Score {score:+d} · {pl_pct:+.1f}%"
                    urgency     = "MEDIUM"
                qty_suggest = qty  # full exit suggestion; user can trim

            elif rec == "BUY" and score >= 4:
                action      = "BUY MORE"
                reason      = f"Add to winner · Score {score:+d} · {pl_pct:+.1f}%"
                urgency     = "LOW"
                # Suggest ~10% of monthly budget
                alloc_eur   = monthly_eur * 0.10
                qty_suggest = max(1, round(alloc_eur / price)) if price > 0 else 0

            else:
                action      = "HOLD"
                reason      = f"Score {score:+d} · {pl_pct:+.1f}%"
                urgency     = "NONE"
                qty_suggest = 0

            recs.append({
                "id":             str(uuid.uuid4())[:8],
                "date":           datetime.now().isoformat(timespec="minutes"),
                "symbol":         sym,
                "name":           h.get("name", sym),
                "market":         market_key,
                "action":         action,
                "reason":         reason,
                "urgency":        urgency,
                "score":          score,
                "rsi":            rsi,
                "price_eur":      price,
                "pl_pct":         pl_pct,
                "qty_held":       qty,
                "qty_suggested":  qty_suggest,
                "amount_eur":     round(qty_suggest * price, 2),
                "status":         "pending",
                "qty_executed":   None,
                "price_executed": None,
                "note":           "",
                "is_new_position": False,
            })

    # ── 2. New position suggestions (from watchlist, not held) ────────────
    held_symbols = set()
    for block in [portfolio.get("india", {}), portfolio.get("eu_us", {})]:
        held_symbols.update(k.upper() for k in block.get("holdings", {}).keys())

    strong_buys = sorted(
        [r for r in analysis_results
         if r["recommendation"] == "BUY"
         and r["symbol"].upper() not in held_symbols
         and r["score"] >= 4],
        key=lambda x: x["score"],
        reverse=True,
    )[:4]

    alloc_weights = [0.40, 0.30, 0.20, 0.10]
    for i, ar in enumerate(strong_buys):
        alloc_eur   = monthly_eur * alloc_weights[i]
        price       = ar.get("price_eur", 0)
        qty_suggest = max(1, round(alloc_eur / price)) if price > 0 else 0

        recs.append({
            "id":             str(uuid.uuid4())[:8],
            "date":           datetime.now().isoformat(timespec="minutes"),
            "symbol":         ar["symbol"],
            "name":           ar["name"],
            "market":         _detect_market(ar["symbol"]),
            "action":         "BUY NEW",
            "reason":         f"New position · Score {ar['score']:+d} · RSI {ar.get('rsi', 0):.0f}",
            "urgency":        "MEDIUM" if ar["score"] >= 6 else "LOW",
            "score":          ar["score"],
            "rsi":            ar.get("rsi"),
            "price_eur":      price,
            "pl_pct":         0.0,
            "qty_held":       0,
            "qty_suggested":  qty_suggest,
            "amount_eur":     round(qty_suggest * price, 2),
            "status":         "pending",
            "qty_executed":   None,
            "price_executed": None,
            "note":           "",
            "is_new_position": True,
        })

    return recs


def _detect_market(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith((".NS", ".BO")):
        return "india"
    return "eu_us"


# ─────────────────────────────────────────────
# APPLY APPROVED RECOMMENDATION → UPDATE PORTFOLIO
# ─────────────────────────────────────────────
def apply_recommendation(portfolio: dict, rec: dict,
                          qty_executed: float, price_executed: float) -> dict:
    """
    Apply an approved recommendation to portfolio holdings.
    Returns updated portfolio dict (caller must call save_portfolio).
    """
    sym    = rec["symbol"]
    market = rec["market"]   # "india" or "eu_us"
    action = rec["action"]

    block    = portfolio.setdefault(market, {"currency": "INR" if market == "india" else "EUR",
                                              "holdings": {}})
    holdings = block.setdefault("holdings", {})

    if action in ("SELL",):
        if sym in holdings:
            current_qty = float(holdings[sym].get("qty", 0))
            new_qty     = max(0.0, current_qty - qty_executed)
            if new_qty <= 0:
                del holdings[sym]
            else:
                holdings[sym]["qty"] = new_qty
        block["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    elif action in ("BUY MORE", "BUY NEW"):
        if sym in holdings:
            # Update average price
            old_qty   = float(holdings[sym].get("qty", 0))
            old_avg   = float(holdings[sym].get("avg_price", 0))
            new_qty   = old_qty + qty_executed
            new_avg   = ((old_qty * old_avg) + (qty_executed * price_executed)) / new_qty
            holdings[sym]["qty"]       = new_qty
            holdings[sym]["avg_price"] = round(new_avg, 4)
        else:
            holdings[sym] = {
                "name":      rec.get("name", sym),
                "qty":       qty_executed,
                "avg_price": price_executed,
            }
        block["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    # Update rec status
    rec["status"]         = "approved"
    rec["qty_executed"]   = qty_executed
    rec["price_executed"] = price_executed

    # Persist to log
    log = portfolio.setdefault("recommendations_log", [])
    log.append(dict(rec))

    return portfolio


def disapprove_recommendation(portfolio: dict, rec: dict, note: str = "") -> dict:
    """Mark a recommendation as disapproved without changing holdings."""
    rec["status"] = "disapproved"
    rec["note"]   = note
    log = portfolio.setdefault("recommendations_log", [])
    log.append(dict(rec))
    return portfolio


# ─────────────────────────────────────────────
# TELEGRAM FORMATTING — PORTFOLIO REPORT
# ─────────────────────────────────────────────
def format_portfolio_telegram(
    portfolio: dict,
    recommendations: list,
    inr_eur_rate: float,
) -> str:
    lines = [
        "💼 <b>Portfolio Report — AI Stock Recommender</b>",
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC",
        "",
    ]

    # India block
    india_holds = portfolio.get("india", {}).get("holdings", {})
    if india_holds:
        lines.append("🇮🇳 <b>India (INR)</b>")
        for sym, h in india_holds.items():
            lines.append(f"  • <code>{sym}</code> {h['name']} — {h['qty']:.0f} @ ₹{h['avg_price']:,.2f}")
        lines.append("")

    # EU/US block
    eu_holds = portfolio.get("eu_us", {}).get("holdings", {})
    if eu_holds:
        lines.append("🌍 <b>EU / US (EUR)</b>")
        for sym, h in eu_holds.items():
            lines.append(f"  • <code>{sym}</code> {h['name']} — {h['qty']:.0f} @ €{h['avg_price']:,.2f}")
        lines.append("")

    # Recommendations
    sells    = [r for r in recommendations if r["action"] == "SELL"     and r["status"] == "pending"]
    buy_more = [r for r in recommendations if r["action"] == "BUY MORE" and r["status"] == "pending"]
    buy_new  = [r for r in recommendations if r["action"] == "BUY NEW"  and r["status"] == "pending"]

    if sells:
        lines.append("🔴 <b>SELL / Exit</b>")
        for r in sells:
            lines.append(
                f"  ⚠️ <code>{r['symbol']}</code> — {r['reason']}"
            )
        lines.append("")

    if buy_more:
        lines.append("🟢 <b>BUY MORE (existing)</b>")
        for r in buy_more:
            lines.append(
                f"  ✅ <code>{r['symbol']}</code> +{r['qty_suggested']} shares"
                f" ≈ €{r['amount_eur']:,.0f} — {r['reason']}"
            )
        lines.append("")

    if buy_new:
        lines.append("🆕 <b>NEW Positions (monthly budget)</b>")
        total = sum(r["amount_eur"] for r in buy_new)
        for r in buy_new:
            lines.append(
                f"  💡 <code>{r['symbol']}</code> {r['name']}"
                f" — {r['qty_suggested']} shares ≈ €{r['amount_eur']:,.0f}"
            )
        lines.append(f"  📦 Total budget used: ≈ €{total:,.0f}")
        lines.append("")

    if not sells and not buy_more and not buy_new:
        lines.append("✅ No urgent actions — portfolio looks stable.")
        lines.append("")

    lines.append("⚠️ <i>For informational purposes only. Not financial advice.</i>")
    return "\n".join(lines)
