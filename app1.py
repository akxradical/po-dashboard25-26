"""
Zetwerk CPT — Central Procurement Dashboard
Live Google Sheets + CAT 2 Buddy (Anthropic)
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import time
from datetime import date, datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import anthropic

st.set_page_config(
    page_title="Zetwerk CPT Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── SCORE MAP ─────────────────────────────────────────────────
SCORE_MAP = {
    "advance": -2, "on dispatch": 0,
    "ibc 90": 1, "ibc 60": 2,
    "ibc 60, ifc 30": 3, "ibc 60+ifc 30": 3,
    "vfs": 3, "clean credit 15": 3,
    "ibc 45, ifc 45": 4, "ibc 45+ifc 45": 4, "rxil": 4,
    "ifc 30": 5, "ifc 45": 5, "ifc 60": 5,
    "ibc 30, ifc 60": 5, "ibc 30+ifc 60": 5, "clean credit 30": 5,
    "ifc 90": 6, "clean credit 45": 7,
    "clean credit 60": 8, "clean credit 90": 10,
}

def get_score(term):
    if not term or str(term).strip() in ['', '0', 'nan']:
        return None
    t = str(term).lower()
    parts = t.replace('+', '|').split('|')
    total = 0.0
    for part in parts:
        part = part.strip()
        pct = 100.0
        for word in part.split():
            if '%' in word:
                try: pct = float(word.replace('%',''))
                except: pass
        best = 0
        for key, val in SCORE_MAP.items():
            if key in part:
                best = val; break
        total += (pct / 100.0) * best
    return round(total, 3)

# ── LOAD DATA ─────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_sheet_data():
    try:
        if "gcp_service_account" not in st.secrets:
            return pd.DataFrame(), pd.DataFrame(), "Missing gcp_service_account secret"
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive"])
        gc   = gspread.authorize(creds)
        book = gc.open_by_key("11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU")

        # PO TRACKER
        ws  = book.worksheet("PO TRACKER")
        raw = ws.get_all_values()
        if len(raw) < 2:
            return pd.DataFrame(), pd.DataFrame(), "PO TRACKER is empty"
        df = pd.DataFrame(raw[1:], columns=[c.strip() for c in raw[0]])
        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()

        for col in ['PR Dt.', 'PO Dt.', 'MFC Dt.', 'Delivery Date at Site']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)

        num_cols = ['PO Basic Value', 'PO Value with GST', 'PCA Basic Value',
                    'PCA Value with GST', 'Savings Value', 'PR - PO TAT',
                    'Realized Saving', 'OTD', 'OTIF',
                    'Delivery Time from MFC (Days)', 'Actual Delivery TAT (Days)']
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(',','').str.replace('%',''),
                    errors='coerce').fillna(0)

        if 'PO Dt.' in df.columns:
            df = df[(df['PO Dt.'] >= pd.Timestamp('2025-04-01')) &
                    (df['PO Dt.'] <= pd.Timestamp('2026-03-31'))].copy()

        pt_col = next((c for c in ['PAYMENT TERMS','Payment Terms'] if c in df.columns), None)
        if pt_col:
            if pt_col != 'PAYMENT TERMS':
                df = df.rename(columns={pt_col: 'PAYMENT TERMS'})
            df['Payment Score'] = df['PAYMENT TERMS'].apply(get_score)

        if 'PO Dt.' in df.columns:
            df['Month_str'] = df['PO Dt.'].dt.strftime("%b'%y")

        # YET TO BE DELIVERED
        try:
            ws2  = book.worksheet("yet to be delivered")
            raw2 = ws2.get_all_values()
            ytd  = pd.DataFrame(raw2[1:], columns=[c.strip() for c in raw2[0]]) if len(raw2)>1 else pd.DataFrame()
            for c in ytd.columns:
                if any(k in c.lower() for k in ['value','deliver','gst']):
                    ytd[c] = pd.to_numeric(ytd[c].astype(str).str.replace(',',''), errors='coerce')
        except Exception:
            ytd = pd.DataFrame()

        return df, ytd, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), str(e)

# ── BUILD BUDDY CONTEXT ───────────────────────────────────────
def build_context(df):
    if df.empty:
        return "No data available."
    ctx = f"""You are CAT 2 Buddy, the AI procurement assistant for Zetwerk CPT CAT-2.
Sharp, professional, data-driven. Never mention Claude or Anthropic. You are CAT 2 Buddy.

=== FY 2025-26 DATA ===
Total POs: {len(df)}
Total Spend (Basic): Rs {df['PO Basic Value'].sum()/1e7:.2f} Cr
Total Savings: Rs {df['Savings Value'].sum()/1e7:.2f} Cr

BU Breakdown:\n"""
    if 'BU' in df.columns:
        for bu in df['BU'].dropna().unique():
            if str(bu).strip():
                sub = df[df['BU']==bu]
                ctx += f"  {bu}: {len(sub)} POs, Rs {sub['PO Basic Value'].sum()/1e7:.2f} Cr\n"
    if 'Supplier type' in df.columns:
        ctx += "\nSupplier Types:\n"
        for st2, cnt in df['Supplier type'].value_counts().items():
            if st2: ctx += f"  {st2}: {cnt} POs\n"
    if 'Category' in df.columns:
        ctx += "\nTop Categories:\n"
        for c, v in df.groupby('Category')['PO Basic Value'].sum().sort_values(ascending=False).head(8).items():
            if c: ctx += f"  {c}: Rs {v/1e7:.2f} Cr\n"
    if 'Payment Score' in df.columns:
        scored = df[df['Payment Score'].notna() & (df['PO Basic Value']>0)]
        if len(scored) > 0:
            wce = (scored['Payment Score']*scored['PO Basic Value']).sum() / scored['PO Basic Value'].sum()
            ctx += f"\nWorking Capital Score: {wce:.2f} (Target: 4.5)\n"
    ctx += "\nBe precise. Use Rs in Crores. Answer based on this data only."
    return ctx

def chat_with_buddy(user_msg, df):
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY","")
        if not api_key:
            return "ANTHROPIC_API_KEY not found in secrets. Please add it."
        context = build_context(df)
        client  = anthropic.Anthropic(api_key=api_key)
        resp    = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role":"user","content": context + "\n\nQuestion: " + user_msg}]
        )
        return resp.content[0].text
    except Exception as e:
        return f"Error: {str(e)}"

# ══════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
*, html, body { font-family:'DM Sans',sans-serif !important; }
[data-testid="stAppViewContainer"],[data-testid="stMain"] {
    background:#0e0e12 !important; padding:0 !important; max-width:100% !important;
}
[data-testid="stSidebar"] { display:none !important; }
[data-testid="stMainBlockContainer"] { padding:0 !important; max-width:100% !important; }
.nav {
    background:#13131a; border-bottom:1px solid rgba(255,255,255,0.07);
    padding:0 24px; display:flex; align-items:center;
    justify-content:space-between; height:54px; position:sticky; top:0; z-index:100;
}
.nav-logo { display:flex; align-items:center; gap:10px; }
.nav-z {
    width:32px; height:32px; background:linear-gradient(135deg,#e53e3e,#fc4f4f);
    border-radius:8px; display:flex; align-items:center; justify-content:center;
    font-size:16px; font-weight:900; color:white;
}
.nav-brand { font-size:14px; font-weight:700; color:white; }
.nav-sub   { font-size:10px; color:#444; }
.nav-right { display:flex; align-items:center; gap:10px; }
.fy-pill {
    background:rgba(229,62,62,0.12); border:1px solid rgba(229,62,62,0.25);
    color:#fc4f4f; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:600;
}
.live-dot { display:flex; align-items:center; gap:5px; font-size:11px; color:#38a169; }
.dot { width:7px; height:7px; background:#38a169; border-radius:50%; animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.krow { display:grid; gap:10px; padding:14px 20px 0; }
.k5 { grid-template-columns:repeat(5,1fr); }
.k4 { grid-template-columns:repeat(4,1fr); }
.k3 { grid-template-columns:repeat(3,1fr); }
.kcard {
    background:#13131a; border:1px solid rgba(255,255,255,0.07);
    border-radius:12px; padding:16px 18px; position:relative; overflow:hidden;
}
.kcard::before {
    content:''; position:absolute; top:0; left:0; right:0; height:2px; border-radius:12px 12px 0 0;
}
.kc-red::before    { background:linear-gradient(90deg,#e53e3e,#fc8181); }
.kc-green::before  { background:linear-gradient(90deg,#38a169,#68d391); }
.kc-blue::before   { background:linear-gradient(90deg,#3182ce,#63b3ed); }
.kc-amber::before  { background:linear-gradient(90deg,#d69e2e,#f6e05e); }
.kc-purple::before { background:linear-gradient(90deg,#805ad5,#b794f4); }
.kc-teal::before   { background:linear-gradient(90deg,#2c7a7b,#4fd1c5); }
.klabel { font-size:10px; color:#555; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; }
.kvalue { font-size:26px; font-weight:700; color:#fff; line-height:1.1; margin:4px 0 2px;
          letter-spacing:-0.03em; font-family:'DM Mono',monospace; }
.ksub   { font-size:10px; color:#444; }
.kdelta { font-size:11px; font-weight:600; margin-top:5px; }
.kup  { color:#68d391; } .kdown { color:#fc8181; } .kwarn { color:#f6e05e; }
.sec { display:flex; align-items:center; justify-content:space-between; padding:18px 20px 8px; }
.sec-title { font-size:13px; font-weight:700; color:#bbb; }
.sec-tag { font-size:10px; color:#444; background:rgba(255,255,255,0.04);
           border:1px solid rgba(255,255,255,0.07); padding:3px 8px; border-radius:5px; }
.ccard { background:#13131a; border:1px solid rgba(255,255,255,0.07); border-radius:12px; overflow:hidden; }
.ccard-head { padding:12px 16px 0; display:flex; align-items:center; justify-content:space-between; }
.ccard-title { font-size:12px; font-weight:600; color:#888; }
.tbl { width:100%; border-collapse:collapse; font-size:12px; }
.tbl th { text-align:left; padding:9px 12px; font-size:10px; font-weight:600; color:#555;
          text-transform:uppercase; letter-spacing:0.06em; border-bottom:1px solid rgba(255,255,255,0.07); }
.tbl td { padding:9px 12px; color:#bbb; border-bottom:1px solid rgba(255,255,255,0.04); }
.tbl tr:hover td { background:rgba(255,255,255,0.02); }
.mono { font-family:'DM Mono',monospace; font-size:11px; }
.pg { background:rgba(56,161,105,0.15); color:#68d391; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600; }
.pr { background:rgba(229,62,62,0.15);  color:#fc8181; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600; }
.pa { background:rgba(214,158,46,0.15); color:#f6e05e; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600; }
.alert-red  { background:#3a0000; border-left:4px solid #ff4444; padding:12px;
              border-radius:6px; color:#ff9999; font-size:0.95rem; margin:8px 20px; }
.alert-amb  { background:#2a1a00; border-left:4px solid #ffaa00; padding:12px;
              border-radius:6px; color:#ffcc66; font-size:0.95rem; margin:8px 20px; }
/* Streamlit widget overrides */
div[data-testid="stTabs"] button[role="tab"] {
    font-size:12px !important; font-weight:500 !important; color:#555 !important; }
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color:#fc4f4f !important; border-bottom:2px solid #e53e3e !important; }
.stSelectbox>div>div { background:#13131a !important; border:1px solid rgba(255,255,255,0.1) !important;
                       border-radius:8px !important; color:#ccc !important; font-size:12px !important; }
div[data-baseweb="select"] span { color:#ccc !important; font-size:12px !important; }
/* buddy sidebar */
[data-testid="stSidebar"].buddy-active {
    display:block !important; background:#0e0e12 !important;
    border-right:1px solid rgba(255,255,255,0.07) !important;
    min-width:300px !important; max-width:300px !important;
}
</style>
""", unsafe_allow_html=True)

# ── SPLASH + LOAD ─────────────────────────────────────────────
if 'loaded' not in st.session_state:
    splash = st.empty()
    splash.markdown("""
    <div style="position:fixed;inset:0;background:#0e0e12;display:flex;align-items:center;
         justify-content:center;flex-direction:column;z-index:9999;">
      <div style="position:relative;width:80px;height:80px;margin-bottom:24px;">
        <div style="position:absolute;inset:0;border-radius:50%;
             border:2px solid rgba(229,62,62,0.2);border-top:2px solid #e53e3e;
             animation:zspin 1s linear infinite;"></div>
        <style>@keyframes zspin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}</style>
        <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
             width:54px;height:54px;background:linear-gradient(135deg,#e53e3e,#ff6b6b);
             border-radius:14px;display:flex;align-items:center;justify-content:center;
             font-size:26px;font-weight:900;color:white;">Z</div>
      </div>
      <div style="font-size:20px;font-weight:700;color:#fff;">Zetwerk CPT</div>
      <div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.12em;margin-top:6px;">
           Central Procurement · CAT-2</div>
      <div style="margin-top:16px;font-size:11px;color:#333;">Connecting to Google Sheets...</div>
    </div>
    """, unsafe_allow_html=True)
    df_main, ytd_main, err_main = load_sheet_data()
    time.sleep(0.3)
    splash.empty()
    st.session_state['loaded']   = True
    st.session_state['df']       = df_main
    st.session_state['ytd']      = ytd_main
    st.session_state['err']      = err_main
    st.session_state['buddy_msgs'] = [{"role":"assistant","content":"Hi! I am CAT 2 Buddy. Ask me anything about your procurement data."}]
    st.rerun()

df_main  = st.session_state.get('df',  pd.DataFrame())
ytd_main = st.session_state.get('ytd', pd.DataFrame())
err_main = st.session_state.get('err', None)

# ── NAV ───────────────────────────────────────────────────────
now = datetime.now().strftime("%d %b %Y %H:%M")
st.markdown(f"""
<div class="nav">
  <div class="nav-logo">
    <div class="nav-z">Z</div>
    <div><div class="nav-brand">Zetwerk CPT</div><div class="nav-sub">Central Procurement Team</div></div>
  </div>
  <div class="nav-right">
    <div class="live-dot"><div class="dot"></div>Live &middot; {now}</div>
    <div class="fy-pill">FY 2025-26</div>
  </div>
</div>
""", unsafe_allow_html=True)

if err_main:
    st.error(f"Sheet error: {err_main}")
    st.stop()
if df_main.empty:
    st.warning("No data loaded. Check GCP secret and sheet access.")
    st.stop()

df = df_main.copy()

# ── FILTER ROW (top, above tabs) ─────────────────────────────
f1, f2, f3, f4, _ = st.columns([1,1,1,1,2])
with f1:
    bu_opts = ['All BU'] + sorted([b for b in df['BU'].dropna().unique() if b])
    sel_bu  = st.selectbox('BU', bu_opts, key='f_bu')
with f2:
    cat_opts = ['All Category'] + sorted([c for c in df['Category'].dropna().unique() if c]) if 'Category' in df.columns else ['All Category']
    sel_cat  = st.selectbox('Category', cat_opts, key='f_cat')
with f3:
    buyer_opts = ['All Buyers'] + sorted([b for b in df['Handled by'].dropna().unique() if b]) if 'Handled by' in df.columns else ['All Buyers']
    sel_buyer  = st.selectbox('Buyer', buyer_opts, key='f_buyer')
with f4:
    stype_col  = 'Supplier type' if 'Supplier type' in df.columns else None
    stype_opts = ['All Supplier Types'] + (sorted([s for s in df[stype_col].dropna().unique() if s]) if stype_col else [])
    sel_stype  = st.selectbox('Supplier Type', stype_opts, key='f_stype')

dff = df.copy()
if sel_bu    != 'All BU':             dff = dff[dff['BU']==sel_bu]
if sel_cat   != 'All Category'   and 'Category'    in dff.columns: dff = dff[dff['Category']==sel_cat]
if sel_buyer != 'All Buyers'     and 'Handled by'  in dff.columns: dff = dff[dff['Handled by']==sel_buyer]
if sel_stype != 'All Supplier Types' and stype_col: dff = dff[dff[stype_col]==sel_stype]

# ── KPIs ──────────────────────────────────────────────────────
total_pos   = len(dff[dff['PO Basic Value']>0])
total_spend = dff['PO Basic Value'].sum() / 1e7
total_sav   = dff['Savings Value'].sum() / 1e7
sav_pct     = (total_sav / total_spend * 100) if total_spend > 0 else 0
avg_tat     = pd.to_numeric(dff['PR - PO TAT'], errors='coerce').replace(0, np.nan).mean() if 'PR - PO TAT' in dff.columns else 0

comp_mask   = dff['Delivery Status'].str.strip().str.lower().isin(['completed','shortclose']) if 'Delivery Status' in dff.columns else pd.Series([True]*len(dff))
comp        = dff[comp_mask]
otif_vals   = pd.to_numeric(comp['OTIF'], errors='coerce').replace(0,np.nan).dropna() if 'OTIF' in comp.columns else pd.Series(dtype=float)
otd_vals    = pd.to_numeric(comp['OTD'],  errors='coerce').replace(0,np.nan).dropna() if 'OTD'  in comp.columns else pd.Series(dtype=float)
otif_pct    = (otif_vals <= 1.05).mean() * 100 if len(otif_vals)>0 else 0
otd_pct     = (otd_vals  <= 1.0).mean()  * 100 if len(otd_vals)>0  else 0

nv_pct = nv_count = 0
if stype_col:
    nv_mask  = dff[stype_col].str.contains('NV', case=False, na=False)
    nv_count = nv_mask.sum()
    nv_pct   = (nv_count / len(dff) * 100) if len(dff)>0 else 0

wce_score = None
if 'Payment Score' in dff.columns:
    scored = dff[dff['Payment Score'].notna() & (dff['PO Basic Value']>0)]
    if len(scored)>0:
        wce_score = (scored['Payment Score']*scored['PO Basic Value']).sum() / scored['PO Basic Value'].sum()

DARK = dict(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="#666", size=11),
    xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#333", linecolor="#333"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#333", linecolor="#333"),
    margin=dict(l=8,r=8,t=30,b=8),
)
RED="#e53e3e"; GREEN="#38a169"; BLUE="#3182ce"; AMBER="#d69e2e"

# ── TABS ──────────────────────────────────────────────────────
tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
    " Overview ", " Spend & Savings ", " TAT & OTIF ",
    " Working Capital ", " New Vendor Dev ", " MFC Tracker "
])

# ════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════
with tab1:
    st.markdown(f"""
    <div class="krow k5">
      <div class="kcard kc-blue">
        <div class="klabel">Total POs</div>
        <div class="kvalue">{total_pos}</div>
        <div class="ksub">FY 2025-26</div>
      </div>
      <div class="kcard kc-green">
        <div class="klabel">Total Spend</div>
        <div class="kvalue">Rs {total_spend:.1f} Cr</div>
        <div class="ksub">PO Basic Value</div>
      </div>
      <div class="kcard kc-{'green' if sav_pct>=4.5 else 'amber'}">
        <div class="klabel">Savings</div>
        <div class="kvalue">Rs {total_sav:.2f} Cr</div>
        <div class="ksub">{sav_pct:.1f}% of spend</div>
        <div class="kdelta {'kup' if sav_pct>=4.5 else 'kwarn'}">{'Above' if sav_pct>=4.5 else 'Below'} 4.5% target</div>
      </div>
      <div class="kcard kc-{'green' if avg_tat<=90 else 'red'}">
        <div class="klabel">Avg PR-PO TAT</div>
        <div class="kvalue">{avg_tat:.0f}d</div>
        <div class="ksub">Target: 90 days</div>
        <div class="kdelta {'kup' if avg_tat<=90 else 'kdown'}">{'On track' if avg_tat<=90 else 'Above target'}</div>
      </div>
      <div class="kcard kc-{'green' if wce_score and wce_score>=4.5 else 'red' if wce_score else 'purple'}">
        <div class="klabel">WC Score</div>
        <div class="kvalue">{f"{wce_score:.2f}" if wce_score else "N/A"}</div>
        <div class="ksub">Target: 4.5</div>
        <div class="kdelta {'kup' if wce_score and wce_score>=4.5 else 'kdown' if wce_score else ''}">
          {'Above target' if wce_score and wce_score>=4.5 else 'Below target' if wce_score else 'Fill payment terms'}</div>
      </div>
    </div>
    <div class="krow k4">
      <div class="kcard kc-{'green' if otif_pct>=75 else 'red'}">
        <div class="klabel">OTIF / OTD</div>
        <div class="kvalue">{otif_pct:.1f}%</div>
        <div class="ksub">OTD: {otd_pct:.1f}% | {len(otif_vals)} completed</div>
        <div class="kdelta {'kup' if otif_pct>=75 else 'kdown'}">{'Above' if otif_pct>=75 else 'Below'} 75% target</div>
      </div>
      <div class="kcard kc-{'green' if 10<=nv_pct<=15 else 'amber'}">
        <div class="klabel">New Vendor Dev</div>
        <div class="kvalue">{nv_pct:.1f}%</div>
        <div class="ksub">{nv_count} NV of {len(dff)} POs</div>
        <div class="kdelta kwarn">Target: 10-15%</div>
      </div>
      <div class="kcard kc-teal">
        <div class="klabel">Categories</div>
        <div class="kvalue">{dff['Category'].nunique() if 'Category' in dff.columns else 0}</div>
        <div class="ksub">Active categories</div>
      </div>
      <div class="kcard kc-purple">
        <div class="klabel">Suppliers</div>
        <div class="kvalue">{dff['Supplier Name'].nunique() if 'Supplier Name' in dff.columns else 0}</div>
        <div class="ksub">Unique suppliers</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec"><div class="sec-title">BU Performance</div><div class="sec-tag">FY26 Live</div></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        bg = dff.groupby('BU').agg(spend=('PO Basic Value','sum'),savings=('Savings Value','sum')).reset_index()
        bg['spend_cr']=bg['spend']/1e7; bg['sav_cr']=bg['savings']/1e7
        fig=go.Figure()
        fig.add_trace(go.Bar(name='Spend',x=bg['BU'],y=bg['spend_cr'],marker_color=RED,marker_line_width=0))
        fig.add_trace(go.Bar(name='Savings',x=bg['BU'],y=bg['sav_cr'],marker_color='rgba(56,161,105,0.7)',marker_line_width=0))
        fig.update_layout(**DARK,height=280,barmode='group',title_text='Spend & Savings by BU (Rs Cr)',
                          legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=10)))
        st.plotly_chart(fig,use_container_width=True)
    with c2:
        if 'Category' in dff.columns:
            cg=dff.groupby('Category')['PO Basic Value'].sum().sort_values(ascending=False).head(8).reset_index()
            cg['cr']=cg['PO Basic Value']/1e7
            fig2=go.Figure(go.Bar(y=cg['Category'],x=cg['cr'],orientation='h',marker_color=RED,marker_line_width=0,
                                  text=cg['cr'].apply(lambda x:f'Rs{x:.1f}Cr'),textposition='outside',textfont=dict(color='#888',size=10)))
            fig2.update_layout(**DARK,height=280,title_text='Top Categories by Spend')
            st.plotly_chart(fig2,use_container_width=True)

    # YTD section
    if not ytd_main.empty:
        st.markdown('<div class="sec"><div class="sec-title">Yet to Be Delivered</div></div>', unsafe_allow_html=True)
        ytd_val_col = None
        for c in ytd_main.columns:
            if any(k in c.lower() for k in ['yet','deliver']) and pd.api.types.is_numeric_dtype(ytd_main[c]):
                ytd_val_col = c; break
        if ytd_val_col:
            total_ytd = pd.to_numeric(ytd_main[ytd_val_col], errors='coerce').sum() / 1e7
            st.markdown(f'<div style="padding:0 20px 8px;font-size:13px;color:#aaa;">Total yet to be delivered: <b style="color:#7eb8f7">Rs {total_ytd:.2f} Cr</b> across <b style="color:#7eb8f7">{len(ytd_main)} ongoing POs</b></div>', unsafe_allow_html=True)
        with st.container():
            st.dataframe(ytd_main.head(25), use_container_width=True, height=300)

# ════════════════════════════════════════════════
# TAB 2 — SPEND & SAVINGS
# ════════════════════════════════════════════════
with tab2:
    pca_sum  = dff['PCA Value with GST'].sum() if 'PCA Value with GST' in dff.columns else 0
    sav_pct2 = (dff['Savings Value'].sum()/pca_sum*100) if pca_sum>0 else 0
    pca_cr   = pca_sum/1e7

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total Spend",   f"Rs {total_spend:.2f} Cr")
    c2.metric("Total Savings", f"Rs {total_sav:.2f} Cr", f"{sav_pct:.1f}%")
    c3.metric("Target Savings%","4.5%", f"{sav_pct-4.5:.1f}pp vs target")
    best_bu = dff.groupby('BU').apply(lambda x: x['Savings Value'].sum()/x['PO Basic Value'].sum()*100 if x['PO Basic Value'].sum()>0 else 0).idxmax() if len(dff)>0 and 'BU' in dff.columns else "N/A"
    c4.metric("Best Savings BU", best_bu)

    c1,c2 = st.columns(2)
    with c1:
        if 'Month_str' in dff.columns:
            mo = dff.groupby('Month_str').agg(spend=('PO Basic Value','sum'),sav=('Savings Value','sum')).reset_index()
            mo['s_cr']=mo['spend']/1e7; mo['sv_cr']=mo['sav']/1e7
            fig3=go.Figure()
            fig3.add_trace(go.Bar(name='Spend',x=mo['Month_str'],y=mo['s_cr'],marker_color='rgba(229,62,62,0.3)',marker_line_width=0))
            fig3.add_trace(go.Scatter(name='Savings',x=mo['Month_str'],y=mo['sv_cr'],line=dict(color=GREEN,width=2.5),
                                      mode='lines+markers',marker=dict(size=5),yaxis='y2'))
            _d={k:v for k,v in DARK.items() if k not in ('yaxis',)}
            fig3.update_layout(**_d,height=300,title_text='Monthly Spend vs Savings',
                               yaxis=dict(title='Spend Rs Cr',gridcolor='rgba(255,255,255,0.05)',tickcolor='#333',linecolor='#333'),
                               yaxis2=dict(title='Savings Rs Cr',overlaying='y',side='right',gridcolor='rgba(0,0,0,0)'),
                               legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=10)))
            st.plotly_chart(fig3,use_container_width=True)
    with c2:
        bu_s=dff.groupby('BU').agg(spend=('PO Basic Value','sum'),sav=('Savings Value','sum'),count=('PO Basic Value','count')).reset_index()
        bu_s['pct']=(bu_s['sav']/bu_s['spend']*100).fillna(0)
        rows=""
        for _,r in bu_s.sort_values('spend',ascending=False).iterrows():
            pill="pg" if r['pct']>=4.5 else ("pr" if r['pct']<0 else "pa")
            rows+=f"<tr><td><b style='color:#eee'>{r['BU']}</b></td><td class='mono'>Rs{r['spend']/1e7:.2f}Cr</td><td class='mono'>Rs{r['sav']/1e7:.2f}Cr</td><td><span class='{pill}'>{r['pct']:.1f}%</span></td><td class='mono'>{int(r['count'])}</td></tr>"
        st.markdown(f"""<div class="ccard" style="padding:4px 0 8px;margin:0 0 8px;">
          <div class="ccard-head"><span class="ccard-title">BU Savings Summary</span></div>
          <table class="tbl" style="margin-top:8px"><thead><tr><th>BU</th><th>Spend</th><th>Savings</th><th>Sav%</th><th>POs</th></tr></thead>
          <tbody>{rows}</tbody></table></div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════
# TAB 3 — TAT & OTIF
# ════════════════════════════════════════════════
with tab3:
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Avg PR-PO TAT", f"{avg_tat:.0f} days", f"{avg_tat-90:.0f}d vs 90d target")
    c2.metric("OTIF", f"{otif_pct:.1f}%", f"{len(otif_vals)} completed POs")
    c3.metric("OTD",  f"{otd_pct:.1f}%",  f"{len(otd_vals)} completed POs")
    if 'Delivery Status' in dff.columns:
        n_comp = len(dff[dff['Delivery Status'].str.strip().str.lower().isin(['completed','shortclose'])])
        n_ong  = len(dff[dff['Delivery Status'].str.strip().str.lower()=='ongoing'])
        c4.metric("Completed / Ongoing", f"{n_comp} / {n_ong}")

    c1,c2 = st.columns(2)
    with c1:
        if 'PR - PO TAT' in dff.columns and 'BU' in dff.columns:
            bt=dff.groupby('BU').apply(lambda x: pd.to_numeric(x['PR - PO TAT'],errors='coerce').replace(0,np.nan).mean()).reset_index()
            bt.columns=['BU','TAT']; bt=bt.dropna()
            fig4=go.Figure(go.Bar(x=bt['BU'],y=bt['TAT'],
                marker_color=[GREEN if v<=90 else RED for v in bt['TAT']],marker_line_width=0,
                text=bt['TAT'].apply(lambda x:f'{x:.0f}d'),textposition='outside',textfont=dict(color='#888',size=10)))
            fig4.add_hline(y=90,line_dash='dash',line_color=AMBER,annotation_text='90d target',annotation_font_color=AMBER)
            fig4.update_layout(**DARK,height=280,title_text='Avg PR-PO TAT by BU',showlegend=False)
            st.plotly_chart(fig4,use_container_width=True)
    with c2:
        if 'OTIF' in dff.columns and 'BU' in dff.columns:
            rows=[]
            for bu2 in dff['BU'].dropna().unique():
                sub=dff[dff['BU']==bu2]
                if 'Delivery Status' in sub.columns:
                    sub=sub[sub['Delivery Status'].str.strip().str.lower().isin(['completed','shortclose'])]
                v=pd.to_numeric(sub['OTIF'],errors='coerce').replace(0,np.nan).dropna()
                if len(v)>0: rows.append({'BU':bu2,'OTIF%':(v<=1.05).mean()*100})
            if rows:
                bo=pd.DataFrame(rows)
                fig5=go.Figure(go.Bar(x=bo['BU'],y=bo['OTIF%'],
                    marker_color=[GREEN if v>=75 else RED for v in bo['OTIF%']],marker_line_width=0,
                    text=bo['OTIF%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#888',size=10)))
                fig5.add_hline(y=75,line_dash='dash',line_color=AMBER,annotation_text='75% target',annotation_font_color=AMBER)
                fig5.update_layout(**DARK,height=280,title_text='OTIF % by BU',showlegend=False,yaxis_range=[0,110])
                st.plotly_chart(fig5,use_container_width=True)

# ════════════════════════════════════════════════
# TAB 4 — WORKING CAPITAL
# ════════════════════════════════════════════════
with tab4:
    st.markdown("""<div style="background:rgba(229,62,62,0.08);border:1px solid rgba(229,62,62,0.2);border-radius:10px;padding:12px 16px;margin:10px 0 0;">
      <div style="font-size:12px;color:#fc8181;font-weight:600;">Working Capital Score = Sum(Payment Term Score x PO Value) / Total PO Value | Target: 4.5</div>
      <div style="font-size:11px;color:#666;margin-top:4px;">
        Advance=-2 | IBC 90=1 | IFC 90=6 | Clean Credit 90=10 | Higher = better WC for Zetwerk</div>
    </div>""", unsafe_allow_html=True)

    if 'Payment Score' in dff.columns and 'PAYMENT TERMS' in dff.columns:
        scored=dff[dff['Payment Score'].notna()&(dff['PO Basic Value']>0)].copy()
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Overall WC Score", f"{wce_score:.2f}" if wce_score else "N/A", f"{'Above' if wce_score and wce_score>=4.5 else 'Below'} 4.5 target")
        c2.metric("POs with Terms", f"{len(scored)}/{total_pos}")
        adv_pct=len(scored[scored['Payment Score']<0])/len(scored)*100 if len(scored)>0 else 0
        c3.metric("Advance %", f"{adv_pct:.1f}%", "Lower is better")
        good_pct=len(scored[scored['Payment Score']>=5])/len(scored)*100 if len(scored)>0 else 0
        c4.metric("IFC/CC Terms %", f"{good_pct:.1f}%", "Higher is better")

        if len(scored)>0 and 'Month_str' in scored.columns:
            mwce=scored.groupby('Month_str').apply(lambda x:(x['Payment Score']*x['PO Basic Value']).sum()/x['PO Basic Value'].sum() if x['PO Basic Value'].sum()>0 else 0).reset_index()
            mwce.columns=['Month','Score']
            msp=scored.groupby('Month_str')['PO Basic Value'].sum().reset_index(); msp.columns=['Month','Spend']
            c1,c2=st.columns(2)
            with c1:
                fig6=go.Figure()
                fig6.add_trace(go.Bar(x=msp['Month'],y=msp['Spend']/1e7,name='Spend',marker_color='rgba(229,62,62,0.2)',marker_line_width=0))
                fig6.add_trace(go.Scatter(x=mwce['Month'],y=mwce['Score'],name='WC Score',line=dict(color=RED,width=2.5),mode='lines+markers',marker=dict(size=6),yaxis='y2'))
                fig6.add_hline(y=4.5,line_dash='dash',line_color=AMBER,annotation_text='Target 4.5',annotation_font_color=AMBER)
                _d={k:v for k,v in DARK.items() if k not in ('yaxis',)}
                fig6.update_layout(**_d,height=300,title_text='Monthly WC Score vs Spend',
                                   yaxis=dict(title='Spend Rs Cr',gridcolor='rgba(255,255,255,0.05)',tickcolor='#333',linecolor='#333'),
                                   yaxis2=dict(title='Score',overlaying='y',side='right'),
                                   legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=10)))
                st.plotly_chart(fig6,use_container_width=True)
            with c2:
                pt=scored.groupby('PAYMENT TERMS').agg(count=('PO Basic Value','count'),value=('PO Basic Value','sum'),score=('Payment Score','first')).reset_index().sort_values('value',ascending=False).head(10)
                rows=""
                for _,r in pt.iterrows():
                    s=r['score']; pill="pg" if s>=5 else ("pr" if s<0 else "pa")
                    rows+=f"<tr><td style='color:#ccc;font-size:11px'>{r['PAYMENT TERMS']}</td><td class='mono'>{int(r['count'])}</td><td class='mono'>Rs{r['value']/1e7:.2f}Cr</td><td><span class='{pill}'>{s:.0f}</span></td></tr>"
                st.markdown(f"""<div class="ccard" style="padding:4px 0 8px;">
                  <div class="ccard-head"><span class="ccard-title">Payment Terms Breakdown</span></div>
                  <table class="tbl" style="margin-top:8px"><thead><tr><th>Term</th><th>POs</th><th>Value</th><th>Score</th></tr></thead>
                  <tbody>{rows}</tbody></table></div>""", unsafe_allow_html=True)
    else:
        st.info("Payment terms not filled in PO TRACKER column PAYMENT TERMS.")

# ════════════════════════════════════════════════
# TAB 5 — NEW VENDOR DEV
# ════════════════════════════════════════════════
with tab5:
    if stype_col:
        nv_spend=dff[dff[stype_col].str.contains('NV',case=False,na=False)]['PO Basic Value'].sum()/1e7
        avl_count=len(dff[dff[stype_col].str.contains('AVL',case=False,na=False)])
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Overall NVD%", f"{nv_pct:.1f}%", "On target" if 10<=nv_pct<=15 else "Off target")
        c2.metric("New Vendor POs", str(nv_count))
        c3.metric("AVL POs", str(avl_count))
        c4.metric("NV Spend", f"Rs {nv_spend:.2f} Cr")

        bu_nv=dff.groupby('BU').apply(lambda x: pd.Series({'Total':len(x),'NV':x[stype_col].str.contains('NV',case=False,na=False).sum(),'AVL':x[stype_col].str.contains('AVL',case=False,na=False).sum()})).reset_index()
        bu_nv['NV%']=(bu_nv['NV']/bu_nv['Total']*100).fillna(0)
        c1,c2=st.columns(2)
        with c1:
            fig8=go.Figure(go.Bar(name='NV%',x=bu_nv['BU'],y=bu_nv['NV%'],
                marker_color=[GREEN if 10<=v<=15 else (AMBER if v<10 else RED) for v in bu_nv['NV%']],marker_line_width=0,
                text=bu_nv['NV%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#888',size=10)))
            fig8.add_hrect(y0=10,y1=15,fillcolor="rgba(56,161,105,0.08)",line_width=0,annotation_text="Target 10-15%",annotation_font_color="#38a169",annotation_font_size=10)
            fig8.update_layout(**DARK,height=280,title_text='NVD % by BU',showlegend=False,yaxis_range=[0,max(bu_nv['NV%'].max()*1.3,20)])
            st.plotly_chart(fig8,use_container_width=True)
        with c2:
            rows=""
            for _,r in bu_nv.iterrows():
                pill="pg" if 10<=r['NV%']<=15 else ("pa" if r['NV%']<10 else "pr")
                rows+=f"<tr><td><b style='color:#eee'>{r['BU']}</b></td><td class='mono'>{int(r['Total'])}</td><td class='mono'>{int(r['NV'])}</td><td class='mono'>{int(r['AVL'])}</td><td><span class='{pill}'>{r['NV%']:.1f}%</span></td></tr>"
            st.markdown(f"""<div class="ccard" style="padding:4px 0 8px;">
              <div class="ccard-head"><span class="ccard-title">NVD by BU</span></div>
              <table class="tbl" style="margin-top:8px"><thead><tr><th>BU</th><th>Total</th><th>NV</th><th>AVL</th><th>NV%</th></tr></thead>
              <tbody>{rows}</tbody></table></div>""", unsafe_allow_html=True)
    else:
        st.info("Supplier type column not found in PO TRACKER.")

# ════════════════════════════════════════════════
# TAB 6 — MFC TRACKER
# ════════════════════════════════════════════════
with tab6:
    today    = pd.Timestamp(date.today())
    mfc_col  = next((c for c in ["MFC Dt.","MFC Date"] if c in dff.columns), None)
    days_col = next((c for c in ["Delivery Time from MFC (Days)","Delivery Time from MFC"] if c in dff.columns), None)

    if not mfc_col or not days_col:
        st.warning("MFC Dt. or Delivery Time from MFC columns not found. Run CPT Tools > Add Missing Cols in Google Sheets first.")
    else:
        keep=[c for c in ["SN","BU","Project Name","Items","Category","Handled by",
              "Supplier Name","PO/ OD Ref.","PO Dt.",mfc_col,days_col,
              "PO Yet to Deliver (incl. GST)","Delivery Status","Current Status"] if c in dff.columns]
        mdf=dff[keep].copy()
        mdf[mfc_col]=pd.to_datetime(mdf[mfc_col],dayfirst=True,errors='coerce')
        mdf[days_col]=pd.to_numeric(mdf[days_col],errors='coerce')
        mdf=mdf.dropna(subset=[mfc_col,days_col])
        mdf=mdf[mdf[days_col]>0]

        if mdf.empty:
            st.info("No rows with valid MFC date and delivery days found.")
        else:
            mdf["Expected Delivery"]=(mdf.apply(lambda r:r[mfc_col]+timedelta(days=int(r[days_col])),axis=1))
            mdf["Days Remaining"]=(mdf["Expected Delivery"]-today).dt.days
            mdf["Red Threshold"]=np.ceil(mdf[days_col]/3).astype(int)

            def classify(r):
                rem=r["Days Remaining"]; thr=r["Red Threshold"]
                if rem<=0: return "OVERDUE"
                elif rem<=thr: return "RED"
                elif rem<=30: return "AMBER"
                else: return "GREEN"
            mdf["Alert"]=mdf.apply(classify,axis=1)
            counts=mdf["Alert"].value_counts()

            st.markdown(f"""
            <div class="krow k4" style="padding-bottom:12px;">
              <div class="kcard kc-green"><div class="klabel">On Track</div><div class="kvalue">{counts.get('GREEN',0)}</div><div class="ksub">More than 30 days left</div></div>
              <div class="kcard kc-amber"><div class="klabel">Amber Alert</div><div class="kvalue">{counts.get('AMBER',0)}</div><div class="ksub">30 days or less</div></div>
              <div class="kcard kc-red"><div class="klabel">Red Alert</div><div class="kvalue">{counts.get('RED',0)}</div><div class="ksub">1/3 of days or less</div></div>
              <div class="kcard kc-red"><div class="klabel">Overdue</div><div class="kvalue">{counts.get('OVERDUE',0)}</div><div class="ksub">Past expected date</div></div>
            </div>
            """, unsafe_allow_html=True)

            red_pos=mdf[mdf["Alert"].isin(["RED","OVERDUE"])]
            if not red_pos.empty:
                st.markdown(f'<div class="alert-red"><b>{len(red_pos)} PO(s) are RED or OVERDUE.</b> Immediate action required. Weekly email sent to ayushkamle16@gmail.com every Monday 8AM.</div>', unsafe_allow_html=True)

            af=st.multiselect("Filter by Alert Status",["OVERDUE","RED","AMBER","GREEN"],default=["OVERDUE","RED","AMBER"])
            disp=mdf[mdf["Alert"].isin(af)].copy() if af else mdf.copy()
            ds=disp.copy()
            ds[mfc_col]=ds[mfc_col].dt.strftime("%d-%b-%Y")
            ds["Expected Delivery"]=ds["Expected Delivery"].dt.strftime("%d-%b-%Y")
            if "PO Dt." in ds.columns:
                ds["PO Dt."]=pd.to_datetime(ds["PO Dt."],errors='coerce').dt.strftime("%d-%b-%Y")
            ytd_c="PO Yet to Deliver (incl. GST)"
            if ytd_c in ds.columns:
                ds[ytd_c]=pd.to_numeric(ds[ytd_c],errors='coerce').apply(lambda x:f"Rs {x:,.0f}" if pd.notna(x) else "")

            def hl(row):
                s={"OVERDUE":"background-color:#3a0000;color:#ff9999;font-weight:bold;font-size:13px",
                   "RED":"background-color:#2a0000;color:#ff6666;font-weight:bold;font-size:13px",
                   "AMBER":"background-color:#2a1a00;color:#ffcc66;font-size:13px",
                   "GREEN":"background-color:#0a2a0a;color:#66cc66;font-size:13px"}.get(row["Alert"],"")
                return [s]*len(row)

            st.dataframe(ds.style.apply(hl,axis=1),use_container_width=True,height=500)

            c1,c2=st.columns(2)
            with c1:
                ab=mdf.groupby(["BU","Alert"]).size().reset_index(name="Count")
                fig=px.bar(ab,x="BU",y="Count",color="Alert",title="Alert by BU",
                           color_discrete_map={"GREEN":"#4caf50","AMBER":"#ff9800","RED":"#f44336","OVERDUE":"#9c0000"},
                           template="plotly_dark")
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",font=dict(size=13))
                st.plotly_chart(fig,use_container_width=True)
            with c2:
                ap=mdf["Alert"].value_counts().reset_index(); ap.columns=["Alert","Count"]
                fig2=px.pie(ap,names="Alert",values="Count",title="Alert Distribution",
                            color="Alert",color_discrete_map={"GREEN":"#4caf50","AMBER":"#ff9800","RED":"#f44336","OVERDUE":"#9c0000"},
                            hole=0.4,template="plotly_dark")
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",font=dict(size=13))
                st.plotly_chart(fig2,use_container_width=True)

# ── FOOTER ────────────────────────────────────────────────────
st.markdown(f"""
<div style="padding:12px 20px;border-top:1px solid rgba(255,255,255,0.05);margin-top:20px;
     display:flex;justify-content:space-between;align-items:center;">
  <div style="font-size:11px;color:#333;">Zetwerk CPT · CAT-2 · Live Dashboard</div>
  <div style="font-size:10px;color:#222;font-family:'DM Mono',monospace;">Updated: {now} · Auto-refresh: 5 min</div>
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════
# CAT 2 BUDDY — RIGHT SIDEBAR
# ════════════════════════════════════════════════
st.markdown("""
<style>
[data-testid="stSidebar"] {
    display:block !important;
    background:#0e0e12 !important;
    border-left:1px solid rgba(255,255,255,0.07) !important;
    border-right:none !important;
    min-width:310px !important; max-width:310px !important;
    left:auto !important; right:0 !important;
}
[data-testid="stSidebar"] h3 { color:#fff !important; font-size:15px !important; }
[data-testid="stSidebar"] p  { color:#666 !important; font-size:11px !important; }
[data-testid="stSidebar"] .stButton button {
    background:rgba(255,255,255,0.04) !important;
    border:1px solid rgba(255,255,255,0.08) !important;
    color:#888 !important; font-size:11px !important;
    border-radius:6px !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background:rgba(229,62,62,0.1) !important;
    border-color:rgba(229,62,62,0.3) !important;
    color:#fc8181 !important;
}
[data-testid="stSidebar"] .stTextInput input {
    background:#13131a !important; border:1px solid rgba(255,255,255,0.1) !important;
    color:#fff !important; font-size:12px !important; border-radius:8px !important;
}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1a0f0f,#200808);border-bottom:1px solid rgba(229,62,62,0.2);
         padding:14px 16px;margin:-1rem -1rem 12px;display:flex;align-items:center;gap:10px;">
      <div style="width:36px;height:36px;background:linear-gradient(135deg,#e53e3e,#fc4f4f);border-radius:10px;
           display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:900;color:white;">C</div>
      <div>
        <div style="font-size:13px;font-weight:700;color:#fff;">CAT 2 Buddy</div>
        <div style="font-size:10px;color:#38a169;">AI Procurement Assistant</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    for msg in st.session_state.buddy_msgs[-8:]:
        if msg['role']=='user':
            st.markdown(f'<div style="background:rgba(229,62,62,0.1);border:1px solid rgba(229,62,62,0.2);border-radius:10px;padding:8px 12px;margin:4px 0;font-size:12px;color:#eee;">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:8px 12px;margin:4px 0;font-size:12px;color:#ccc;">{msg["content"]}</div>', unsafe_allow_html=True)

    st.markdown("**Quick Questions:**")
    quick_qs = ["Total spend by BU?","Best savings BU?","Working capital score?",
                "New vendor development %?","How many VFS POs?","Average TAT this FY?"]
    for q in quick_qs:
        if st.button(q, key=f"qq_{q}", use_container_width=True):
            st.session_state.buddy_msgs.append({"role":"user","content":q})
            with st.spinner("Thinking..."):
                reply = chat_with_buddy(q, dff)
            st.session_state.buddy_msgs.append({"role":"assistant","content":reply})
            st.rerun()

    user_input = st.text_input("Ask CAT 2 Buddy:", placeholder="e.g. How many IFC 90 POs?", key="buddy_input")
    c1,c2 = st.columns(2)
    with c1:
        if st.button("Ask", type="primary", use_container_width=True) and user_input:
            st.session_state.buddy_msgs.append({"role":"user","content":user_input})
            with st.spinner("Thinking..."):
                reply = chat_with_buddy(user_input, dff)
            st.session_state.buddy_msgs.append({"role":"assistant","content":reply})
            st.rerun()
    with c2:
        if st.button("Clear", use_container_width=True):
            st.session_state.buddy_msgs = [{"role":"assistant","content":"Hi! I am CAT 2 Buddy. Ask me anything about your procurement data."}]
            st.rerun()
