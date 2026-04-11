"""
chart_builder.py — Plotly chart construction for the stock analyser.

No Streamlit dependency — can be imported anywhere Plotly is available.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from indicators import (
    find_support_resistance,
    compute_fibonacci_levels,
    compute_pivot_points,
)


def _add_level(
    fig: go.Figure,
    price: float,
    line_color: str,
    dash: str,
    label: str,
    label_color: str,
    x_anchor: float,          # 0.0 = left edge, 1.0 = right edge
) -> None:
    """Draw a horizontal price level line with a small labelled annotation tag."""
    fig.add_shape(
        type="line", xref="paper", yref="y",
        x0=0, x1=1, y0=price, y1=price,
        line=dict(color=line_color, width=1, dash=dash),
        layer="below",
    )
    fig.add_annotation(
        xref="paper", yref="y",
        x=x_anchor, y=price,
        text=label, showarrow=False,
        font=dict(size=8, color=label_color),
        bgcolor="rgba(14,17,23,0.75)",
        borderpad=2,
        xanchor="left" if x_anchor < 0.5 else "right",
        yanchor="middle",
    )


def build_chart(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    mult: float,
    show_sr: bool = True,
    show_fib: bool = False,
    show_pivots: bool = False,
    show_stoch: bool = False,
) -> go.Figure:
    """
    Build a multi-panel Plotly figure for a stock.

    Panels: candlestick + overlays · RSI · MACD · (optional) Stochastic
    """
    n_rows  = 4 if show_stoch else 3
    heights = [0.46, 0.18, 0.18, 0.18] if show_stoch else [0.55, 0.22, 0.23]
    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=heights, vertical_spacing=0.04,
    )

    # ── Panel 1: Candlestick ─────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"] * mult, high=df["High"] * mult,
        low=df["Low"]   * mult, close=df["Close"] * mult,
        name="Price",
        increasing_line_color="#26A69A", decreasing_line_color="#EF5350",
        showlegend=False,
    ), row=1, col=1)

    # ── Moving averages ───────────────────────
    for label, col, color, width in [
        ("SMA 20",  "SMA20",  "#42A5F5", 1.2),
        ("SMA 50",  "SMA50",  "#FFA726", 1.2),
        ("SMA 200", "SMA200", "#CE93D8", 2.2),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col] * mult,
                name=label, line=dict(color=color, width=width), opacity=0.9,
            ), row=1, col=1)

    # ── Bollinger Bands ───────────────────────
    if "BB_Upper" in df.columns and "BB_Lower" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"] * mult, name="BB ±2σ",
            line=dict(color="#78909C", dash="dot", width=1), opacity=0.6,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"] * mult,
            line=dict(color="#78909C", dash="dot", width=1),
            fill="tonexty", fillcolor="rgba(120,144,156,0.07)",
            opacity=0.6, showlegend=False,
        ), row=1, col=1)

    # ── Support & Resistance lines ────────────
    # Support labels LEFT edge, resistance labels RIGHT edge — never overlap
    if show_sr:
        supports, resistances = find_support_resistance(df["Close"])
        for lvl in supports:
            _add_level(fig, lvl * mult,
                       "rgba(0,200,83,0.45)", "dash",
                       f"S  €{lvl * mult:,.0f}", "rgba(0,220,100,0.9)", 0.01)
        for lvl in resistances:
            _add_level(fig, lvl * mult,
                       "rgba(255,82,82,0.45)", "dash",
                       f"€{lvl * mult:,.0f}  R", "rgba(255,100,100,0.9)", 0.99)

    # ── Fibonacci retracement (last 90 candles ≈ 4 months) ──────────
    if show_fib:
        window   = df.tail(90)
        fib_high = float(window["High"].max())
        fib_low  = float(window["Low"].min())
        fib_pcts = {
            "78.6": 0.214, "61.8": 0.382, "50.0": 0.500,
            "38.2": 0.618, "23.6": 0.764,
        }
        _add_level(fig, fib_high * mult, "rgba(251,191,36,0.5)", "dot",
                   "100%", "#FBBF24", 0.98)
        _add_level(fig, fib_low  * mult, "rgba(251,191,36,0.5)", "dot",
                   "0%",   "#FBBF24", 0.98)
        for pct_label, ratio in fib_pcts.items():
            price = fib_high - ratio * (fib_high - fib_low)
            _add_level(fig, price * mult, "rgba(251,191,36,0.35)", "dot",
                       pct_label, "#FCD34D", 0.98)

    # ── Pivot points — R labels right, S labels left, PP centre ─────
    if show_pivots:
        piv = compute_pivot_points(df)
        piv_cfg = {
            "PP":  ("rgba(167,139,250,0.6)", "longdash", "#A78BFA", 0.50),
            "R1":  ("rgba(248,113,113,0.6)", "longdash", "#F87171", 0.99),
            "R2":  ("rgba(239,68,68,0.6)",   "longdash", "#EF4444", 0.99),
            "S1":  ("rgba(74,222,128,0.6)",  "longdash", "#4ADE80", 0.01),
            "S2":  ("rgba(22,163,74,0.6)",   "longdash", "#16A34A", 0.01),
        }
        for lbl, (lc, dash, fc, xa) in piv_cfg.items():
            _add_level(fig, piv[lbl] * mult, lc, dash, lbl, fc, xa)

    # ── Panel 2: RSI ─────────────────────────
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(color="#26C6DA", width=1.5), showlegend=False,
        ), row=2, col=1)
        for lvl, clr in [(70, "rgba(239,83,80,0.4)"), (50, "rgba(160,160,160,0.18)"),
                         (30, "rgba(38,166,154,0.4)")]:
            fig.add_hline(y=lvl, line_dash="dot", line_color=clr, row=2, col=1)

    # ── Panel 3: MACD ────────────────────────
    if "MACD_Hist" in df.columns:
        hist_colors = ["#26A69A" if v >= 0 else "#EF5350"
                       for v in df["MACD_Hist"].fillna(0)]
        fig.add_trace(go.Bar(
            x=df.index, y=df["MACD_Hist"],
            name="Hist", marker_color=hist_colors, opacity=0.55, showlegend=False,
        ), row=3, col=1)
    for col_name, color, lbl in [("MACD", "#42A5F5", "MACD"),
                                   ("MACD_Signal", "#FFA726", "Signal")]:
        if col_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col_name], name=lbl,
                line=dict(color=color, width=1.3), showlegend=False,
            ), row=3, col=1)

    # ── Panel 4: Stochastic (optional) ───────
    if show_stoch and "Stoch_K" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Stoch_K"], name="%K",
            line=dict(color="#F472B6", width=1.3), showlegend=False,
        ), row=4, col=1)
        if "Stoch_D" in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df["Stoch_D"], name="%D",
                line=dict(color="#C084FC", width=1.3, dash="dot"), showlegend=False,
            ), row=4, col=1)
        for lvl, clr in [(80, "rgba(239,83,80,0.4)"), (20, "rgba(38,166,154,0.4)")]:
            fig.add_hline(y=lvl, line_dash="dot", line_color=clr, row=4, col=1)

    # ── Layout ───────────────────────────────
    fig.update_layout(
        height=730 if show_stoch else 660,
        template="plotly_dark",
        paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h", yanchor="top", y=1.01, xanchor="left", x=0,
            font=dict(size=11), bgcolor="rgba(14,17,23,0.7)",
            bordercolor="rgba(255,255,255,0.08)", borderwidth=1,
        ),
        margin=dict(l=10, r=10, t=8, b=8),
        hoverlabel=dict(bgcolor="#1A1F36", font_size=12),
    )
    fig.update_yaxes(tickprefix="€", tickformat=",.0f",
                     gridcolor="rgba(255,255,255,0.05)", row=1, col=1)
    fig.update_yaxes(title_text="RSI", title_standoff=4, range=[0, 100],
                     title_font=dict(size=10, color="#888"),
                     gridcolor="rgba(255,255,255,0.05)", row=2, col=1)
    fig.update_yaxes(title_text="MACD", title_standoff=4,
                     title_font=dict(size=10, color="#888"),
                     gridcolor="rgba(255,255,255,0.05)", row=3, col=1)
    if show_stoch:
        fig.update_yaxes(title_text="Stoch %", title_standoff=4, range=[0, 100],
                         title_font=dict(size=10, color="#888"),
                         gridcolor="rgba(255,255,255,0.05)", row=4, col=1)
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.04)")
    return fig
