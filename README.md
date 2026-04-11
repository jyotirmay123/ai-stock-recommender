# 📈 AI Stock Investment Recommender

[![Daily Stock Picks → Telegram](https://github.com/jyotirmay123/ai-stock-recommender/actions/workflows/daily_picks.yml/badge.svg)](https://github.com/jyotirmay123/ai-stock-recommender/actions/workflows/daily_picks.yml)

> Real-time technical analysis · BUY / HOLD / SELL signals · Prices in **€ (EUR)**

A fully interactive, browser-based stock screener and investment analyser built with
**Streamlit** and **Yahoo Finance**.  It covers European blue-chips, the US S&P 500,
Bitcoin, and **any global ticker** (stocks, ETFs, indices, crypto, futures, commodities)
— all with prices automatically converted to Euros.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 🌍 Global Coverage | EU, US S&P 500, Bitcoin watchlist **+** search for any ticker worldwide |
| 📡 6 Technical Indicators | RSI, MACD crossover, SMA 20/50, Bollinger Bands, Volume confirmation |
| 🧮 Composite Score | Each indicator contributes points → single −10 to +10 score |
| 🟢🟡🔴 BUY / HOLD / SELL | Threshold-based recommendation driven by score + risk profile |
| ⚖️ 3 Risk Profiles | Conservative · Balanced · Aggressive (adjusts RSI thresholds & score minimums) |
| 💱 Live EUR Conversion | Live EURUSD=X rate from Yahoo Finance; fallback 0.92 |
| 🔍 Smart Ticker Search | Enter a ticker OR company name; fuzzy Yahoo Finance search suggests matches |
| 🕯️ Interactive Charts | Plotly candlestick + SMA/BB overlays, RSI panel, MACD histogram |
| 📖 Hover Tooltips | 25+ financial terms explained on hover (educational mode) |
| 📚 How It Works tab | Full methodology, glossary, scoring tables, and chart guide |

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ai-stock-recommender.git
cd ai-stock-recommender
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the app

**Option A — shell script (recommended)**

```bash
bash run_analyser.sh
```

**Option B — direct Streamlit command**

```bash
streamlit run stock_analyser.py \
  --server.headless true \
  --theme.base dark \
  --theme.primaryColor "#1E88E5"
```

### 4. Open in browser

```
http://localhost:8501
```

---

## 📁 Project Structure

```
ai-stock-recommender/
├── stock_analyser.py      # Main Streamlit application
├── run_analyser.sh        # One-click launcher (installs deps + starts app)
├── requirements.txt       # Python dependencies
├── .gitignore             # Git ignore rules
└── README.md              # This file
```

---

## 🧮 Scoring Methodology

Each of six indicators contributes points to a composite score (max ±10):

| Indicator | Points | Bullish Condition | Bearish Condition |
|---|---|---|---|
| **RSI** | ±2 | RSI < buy threshold (oversold) | RSI > sell threshold (overbought) |
| **MACD** | ±1 or ±2 | Bullish crossover or above signal | Bearish crossover or below signal |
| **SMA 20** | ±1 | Price above 20-day moving average | Price below 20-day moving average |
| **SMA 50** | ±1 | Price above 50-day moving average | Price below 50-day moving average |
| **Bollinger Bands** | ±1 | Price below lower band | Price above upper band |
| **Volume** | 0 or +1 | Volume > 1.5× 20-day average | Normal volume = 0 pts |

**Recommendation thresholds:**

```
score / 10 ≥  0.30  →  BUY
score / 10 ≤ −0.20  →  SELL
otherwise           →  HOLD
```

---

## ⚖️ Risk Profiles

| Profile | RSI Buy Below | RSI Sell Above | Min Score (BUY) |
|---|---|---|---|
| Conservative | 35 | 65 | 4 |
| Balanced *(default)* | 40 | 60 | 3 |
| Aggressive | 45 | 55 | 2 |

---

## 🌍 Supported Markets (pre-loaded watchlist)

**🇪🇺 European** — ASML, SAP, Siemens, LVMH, TotalEnergies, Airbus, Sanofi, Deutsche Telekom, Allianz, BASF

**🇺🇸 US S&P 500** — Apple, Microsoft, NVIDIA, Alphabet, Amazon, Meta, Tesla, JPMorgan Chase, Visa, J&J

**₿ Crypto** — Bitcoin (BTC-EUR)

> You can search **any** additional ticker via the "🔍 Search Any Ticker" tab — stocks, ETFs, indices, forex, futures, commodities, and crypto from any global exchange.

---

## 📡 Technical Stack

| Library | Version | Purpose |
|---|---|---|
| `streamlit` | ≥1.32 | Web dashboard & UI |
| `yfinance` | ≥0.2 | Live market data (Yahoo Finance) |
| `pandas` | ≥2.0 | Data manipulation |
| `numpy` | ≥1.26 | Numerical calculations |
| `plotly` | ≥5.18 | Interactive candlestick charts |
| `requests` | ≥2.31 | Yahoo Finance search API (smart ticker lookup) |

---

## 📈 Chart Guide

The interactive chart for each asset has three panels:

1. **Candlestick + Overlays** — price candles with SMA 20 (blue), SMA 50 (orange), SMA 200 (purple dot), Bollinger Bands (grey dash)
2. **RSI** — 14-day RSI with overbought (70) and oversold (30) reference lines
3. **MACD** — Histogram bars (momentum), MACD line (blue), Signal line (orange)

---

## ⚠️ Disclaimer

This tool is for **informational and educational purposes only** and does **not** constitute financial advice.  All signals are derived from historical price data using standard technical analysis rules.  Past signals do not guarantee future performance.

Always conduct your own research and consult a qualified financial advisor before making investment decisions.

---

## 📄 License

MIT License — feel free to fork, modify, and build on this project.
See [LICENSE](LICENSE) for details.

---

*Data sourced from [Yahoo Finance](https://finance.yahoo.com).
Built with [Streamlit](https://streamlit.io) · [yfinance](https://github.com/ranaroussi/yfinance) · [Plotly](https://plotly.com).*
