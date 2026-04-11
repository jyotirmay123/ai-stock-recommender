# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Preferred — uses uv venv
uv run streamlit run stock_analyser.py

# Or activate the venv first
source .venv/bin/activate
streamlit run stock_analyser.py \
  --server.headless true \
  --theme.base dark \
  --theme.primaryColor "#1E88E5"
```

The app is served at `http://localhost:8501`. Theme and server defaults are already in [.streamlit/config.toml](.streamlit/config.toml), so the flags above are optional.

## Dependency management

```bash
uv sync          # install / sync all deps from pyproject.toml
```

`pyproject.toml` uses `tool.uv.package = false` — this is **not** an installable package; never add a `[build-system]` section or try to build a wheel.

## Secrets / configuration

Secrets live in `.streamlit/secrets.toml` (git-ignored). Use [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) as the template. On Streamlit Cloud, paste the same keys in App settings → Secrets.

Required secrets:

- `APP_PASSWORD` — leave empty for open access
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional, disables Telegram push if absent
- `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` — one is needed for portfolio screenshot OCR; first configured key wins

## Running the daily picks sender

```bash
python daily_picks.py
```

Standalone script (no Streamlit), reads secrets from `.streamlit/secrets.toml` or env vars. Intended to run on a cron/scheduler every weekday at 09:00 Berlin time.

**GitHub Actions automation** — `.github/workflows/daily_picks.yml` runs `daily_picks.py` every weekday at 06:00 UTC (≈08:00 Berlin). Uses `actions/checkout@v6` and `actions/setup-python@v6` (Node.js 24 native). Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the repo's Settings → Secrets and variables → Actions.

## Architecture

There are seven Python files, organised by single responsibility:

**[constants.py](constants.py)** — Pure data and pure helper functions. No external deps. Shared by all modules:

- `STOCKS`, `RISK_PARAMS` — ticker universe and risk-profile thresholds
- `EUR_SUFFIXES`, `INR_SUFFIXES`, `is_eur_symbol`, `is_inr_symbol`, `get_mult` — currency helpers
- `BULLISH_WORDS`, `BEARISH_WORDS` — news-sentiment keyword sets
- `QTYPE_ICON` — quote-type emoji map

**[indicators.py](indicators.py)** — Technical indicator computation and scoring. No Streamlit dependency. Shared by `stock_analyser.py` and `daily_picks.py`:

- `compute_rsi / compute_macd / compute_bollinger / compute_atr / compute_stochastic` — individual indicator functions
- `find_support_resistance`, `compute_fibonacci_levels`, `compute_pivot_points` — advanced level functions
- `add_indicators(df)` — applies all indicators to a price DataFrame
- `score_stock(df, risk)` — produces composite score (−10 to +10) + BUY/HOLD/SELL signal
- `build_result(sym, name, market, df, eur_rate, inr_eur_rate, risk)` — flat result dict used by the UI

**[chart_builder.py](chart_builder.py)** — Plotly chart construction. No Streamlit dependency:

- `_add_level(fig, price, ...)` — draws a horizontal level line with a labelled annotation
- `build_chart(df, symbol, name, mult, show_sr, show_fib, show_pivots, show_stoch)` — multi-panel Plotly figure

**[ai_analyst.py](ai_analyst.py)** — AI-enhanced signal analysis module (no Streamlit dependency). Owns:

- `ai_enhanced_signal()` — sends indicator + news context to a small LLM (Groq `llama-3.1-8b-instant` first, Anthropic `claude-haiku-4-5` fallback) and returns `{signal, confidence, reasoning, provider}`
- `build_indicator_context()` — converts the `signals` dict from `score_stock()` into human-readable strings for the prompt
- File-based cache (`ai_analysis_cache.json`, one entry per ticker per calendar day) — prevents redundant API calls across Streamlit re-renders and `daily_picks.py` runs
- `_get_secret()` — resolves secrets from Streamlit secrets, `.streamlit/secrets.toml`, or env vars so the module works in both Streamlit and standalone contexts

**[stock_analyser.py](stock_analyser.py)** — the Streamlit app entry point. Owns:

- `get_eur_rate`, `get_inr_eur_rate` — `@st.cache_data(ttl=300)` live FX rate fetchers
- `fetch_stock_data` — `yfinance` download, cached 5 min via `@st.cache_data`
- News sentiment (`fetch_news`, `news_sentiment`) — simple keyword scoring on Yahoo Finance headlines
- `get_ai_signal()` — `@st.cache_data(ttl=3600)` wrapper around `ai_analyst.ai_enhanced_signal`; shown in the deep-dive signal panel as an "🤖 AI Analysis" card with signal, confidence %, and reasoning
- `render_deep_dive()` — chart panel with overlay checkboxes, full-width AI card, Advanced Metrics expander (ATR · Stochastic · Pivots), and news list
- `format_telegram_picks` — formats watchlist BUY picks + tracked-buy SELL alerts for Telegram
- UI rendering: sidebar controls, watchlist tabs (including "Tracked Buy Recommendations" section), ticker search, portfolio tab

**[portfolio_manager.py](portfolio_manager.py)** — imported by `stock_analyser.py`. Owns:

- `portfolio.json` persistence (`load_portfolio`, `save_portfolio`)
- AI screenshot OCR (`parse_screenshot_with_ai`) — uploads a brokerage screenshot to Anthropic/Gemini/Groq and extracts holdings as JSON
- `portfolio_summary` — enriches holdings with live prices and EUR P&L
- `generate_portfolio_recommendations` / `apply_recommendation` / `disapprove_recommendation` — AI-generated rebalancing suggestions with approve/reject workflow
- `format_portfolio_telegram` — formats portfolio summary for Telegram push

**[daily_picks.py](daily_picks.py)** — standalone script. Imports shared logic from `constants.py` and `indicators.py` (no Streamlit dep). Each run:

1. Sends top BUY picks per market to Telegram
2. For the top-3 picks per market, calls `ai_analyst.ai_enhanced_signal()` and appends the AI reasoning line to the Telegram message
3. Persists newly recommended BUY tickers to `portfolio.json` → `tracked_buys`
4. Checks all tracked tickers for SELL signals and appends a sell-alert section to the Telegram message
5. Increments `consecutive_sell_days` per ticker; removes any ticker that hits 3 consecutive SELL days

## Tracked Buys

`portfolio.json` contains a `tracked_buys` key — a dict keyed by ticker symbol. Every ticker that appears in the daily top-5 BUY picks is automatically added here. The structure per entry:

```json
{
  "NVDA": {
    "name": "NVIDIA",
    "market": "🇺🇸 US S&P 500",
    "first_recommended": "2026-01-15",
    "last_recommended": "2026-04-10",
    "price_at_recommendation": 850.00,
    "consecutive_sell_days": 0
  }
}
```

- `consecutive_sell_days` is incremented each day a tracked ticker scores SELL, reset to 0 on BUY or HOLD
- At 3 consecutive SELL days the ticker is removed automatically (both from `daily_picks.py` and from the Streamlit UI on next load)
- Tickers can be manually seeded in `portfolio.json` (e.g. WIPRO.NS, ASML.AS, BTC-EUR, RELIANCE.NS)
- The "🎯 Tracked Buy Recommendations — Live Signals" section in the Market Watchlist tab renders colour-coded cards: 🟢 green border = BUY, 🟠 orange border = HOLD, 🔴 red border = SELL

## Key data-flow notes

- All prices displayed to the user are in EUR. The multiplier chain is: native price × `get_mult(symbol, eur_rate, inr_eur_rate)`.
- `portfolio.json` stores two sub-portfolios: `india` (INR) and `eu_us` (EUR), plus `tracked_buys` and `recommendations_log`.
- `@st.cache_data(ttl=...)` is used throughout for all network calls; TTLs range from 2 min (live prices) to 30 min (news). AI signals are cached 1 hour in Streamlit memory (`get_ai_signal`) and 24 hours on disk (`ai_analysis_cache.json`).
- The rule-based scoring system is purely arithmetic — no ML model. Each of 6 indicators contributes ±1 or ±2 points to a composite score; the sign and magnitude of `score / 10` vs configurable thresholds determines the signal. The AI layer then validates or challenges this signal with natural-language reasoning.
- `ai_analysis_cache.json` is git-ignored (written at runtime next to `portfolio.json`).
- All timestamps use `Europe/Berlin` timezone (`ZoneInfo("Europe/Berlin")`), not UTC — `now_berlin()` in `stock_analyser.py`, `_now()` in `portfolio_manager.py`.
- `Styler.map()` is used for DataFrame cell styling (pandas ≥2.1 — `.applymap()` was removed).
