"""
PO Tracker Dashboard — Central Procurement
Zetwerk | Live data from Google Sheets | 2025 UI
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
import gspread
import time

st.set_page_config(
    page_title="PO Tracker | Zetwerk",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Splash animation ── */
@keyframes fadeInDown {
    from { opacity: 0; transform: translateY(-20px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.5; }
}
@keyframes shimmer {
    0%   { background-position: -200% center; }
    100% { background-position: 200% center; }
}
@keyframes countUp {
    from { opacity: 0; transform: scale(0.8); }
    to   { opacity: 1; transform: scale(1); }
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0a0f1e !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
}
[data-testid="stSidebar"] * { color: #c8d8e8 !important; }
[data-testid="stSidebar"] .stSelectbox label {
    color: #5b7fa6 !important;
    font-size: 10px !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
}
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.08) !important; }
[data-testid="stSidebar"] .stButton button {
    background: linear-gradient(135deg, #1a56db, #0e3eb5) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    width: 100%;
}

/* ── Main background ── */
[data-testid="stMain"] { background: #f0f2f8 !important; }
[data-testid="stAppViewBlockContainer"] {
    padding-top: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    max-width: 100% !important;
    background: #f0f2f8 !important;
}

/* ── KPI Cards ── */
.kpi-grid { display: grid; grid-template-columns: repeat(6,1fr); gap: 12px; padding: 0 1.5rem; margin-bottom: 12px; }
.kpi-grid-4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; padding: 0 1.5rem; margin-bottom: 20px; }

.kpi-card {
    background: #ffffff;
    border-radius: 16px;
    padding: 16px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04);
    border: 1px solid rgba(255,255,255,0.8);
    position: relative;
    overflow: hidden;
    animation: countUp 0.5s ease forwards;
    transition: transform 0.2s, box-shadow 0.2s;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    border-radius: 16px 16px 0 0;
}
.kpi-card.blue::before   { background: linear-gradient(90deg, #1a56db, #3b82f6); }
.kpi-card.green::before  { background: linear-gradient(90deg, #059669, #34d399); }
.kpi-card.orange::before { background: linear-gradient(90deg, #ea580c, #fb923c); }
.kpi-card.purple::before { background: linear-gradient(90deg, #7c3aed, #a78bfa); }
.kpi-card.teal::before   { background: linear-gradient(90deg, #0d9488, #2dd4bf); }
.kpi-card.pink::before   { background: linear-gradient(90deg, #db2777, #f472b6); }
.kpi-card.amber::before  { background: linear-gradient(90deg, #d97706, #fbbf24); }
.kpi-card.red::before    { background: linear-gradient(90deg, #dc2626, #f87171); }

.kpi-icon-wrap {
    width: 36px; height: 36px;
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    margin-bottom: 10px;
}
.kpi-card.blue   .kpi-icon-wrap { background: #eff6ff; }
.kpi-card.green  .kpi-icon-wrap { background: #f0fdf4; }
.kpi-card.orange .kpi-icon-wrap { background: #fff7ed; }
.kpi-card.purple .kpi-icon-wrap { background: #faf5ff; }
.kpi-card.teal   .kpi-icon-wrap { background: #f0fdfa; }
.kpi-card.pink   .kpi-icon-wrap { background: #fdf2f8; }
.kpi-card.amber  .kpi-icon-wrap { background: #fffbeb; }
.kpi-card.red    .kpi-icon-wrap { background: #fef2f2; }

.kpi-label { font-size: 10px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 2px; }
.kpi-value { font-size: 22px; font-weight: 800; color: #0f172a; line-height: 1.1; letter-spacing: -0.02em; }
.kpi-sub   { font-size: 11px; color: #94a3b8; margin-top: 4px; }
.kpi-trend { font-size: 11px; font-weight: 600; margin-top: 4px; }
.kpi-trend.up   { color: #059669; }
.kpi-trend.down { color: #dc2626; }
.kpi-trend.neutral { color: #64748b; }

/* ── Section titles ── */
.section-title {
    font-size: 13px; font-weight: 700; color: #334155;
    margin: 0 1.5rem 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    display: flex; align-items: center; gap: 8px;
}

/* ── Tabs ── */
div[data-testid="stTabs"] {
    background: white;
    border-radius: 0;
    border-bottom: 1px solid #e2e8f0;
    padding: 0 1.5rem;
    margin-bottom: 0;
}
div[data-testid="stTabs"] button[role="tab"] {
    font-size: 13px !important;
    font-weight: 600 !important;
    padding: 14px 20px !important;
    color: #64748b !important;
    border-radius: 0 !important;
    letter-spacing: 0.01em;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #1a56db !important;
    border-bottom: 2px solid #1a56db !important;
    background: transparent !important;
}
div[data-testid="stTabs"] button[role="tab"]:hover {
    color: #1a56db !important;
    background: #f8faff !important;
}

/* ── Chart containers ── */
.chart-container {
    background: white;
    border-radius: 16px;
    padding: 4px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    border: 1px solid #f1f5f9;
    margin-bottom: 16px;
}

/* ── Score badge ── */
.score-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px;
    border-radius: 8px;
    font-size: 13px; font-weight: 700;
}

/* ── Status pill ── */
.pill {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
}

/* ── Live indicator ── */
.live-dot {
    display: inline-block;
    width: 8px; height: 8px;
    background: #22c55e;
    border-radius: 50%;
    animation: pulse 2s infinite;
    margin-right: 6px;
}

.chart-wrap { padding: 0 1.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Google Sheets ─────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
YET_COL   = "PO YET TO BE DELIVERED\n(incl. GST)"
DELIV_COL = "PO DELIVERED VALUE \n(incl. GST)"

PAYMENT_SCORES = {
    "Advance": -2, "Advance on Dispatch": 0,
    "IBC 90": 1, "IBC 60": 2, "IBC 45": 3, "IBC 30": 5,
    "VFS": 3, "IFC 30": 5, "IFC 45": 4, "IFC 60": 3, "IFC 90": 6,
    "Clean Credit 15": 3, "Clean Credit 30": 5,
    "Clean Credit 45": 7, "Clean Credit 60": 8, "Clean Credit 90": 10,
    "On Delivery": 2, "On Dispatch": 0,
}

def parse_payment_score(term):
    if not term or str(term).strip() == "": return None
    total_score, total_pct = 0, 0
    parts = str(term).split("+")
    for part in parts:
        part = part.strip()
        pct = 100
        for p in part.split():
            if "%" in p:
                try: pct = float(p.replace("%",""))
                except: pass
        score = 0
        for key, val in PAYMENT_SCORES.items():
            if key.lower() in part.lower():
                score = val; break
        total_score += (pct/100) * score
        total_pct += pct
    return round(total_score, 2) if total_pct > 0 else None

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

    NUM = ["PR Qty","PO Basic Value","GST","PO Value with GST","PCA Basic Value",
           "PCA Value with GST","Savings Value","Savings %","PR - PO TAT",
           "Actual Delivery TAT (Days)","Realized Saving","Realized PO Value (Basic)",
           YET_COL, DELIV_COL]
    for c in NUM:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")

    DATES = ["PR Dt.","PO Dt.","Delivery Date at Project Site",
             "NFA Dt.","NFA App. Dt","MFC Dt.","Rev. PR Dt/ PR App. From Finance"]
    for c in DATES:
        if c in df.columns: df[c] = pd.to_datetime(df[c], errors="coerce")

    for c in ["OTD","OTIF"]:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")

    if "PO Payment Terms" in df.columns:
        df["payment_score"] = df["PO Payment Terms"].apply(parse_payment_score)

    return df

# ── Splash Screen ─────────────────────────────────────────────────────────────
splash = st.empty()
with splash.container():
    st.markdown("""
    <div style="min-height:100vh; display:flex; align-items:center; justify-content:center;
                background:linear-gradient(135deg,#0a0f1e 0%,#0d1f3c 50%,#0a1628 100%);">
      <div style="text-align:center; animation:fadeInDown 0.8s ease;">
        <div style="font-size:64px; margin-bottom:16px; animation:fadeInDown 0.6s ease;">📦</div>
        <div style="font-size:13px; color:#3b82f6; letter-spacing:0.2em; font-weight:600;
                    text-transform:uppercase; margin-bottom:8px; animation:fadeInDown 0.7s ease;">
          ZETWERK · CENTRAL PROCUREMENT
        </div>
        <h1 style="font-size:2.8rem; font-weight:900; color:white; margin:0 0 8px;
                   letter-spacing:-0.03em; animation:fadeInDown 0.8s ease;">
          PO Tracker
        </h1>
        <p style="color:rgba(255,255,255,0.45); font-size:14px; margin:0 0 40px;
                  animation:fadeInUp 0.9s ease;">
          CAT-2 · EM / Pipes / Fittings / Consumables
        </p>
        <div style="display:flex; align-items:center; justify-content:center; gap:10px;
                    animation:fadeInUp 1s ease;">
          <div style="width:200px; height:4px; background:rgba(255,255,255,0.1);
                      border-radius:4px; overflow:hidden;">
            <div style="height:100%; background:linear-gradient(90deg,#1a56db,#3b82f6,#1a56db);
                        background-size:200% auto; animation:shimmer 1.5s linear infinite;
                        border-radius:4px; width:100%;"></div>
          </div>
        </div>
        <p style="color:rgba(255,255,255,0.3); font-size:12px; margin-top:16px;
                  animation:pulse 2s infinite;">
          Connecting to Google Sheets…
        </p>
      </div>
    </div>
    """, unsafe_allow_html=True)

df_raw = load_data()
time.sleep(0.5)
splash.empty()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:linear-gradient(135deg,#0a0f1e 0%,#0d1f3c 60%,#0f2d5e 100%);
            padding:20px 2rem 16px; margin:0; width:100%; box-sizing:border-box;
            border-bottom:1px solid rgba(255,255,255,0.06);">
  <div style="display:flex; align-items:center; justify-content:space-between;">
    <div style="display:flex; align-items:center; gap:14px;">
      <div style="width:42px; height:42px; background:linear-gradient(135deg,#1a56db,#3b82f6);
                  border-radius:12px; display:flex; align-items:center; justify-content:center;
                  font-size:20px; box-shadow:0 4px 12px rgba(26,86,219,0.4);">📦</div>
      <div>
        <div style="font-size:10px; color:#3b82f6; letter-spacing:0.15em; font-weight:700;
                    text-transform:uppercase;">Zetwerk · Central Procurement</div>
        <h1 style="margin:2px 0 0; color:#fff; font-size:1.4rem; font-weight:800;
                   letter-spacing:-0.02em;">PO Tracker Dashboard</h1>
      </div>
    </div>
    <div style="display:flex; align-items:center; gap:16px;">
      <div style="text-align:right;">
        <div style="font-size:10px; color:rgba(255,255,255,0.4); letter-spacing:0.05em;">LAST UPDATED</div>
        <div style="font-size:12px; color:rgba(255,255,255,0.7); font-weight:500;">
          {pd.Timestamp.now().strftime('%d %b %Y, %H:%M')}
        </div>
      </div>
      <div style="display:flex; align-items:center; background:rgba(34,197,94,0.12);
                  border:1px solid rgba(34,197,94,0.25); border-radius:999px;
                  padding:5px 12px; gap:6px;">
        <div class="live-dot"></div>
        <span style="font-size:11px; color:#22c55e; font-weight:600;">LIVE</span>
      </div>
    </div>
  </div>
</div>
<div style="height:1px; background:linear-gradient(90deg,transparent,rgba(59,130,246,0.3),transparent);"></div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("""
<div style="padding:16px 0 8px;">
  <div style="font-size:10px; color:#3b82f6; letter-spacing:0.15em; font-weight:700;
              text-transform:uppercase; margin-bottom:4px;">Dashboard</div>
  <div style="font-size:16px; color:white; font-weight:700;">Filters</div>
</div>
""", unsafe_allow_html=True)

def opts(col):
    return ["All"] + sorted(df_raw[col].dropna().astype(str).unique().tolist())

sel_bu     = st.sidebar.selectbox("Business Unit",    opts("BU"))
sel_buyer  = st.sidebar.selectbox("Handled By",       opts("Handled by"))
sel_cat    = st.sidebar.selectbox("Category",         opts("Category"))
sel_status = st.sidebar.selectbox("Current Status",   opts("Current Status"))
sel_deliv  = st.sidebar.selectbox("Delivery Status",  opts("Delivery Status"))

st.sidebar.divider()

if st.sidebar.button("🔄  Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown(f"""
<div style="padding:12px 0; text-align:center;">
  <div style="font-size:10px; color:#3b6b9a; margin-bottom:4px;">AUTO-REFRESH EVERY 5 MIN</div>
  <div style="font-size:11px; color:#4a7fa5;">
    {pd.Timestamp.now().strftime('%d %b %Y · %H:%M')}
  </div>
</div>
""", unsafe_allow_html=True)

# ── Filters ───────────────────────────────────────────────────────────────────
df = df_raw.copy()
if sel_bu     != "All": df = df[df["BU"].astype(str)             == sel_bu]
if sel_buyer  != "All": df = df[df["Handled by"].astype(str)     == sel_buyer]
if sel_cat    != "All": df = df[df["Category"].astype(str)       == sel_cat]
if sel_status != "All": df = df[df["Current Status"].astype(str) == sel_status]
if sel_deliv  != "All": df = df[df["Delivery Status"].astype(str)== sel_deliv]

# ── KPIs ──────────────────────────────────────────────────────────────────────
total_rows     = len(df)
po_released    = (df["Current Status"] == "PO RELEASED").sum()
delivered      = (df["Current Status"] == "MATERIAL DELIVERED AT SITE").sum()
partial_deliv  = (df["Current Status"] == "PARTIAL MATERIAL DELIVERED AT SITE").sum()
ongoing        = (df["Delivery Status"] == "Ongoing").sum()
completed      = (df["Delivery Status"] == "Completed").sum()
on_hold        = (df["Current Status"].str.contains("HOLD|Hold", na=False)).sum()
total_po_val   = df["PO Basic Value"].fillna(0).sum()
total_po_gst   = df["PO Value with GST"].fillna(0).sum()
total_savings  = df["Savings Value"].fillna(0).sum()
total_yet      = df[YET_COL].fillna(0).sum()   if YET_COL   in df.columns else 0
total_deliv_v  = df[DELIV_COL].fillna(0).sum() if DELIV_COL in df.columns else 0
savings_pct    = (total_savings / total_po_val * 100) if total_po_val else 0
avg_pr_po_tat  = df["PR - PO TAT"].mean()
avg_deliv_tat  = df["Actual Delivery TAT (Days)"].mean()
otd_ok         = (df["OTD"].dropna() <= 1).sum()
otd_total      = df["OTD"].dropna().count()
otd_rate       = (otd_ok / otd_total * 100) if otd_total else 0
deliv_pct      = (total_deliv_v / total_po_gst * 100) if total_po_gst else 0

has_payment    = "payment_score" in df.columns and df["payment_score"].notna().any()
avg_pt_score   = df["payment_score"].mean() if has_payment else None

COMMON = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter", size=12, color="#475569"),
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "  Overview  ", "  Performance  ", "  Delivery  ", "  Data Table  "
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # KPI Row 1
    st.markdown('<div class="kpi-grid">', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)

    cards_r1 = [
        (c1,"blue","📋","Total PRs / POs", f"{total_rows:,}", f"Active records","neutral"),
        (c2,"green","✅","PO Released", f"{po_released:,}", f"{po_released/max(total_rows,1)*100:.0f}% of total","up"),
        (c3,"teal","🏭","At Site", f"{delivered:,}", f"+{partial_deliv} partial","up"),
        (c4,"purple","💰","PO Value", f"₹{total_po_val/1e7:.1f} Cr", "Basic value","neutral"),
        (c5,"green","💚","Savings", f"₹{total_savings/1e5:.1f} L", f"{savings_pct:.1f}% saved","up"),
        (c6,"orange","⏳","Yet to Deliver", f"₹{total_yet/1e7:.1f} Cr", "Pending","down"),
    ]
    for col, color, icon, label, value, sub, trend in cards_r1:
        with col:
            st.markdown(f"""
            <div class="kpi-card {color}">
              <div class="kpi-icon-wrap">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # KPI Row 2
    st.markdown('<div class="kpi-grid-4">', unsafe_allow_html=True)
    c7,c8,c9,c10 = st.columns(4)
    cards_r2 = [
        (c7,"blue","⚡","Avg PR→PO TAT", f"{avg_pr_po_tat:.0f} days","Procurement speed","neutral"),
        (c8,"amber","🚛","Avg Delivery TAT", f"{avg_deliv_tat:.0f} days","PO to site","neutral"),
        (c9,"green","🎯","OTD Rate", f"{otd_rate:.0f}%", f"{otd_ok}/{otd_total} on time","up"),
        (c10,"pink","⛔","On Hold", f"{on_hold:,}", "Needs attention","down"),
    ]
    for col, color, icon, label, value, sub, trend in cards_r2:
        with col:
            st.markdown(f"""
            <div class="kpi-card {color}">
              <div class="kpi-icon-wrap">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Charts
    st.markdown('<div class="section-title">📊 Business Unit Breakdown</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)
    ch1, ch2 = st.columns(2)

    with ch1:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        bu_grp = df.groupby("BU").agg(Count=("SN","count"), Value=("PO Basic Value","sum")).reset_index().sort_values("Value",ascending=False)
        bu_grp["Value (Cr)"] = bu_grp["Value"]/1e7
        fig1 = px.bar(bu_grp, x="BU", y="Value (Cr)", title="PO Value by BU (₹ Cr)",
                      color="Value (Cr)", color_continuous_scale=["#bfdbfe","#1a56db","#0e3eb5"],
                      text="Value (Cr)", custom_data=["Count"])
        fig1.update_traces(texttemplate='₹%{text:.1f}Cr', textposition='outside',
                           hovertemplate="<b>%{x}</b><br>₹%{y:.1f} Cr<br>%{customdata[0]} POs<extra></extra>",
                           marker_line_width=0)
        fig1.update_layout(**COMMON, height=340, margin=dict(l=10,r=10,t=50,b=20),
                           showlegend=False, coloraxis_showscale=False,
                           title_font=dict(size=13, color="#0f172a"))
        st.plotly_chart(fig1, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with ch2:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        sc = df["Current Status"].value_counts().reset_index()
        sc.columns = ["Status","Count"]
        sc.loc[sc["Count"] < 4, "Status"] = "Others"
        sc = sc.groupby("Status")["Count"].sum().reset_index().sort_values("Count",ascending=False)
        fig2 = px.pie(sc, names="Status", values="Count", title="Status Distribution",
                      hole=0.55, color_discrete_sequence=["#1a56db","#0d9488","#7c3aed","#ea580c","#db2777","#d97706","#64748b"])
        fig2.update_traces(textposition="outside", textinfo="percent+label", pull=[0.02]*len(sc))
        fig2.update_layout(**COMMON, height=340, margin=dict(l=20,r=20,t=50,b=20),
                           showlegend=False, title_font=dict(size=13, color="#0f172a"))
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    ch3, ch4 = st.columns(2)
    with ch3:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        bg = df.groupby("Handled by").agg(Count=("SN","count"), Value=("PO Basic Value","sum")).reset_index().sort_values("Count",ascending=True)
        bg["Value (Cr)"] = bg["Value"]/1e7
        fig3 = px.bar(bg, x="Count", y="Handled by", orientation="h",
                      title="POs per Buyer", color="Value (Cr)",
                      color_continuous_scale=["#a7f3d0","#059669","#064e3b"],
                      text="Count", custom_data=["Value (Cr)"])
        fig3.update_traces(textposition="outside", marker_line_width=0,
                           hovertemplate="<b>%{y}</b><br>%{x} POs · ₹%{customdata[0]:.1f}Cr<extra></extra>")
        fig3.update_layout(**COMMON, height=340, margin=dict(l=10,r=50,t=50,b=20),
                           coloraxis_showscale=False, title_font=dict(size=13, color="#0f172a"))
        st.plotly_chart(fig3, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with ch4:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        cs = df.groupby("Category")["Savings Value"].sum().reset_index()
        cs = cs[cs["Savings Value"]>0].sort_values("Savings Value",ascending=False).head(10)
        cs["Savings (L)"] = cs["Savings Value"]/1e5
        fig4 = px.bar(cs, x="Category", y="Savings (L)", title="Savings by Category (₹ L)",
                      color="Savings (L)", color_continuous_scale=["#fde68a","#f59e0b","#78350f"],
                      text="Savings (L)")
        fig4.update_traces(texttemplate='₹%{text:.1f}L', textposition='outside', marker_line_width=0)
        fig4.update_layout(**COMMON, height=340, margin=dict(l=10,r=10,t=50,b=50),
                           coloraxis_showscale=False, xaxis_tickangle=30,
                           title_font=dict(size=13, color="#0f172a"))
        st.plotly_chart(fig4, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📈 Procurement Performance</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    ch5, ch6 = st.columns(2)
    with ch5:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        tat = df.groupby("Handled by")["PR - PO TAT"].mean().reset_index().dropna()
        tat.columns = ["Buyer","Avg TAT"]
        tat = tat.sort_values("Avg TAT")
        fig5 = px.bar(tat, x="Avg TAT", y="Buyer", orientation="h",
                      title="Avg PR→PO TAT by Buyer (Days)",
                      color="Avg TAT", color_continuous_scale=["#86efac","#f97316","#dc2626"],
                      text="Avg TAT")
        fig5.update_traces(texttemplate='%{text:.0f}d', textposition='outside', marker_line_width=0)
        fig5.update_layout(**COMMON, height=360, margin=dict(l=10,r=50,t=50,b=20),
                           coloraxis_showscale=False, title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig5, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with ch6:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        trend = df.dropna(subset=["PO Dt."]).copy()
        trend["Month"] = trend["PO Dt."].dt.to_period("M").astype(str)
        monthly = trend.groupby("Month").agg(Count=("SN","count"), Value=("PO Basic Value","sum")).reset_index().tail(18)
        monthly["Value (Cr)"] = monthly["Value"]/1e7
        fig6 = go.Figure()
        fig6.add_trace(go.Bar(x=monthly["Month"], y=monthly["Count"],
                              name="Count", marker_color="#bfdbfe", yaxis="y"))
        fig6.add_trace(go.Scatter(x=monthly["Month"], y=monthly["Value (Cr)"],
                                  name="₹Cr", line=dict(color="#1a56db",width=2.5),
                                  mode="lines+markers", marker=dict(size=5,color="#1a56db"), yaxis="y2"))
        fig6.update_layout(**COMMON, title="Monthly PO Trend",
                           height=360, margin=dict(l=10,r=60,t=50,b=70),
                           legend=dict(orientation="h",y=-0.25),
                           xaxis=dict(tickangle=45),
                           yaxis=dict(title="Count"),
                           yaxis2=dict(title="₹ Cr", overlaying="y", side="right"),
                           title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig6, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    ch7, ch8 = st.columns(2)
    with ch7:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        cv = df.groupby("Category")["PO Basic Value"].sum().reset_index().sort_values("PO Basic Value",ascending=False).head(10)
        cv["Value (Cr)"] = cv["PO Basic Value"]/1e7
        fig7 = px.pie(cv, names="Category", values="Value (Cr)", title="Value by Category — Top 10",
                      hole=0.45, color_discrete_sequence=px.colors.qualitative.Vivid)
        fig7.update_traces(textposition="outside", textinfo="percent+label")
        fig7.update_layout(**COMMON, height=380, margin=dict(l=20,r=20,t=50,b=20),
                           showlegend=False, title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig7, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with ch8:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        ps = df.groupby("Project Name").agg(Savings=("Savings Value","sum"), Value=("PO Basic Value","sum")).reset_index()
        ps = ps[ps["Value"]>0].copy()
        ps["Savings %"] = ps["Savings"]/ps["Value"]*100
        ps = ps[ps["Savings"]>0].sort_values("Savings",ascending=False).head(12)
        ps["Savings (L)"] = ps["Savings"]/1e5
        fig8 = px.bar(ps, x="Savings (L)", y="Project Name", orientation="h",
                      title="Top 12 Projects by Savings",
                      color="Savings %", color_continuous_scale=["#a7f3d0","#16a34a","#14532d"],
                      text="Savings %", custom_data=["Savings (L)"])
        fig8.update_traces(texttemplate='%{text:.1f}%', textposition='outside', marker_line_width=0)
        fig8.update_layout(**COMMON, height=380, margin=dict(l=10,r=60,t=50,b=20),
                           coloraxis_showscale=False, title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig8, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — DELIVERY
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">🚚 Delivery & OTD Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    ch9, ch10 = st.columns(2)
    with ch9:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        db = df.groupby(["BU","Delivery Status"]).size().reset_index(name="Count")
        fig9 = px.bar(db, x="BU", y="Count", color="Delivery Status",
                      title="Delivery Status by BU",
                      color_discrete_map={"Completed":"#059669","Ongoing":"#1a56db","Shortclose":"#dc2626"},
                      barmode="stack", text_auto=True)
        fig9.update_layout(**COMMON, height=360, margin=dict(l=10,r=10,t=50,b=20),
                           legend=dict(orientation="h",y=-0.15),
                           title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig9, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with ch10:
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        tb = df.groupby("BU")["Actual Delivery TAT (Days)"].mean().reset_index().dropna()
        tb.columns = ["BU","Avg TAT"]
        tb = tb.sort_values("Avg TAT",ascending=False)
        fig10 = px.bar(tb, x="BU", y="Avg TAT", title="Avg Delivery TAT by BU (Days)",
                       color="Avg TAT", color_continuous_scale=["#86efac","#f97316","#dc2626"],
                       text="Avg TAT")
        fig10.update_traces(texttemplate='%{text:.0f}d', textposition='outside', marker_line_width=0)
        fig10.update_layout(**COMMON, height=360, margin=dict(l=10,r=10,t=50,b=20),
                            coloraxis_showscale=False, title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig10, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    df_otd = df.dropna(subset=["OTD","OTIF","PO Basic Value"]).copy()
    if len(df_otd) > 0:
        df_otd["OTD %"]  = df_otd["OTD"]  * 100
        df_otd["OTIF %"] = df_otd["OTIF"] * 100
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        fig11 = px.scatter(df_otd, x="OTD %", y="OTIF %",
                           color="BU", size="PO Basic Value", size_max=28,
                           hover_data=["Supplier Name","Project Name","Category","PO/ OD Ref."],
                           title="OTD vs OTIF — Bubble = PO Value",
                           color_discrete_sequence=px.colors.qualitative.Bold)
        fig11.add_hline(y=100, line_dash="dash", line_color="#dc2626", line_width=1)
        fig11.add_vline(x=100, line_dash="dash", line_color="#059669", line_width=1)
        fig11.update_layout(**COMMON, height=420, margin=dict(l=10,r=10,t=50,b=20),
                            legend=dict(orientation="h",y=-0.12),
                            title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig11, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    if YET_COL in df.columns and DELIV_COL in df.columns:
        dv = df.groupby("BU").agg(Delivered=(DELIV_COL,"sum"), Yet=(YET_COL,"sum")).reset_index()
        dv["Delivered (Cr)"] = dv["Delivered"]/1e7
        dv["Yet (Cr)"]       = dv["Yet"]/1e7
        dvm = dv.melt(id_vars="BU", value_vars=["Delivered (Cr)","Yet (Cr)"],
                      var_name="Type", value_name="Value (Cr)")
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        fig12 = px.bar(dvm, x="BU", y="Value (Cr)", color="Type",
                       title="Delivered vs Yet-to-Deliver by BU (₹ Cr, incl. GST)",
                       color_discrete_map={"Delivered (Cr)":"#059669","Yet (Cr)":"#ea580c"},
                       barmode="group", text_auto=True)
        fig12.update_traces(texttemplate='₹%{text:.1f}Cr', marker_line_width=0)
        fig12.update_layout(**COMMON, height=360, margin=dict(l=10,r=10,t=50,b=20),
                            legend=dict(orientation="h",y=-0.15),
                            title_font=dict(size=13,color="#0f172a"))
        st.plotly_chart(fig12, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — DATA TABLE
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📋 Full Data View</div>', unsafe_allow_html=True)
    st.markdown('<div class="chart-wrap">', unsafe_allow_html=True)

    srch = st.text_input("🔍 Search by Project / Supplier / PO Number / Category", placeholder="Type to filter…")

    SHOW = ["SN","BU","Project Name","Items","Category","Handled by",
            "PR Dt.","Supplier Name","PO/ OD Ref.","PO Dt.",
            "PO Basic Value","Savings Value","Savings %",
            "Delivery Status","Current Status",
            "Delivery Date at Project Site","PR - PO TAT","Actual Delivery TAT (Days)", YET_COL]
    SHOW = [c for c in SHOW if c in df.columns]
    df_tbl = df[SHOW].copy()

    if srch:
        mask = df_tbl.apply(lambda r: r.astype(str).str.contains(srch, case=False).any(), axis=1)
        df_tbl = df_tbl[mask]

    for c in ["PO Basic Value","Savings Value",YET_COL]:
        if c in df_tbl.columns:
            df_tbl[c] = df_tbl[c].apply(lambda x: f"₹{x/1e5:.1f}L" if pd.notna(x) and x!=0 else "—")
    if "Savings %" in df_tbl.columns:
        df_tbl["Savings %"] = df_tbl["Savings %"].apply(
            lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) and str(x).strip() not in ["","nan"] else "—"
        )

    st.markdown(f"**{len(df_tbl):,} records** matching filters", unsafe_allow_html=False)
    st.dataframe(df_tbl.reset_index(drop=True), use_container_width=True, hide_index=True, height=500)

    csv = df[SHOW].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Export CSV", csv, "po_tracker_export.csv", "text/csv")
    st.markdown('</div>', unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:#0a0f1e; padding:16px 2rem; margin-top:24px;
            border-top:1px solid rgba(255,255,255,0.06);">
  <div style="display:flex; align-items:center; justify-content:space-between;">
    <div style="display:flex; align-items:center; gap:8px;">
      <span style="font-size:14px;">📦</span>
      <span style="font-size:12px; color:rgba(255,255,255,0.35);">
        PO Tracker · Central Procurement · Zetwerk
      </span>
    </div>
    <div style="font-size:12px; color:rgba(255,255,255,0.25);">
      {total_rows:,} records · refreshed {pd.Timestamp.now().strftime('%d %b %Y %H:%M')}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)
