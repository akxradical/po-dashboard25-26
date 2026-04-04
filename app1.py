"""
Central Procurement Dashboard — Zetwerk
Inspired by Quantix UI | Live Google Sheets + Excel KPIs
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread

st.set_page_config(
    page_title="CPT Dashboard | Zetwerk",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Embedded KPI data from Excel ─────────────────────────────────────────────
OTIF_DATA = {
    "BU":          ["O&G",  "Water", "Railways", "CAT-2"],
    "FY26":        [68.00,  71.00,   72.83,       70.61],
    "FY25":        [74.00,  81.90,   68.60,       77.40],
    "Target":      [75,     75,      75,           75],
}

TAT_DATA = {
    "BU":          ["O&G",  "Water", "Railways", "CAT-2"],
    "FY26 PO":     [133,    68,      124,         325],
    "FY25 PO":     [138,    141,     14,          293],
    "FY26 TAT":    [92.0,   68.0,    75.0,        80.5],
    "FY25 TAT":    [98.79,  72.93,   92.21,       86.03],
    "Target TAT":  [90,     90,      90,           90],
}

CAT_DATA = {
    "Category":    ["Pipes","EM","Fittings","Consumables","Cables","Valves","CAPEX","Pumps","Electrical Panel","Sleepers"],
    "Spend FY26":  [195.70, 102.42, 12.30, 5.01, 2.73, 8.90, 1.86, 2.70, 0.90, 1.40],
    "Savings FY26":[15.80,  4.37,   0.60,  1.87, 0.05, -0.20,0.00, 0.40, 0.05, 0.10],
    "Spend FY25":  [180.00, 67.00,  31.10, 5.00, 13.80,13.20, 2.20,20.00, 5.30,10.20],
    "Savings FY25":[3.80,   5.00,   1.20,  0.90, 0.00, 1.48,  1.00, 1.70, 0.30, 0.30],
}

SPEND_DATA = {
    "BU":           ["O&G",  "Water",  "Railways", "ZAP91", "Total"],
    "Spend FY26":   [47.29,  201.02,   24.74,      12.67,   285.72],
    "Savings FY26": [4.91,   16.72,    -1.99,      -0.20,   19.44],
    "Savings% FY26":[9.41,   8.32,     -8.05,      -1.58,   6.80],
    "Spend FY25":   [116.51, 245.52,   36.56,      0,       398.59],
    "Savings FY25": [13.15,  9.76,     2.11,       0,       25.02],
    "Target%":      [4.5,    4.5,      4.5,        None,    None],
}

AOP_DATA = {
    "BU":       ["O&G",  "Water", "Railways", "Total"],
    "AOP":      [55.6,   67.9,    1.61,       125.11],
    "Achieved": [29.0,   43.32,   0.73,       73.05],
    "Variance": [-26.6,  -24.58,  -0.88,      -52.06],
    "Var%":     [-47.8,  -36.2,   -54.7,      -41.6],
}

CREDIT_MONTHS = ["Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec","Jan","Feb"]
CREDIT_FY26   = [5.33, 5.94, 3.64, 4.99, 5.20, 5.35, 5.21, 5.00, 2.11, 1.97, 4.65]
CREDIT_FY25   = [5.97, 5.25, 3.00, 5.09, 4.82, 2.12, 3.60, 4.30, 4.68, 3.97, 5.57]
CREDIT_TARGET = [4.5]*11

SPEND_MONTHLY = [47.26,166.22,11.73,5.35,7.69,6.88,24.42,38.56,26.98,42.20,13.70]

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

*, html, body { font-family: 'DM Sans', sans-serif; }

[data-testid="stAppViewBlockContainer"] {
    padding: 0 !important; max-width: 100% !important;
    background: #0e0e12 !important;
}
[data-testid="stMain"] { background: #0e0e12 !important; }
[data-testid="stSidebar"] { display: none !important; }

/* Header */
.top-nav {
    background: #13131a;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    padding: 0 2rem;
    display: flex; align-items: center; justify-content: space-between;
    height: 56px;
}
.nav-logo { display:flex; align-items:center; gap:10px; }
.nav-logo-mark {
    width:32px; height:32px;
    background: linear-gradient(135deg,#e53e3e,#fc4f4f);
    border-radius:8px; display:flex; align-items:center; justify-content:center;
    font-size:16px; font-weight:900; color:white;
}
.nav-brand { font-size:15px; font-weight:700; color:white; letter-spacing:-0.02em; }
.nav-sub { font-size:11px; color:#666; font-weight:400; }
.nav-tabs { display:flex; gap:2px; }
.nav-tab {
    padding:6px 14px; border-radius:6px; font-size:13px;
    font-weight:500; color:#888; cursor:pointer; transition:all 0.15s;
}
.nav-tab.active { background:#e53e3e; color:white; }
.nav-tab:hover:not(.active) { background:rgba(255,255,255,0.06); color:#ccc; }
.nav-right { display:flex; align-items:center; gap:12px; }
.nav-badge {
    background:rgba(229,62,62,0.15); border:1px solid rgba(229,62,62,0.3);
    color:#fc4f4f; padding:4px 10px; border-radius:999px;
    font-size:11px; font-weight:600; letter-spacing:0.05em;
}
.nav-refresh {
    background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1);
    color:#ccc; padding:6px 14px; border-radius:8px;
    font-size:12px; font-weight:500; cursor:pointer;
}

/* Page title */
.page-header {
    padding: 20px 2rem 0;
    display: flex; align-items:flex-end; justify-content:space-between;
}
.page-title { font-size:26px; font-weight:700; color:#fff; letter-spacing:-0.03em; }
.page-sub { font-size:13px; color:#555; margin-top:2px; }
.fy-badge {
    background:rgba(229,62,62,0.12); border:1px solid rgba(229,62,62,0.25);
    color:#fc4f4f; padding:5px 14px; border-radius:8px;
    font-size:12px; font-weight:600;
}

/* KPI Cards */
.kpi-row { display:grid; gap:12px; padding:16px 2rem 0; }
.kpi-row-3 { grid-template-columns: repeat(3,1fr); }
.kpi-row-4 { grid-template-columns: repeat(4,1fr); }
.kpi-row-5 { grid-template-columns: repeat(5,1fr); }

.kcard {
    background: #13131a;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    padding: 18px 20px;
    position: relative; overflow: hidden;
    transition: border-color 0.2s, transform 0.2s;
}
.kcard:hover { border-color:rgba(255,255,255,0.15); transform:translateY(-1px); }
.kcard::before {
    content:''; position:absolute; top:0; left:0; right:0; height:2px;
    border-radius:14px 14px 0 0;
}
.kcard.red::before  { background:linear-gradient(90deg,#e53e3e,#fc8181); }
.kcard.green::before{ background:linear-gradient(90deg,#38a169,#68d391); }
.kcard.blue::before { background:linear-gradient(90deg,#3182ce,#63b3ed); }
.kcard.amber::before{ background:linear-gradient(90deg,#d69e2e,#f6e05e); }
.kcard.purple::before{background:linear-gradient(90deg,#805ad5,#b794f4); }
.kcard.teal::before { background:linear-gradient(90deg,#2c7a7b,#4fd1c5); }
.kcard.gray::before { background:linear-gradient(90deg,#4a5568,#a0aec0); }

.kcard-icon {
    width:34px; height:34px; border-radius:9px;
    display:flex; align-items:center; justify-content:center;
    font-size:16px; margin-bottom:12px;
}
.kcard.red .kcard-icon   { background:rgba(229,62,62,0.15); }
.kcard.green .kcard-icon { background:rgba(56,161,105,0.15); }
.kcard.blue .kcard-icon  { background:rgba(49,130,206,0.15); }
.kcard.amber .kcard-icon { background:rgba(214,158,46,0.15); }
.kcard.purple .kcard-icon{ background:rgba(128,90,213,0.15); }
.kcard.teal .kcard-icon  { background:rgba(44,122,123,0.15); }
.kcard.gray .kcard-icon  { background:rgba(74,85,104,0.15); }

.kcard-label { font-size:11px; color:#555; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; }
.kcard-value { font-size:28px; font-weight:700; color:#fff; line-height:1.1; margin:4px 0 2px; letter-spacing:-0.03em; font-family:'DM Mono',monospace; }
.kcard-sub   { font-size:11px; color:#555; }
.kcard-delta { font-size:11px; font-weight:600; margin-top:6px; }
.kcard-delta.up   { color:#68d391; }
.kcard-delta.down { color:#fc8181; }
.kcard-delta.warn { color:#f6e05e; }

/* Section headers */
.sec-header {
    display:flex; align-items:center; justify-content:space-between;
    padding:20px 2rem 10px; margin-top:4px;
}
.sec-title { font-size:14px; font-weight:700; color:#ccc; letter-spacing:-0.01em; }
.sec-badge {
    font-size:11px; color:#555; background:rgba(255,255,255,0.04);
    border:1px solid rgba(255,255,255,0.07); padding:3px 10px; border-radius:6px;
}

/* Chart wrappers */
.chart-wrap { padding:0 2rem; }
.chart-card {
    background:#13131a; border:1px solid rgba(255,255,255,0.07);
    border-radius:14px; overflow:hidden;
}
.chart-card-header {
    padding:14px 16px 0;
    display:flex; align-items:center; justify-content:space-between;
}
.chart-card-title { font-size:13px; font-weight:600; color:#aaa; }

/* Table */
.data-table { width:100%; border-collapse:collapse; font-size:13px; }
.data-table th {
    text-align:left; padding:10px 14px; font-size:10px; font-weight:600;
    color:#555; text-transform:uppercase; letter-spacing:0.07em;
    border-bottom:1px solid rgba(255,255,255,0.07);
}
.data-table td {
    padding:10px 14px; color:#ccc; border-bottom:1px solid rgba(255,255,255,0.04);
}
.data-table tr:hover td { background:rgba(255,255,255,0.03); }
.data-table .num { font-family:'DM Mono',monospace; font-size:12px; }
.pill-green { background:rgba(56,161,105,0.15); color:#68d391; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }
.pill-red   { background:rgba(229,62,62,0.15);  color:#fc8181; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }
.pill-amber { background:rgba(214,158,46,0.15); color:#f6e05e; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }

/* Footer */
.footer { padding:16px 2rem; border-top:1px solid rgba(255,255,255,0.05); margin-top:24px; display:flex; align-items:center; justify-content:space-between; }
.footer-left { font-size:12px; color:#333; }
.footer-right { font-size:11px; color:#2a2a35; font-family:'DM Mono',monospace; }

/* Plotly override */
.stPlotlyChart { border-radius:0 0 14px 14px; overflow:hidden; }
div[data-testid="stTabs"] button[role="tab"] {
    font-size:13px !important; font-weight:500 !important;
    color:#555 !important; padding:10px 18px !important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color:#fc4f4f !important; border-bottom:2px solid #e53e3e !important;
}
[data-testid="stMainBlockContainer"] { padding:0 !important; }
</style>
""", unsafe_allow_html=True)

# ── PLOTLY THEME ──────────────────────────────────────────────────────────────
DARK = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="#666", size=11),
    xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#333", linecolor="#333"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#333", linecolor="#333"),
    margin=dict(l=12,r=12,t=36,b=12),
)

RED   = "#e53e3e"
GREEN = "#38a169"
BLUE  = "#3182ce"
AMBER = "#d69e2e"

# ── NAV ───────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="top-nav">
  <div class="nav-logo">
    <div class="nav-logo-mark">Z</div>
    <div>
      <div class="nav-brand">Zetwerk CPT</div>
      <div class="nav-sub">Central Procurement</div>
    </div>
  </div>
  <div class="nav-tabs">
    <div class="nav-tab active">Dashboard</div>
    <div class="nav-tab">PO Tracker</div>
    <div class="nav-tab">Suppliers</div>
    <div class="nav-tab">Analytics</div>
  </div>
  <div class="nav-right">
    <div class="nav-badge">FY 2025-26</div>
    <div class="nav-refresh">↻ Refresh</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── PAGE HEADER ───────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="page-header">
  <div>
    <div class="page-title">Procurement Dashboard</div>
    <div class="page-sub">CAT-2: EM / Pipes / Fittings / Consumables · Apr 2025 – Feb 2026</div>
  </div>
  <div class="fy-badge">FY26 · Apr–Feb · 11 months</div>
</div>
""", unsafe_allow_html=True)

# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "  Overview  ", "  Spend & Savings  ", "  TAT & OTD  ", "  Credit Metric  "
])

# ════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════
with tab1:

    # KPI Row 1 — Top numbers
    st.markdown("""
    <div class="kpi-row kpi-row-5">
      <div class="kcard blue">
        <div class="kcard-icon">📦</div>
        <div class="kcard-label">Total POs (FY26)</div>
        <div class="kcard-value">325</div>
        <div class="kcard-sub">vs 293 in FY25</div>
        <div class="kcard-delta up">▲ +10.9% YoY</div>
      </div>
      <div class="kcard green">
        <div class="kcard-icon">💰</div>
        <div class="kcard-label">Total Spend (INR Cr)</div>
        <div class="kcard-value">285.7</div>
        <div class="kcard-sub">vs 398.6 Cr FY25</div>
        <div class="kcard-delta down">▼ -28.3% YoY</div>
      </div>
      <div class="kcard green">
        <div class="kcard-icon">📈</div>
        <div class="kcard-label">Total Savings (INR Cr)</div>
        <div class="kcard-value">19.44</div>
        <div class="kcard-sub">6.80% savings rate</div>
        <div class="kcard-delta down">▼ vs 25.02 Cr FY25</div>
      </div>
      <div class="kcard amber">
        <div class="kcard-icon">⏱️</div>
        <div class="kcard-label">Avg PR→PO TAT</div>
        <div class="kcard-value">80.5d</div>
        <div class="kcard-sub">Target: 90 days</div>
        <div class="kcard-delta up">✓ Within target</div>
      </div>
      <div class="kcard red">
        <div class="kcard-icon">🎯</div>
        <div class="kcard-label">CAT-2 OTIF</div>
        <div class="kcard-value">70.6%</div>
        <div class="kcard-sub">Target: 75%</div>
        <div class="kcard-delta down">▼ Below target</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # KPI Row 2 — AOP
    st.markdown("""
    <div class="sec-header" style="margin-top:12px;">
      <div class="sec-title">AOP vs Achieved (FY26 H1)</div>
      <div class="sec-badge">INR Crore</div>
    </div>
    <div class="kpi-row kpi-row-4">
      <div class="kcard red">
        <div class="kcard-icon">🏭</div>
        <div class="kcard-label">O&G — AOP vs Achieved</div>
        <div class="kcard-value">29 / 55.6</div>
        <div class="kcard-sub">AOP: ₹55.6 Cr</div>
        <div class="kcard-delta down">▼ -26.6 Cr (-47.8%)</div>
      </div>
      <div class="kcard amber">
        <div class="kcard-icon">💧</div>
        <div class="kcard-label">Water — AOP vs Achieved</div>
        <div class="kcard-value">43.3 / 67.9</div>
        <div class="kcard-sub">AOP: ₹67.9 Cr</div>
        <div class="kcard-delta down">▼ -24.6 Cr (-36.2%)</div>
      </div>
      <div class="kcard red">
        <div class="kcard-icon">🚂</div>
        <div class="kcard-label">Railways — AOP vs Achieved</div>
        <div class="kcard-value">0.73 / 1.61</div>
        <div class="kcard-sub">AOP: ₹1.61 Cr</div>
        <div class="kcard-delta down">▼ -0.88 Cr (-54.7%)</div>
      </div>
      <div class="kcard red">
        <div class="kcard-icon">📊</div>
        <div class="kcard-label">Total — AOP vs Achieved</div>
        <div class="kcard-value">73 / 125</div>
        <div class="kcard-sub">AOP: ₹125.1 Cr</div>
        <div class="kcard-delta down">▼ -52.1 Cr (-41.6%)</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Charts
    st.markdown('<div class="sec-header"><div class="sec-title">BU Performance Overview</div><div class="sec-badge">FY26 vs FY25</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    c1, c2 = st.columns(2)

    with c1:
        st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">Spend by BU — FY26 vs FY25 (₹ Cr)</span></div>', unsafe_allow_html=True)
        df_spend = pd.DataFrame({
            "BU": ["O&G","Water","Railways","ZAP91"],
            "FY26": [47.29, 201.02, 24.74, 12.67],
            "FY25": [116.51, 245.52, 36.56, 0],
        })
        fig = go.Figure()
        fig.add_trace(go.Bar(name="FY26", x=df_spend["BU"], y=df_spend["FY26"],
                             marker_color=RED, marker_line_width=0))
        fig.add_trace(go.Bar(name="FY25", x=df_spend["BU"], y=df_spend["FY25"],
                             marker_color="rgba(229,62,62,0.25)", marker_line_width=0))
        fig.update_layout(**DARK, height=300, barmode="group",
                          title_text="", showlegend=True,
                          legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">Savings Rate by BU — FY26 vs Target 4.5% (₹ Cr)</span></div>', unsafe_allow_html=True)
        df_sav = pd.DataFrame({
            "BU":    ["O&G","Water","Railways","ZAP91"],
            "FY26%": [9.41,  8.32,   -8.05,    -1.58],
            "FY25%": [11.28, 3.97,    5.77,     0],
        })
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(name="FY26 Savings%", x=df_sav["BU"], y=df_sav["FY26%"],
                              marker_color=[GREEN if v>0 else RED for v in df_sav["FY26%"]],
                              marker_line_width=0))
        fig2.add_hline(y=4.5, line_dash="dash", line_color=AMBER,
                       annotation_text="Target 4.5%", annotation_font_color=AMBER)
        fig2.update_layout(**DARK, height=300, showlegend=False, title_text="")
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# TAB 2 — SPEND & SAVINGS
# ════════════════════════════════════════════════════════════════════
with tab2:

    # KPI row
    total_spend = 285.72
    total_sav   = 19.44
    sav_pct     = 6.80
    st.markdown(f"""
    <div class="kpi-row kpi-row-4">
      <div class="kcard blue">
        <div class="kcard-icon">💼</div>
        <div class="kcard-label">Total Spend FY26</div>
        <div class="kcard-value">₹285.7 Cr</div>
        <div class="kcard-sub">Apr 2025 – Feb 2026</div>
      </div>
      <div class="kcard green">
        <div class="kcard-icon">🏆</div>
        <div class="kcard-label">Total Savings FY26</div>
        <div class="kcard-value">₹19.44 Cr</div>
        <div class="kcard-sub">6.8% of spend</div>
        <div class="kcard-delta up">▲ Above 4.5% target</div>
      </div>
      <div class="kcard amber">
        <div class="kcard-icon">📉</div>
        <div class="kcard-label">Biggest Category</div>
        <div class="kcard-value">Pipes</div>
        <div class="kcard-sub">₹195.7 Cr spend · ₹15.8 Cr savings</div>
      </div>
      <div class="kcard purple">
        <div class="kcard-icon">⚡</div>
        <div class="kcard-label">Best Savings BU</div>
        <div class="kcard-value">O&G</div>
        <div class="kcard-sub">9.41% savings rate</div>
        <div class="kcard-delta up">▲ vs 4.5% target</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec-header"><div class="sec-title">Category Spend & Savings</div><div class="sec-badge">FY26 vs FY25 · INR Crore</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    c3, c4 = st.columns([3, 2])

    with c3:
        st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">Category Spend — FY26 vs FY25</span></div>', unsafe_allow_html=True)
        df_cat = pd.DataFrame(CAT_DATA).sort_values("Spend FY26", ascending=True)
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(name="FY26", y=df_cat["Category"], x=df_cat["Spend FY26"],
                              orientation="h", marker_color=RED, marker_line_width=0))
        fig3.add_trace(go.Bar(name="FY25", y=df_cat["Category"], x=df_cat["Spend FY25"],
                              orientation="h", marker_color="rgba(229,62,62,0.2)", marker_line_width=0))
        fig3.update_layout(**DARK, height=360, barmode="group",
                          legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
        st.plotly_chart(fig3, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c4:
        st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">Savings by Category FY26</span></div>', unsafe_allow_html=True)
        df_sav_cat = pd.DataFrame(CAT_DATA).sort_values("Savings FY26", ascending=False)
        df_sav_cat = df_sav_cat[df_sav_cat["Savings FY26"] != 0]
        colors = [GREEN if v > 0 else RED for v in df_sav_cat["Savings FY26"]]
        fig4 = px.bar(df_sav_cat, x="Savings FY26", y="Category",
                      orientation="h", color="Savings FY26",
                      color_continuous_scale=[[0,RED],[0.5,"#666"],[1,GREEN]])
        fig4.update_layout(**DARK, height=360, showlegend=False,
                           coloraxis_showscale=False)
        st.plotly_chart(fig4, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # Spend & Savings table
    st.markdown('<div class="sec-header"><div class="sec-title">BU-wise Spend & Savings Summary</div><div class="sec-badge">Detailed View</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap"><div class="chart-card" style="padding:0 0 8px;">', unsafe_allow_html=True)
    rows = ""
    bus = ["O&G","Water","Railways","ZAP91","Total"]
    spends26 = [47.29, 201.02, 24.74, 12.67, 285.72]
    savs26   = [4.91,  16.72,  -1.99, -0.20, 19.44]
    savp26   = [9.41,  8.32,  -8.05, -1.58, 6.80]
    spends25 = [116.51,245.52, 36.56, 0,    398.59]
    savs25   = [13.15, 9.76,   2.11,  0,    25.02]
    savp25   = [11.28, 3.97,   5.77,  0,     6.27]
    tgt      = ["4.5%","4.5%","4.5%","—","—"]
    for i, bu in enumerate(bus):
        pill_class = "pill-green" if savp26[i] >= 4.5 else ("pill-red" if savp26[i] < 0 else "pill-amber")
        rows += f"""<tr>
          <td><b style="color:#eee">{bu}</b></td>
          <td class="num">₹{spends26[i]:.1f} Cr</td>
          <td class="num">₹{savs26[i]:.2f} Cr</td>
          <td><span class="{pill_class}">{savp26[i]:.1f}%</span></td>
          <td class="num" style="color:#444">{tgt[i]}</td>
          <td class="num" style="color:#555">₹{spends25[i]:.1f} Cr</td>
          <td class="num" style="color:#555">₹{savs25[i]:.2f} Cr</td>
          <td class="num" style="color:#555">{savp25[i]:.1f}%</td>
        </tr>"""
    st.markdown(f"""
    <table class="data-table">
      <thead>
        <tr>
          <th>BU</th>
          <th>Spend FY26</th>
          <th>Savings FY26</th>
          <th>Savings %</th>
          <th>Target</th>
          <th>Spend FY25</th>
          <th>Savings FY25</th>
          <th>Savings % FY25</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    """, unsafe_allow_html=True)
    st.markdown('</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# TAB 3 — TAT & OTD
# ════════════════════════════════════════════════════════════════════
with tab3:

    # KPI row
    st.markdown("""
    <div class="kpi-row kpi-row-4">
      <div class="kcard blue">
        <div class="kcard-icon">⏱️</div>
        <div class="kcard-label">CAT-2 Avg TAT FY26</div>
        <div class="kcard-value">80.5 days</div>
        <div class="kcard-sub">Target: 90 days</div>
        <div class="kcard-delta up">✓ Within target</div>
      </div>
      <div class="kcard green">
        <div class="kcard-icon">⚡</div>
        <div class="kcard-label">Best TAT — Water</div>
        <div class="kcard-value">68 days</div>
        <div class="kcard-sub">vs 72.9 days FY25</div>
        <div class="kcard-delta up">▲ Improved</div>
      </div>
      <div class="kcard red">
        <div class="kcard-icon">🎯</div>
        <div class="kcard-label">CAT-2 OTIF FY26</div>
        <div class="kcard-value">70.61%</div>
        <div class="kcard-sub">Target: 75%</div>
        <div class="kcard-delta down">▼ -4.4pp vs target</div>
      </div>
      <div class="kcard amber">
        <div class="kcard-icon">📊</div>
        <div class="kcard-label">Best OTIF — Railways</div>
        <div class="kcard-value">72.83%</div>
        <div class="kcard-sub">vs 68.6% FY25</div>
        <div class="kcard-delta up">▲ +4.2pp YoY</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec-header"><div class="sec-title">TAT & OTIF Analysis</div><div class="sec-badge">FY26 vs FY25 vs Target</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    c5, c6 = st.columns(2)

    with c5:
        st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">OTIF by BU — FY26 vs FY25 vs Target 75%</span></div>', unsafe_allow_html=True)
        df_otif = pd.DataFrame(OTIF_DATA)
        fig5 = go.Figure()
        fig5.add_trace(go.Bar(name="FY26", x=df_otif["BU"], y=df_otif["FY26"],
                              marker_color=RED, marker_line_width=0))
        fig5.add_trace(go.Bar(name="FY25", x=df_otif["BU"], y=df_otif["FY25"],
                              marker_color="rgba(229,62,62,0.3)", marker_line_width=0))
        fig5.add_hline(y=75, line_dash="dash", line_color=AMBER,
                       annotation_text="Target 75%", annotation_font_color=AMBER)
        fig5.update_layout(**DARK, height=320, barmode="group",
                          yaxis=dict(range=[60,85], **DARK["yaxis"]),
                          legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        st.plotly_chart(fig5, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c6:
        st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">PR→PO TAT by BU — FY26 vs FY25 vs Target 90d</span></div>', unsafe_allow_html=True)
        df_tat = pd.DataFrame(TAT_DATA)
        fig6 = go.Figure()
        fig6.add_trace(go.Bar(name="FY26 TAT", x=df_tat["BU"], y=df_tat["FY26 TAT"],
                              marker_color=BLUE, marker_line_width=0))
        fig6.add_trace(go.Bar(name="FY25 TAT", x=df_tat["BU"], y=df_tat["FY25 TAT"],
                              marker_color="rgba(49,130,206,0.3)", marker_line_width=0))
        fig6.add_hline(y=90, line_dash="dash", line_color=AMBER,
                       annotation_text="Target 90d", annotation_font_color=AMBER)
        fig6.update_layout(**DARK, height=320, barmode="group",
                          legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        st.plotly_chart(fig6, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # PO Count chart
    c7, c8 = st.columns(2)
    with c7:
        st.markdown('<div class="chart-card" style="margin-top:14px"><div class="chart-card-header"><span class="chart-card-title">PO Count by BU — FY26 vs FY25</span></div>', unsafe_allow_html=True)
        fig7 = go.Figure()
        fig7.add_trace(go.Bar(name="FY26", x=df_tat["BU"], y=df_tat["FY26 PO"],
                              marker_color=RED, marker_line_width=0,
                              text=df_tat["FY26 PO"], textposition="outside",
                              textfont=dict(color="#aaa", size=11)))
        fig7.add_trace(go.Bar(name="FY25", x=df_tat["BU"], y=df_tat["FY25 PO"],
                              marker_color="rgba(229,62,62,0.2)", marker_line_width=0))
        fig7.update_layout(**DARK, height=300, barmode="group",
                          legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        st.plotly_chart(fig7, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c8:
        st.markdown('<div class="chart-card" style="margin-top:14px"><div class="chart-card-header"><span class="chart-card-title">OTIF Trend — FY26 vs Target (Radar)</span></div>', unsafe_allow_html=True)
        categories = ["O&G","Water","Railways","CAT-2","O&G"]
        fy26_vals  = [68.0, 71.0, 72.83, 70.61, 68.0]
        tgt_vals   = [75, 75, 75, 75, 75]
        fig8 = go.Figure()
        fig8.add_trace(go.Scatterpolar(r=fy26_vals, theta=categories, fill="toself",
                                       name="FY26 OTIF", line=dict(color=RED, width=2),
                                       fillcolor="rgba(229,62,62,0.15)"))
        fig8.add_trace(go.Scatterpolar(r=tgt_vals, theta=categories, fill="toself",
                                       name="Target 75%", line=dict(color=AMBER, width=1.5, dash="dash"),
                                       fillcolor="rgba(214,158,46,0.05)"))
        fig8.update_layout(**DARK, height=300,
                          polar=dict(
                              bgcolor="rgba(0,0,0,0)",
                              radialaxis=dict(range=[60,80], gridcolor="rgba(255,255,255,0.07)", tickcolor="#333", linecolor="#333", tickfont=dict(color="#555")),
                              angularaxis=dict(gridcolor="rgba(255,255,255,0.07)", tickfont=dict(color="#888"))
                          ),
                          legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center"))
        st.plotly_chart(fig8, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# TAB 4 — CREDIT METRIC
# ════════════════════════════════════════════════════════════════════
with tab4:

    # Latest month score
    latest_score = CREDIT_FY26[-1]
    latest_spend = SPEND_MONTHLY[-1]
    avg_score_fy26 = sum(CREDIT_FY26)/len(CREDIT_FY26)

    st.markdown(f"""
    <div class="kpi-row kpi-row-4">
      <div class="kcard {'green' if avg_score_fy26 >= 4.5 else 'amber'}">
        <div class="kcard-icon">⭐</div>
        <div class="kcard-label">Avg Credit Score FY26</div>
        <div class="kcard-value">{avg_score_fy26:.2f}</div>
        <div class="kcard-sub">Target: 4.5 | Higher = better</div>
        <div class="kcard-delta up">▲ Above target</div>
      </div>
      <div class="kcard {'green' if latest_score >= 4.5 else 'red'}">
        <div class="kcard-icon">📅</div>
        <div class="kcard-label">Latest Month (Feb'26)</div>
        <div class="kcard-value">{latest_score:.2f}</div>
        <div class="kcard-sub">Spend: ₹{latest_spend:.1f} Cr</div>
        <div class="kcard-delta {'up' if latest_score >= 4.5 else 'down'}">{'▲ Above' if latest_score >= 4.5 else '▼ Below'} target 4.5</div>
      </div>
      <div class="kcard blue">
        <div class="kcard-icon">💹</div>
        <div class="kcard-label">Best Month Score</div>
        <div class="kcard-value">{max(CREDIT_FY26):.2f}</div>
        <div class="kcard-sub">May'25 · Spend ₹166.2 Cr</div>
        <div class="kcard-delta up">▲ Peak performance</div>
      </div>
      <div class="kcard red">
        <div class="kcard-icon">⚠️</div>
        <div class="kcard-label">Lowest Month Score</div>
        <div class="kcard-value">{min(CREDIT_FY26):.2f}</div>
        <div class="kcard-sub">Jan'26 · Needs attention</div>
        <div class="kcard-delta down">▼ Below target 4.5</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec-header"><div class="sec-title">Credit Metric Trend — FY26 vs FY25 vs Target</div><div class="sec-badge">Monthly · Higher score = better payment terms</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="chart-card"><div class="chart-card-header"><span class="chart-card-title">Payment Terms Credit Score (Weighted Avg) + Monthly Spend</span></div>', unsafe_allow_html=True)

    fig9 = go.Figure()
    fig9.add_trace(go.Bar(name="Monthly Spend (₹Cr)", x=CREDIT_MONTHS, y=SPEND_MONTHLY,
                          marker_color="rgba(229,62,62,0.2)", marker_line_width=0, yaxis="y"))
    fig9.add_trace(go.Scatter(name="FY26 Score", x=CREDIT_MONTHS, y=CREDIT_FY26,
                              line=dict(color=RED, width=2.5), mode="lines+markers",
                              marker=dict(size=6, color=RED), yaxis="y2"))
    fig9.add_trace(go.Scatter(name="FY25 Score", x=CREDIT_MONTHS, y=CREDIT_FY25,
                              line=dict(color="rgba(229,62,62,0.35)", width=1.5, dash="dot"),
                              mode="lines+markers", marker=dict(size=4), yaxis="y2"))
    fig9.add_trace(go.Scatter(name="Target 4.5", x=CREDIT_MONTHS, y=CREDIT_TARGET,
                              line=dict(color=AMBER, width=1.5, dash="dash"),
                              mode="lines", yaxis="y2"))
    fig9.update_layout(
        **DARK, height=380,
        yaxis=dict(title="Spend (₹ Cr)", gridcolor="rgba(255,255,255,0.04)", tickcolor="#333", linecolor="#333"),
        yaxis2=dict(title="Credit Score", overlaying="y", side="right",
                    gridcolor="rgba(255,255,255,0.02)", tickcolor="#333"),
        legend=dict(orientation="h", y=1.1, x=1, xanchor="right"),
    )
    st.plotly_chart(fig9, use_container_width=True)
    st.markdown('</div></div>', unsafe_allow_html=True)

    # Score breakdown table
    st.markdown('<div class="sec-header"><div class="sec-title">Monthly Score Breakdown</div><div class="sec-badge">FY26</div></div>', unsafe_allow_html=True)
    rows2 = ""
    for i, m in enumerate(CREDIT_MONTHS):
        s26 = CREDIT_FY26[i]; s25 = CREDIT_FY25[i]
        sp  = SPEND_MONTHLY[i]
        pill = "pill-green" if s26 >= 4.5 else ("pill-red" if s26 < 3 else "pill-amber")
        delta = s26 - s25
        dclass = "up" if delta > 0 else "down"
        rows2 += f"""<tr>
          <td><b style="color:#ccc">{m}'{'26' if i <= 10 else '25'}</b></td>
          <td class="num">₹{sp:.1f} Cr</td>
          <td><span class="{pill}">{s26:.2f}</span></td>
          <td class="num" style="color:#555">{s25:.2f}</td>
          <td class="num" style="color:#555">4.5</td>
          <td><span style="color:{'#68d391' if delta>0 else '#fc8181'}; font-size:12px; font-family:'DM Mono',monospace;">{'+' if delta>0 else ''}{delta:.2f}</span></td>
          <td><span class="{'pill-green' if s26>=4.5 else 'pill-red'}">{('On Track' if s26>=4.5 else 'Below Target')}</span></td>
        </tr>"""
    st.markdown(f"""
    <div class="chart-wrap"><div class="chart-card" style="padding:0 0 8px;">
    <table class="data-table">
      <thead>
        <tr>
          <th>Month</th>
          <th>PO Spend</th>
          <th>FY26 Score</th>
          <th>FY25 Score</th>
          <th>Target</th>
          <th>YoY Change</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{rows2}</tbody>
    </table>
    </div></div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── FOOTER ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="footer">
  <div class="footer-left">
    ⚡ Zetwerk Central Procurement Dashboard · CAT-2 · FY 2025–26
  </div>
  <div class="footer-right">
    Last updated: {pd.Timestamp.now().strftime('%d %b %Y %H:%M')} · Data: Google Sheets + Backup Excel
  </div>
</div>
""", unsafe_allow_html=True)
