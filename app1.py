# -*- coding: utf-8 -*-
"""
Created on Fri Apr  3 11:55:41 2026

@author: AyushKamle(I)
"""

"""
PO Tracker Dashboard — Central Procurement
Zetwerk | Live data from Google Sheets
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PO Tracker | Zetwerk",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1b2a 0%, #1b2d45 100%) !important;
}
[data-testid="stSidebar"] * { color: #cfe2f3 !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stMultiSelect label {
    color: #94b8d4 !important; font-size: 11px !important;
    text-transform: uppercase; letter-spacing: 0.06em;
}
[data-testid="stSidebar"] hr { border-color: #2d4a63 !important; }

[data-testid="stMain"] { background: #f0f4f8 !important; }
[data-testid="stAppViewBlockContainer"] {
    padding-top: 0 !important; padding-left: 0 !important;
    padding-right: 0 !important; max-width: 100% !important;
    background: #f0f4f8 !important;
}

.kpi-wrap { padding: 0 2rem; }

.kpi-card {
    background: #ffffff;
    border-radius: 14px;
    padding: 18px 20px 14px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08);
    border-left: 5px solid #2563eb;
    margin-bottom: 10px;
    transition: box-shadow 0.2s;
}
.kpi-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.13); }
.kpi-card.green  { border-left-color: #16a34a; }
.kpi-card.orange { border-left-color: #ea580c; }
.kpi-card.purple { border-left-color: #7c3aed; }
.kpi-card.red    { border-left-color: #dc2626; }
.kpi-card.teal   { border-left-color: #0d9488; }
.kpi-card.amber  { border-left-color: #d97706; }
.kpi-card.blue   { border-left-color: #2563eb; }
.kpi-card.pink   { border-left-color: #db2777; }

.kpi-icon  { font-size: 20px; margin-bottom: 4px; }
.kpi-label { font-size: 11px; color: #6b7280; font-weight: 600;
             text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
.kpi-value { font-size: 26px; font-weight: 800; color: #111827; line-height: 1.1; }
.kpi-sub   { font-size: 11px; color: #9ca3af; margin-top: 3px; }

.section-title {
    font-size: 15px; font-weight: 700; color: #1e293b;
    margin: 24px 2rem 10px; padding-bottom: 8px;
    border-bottom: 2px solid #e2e8f0;
    letter-spacing: -0.01em;
}

div[data-testid="stTabs"] button[role="tab"] {
    font-size: 0.92rem !important; font-weight: 600 !important;
    padding: 10px 22px !important; color: #64748b !important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #2563eb !important;
    border-bottom: 3px solid #2563eb !important;
}
div[data-testid="stTabs"] button[role="tab"]:hover {
    color: #2563eb !important;
    background: rgba(37,99,235,0.05) !important;
    border-radius: 6px 6px 0 0;
}

.chart-wrap { padding: 0 2rem; }
</style>
""", unsafe_allow_html=True)

# ── Google Sheets ─────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

YET_COL   = "PO YET TO BE DELIVERED\n(incl. GST)"
DELIV_COL = "PO DELIVERED VALUE \n(incl. GST)"

@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    creds  = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    sheet  = client.open("po tracker").worksheet("PR Tracker")
    raw    = sheet.get_all_values()

    headers = raw[2]
    data    = raw[3:]
    df = pd.DataFrame(data, columns=headers)
    df = df[df["SN"].str.strip().str.match(r"^\d+")].copy()
    df.reset_index(drop=True, inplace=True)

    NUM = [
        "PR Qty", "PO Basic Value", "GST", "PO Value with GST",
        "PCA Basic Value", "PCA Value with GST", "Savings Value", "Savings %",
        "PR - PO TAT", "Actual Delivery TAT (Days)",
        "Realized Saving", "Realized PO Value (Basic)",
        YET_COL, DELIV_COL, "Delivery Time from MFC\n(Days)",
    ]
    for c in NUM:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    DATES = [
        "PR Dt.", "PO Dt.", "Delivery Date at Project Site",
        "NFA Dt.", "NFA App. Dt", "MFC Dt.",
        "Rev. PR Dt/ PR App. From Finance", "RFQ Dt.",
        "TQR/ TER Dt.", "QAP App. Dt.",
    ]
    for c in DATES:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    for c in ["OTD", "OTIF"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df

# ── Load ──────────────────────────────────────────────────────────────────────
with st.spinner("Connecting to Google Sheets…"):
    df_raw = load_data()

# ── Header Banner ─────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(120deg,#0d1b2a 0%,#1e3a5f 45%,#1d4ed8 100%);
            padding:26px 2.5rem 18px; margin:0; width:100%; box-sizing:border-box;
            border-bottom:3px solid rgba(255,255,255,0.08);">
  <div style="display:flex; align-items:center; gap:16px;">
    <div style="font-size:2.4rem; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.4));">📦</div>
    <div>
      <h1 style="margin:0; color:#fff; font-size:1.75rem; font-weight:800; letter-spacing:-0.02em;">
        PO Tracker Dashboard
      </h1>
      <p style="margin:5px 0 0; color:rgba(255,255,255,0.60); font-size:13px; letter-spacing:0.02em;">
        Central Procurement &nbsp;·&nbsp; CAT-2: EM / Pipes / Fittings / Consumables
        &nbsp;·&nbsp; Live from Google Sheets
      </p>
    </div>
  </div>
</div>
<div style="margin-bottom:4px;"></div>
""", unsafe_allow_html=True)

# ── Sidebar Filters ───────────────────────────────────────────────────────────
st.sidebar.markdown("## 🔍 Filters")

def opts(col):
    return ["All"] + sorted(df_raw[col].dropna().astype(str).unique().tolist())

sel_bu     = st.sidebar.selectbox("Business Unit",    opts("BU"))
sel_buyer  = st.sidebar.selectbox("Handled By",       opts("Handled by"))
sel_cat    = st.sidebar.selectbox("Category",         opts("Category"))
sel_status = st.sidebar.selectbox("Current Status",   opts("Current Status"))
sel_deliv  = st.sidebar.selectbox("Delivery Status",  opts("Delivery Status"))

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption(f"⚡ Auto-refresh every 5 min\n\n📅 {pd.Timestamp.now().strftime('%d-%b-%Y %H:%M')}")

# ── Apply Filters ─────────────────────────────────────────────────────────────
df = df_raw.copy()
if sel_bu     != "All": df = df[df["BU"].astype(str)             == sel_bu]
if sel_buyer  != "All": df = df[df["Handled by"].astype(str)     == sel_buyer]
if sel_cat    != "All": df = df[df["Category"].astype(str)       == sel_cat]
if sel_status != "All": df = df[df["Current Status"].astype(str) == sel_status]
if sel_deliv  != "All": df = df[df["Delivery Status"].astype(str)== sel_deliv]

# ── KPI Helpers ───────────────────────────────────────────────────────────────
total_rows     = len(df)
po_released    = (df["Current Status"] == "PO RELEASED").sum()
delivered      = (df["Current Status"] == "MATERIAL DELIVERED AT SITE").sum()
partial_deliv  = (df["Current Status"] == "PARTIAL MATERIAL DELIVERED AT SITE").sum()
ongoing        = (df["Delivery Status"] == "Ongoing").sum()
completed      = (df["Delivery Status"] == "Completed").sum()
on_hold        = (df["Current Status"].str.contains("HOLD", na=False)).sum()

total_po_val   = df["PO Basic Value"].fillna(0).sum()
total_po_gst   = df["PO Value with GST"].fillna(0).sum()
total_savings  = df["Savings Value"].fillna(0).sum()
total_yet      = df[YET_COL].fillna(0).sum()   if YET_COL   in df.columns else 0
total_delivered_val = df[DELIV_COL].fillna(0).sum() if DELIV_COL in df.columns else 0
savings_pct    = (total_savings / total_po_val * 100) if total_po_val else 0

avg_pr_po_tat  = df["PR - PO TAT"].mean()
avg_deliv_tat  = df["Actual Delivery TAT (Days)"].mean()
otd_ok         = (df["OTD"].dropna() <= 1).sum()
otd_total      = df["OTD"].dropna().count()
otd_rate       = (otd_ok / otd_total * 100) if otd_total else 0

COMMON = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter", size=12),
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📊  Overview", "📈  Performance", "🚚  Delivery", "📋  Data Table"
])

# ═══════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ═══════════════════════════════════════════════════════════════════════
with tab1:

    # ── KPI Row 1 ────────────────────────────────────────────────────
    st.markdown('<div class="kpi-wrap">', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)

    kpis_row1 = [
        (c1, "blue",   "📋", "Total PRs / POs",    f"{total_rows:,}",                  "In current view"),
        (c2, "green",  "✅", "PO Released",         f"{po_released:,}",                 f"{po_released/max(total_rows,1)*100:.0f}% of total"),
        (c3, "teal",   "🏭", "Delivered at Site",   f"{delivered:,}",                   f"+{partial_deliv} partial"),
        (c4, "purple", "💰", "Total PO Value",      f"₹{total_po_val/1e7:.1f} Cr",      "Basic value"),
        (c5, "green",  "💚", "Total Savings",       f"₹{total_savings/1e5:.1f} L",      f"{savings_pct:.1f}% of PO value"),
        (c6, "orange", "⏳", "Yet to Deliver",      f"₹{total_yet/1e7:.1f} Cr",         "Pending at supplier"),
    ]
    for col, color, icon, label, value, sub in kpis_row1:
        with col:
            st.markdown(f"""
            <div class="kpi-card {color}">
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── KPI Row 2 ────────────────────────────────────────────────────
    c7,c8,c9,c10,c11,c12 = st.columns(6)
    kpis_row2 = [
        (c7,  "blue",   "⚡", "Avg PR → PO TAT",    f"{avg_pr_po_tat:.0f} days",        "Procurement speed"),
        (c8,  "amber",  "🚛", "Avg Delivery TAT",   f"{avg_deliv_tat:.0f} days",        "PO to site"),
        (c9,  "green",  "🎯", "OTD Rate",           f"{otd_rate:.0f}%",                 f"{otd_ok}/{otd_total} on time"),
        (c10, "teal",   "🔄", "Ongoing",            f"{ongoing:,}",                     "Active deliveries"),
        (c11, "pink",   "⛔", "On Hold",            f"{on_hold:,}",                     "Needs attention"),
        (c12, "purple", "📦", "PO Value with GST",  f"₹{total_po_gst/1e7:.1f} Cr",     "Incl. GST"),
    ]
    for col, color, icon, label, value, sub in kpis_row2:
        with col:
            st.markdown(f"""
            <div class="kpi-card {color}">
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Charts Row 1 ─────────────────────────────────────────────────
    st.markdown('<div class="section-title">📊 Business Unit Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
    ch1, ch2 = st.columns(2)

    with ch1:
        bu_grp = df.groupby("BU").agg(
            Count=("SN","count"),
            Value=("PO Basic Value","sum"),
            Savings=("Savings Value","sum"),
        ).reset_index().sort_values("Value", ascending=False)
        bu_grp["Value (Cr)"] = bu_grp["Value"] / 1e7
        fig1 = px.bar(bu_grp, x="BU", y="Value (Cr)",
                      title="PO Value by Business Unit (₹ Crore)",
                      color="Value (Cr)",
                      color_continuous_scale=["#93c5fd","#2563eb","#1e3a5f"],
                      text="Value (Cr)",
                      custom_data=["Count","Savings"])
        fig1.update_traces(
            texttemplate='₹%{text:.1f}Cr',
            textposition='outside',
            hovertemplate="<b>%{x}</b><br>Value: ₹%{y:.1f} Cr<br>POs: %{customdata[0]}<br>Savings: ₹%{customdata[1]:,.0f}<extra></extra>"
        )
        fig1.update_layout(**COMMON, height=370, margin=dict(l=10,r=10,t=50,b=20),
                           showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig1, use_container_width=True)

    with ch2:
        sc = df["Current Status"].value_counts().reset_index()
        sc.columns = ["Status","Count"]
        sc.loc[sc["Count"] < 4, "Status"] = "Others"
        sc = sc.groupby("Status")["Count"].sum().reset_index().sort_values("Count", ascending=False)
        fig2 = px.pie(sc, names="Status", values="Count",
                      title="Current Status Distribution",
                      hole=0.48,
                      color_discrete_sequence=px.colors.qualitative.Bold)
        fig2.update_traces(textposition="outside", textinfo="percent+label",
                           pull=[0.03]*len(sc))
        fig2.update_layout(**COMMON, height=370, margin=dict(l=20,r=20,t=50,b=20),
                           showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    # ── Charts Row 2 ─────────────────────────────────────────────────
    ch3, ch4 = st.columns(2)

    with ch3:
        buyer_grp = df.groupby("Handled by").agg(
            Count=("SN","count"),
            Value=("PO Basic Value","sum")
        ).reset_index().sort_values("Count", ascending=True)
        buyer_grp["Value (Cr)"] = buyer_grp["Value"] / 1e7
        fig3 = px.bar(buyer_grp, x="Count", y="Handled by",
                      orientation="h",
                      title="PO Count & Value by Buyer",
                      color="Value (Cr)",
                      color_continuous_scale=["#a7f3d0","#059669","#064e3b"],
                      text="Count",
                      custom_data=["Value (Cr)"])
        fig3.update_traces(
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>POs: %{x}<br>Value: ₹%{customdata[0]:.1f} Cr<extra></extra>"
        )
        fig3.update_layout(**COMMON, height=370, margin=dict(l=10,r=40,t=50,b=20),
                           coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)

    with ch4:
        cat_sav = df.groupby("Category")["Savings Value"].sum().reset_index()
        cat_sav = cat_sav[cat_sav["Savings Value"] > 0].sort_values("Savings Value", ascending=False).head(12)
        cat_sav["Savings (L)"] = cat_sav["Savings Value"] / 1e5
        fig4 = px.bar(cat_sav, x="Category", y="Savings (L)",
                      title="Savings by Category (₹ Lakhs)",
                      color="Savings (L)",
                      color_continuous_scale=["#fde68a","#f59e0b","#78350f"],
                      text="Savings (L)")
        fig4.update_traces(texttemplate='₹%{text:.1f}L', textposition='outside')
        fig4.update_layout(**COMMON, height=370, margin=dict(l=10,r=10,t=50,b=60),
                           coloraxis_showscale=False, xaxis_tickangle=35)
        st.plotly_chart(fig4, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 2 — PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div class="section-title">📈 Procurement Performance</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    ch5, ch6 = st.columns(2)

    with ch5:
        # PR→PO TAT by buyer
        tat = df.groupby("Handled by")["PR - PO TAT"].mean().reset_index().dropna()
        tat.columns = ["Buyer","Avg TAT (Days)"]
        tat = tat.sort_values("Avg TAT (Days)")
        fig5 = px.bar(tat, x="Avg TAT (Days)", y="Buyer", orientation="h",
                      title="Average PR to PO TAT by Buyer (Days)",
                      color="Avg TAT (Days)",
                      color_continuous_scale=["#86efac","#f97316","#dc2626"],
                      text="Avg TAT (Days)")
        fig5.update_traces(texttemplate='%{text:.0f}d', textposition='outside')
        fig5.update_layout(**COMMON, height=380, margin=dict(l=10,r=50,t=50,b=20),
                           coloraxis_showscale=False)
        st.plotly_chart(fig5, use_container_width=True)

    with ch6:
        # Monthly PO trend
        trend = df.dropna(subset=["PO Dt."]).copy()
        trend["Month"] = trend["PO Dt."].dt.to_period("M").astype(str)
        monthly = trend.groupby("Month").agg(
            Count=("SN","count"),
            Value=("PO Basic Value","sum")
        ).reset_index().tail(18)
        monthly["Value (Cr)"] = monthly["Value"] / 1e7

        fig6 = go.Figure()
        fig6.add_trace(go.Bar(
            x=monthly["Month"], y=monthly["Count"],
            name="PO Count", marker_color="#bfdbfe", yaxis="y",
        ))
        fig6.add_trace(go.Scatter(
            x=monthly["Month"], y=monthly["Value (Cr)"],
            name="Value (₹Cr)", line=dict(color="#1d4ed8", width=2.5),
            mode="lines+markers", marker=dict(size=6), yaxis="y2",
        ))
        fig6.update_layout(
            **COMMON, title="Monthly PO Trend — Count & Value",
            height=380, margin=dict(l=10,r=60,t=50,b=70),
            legend=dict(orientation="h", y=-0.25),
            xaxis=dict(tickangle=45),
            yaxis=dict(title="Count"),
            yaxis2=dict(title="₹ Crore", overlaying="y", side="right"),
            barmode="group",
        )
        st.plotly_chart(fig6, use_container_width=True)

    ch7, ch8 = st.columns(2)

    with ch7:
        # Category value share
        cat_val = df.groupby("Category")["PO Basic Value"].sum().reset_index()
        cat_val = cat_val.sort_values("PO Basic Value", ascending=False).head(10)
        cat_val["Value (Cr)"] = cat_val["PO Basic Value"] / 1e7
        fig7 = px.pie(cat_val, names="Category", values="Value (Cr)",
                      title="PO Value by Category — Top 10",
                      hole=0.42,
                      color_discrete_sequence=px.colors.qualitative.Vivid)
        fig7.update_traces(textposition="outside", textinfo="percent+label")
        fig7.update_layout(**COMMON, height=400, margin=dict(l=20,r=20,t=50,b=20),
                           showlegend=False)
        st.plotly_chart(fig7, use_container_width=True)

    with ch8:
        # Savings % by Project top 15
        proj_sav = df.groupby("Project Name").agg(
            Savings=("Savings Value","sum"),
            Value=("PO Basic Value","sum")
        ).reset_index()
        proj_sav = proj_sav[proj_sav["Value"] > 0].copy()
        proj_sav["Savings %"] = proj_sav["Savings"] / proj_sav["Value"] * 100
        proj_sav = proj_sav[proj_sav["Savings"] > 0].sort_values("Savings", ascending=False).head(12)
        proj_sav["Savings (L)"] = proj_sav["Savings"] / 1e5
        fig8 = px.bar(proj_sav, x="Savings (L)", y="Project Name",
                      orientation="h",
                      title="Top 12 Projects by Savings (₹ Lakhs)",
                      color="Savings %",
                      color_continuous_scale=["#a7f3d0","#16a34a","#14532d"],
                      text="Savings %",
                      custom_data=["Savings (L)"])
        fig8.update_traces(
            texttemplate='%{text:.1f}%',
            textposition='outside',
            hovertemplate="<b>%{y}</b><br>Savings: ₹%{customdata[0]:.1f}L<br>Savings %: %{text}<extra></extra>"
        )
        fig8.update_layout(**COMMON, height=400, margin=dict(l=10,r=60,t=50,b=20),
                           coloraxis_showscale=False)
        st.plotly_chart(fig8, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 3 — DELIVERY
# ═══════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div class="section-title">🚚 Delivery & OTD Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    ch9, ch10 = st.columns(2)

    with ch9:
        # Delivery status by BU stacked
        deliv_bu = df.groupby(["BU","Delivery Status"]).size().reset_index(name="Count")
        fig9 = px.bar(deliv_bu, x="BU", y="Count", color="Delivery Status",
                      title="Delivery Status by Business Unit",
                      color_discrete_map={
                          "Completed":  "#16a34a",
                          "Ongoing":    "#2563eb",
                          "Shortclose": "#dc2626",
                      },
                      barmode="stack", text_auto=True)
        fig9.update_layout(**COMMON, height=380, margin=dict(l=10,r=10,t=50,b=20),
                           legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig9, use_container_width=True)

    with ch10:
        # Avg Delivery TAT by BU
        tat_bu = df.groupby("BU")["Actual Delivery TAT (Days)"].mean().reset_index().dropna()
        tat_bu.columns = ["BU","Avg TAT"]
        tat_bu = tat_bu.sort_values("Avg TAT", ascending=False)
        fig10 = px.bar(tat_bu, x="BU", y="Avg TAT",
                       title="Avg Delivery TAT by BU (Days)",
                       color="Avg TAT",
                       color_continuous_scale=["#86efac","#f97316","#dc2626"],
                       text="Avg TAT")
        fig10.update_traces(texttemplate='%{text:.0f}d', textposition='outside')
        fig10.update_layout(**COMMON, height=380, margin=dict(l=10,r=10,t=50,b=20),
                            coloraxis_showscale=False)
        st.plotly_chart(fig10, use_container_width=True)

    # OTD scatter
    df_otd = df.dropna(subset=["OTD","OTIF","PO Basic Value"]).copy()
    df_otd["OTD %"]  = df_otd["OTD"]  * 100
    df_otd["OTIF %"] = df_otd["OTIF"] * 100

    if len(df_otd) > 0:
        fig11 = px.scatter(
            df_otd, x="OTD %", y="OTIF %",
            color="BU", size="PO Basic Value",
            size_max=30,
            hover_data=["Supplier Name","Project Name","Category","PO/ OD Ref."],
            title="OTD vs OTIF Scatter — Bubble size = PO Value",
            labels={"OTD %":"OTD Ratio (%)","OTIF %":"OTIF Ratio (%)"},
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        fig11.add_hline(y=100, line_dash="dash", line_color="#dc2626",
                        annotation_text="OTIF = 100%", annotation_position="bottom right")
        fig11.add_vline(x=100, line_dash="dash", line_color="#16a34a",
                        annotation_text="OTD = 100%", annotation_position="top left")
        fig11.add_hrect(y0=95, y1=105, fillcolor="#dcfce7", opacity=0.08, line_width=0)
        fig11.update_layout(**COMMON, height=440, margin=dict(l=10,r=10,t=50,b=20),
                            legend=dict(orientation="h", y=-0.12))
        st.plotly_chart(fig11, use_container_width=True)

    # Delivered vs Yet-to-deliver by BU
    if YET_COL in df.columns and DELIV_COL in df.columns:
        deliv_val = df.groupby("BU").agg(
            Delivered=(DELIV_COL,"sum"),
            Yet=(YET_COL,"sum"),
        ).reset_index()
        deliv_val["Delivered (Cr)"] = deliv_val["Delivered"] / 1e7
        deliv_val["Yet (Cr)"]       = deliv_val["Yet"]       / 1e7
        dv_melt = deliv_val.melt(id_vars="BU", value_vars=["Delivered (Cr)","Yet (Cr)"],
                                  var_name="Type", value_name="Value (Cr)")
        fig12 = px.bar(dv_melt, x="BU", y="Value (Cr)", color="Type",
                       title="Delivered vs Yet-to-Deliver by BU (₹ Crore, incl. GST)",
                       color_discrete_map={
                           "Delivered (Cr)": "#16a34a",
                           "Yet (Cr)":       "#f97316",
                       },
                       barmode="group", text_auto=True)
        fig12.update_traces(texttemplate='₹%{text:.1f}Cr')
        fig12.update_layout(**COMMON, height=380, margin=dict(l=10,r=10,t=50,b=20),
                            legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig12, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# TAB 4 — DATA TABLE
# ═══════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown('<div class="section-title">📋 Full Data View</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    # Search
    search = st.text_input("🔍 Search by Project / Supplier / PO Number", placeholder="Type to filter…")

    SHOW = [
        "SN","BU","Project Name","Items","Category","Handled by",
        "PR Dt.","Supplier Name","PO/ OD Ref.","PO Dt.",
        "PO Basic Value","Savings Value","Savings %",
        "Delivery Status","Current Status",
        "Delivery Date at Project Site","PR - PO TAT","Actual Delivery TAT (Days)",
        YET_COL,
    ]
    SHOW = [c for c in SHOW if c in df.columns]
    df_tbl = df[SHOW].copy()

    if search:
        mask = df_tbl.apply(lambda row: row.astype(str).str.contains(search, case=False).any(), axis=1)
        df_tbl = df_tbl[mask]

    # Format
    for c in ["PO Basic Value","Savings Value", YET_COL]:
        if c in df_tbl.columns:
            df_tbl[c] = df_tbl[c].apply(lambda x: f"₹{x/1e5:.1f}L" if pd.notna(x) and x != 0 else "—")
    if "Savings %" in df_tbl.columns:
        df_tbl["Savings %"] = df_tbl["Savings %"].apply(
            lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) and x != "" else "—"
        )

    st.markdown(f"**{len(df_tbl):,} records** matching current filters", unsafe_allow_html=False)
    st.dataframe(df_tbl.reset_index(drop=True), use_container_width=True,
                 hide_index=True, height=500)

    csv = df[SHOW].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download as CSV", csv, "po_tracker_export.csv", "text/csv")

    st.markdown('</div>', unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center; padding:20px; color:#94a3b8; font-size:12px;
            margin-top:24px; border-top:1px solid #e2e8f0;">
  📦 PO Tracker Dashboard &nbsp;·&nbsp; Central Procurement &nbsp;·&nbsp; Zetwerk
  &nbsp;·&nbsp; Last refreshed: {pd.Timestamp.now().strftime('%d-%b-%Y %H:%M')}
  &nbsp;·&nbsp; {total_rows:,} records loaded
</div>
""", unsafe_allow_html=True)
