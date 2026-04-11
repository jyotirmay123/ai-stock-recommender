"""
ai_analyst.py — AI-enhanced signal analysis for stock tickers.

Uses a small, free LLM to validate and enrich the rule-based BUY/HOLD/SELL
signal with natural-language reasoning and a confidence score.

Provider priority (first configured key wins):
  1. Groq  — GROQ_API_KEY  — llama-3.1-8b-instant  (free tier, very fast)
  2. Anthropic — ANTHROPIC_API_KEY — claude-haiku-4-5  (near-zero cost)

Results are cached in ai_analysis_cache.json (one entry per ticker per day)
so repeated calls within the same day make no API requests.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Optional

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_analysis_cache.json")

# ─────────────────────────────────────────────
# CACHE HELPERS
# ─────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _cache_key(symbol: str) -> str:
    return f"{symbol}_{date.today().isoformat()}"


# ─────────────────────────────────────────────
# SECRET RESOLUTION  (works with both Streamlit
# secrets and plain env vars / .streamlit/secrets.toml)
# ─────────────────────────────────────────────

def _get_secret(key: str) -> str:
    """Read a secret from Streamlit secrets (if available) or env vars."""
    try:
        import streamlit as st  # noqa: PLC0415
        return st.secrets.get(key, "") or os.environ.get(key, "")
    except Exception:
        pass
    # Fallback: read .streamlit/secrets.toml directly (for daily_picks.py)
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            tomllib = None  # type: ignore[assignment]
    if tomllib is not None:
        toml_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".streamlit",
            "secrets.toml",
        )
        try:
            with open(toml_path, "rb") as f:
                secrets = tomllib.load(f)
            return secrets.get(key, "") or os.environ.get(key, "")
        except Exception:
            pass
    return os.environ.get(key, "")


# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────

def _build_prompt(
    symbol: str,
    name: str,
    rule_score: int,
    rule_signal: str,
    rsi: float | None,
    macd_status: str,
    sma20_pos: str,
    sma50_pos: str,
    bollinger_pos: str,
    volume_status: str,
    pct_chg_1m: float | None,
    pct_chg_6m: float | None,
    news_headlines: list[str],
) -> str:
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
    chg_1m  = f"{pct_chg_1m:+.1f}%" if pct_chg_1m is not None else "N/A"
    chg_6m  = f"{pct_chg_6m:+.1f}%" if pct_chg_6m is not None else "N/A"
    headlines_str = (
        "\n".join(f"  - {h}" for h in news_headlines[:5])
        if news_headlines
        else "  (no recent news available)"
    )

    return f"""You are a quantitative financial analyst. Analyse the following technical data for {name} ({symbol}) and give a concise trading signal assessment.

Technical Summary:
- Rule-based composite score: {rule_score:+d}/10  →  {rule_signal}
- RSI (14): {rsi_str}
- MACD vs signal line: {macd_status}
- Price vs SMA20: {sma20_pos}
- Price vs SMA50: {sma50_pos}
- Bollinger Band position: {bollinger_pos}
- Volume vs 20-day MA: {volume_status}
- 1-month return: {chg_1m}
- 6-month return: {chg_6m}

Recent News Headlines:
{headlines_str}

Task: Based on the technical indicators and news context, determine the most appropriate trading signal. Consider whether the rule-based signal is well-supported or if news context changes the picture.

Return ONLY valid JSON with exactly this structure (no markdown, no extra text):
{{"signal": "BUY", "confidence": 72, "reasoning": "2-3 sentences explaining the key drivers behind the signal."}}

signal must be one of: BUY, HOLD, SELL
confidence must be an integer from 0 to 100"""


# ─────────────────────────────────────────────
# PROVIDERS
# ─────────────────────────────────────────────

def _call_groq(prompt: str, api_key: str) -> Optional[str]:
    """Call Groq chat completions API (OpenAI-compatible)."""
    import requests  # noqa: PLC0415

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 200,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None


def _call_anthropic(prompt: str, api_key: str) -> Optional[str]:
    """Call Anthropic Messages API using claude-haiku-4-5."""
    import requests  # noqa: PLC0415

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        if resp.ok:
            return resp.json()["content"][0]["text"]
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# RESPONSE PARSER
# ─────────────────────────────────────────────

def _parse_response(raw: str) -> Optional[dict]:
    """Extract and validate JSON from model output."""
    if not raw:
        return None
    # Strip markdown fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    # Try to locate a JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    signal = str(data.get("signal", "")).upper()
    if signal not in {"BUY", "HOLD", "SELL"}:
        return None

    try:
        confidence = max(0, min(100, int(data.get("confidence", 50))))
    except (TypeError, ValueError):
        confidence = 50

    reasoning = str(data.get("reasoning", "")).strip()
    if not reasoning:
        return None

    return {"signal": signal, "confidence": confidence, "reasoning": reasoning}


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def ai_enhanced_signal(
    symbol: str,
    name: str,
    rule_score: int,
    rule_signal: str,
    rsi: float | None,
    macd_status: str,
    sma20_pos: str,
    sma50_pos: str,
    bollinger_pos: str,
    volume_status: str,
    pct_chg_1m: float | None,
    pct_chg_6m: float | None,
    news_headlines: list[str],
) -> Optional[dict]:
    """
    Return AI-enhanced signal dict or None if no API key is configured.

    Return value:
        {
            "signal":     "BUY" | "HOLD" | "SELL",
            "confidence": int (0–100),
            "reasoning":  str,
            "provider":   str,
        }
    Results are cached by ticker + date to avoid repeated API calls.
    """
    cache = _load_cache()
    key   = _cache_key(symbol)
    if key in cache:
        return cache[key]

    groq_key      = _get_secret("GROQ_API_KEY")
    anthropic_key = _get_secret("ANTHROPIC_API_KEY")

    if not groq_key and not anthropic_key:
        return None  # no provider configured — silently skip

    prompt = _build_prompt(
        symbol=symbol, name=name,
        rule_score=rule_score, rule_signal=rule_signal,
        rsi=rsi, macd_status=macd_status,
        sma20_pos=sma20_pos, sma50_pos=sma50_pos,
        bollinger_pos=bollinger_pos, volume_status=volume_status,
        pct_chg_1m=pct_chg_1m, pct_chg_6m=pct_chg_6m,
        news_headlines=news_headlines,
    )

    raw: Optional[str] = None
    provider = ""

    if groq_key:
        raw = _call_groq(prompt, groq_key)
        provider = "Groq llama-3.1-8b"

    if raw is None and anthropic_key:
        raw = _call_anthropic(prompt, anthropic_key)
        provider = "Anthropic claude-haiku"

    result = _parse_response(raw) if raw else None
    if result:
        result["provider"] = provider
        # Persist in cache
        cache[key] = result
        _save_cache(cache)

    return result


def build_indicator_context(signals: dict, volume_status: str = "Normal volume") -> dict:
    """
    Extract human-readable strings from score_stock() signals dict.
    Returns keyword args suitable for ai_enhanced_signal().
    """
    def _label(key: str, default: str) -> str:
        entry = signals.get(key)
        if entry:
            return entry[0]  # e.g. "🟢 Oversold"
        return default

    return {
        "macd_status":    _label("MACD",         "No MACD data"),
        "sma20_pos":      _label("SMA20",         "No SMA20 data"),
        "sma50_pos":      _label("SMA50",         "No SMA50 data"),
        "bollinger_pos":  _label("Bollinger",     "No Bollinger data"),
        "volume_status":  _label("Volume",        volume_status),
    }
