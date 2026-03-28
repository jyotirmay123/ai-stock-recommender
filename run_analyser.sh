#!/bin/bash
# ─────────────────────────────────────────────────────────
#  AI Stock Investment Recommender — Launcher
# ─────────────────────────────────────────────────────────

echo ""
echo "  📈  AI Stock Investment Recommender"
echo "  ─────────────────────────────────────"
echo "  Installing / checking dependencies…"
echo ""

pip3 install yfinance pandas numpy streamlit plotly --break-system-packages -q 2>/dev/null || \
pip install  yfinance pandas numpy streamlit plotly -q 2>/dev/null

echo ""
echo "  ✅  Launching dashboard on http://localhost:8501"
echo "  Press Ctrl+C to stop."
echo ""

python3 -m streamlit run "$(dirname "$0")/stock_analyser.py" \
  --server.headless true \
  --server.port 8501 \
  --theme.base dark \
  --theme.primaryColor "#1E88E5"
