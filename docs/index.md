---
title: Home
nav_order: 1
description: "Real-time BUY/HOLD/SELL signals for EU, US, Indian stocks and crypto — prices in EUR"
permalink: /
---

[![Daily Stock Picks → Telegram](https://github.com/jyotirmay123/ai-stock-recommender/actions/workflows/daily_picks.yml/badge.svg)](https://github.com/jyotirmay123/ai-stock-recommender/actions/workflows/daily_picks.yml)

Real-time technical analysis · BUY / HOLD / SELL signals · Prices in **EUR**

A browser-based stock screener built with **Streamlit** and **Yahoo Finance**.
Covers European blue-chips, US S&P 500, Indian NSE stocks, Bitcoin, and any global ticker — all prices automatically converted to Euros.

---

## Quick Start

```bash
git clone https://github.com/jyotirmay123/ai-stock-recommender.git
cd ai-stock-recommender
uv sync
uv run streamlit run stock_analyser.py
```

Open `http://localhost:8501` in your browser.

---

## Features

| Feature | Detail |
| --- | --- |
| Global Coverage | EU, US S&P 500, Indian NSE, Bitcoin + search any ticker worldwide |
| 6 Technical Indicators | RSI, MACD crossover, SMA 20/50/200, Bollinger Bands, Volume confirmation |
| Composite Score | Each indicator contributes points → single −10 to +10 score |
| BUY / HOLD / SELL | Threshold-based recommendation driven by score + risk profile |
| 3 Risk Profiles | Conservative · Balanced · Aggressive |
| Live EUR Conversion | Live EURUSD=X and EURINR=X rates from Yahoo Finance; fallback rates if unavailable |
| Smart Ticker Search | Enter a ticker or company name; fuzzy Yahoo Finance search suggests matches |
| Interactive Charts | Plotly candlestick + SMA/BB overlays, RSI panel, MACD histogram |
| Portfolio Tracker | Track EU/US and Indian holdings with live P&L in EUR |
| AI Screenshot OCR | Upload a brokerage screenshot to auto-import holdings (Anthropic/Gemini/Groq) |
| Tracked Buy Recommendations | Previously recommended BUY tickers tracked live with current signal cards |
| Sell Alerts | Tracked tickers showing SELL signal appear highlighted in the UI and Telegram |
| Auto-Cleanup | Tracked tickers are automatically removed after 3 consecutive SELL days |
| Daily Telegram Picks | Automated weekday BUY-picks digest + sell alerts via GitHub Actions + Telegram bot |

---

## Scoring Methodology

Each of six indicators contributes points to a composite score (max ±10):

| Indicator | Points | Bullish Condition | Bearish Condition |
| --- | --- | --- | --- |
| **RSI** | ±2/3 | RSI < buy threshold (oversold) | RSI > sell threshold (overbought) |
| **MACD** | ±1 or ±2 | Bullish crossover or above signal | Bearish crossover or below signal |
| **SMA 20** | ±1 | Price above 20-day moving average | Price below 20-day moving average |
| **SMA 50** | ±1 | Price above 50-day moving average | Price below 50-day moving average |
| **Bollinger Bands** | ±1 | Price below lower band | Price above upper band |
| **Volume** | 0 or ±1 | Volume > 1.5× 20-day average | Normal volume = 0 pts |

Recommendation thresholds:

```text
score ≥ +3  →  BUY
score ≤ −3  →  SELL
otherwise   →  HOLD
```

---

## Risk Profiles

| Profile | RSI Buy Below | RSI Sell Above | Min Score (BUY) |
| --- | --- | --- | --- |
| Conservative | 35 | 65 | 4 |
| Balanced *(default)* | 40 | 60 | 3 |
| Aggressive | 45 | 55 | 2 |

---

## Tracked Buy Recommendations

Every ticker that appears in the daily top-5 BUY picks is automatically saved to `portfolio.json` under `tracked_buys`. The **🎯 Tracked Buy Recommendations — Live Signals** section in the Market Watchlist tab renders a colour-coded card for each tracked ticker showing its current signal, score, RSI, and P&L since recommendation.

**Signal colours:**

- 🟢 Green border — currently BUY
- 🟠 Orange border — currently HOLD
- 🔴 Red border — currently SELL

**Auto-removal:** if a tracked ticker scores SELL for 3 consecutive days, it is automatically removed from the tracked list and the UI. It will be re-added the next time it appears as a top BUY pick.

**Sell alerts in Telegram:** the daily Telegram message includes a "Tracked Buys — Now Showing SELL Signal" section so you know when to consider selling positions you opened based on prior recommendations.

Tickers can be manually seeded directly in `portfolio.json` under the `tracked_buys` key (e.g. to track positions opened before the app was set up).

---

## Configuration

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in:

```toml
APP_PASSWORD       = ""          # leave empty for open access
TELEGRAM_BOT_TOKEN = ""          # optional
TELEGRAM_CHAT_ID   = ""          # optional
ANTHROPIC_API_KEY  = ""          # for portfolio screenshot OCR
GEMINI_API_KEY     = ""          # alternative OCR provider (free)
GROQ_API_KEY       = ""          # alternative OCR provider (free)
```

On Streamlit Cloud, paste the same key=value pairs in **App settings → Secrets**.

---

## Daily Picks — GitHub Actions

The workflow at `.github/workflows/daily_picks.yml` sends a Telegram message every weekday at ~08:00 Berlin time (06:00 UTC) containing:

1. **Top BUY picks** — up to 5 per market, sorted by score
2. **Tracked Buys → SELL** — any previously recommended ticker now showing a SELL signal, with score, RSI, P&L since recommendation, and consecutive sell-day count

Uses `actions/checkout@v6` and `actions/setup-python@v6` (Node.js 24 native — no deprecation warnings).

To enable, add these secrets to your GitHub repo (**Settings → Secrets and variables → Actions**):

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

You can also trigger it manually from the **Actions** tab.

---

## Architecture

```text
stock_analyser.py      — Streamlit app (entry point, all UI, indicators, scoring, tracked buys UI)
portfolio_manager.py   — Portfolio state, AI OCR, recommendations, Telegram formatting
daily_picks.py         — Standalone Telegram digest (BUY picks + sell alerts, tracked_buys persistence)
portfolio.json         — Persistent state: holdings, recommendations_log, tracked_buys
.streamlit/
  config.toml          — Theme + server defaults
  secrets.toml         — API keys (git-ignored)
  secrets.toml.example — Template
.github/workflows/
  daily_picks.yml      — GitHub Actions cron (Mon–Fri 06:00 UTC)
docs/
  index.md             — This page (GitHub Pages / wiki)
  _config.yml          — Jekyll config
```

---

## Technical Stack

| Library | Purpose |
| --- | --- |
| `streamlit` ≥1.32 | Web dashboard & UI |
| `yfinance` ≥0.2 | Live market data (Yahoo Finance) |
| `pandas` ≥2.1 | Data manipulation (`Styler.map()` — not deprecated `applymap`) |
| `numpy` ≥1.26 | Numerical calculations |
| `plotly` ≥5.18 | Interactive candlestick charts |
| `requests` ≥2.31 | Yahoo Finance search API + Telegram Bot API |
| `pillow` ≥9.0 | Image handling for screenshot OCR |

---

## Disclaimer

This tool is for **informational and educational purposes only** and does **not** constitute financial advice. All signals are derived from historical price data using standard technical analysis rules. Past signals do not guarantee future performance.

---

*Data sourced from [Yahoo Finance](https://finance.yahoo.com). Built with [Streamlit](https://streamlit.io).*
