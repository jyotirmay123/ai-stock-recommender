---
title: AI Stock Investment Recommender
layout: default
---

# AI Stock Investment Recommender

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
|---|---|
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
| Daily Telegram Picks | Automated weekday BUY-picks digest via GitHub Actions + Telegram bot |

---

## Scoring Methodology

Each of six indicators contributes points to a composite score (max ±10):

| Indicator | Points | Bullish Condition | Bearish Condition |
|---|---|---|---|
| **RSI** | ±2/3 | RSI < buy threshold (oversold) | RSI > sell threshold (overbought) |
| **MACD** | ±1 or ±2 | Bullish crossover or above signal | Bearish crossover or below signal |
| **SMA 20** | ±1 | Price above 20-day moving average | Price below 20-day moving average |
| **SMA 50** | ±1 | Price above 50-day moving average | Price below 50-day moving average |
| **Bollinger Bands** | ±1 | Price below lower band | Price above upper band |
| **Volume** | 0 or ±1 | Volume > 1.5× 20-day average | Normal volume = 0 pts |

Recommendation thresholds:

```
score ≥ +3  →  BUY
score ≤ −3  →  SELL
otherwise   →  HOLD
```

---

## Risk Profiles

| Profile | RSI Buy Below | RSI Sell Above | Min Score (BUY) |
|---|---|---|---|
| Conservative | 35 | 65 | 4 |
| Balanced *(default)* | 40 | 60 | 3 |
| Aggressive | 45 | 55 | 2 |

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

The workflow at `.github/workflows/daily_picks.yml` sends a Telegram message with the top BUY picks every weekday at ~09:00 Berlin time.

To enable it, add these secrets to your GitHub repo (**Settings → Secrets and variables → Actions**):

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

You can also trigger it manually from the **Actions** tab.

---

## Architecture

```
stock_analyser.py      — Streamlit app (entry point, all UI, indicators, scoring)
portfolio_manager.py   — Portfolio state, AI OCR, recommendations, Telegram formatting
daily_picks.py         — Standalone Telegram digest (no Streamlit dependency)
.streamlit/
  config.toml          — Theme + server defaults
  secrets.toml         — API keys (git-ignored)
  secrets.toml.example — Template
.github/workflows/
  daily_picks.yml      — GitHub Actions cron for daily Telegram picks
```

---

## Technical Stack

| Library | Purpose |
|---|---|
| `streamlit` ≥1.32 | Web dashboard & UI |
| `yfinance` ≥0.2 | Live market data (Yahoo Finance) |
| `pandas` ≥2.0 | Data manipulation |
| `numpy` ≥1.26 | Numerical calculations |
| `plotly` ≥5.18 | Interactive candlestick charts |
| `requests` ≥2.31 | Yahoo Finance search API |
| `pillow` ≥9.0 | Image handling for screenshot OCR |

---

## Disclaimer

This tool is for **informational and educational purposes only** and does **not** constitute financial advice. All signals are derived from historical price data using standard technical analysis rules. Past signals do not guarantee future performance.

---

*Data sourced from [Yahoo Finance](https://finance.yahoo.com). Built with [Streamlit](https://streamlit.io).*
