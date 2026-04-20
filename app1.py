"""
Zetwerk CPT — Central Procurement Dashboard
Live Google Sheets + CAT 2 Buddy (Anthropic)
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import time
from datetime import datetime, date, timedelta
from google.oauth2.service_account import Credentials
import gspread
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Zetwerk CPT Dashboard",
    page_icon="Z",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SCORE_MAP = {
    "advance": -2, "on dispatch": 0,
    "ibc 90": 1, "ibc 60": 2,
    "ibc 60, ifc 30": 3, "ibc 60+ifc 30": 3, "vfs": 3, "clean credit 15": 3,
    "ibc 45, ifc 45": 4, "ibc 45+ifc 45": 4, "rxil": 4,
    "ifc 30": 5, "ifc 45": 5, "ifc 60": 5,
    "ibc 30, ifc 60": 5, "ibc 30+ifc 60": 5, "clean credit 30": 5,
    "ifc 90": 6, "clean credit 45": 7, "clean credit 60": 8, "clean credit 90": 10,
}

def get_score(term):
    if not term or str(term).strip() in ['', '0', 'nan']: return None
    t = str(term).lower()
    parts = t.replace('+', '|').split('|')
    total = 0.0
    for part in parts:
        part = part.strip()
        pct = 100.0
        for word in part.split():
            if '%' in word:
                try: pct = float(word.replace('%', ''))
                except: pass
        best = 0
        for key, val in SCORE_MAP.items():
            if key in part: best = val; break
        total += (pct / 100.0) * best
    return round(total, 3)

@st.cache_data(ttl=300)
def load_sheet_data():
    try:
        if "gcp_service_account" not in st.secrets:
            return pd.DataFrame(), "Missing secret: gcp_service_account"
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key("11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU")
        ws = None
        for tab in ["PO TRACKER", "Sheet1", "PR Tracker"]:
            try: ws = sh.worksheet(tab); break
            except: continue
        if ws is None:
            return pd.DataFrame(), f"Tab not found. Available: {[s.title for s in sh.worksheets()]}"
        data = ws.get_all_values()
        if len(data) < 2: return pd.DataFrame(), "Sheet is empty"
        df = pd.DataFrame(data[1:], columns=data[0])
        df.columns = [c.strip() for c in df.columns]
        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()
        for col in ['PR Dt.', 'PO Dt.']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
        for col in ['PO Basic Value', 'PO Value with GST', 'PCA Basic Value',
                    'Savings Value', 'PR - PO TAT', 'Actual Delivery TAT (Days)',
                    'Delivery Time from MFC (Days)']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(',',''), errors='coerce').fillna(0)
        # OTD and OTIF stored as percentages e.g. "100.00%"
        for col in df.columns:
            if col.strip().upper() in ('OTD', 'OTIF'):
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('%','').str.replace(',',''), errors='coerce')
        if 'PO Dt.' in df.columns:
            df = df[(df['PO Dt.'] >= pd.Timestamp('2025-04-01')) &
                    (df['PO Dt.'] <= pd.Timestamp('2026-03-31'))].copy()  # Full FY Apr25-Mar26
        for pt in ['PAYMENT TERMS', 'PO Payment Terms', 'Payment Terms']:
            if pt in df.columns:
                if pt != 'PAYMENT TERMS': df = df.rename(columns={pt: 'PAYMENT TERMS'})
                break
        if 'PAYMENT TERMS' in df.columns:
            df['Payment Score'] = df['PAYMENT TERMS'].apply(get_score)
        if 'PO Dt.' in df.columns:
            df['Month_str'] = df['PO Dt.'].dt.strftime("%b'%y")
        return df, None
    except Exception as e:
        import traceback
        return pd.DataFrame(), str(e) + "\n" + traceback.format_exc()

@st.cache_data(ttl=300)
def load_ongoing_sheet():
    """Load the ongoing/carry-forward sheet tab"""
    try:
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key("11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU")
        # Try the ongoing tab
        ws = None
        for tab in ["ongoing updated with realized27", "ongoing", "Ongoing"]:
            try: ws = sh.worksheet(tab); break
            except: continue
        if not ws:
            return pd.DataFrame(), f"Ongoing tab not found"
        data = ws.get_all_values()
        if len(data) < 3: return pd.DataFrame(), "Ongoing sheet too short"
        # Row 1 = title, Row 2 = headers
        headers = data[1]
        rows    = data[2:]
        df = pd.DataFrame(rows, columns=headers)
        df.columns = [c.strip() for c in df.columns]
        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()
        # Parse numeric cols
        for col in df.columns:
            if any(x in col.lower() for x in ['value', 'savings', 'amount']):
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(',','').str.replace('₹',''), errors='coerce')
        # Parse date
        for col in df.columns:
            if 'date' in col.lower() or 'dt' in col.lower():
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)

def chat_with_buddy(user_query, df):
    ctx = f"""You are CAT 2 Buddy, AI procurement assistant for Zetwerk CPT CAT-2.
Be sharp and professional. Never mention Claude or Anthropic.
FY 2025-26 data: {len(df)} POs, Rs {df['PO Basic Value'].sum()/1e7:.1f} Cr spend, Rs {df['Savings Value'].sum()/1e7:.1f} Cr savings.
BUs: {dict(df.groupby('BU')['PO Basic Value'].sum().div(1e7).round(1)) if 'BU' in df.columns else {}}
Supplier types: {dict(df['Supplier type'].value_counts()) if 'Supplier type' in df.columns else dict(df['Supplier Type'].value_counts()) if 'Supplier Type' in df.columns else {}}
Answer precisely in Rs Crores."""
    try:
        import anthropic
        api_key = ""
        for k in ["ANTHROPIC_API_KEY", "anthropic_api_key", "ANTHROPIC_KEY"]:
            try:
                v = st.secrets[k]
                if v: api_key = v; break
            except: pass
        if not api_key:
            try: keys = list(st.secrets.keys())
            except: keys = []
            return f"API key not found. Keys visible in secrets: {keys}. Add ANTHROPIC_API_KEY at the bottom of Streamlit Secrets."
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=400,
            messages=[{"role": "user", "content": ctx + "\n\nQuestion: " + user_query}])
        return resp.content[0].text
    except ImportError:
        return "anthropic package missing. Add 'anthropic' to requirements.txt"
    except Exception as e:
        return f"Error: {str(e)}"

# ── SPLASH ─────────────────────────────────────────────────────
if 'loaded' not in st.session_state:
    splash = st.empty()
    splash.markdown("""
<style>
@keyframes sp{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
@keyframes pp{0%,100%{opacity:1}50%{opacity:0.3}}
</style>
<div style="position:fixed;inset:0;background:#0e0e12;display:flex;align-items:center;
justify-content:center;flex-direction:column;z-index:9999;">
<div style="position:relative;width:72px;height:72px;margin-bottom:20px;">
<div style="position:absolute;inset:0;border-radius:50%;border:3px solid rgba(229,62,62,0.2);
border-top:3px solid #e53e3e;animation:sp 1s linear infinite;"></div>
<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:48px;height:48px;
background:linear-gradient(135deg,#e53e3e,#ff6b6b);border-radius:12px;display:flex;
align-items:center;justify-content:center;font-size:22px;font-weight:900;color:white;">Z</div>
</div>
<div style="font-size:22px;font-weight:700;color:#fff;letter-spacing:-0.02em;">Zetwerk CPT</div>
<div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.1em;margin-top:5px;">Central Procurement · CAT-2</div>
<div style="margin-top:20px;width:180px;height:3px;background:rgba(255,255,255,0.06);border-radius:99px;overflow:hidden;">
<div style="height:100%;width:40%;background:#e53e3e;border-radius:99px;animation:pp 1.2s ease infinite;"></div>
</div>
</div>""", unsafe_allow_html=True)
    df_main, load_err = load_sheet_data()
    df_ongoing, _ = load_ongoing_sheet()
    time.sleep(0.3)
    splash.empty()
    st.session_state['loaded'] = True
    st.session_state['df'] = df_main
    st.session_state['load_err'] = load_err
    st.session_state['df_ongoing'] = df_ongoing
    st.rerun()
else:
    df_main  = st.session_state.get('df', pd.DataFrame())
    load_err = st.session_state.get('load_err', None)
    df_ongoing = st.session_state.get('df_ongoing', pd.DataFrame())

if 'buddy_msgs' not in st.session_state:
    st.session_state.buddy_msgs = [{"role":"assistant","content":"Hi! I am CAT 2 Buddy. Ask me anything about your procurement data."}]
if 'buddy_open' not in st.session_state:
    st.session_state.buddy_open = False

# ── CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800&family=DM+Mono:wght@400;500&display=swap');

/* ── Reset & base ── */
*, html, body { font-family: 'DM Sans', sans-serif !important; box-sizing: border-box; }
html, body { font-size: 16px !important; }

/* ── FORCE FULL WIDTH — override ALL Streamlit max-width constraints ── */
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stMainBlockContainer"],
[data-testid="stVerticalBlockBorderWrapper"],
section[data-testid="stMain"],
section[data-testid="stMain"] > div,
.main .block-container,
.block-container,
div[data-layout="wide"] {
    max-width: 100% !important;
    width: 100% !important;
    padding-left: 16px !important;
    padding-right: 16px !important;
}
[data-testid="stAppViewContainer"] { background: #0d0d1a !important; padding: 0 !important; }
[data-testid="stMainBlockContainer"] { padding: 0 !important; }
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stHorizontalBlock"] { gap: 12px !important; }

/* ── Nav bar ── */
.zNav {
    background: #13131a;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: 0 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 56px;
    position: sticky;
    top: 0;
    z-index: 100;
    width: 100%;
}
.zLogo { display:flex; align-items:center; gap:12px; }
.zZ {
    width: 36px; height: 36px;
    background: linear-gradient(135deg,#e53e3e,#fc4f4f);
    border-radius: 9px;
    display: flex; align-items:center; justify-content:center;
    font-size: 18px; font-weight: 900; color: white;
}
.zBrand { font-size: 15px; font-weight: 700; color: white; }
.zSub { font-size: 11px; color: #555; }
.zRight { display:flex; align-items:center; gap:12px; }
.zPill {
    background: rgba(229,62,62,0.12);
    border: 1px solid rgba(229,62,62,0.3);
    color: #fc4f4f;
    padding: 4px 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
}
.zLive { display:flex; align-items:center; gap:6px; font-size:12px; color:#38a169; }
.zDot {
    width: 8px; height: 8px;
    background: #38a169;
    border-radius: 50%;
    animation: livepulse 2s infinite;
}
@keyframes livepulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

/* ── KPI grid ── */
.kGrid {
    display: grid;
    gap: 12px;
    padding: 16px 24px 0;
    width: 100%;
}
.k5 { grid-template-columns: repeat(5, 1fr); }
.k4 { grid-template-columns: repeat(4, 1fr); }

.kCard {
    background: #13131a;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 18px 20px 14px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, transform 0.15s;
    min-height: 100px;
}
.kCard:hover { border-color: rgba(255,255,255,0.16); transform: translateY(-2px); }
.kCard::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    border-radius: 14px 14px 0 0;
}
.kRed::before    { background: linear-gradient(90deg,#e53e3e,#fc8181); }
.kGreen::before  { background: linear-gradient(90deg,#38a169,#68d391); }
.kBlue::before   { background: linear-gradient(90deg,#3182ce,#63b3ed); }
.kAmber::before  { background: linear-gradient(90deg,#d69e2e,#f6e05e); }
.kPurple::before { background: linear-gradient(90deg,#805ad5,#b794f4); }
.kTeal::before   { background: linear-gradient(90deg,#2c7a7b,#4fd1c5); }

.kLabel {
    font-size: 11px;
    font-weight: 600;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 6px;
}
.kVal {
    font-size: 30px;
    font-weight: 800;
    color: #ffffff;
    line-height: 1.1;
    letter-spacing: -0.03em;
    font-family: 'DM Mono', monospace !important;
}
.kSub  { font-size: 11px; color: #555; margin-top: 4px; }
.kDelta { font-size: 12px; font-weight: 600; margin-top: 6px; }
.kUp   { color: #68d391; }
.kDown { color: #fc8181; }
.kWarn { color: #f6e05e; }

/* ── Section header ── */
.secH {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 24px 8px;
}
.secTitle { font-size: 14px; font-weight: 700; color: #ccc; }
.secTag {
    font-size: 11px; color: #555;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    padding: 3px 10px; border-radius: 6px;
}

/* ── HTML table ── */
.zTbl { width:100%; border-collapse:collapse; font-size:13px; }
.zTbl th {
    text-align: left;
    padding: 10px 14px;
    font-size: 11px;
    font-weight: 600;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid rgba(255,255,255,0.07);
}
.zTbl td {
    padding: 10px 14px;
    color: #bbb;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    font-size: 13px;
}
.zTbl tr:hover td { background: rgba(255,255,255,0.02); }
.mono { font-family: 'DM Mono', monospace !important; font-size:12px; }
.pg { background:rgba(56,161,105,0.15); color:#68d391; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }
.pr { background:rgba(229,62,62,0.15); color:#fc8181; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }
.pa { background:rgba(214,158,46,0.15); color:#f6e05e; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }

/* ── Filter row ── */
.filterRow { padding: 10px 24px 0; display:flex; gap:10px; flex-wrap:wrap; }

/* ── Streamlit tab style ── */
[data-testid="stTabs"] { padding: 0 24px; }
[data-testid="stTabs"] button[role="tab"] {
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #666 !important;
    padding: 8px 16px !important;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #fc4f4f !important;
    border-bottom: 2px solid #e53e3e !important;
    font-weight: 600 !important;
}

/* Selectbox */
[data-testid="stSelectbox"] label { font-size:11px !important; color:#666 !important; font-weight:600 !important; text-transform:uppercase; letter-spacing:0.05em; }
[data-testid="stSelectbox"] > div > div {
    background: #13131a !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important;
    color: #ccc !important;
    font-size: 13px !important;
}

/* Streamlit metric */
[data-testid="stMetric"] { background: #13131a !important; border-radius: 10px !important; padding: 12px 16px !important; border: 1px solid rgba(255,255,255,0.07) !important; }
[data-testid="stMetricLabel"] { font-size: 11px !important; color: #666 !important; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: 800 !important; color: #fff !important; font-family: 'DM Mono', monospace !important; }
[data-testid="stMetricDelta"] { font-size: 12px !important; }

/* Dataframe */
[data-testid="stDataFrame"] { border-radius: 10px !important; overflow: hidden; }

/* ── CAT 2 BUDDY FLOATING ── */
#buddyFab {
    position: fixed;
    bottom: 28px; right: 28px;
    z-index: 9999;
    width: 56px; height: 56px;
    border-radius: 50%;
    background: linear-gradient(135deg, #e53e3e, #fc4f4f);
    display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    box-shadow: 0 4px 24px rgba(229,62,62,0.5);
    font-size: 22px; font-weight: 900; color: white;
    border: none;
    user-select: none;
    transition: transform 0.2s;
}
#buddyFab:hover { transform: scale(1.08); }

#buddyPanel {
    position: fixed;
    bottom: 96px; right: 28px;
    z-index: 9998;
    width: 380px;
    background: #13131a;
    border: 1px solid rgba(229,62,62,0.3);
    border-radius: 18px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.7);
    overflow: hidden;
    display: none;
    flex-direction: column;
}
#buddyHeader {
    background: linear-gradient(135deg,#1a0505,#220808);
    border-bottom: 1px solid rgba(229,62,62,0.2);
    padding: 14px 18px;
    display: flex; align-items: center; gap: 12px;
}
#buddyAvatar {
    width: 38px; height: 38px;
    background: linear-gradient(135deg,#e53e3e,#fc4f4f);
    border-radius: 10px;
    display: flex; align-items:center; justify-content:center;
    font-size: 18px; font-weight: 900; color: white;
    flex-shrink: 0;
}
#buddyName { font-size: 14px; font-weight: 700; color: #fff; }
#buddyStatus { font-size: 11px; color: #38a169; }
#buddyMsgs {
    padding: 14px;
    display: flex;
    flex-direction: column;
    height: 300px;
    overflow-y: auto;
    gap: 8px;
}
.bmUser {
    background: rgba(229,62,62,0.12);
    border: 1px solid rgba(229,62,62,0.2);
    border-radius: 12px 12px 2px 12px;
    padding: 9px 13px;
    font-size: 13px; color: #eee;
    max-width: 85%;
    align-self: flex-end;
    margin-left: auto;
}
.bmBot {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 12px 12px 12px 2px;
    padding: 9px 13px;
    font-size: 13px; color: #ccc;
    max-width: 90%;
}
#buddyInputRow {
    padding: 10px 14px;
    border-top: 1px solid rgba(255,255,255,0.06);
    display: flex; gap: 8px;
}
#buddyInput {
    flex: 1;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 9px 13px;
    color: #fff;
    font-size: 13px;
    outline: none;
    font-family: 'DM Sans', sans-serif;
}
#buddyInput:focus { border-color: rgba(229,62,62,0.4); }
#buddySend {
    background: #e53e3e; border: none;
    border-radius: 8px; padding: 9px 16px;
    color: white; font-size: 13px;
    cursor: pointer; font-weight: 600;
    font-family: 'DM Sans', sans-serif;
    white-space: nowrap;
}
#buddySend:hover { background: #c53030; }
</style>
""", unsafe_allow_html=True)

# ── NAV ──────────────────────────────────────────────────────────
now = datetime.now().strftime("%d %b %Y %H:%M")
st.markdown(f"""
<div class="zNav">
  <div class="zLogo">
    <div class="zZ">Z</div>
    <div>
      <div class="zBrand">Zetwerk CPT</div>
      <div class="zSub">Central Procurement Team</div>
    </div>
  </div>
  <div class="zRight">
    <div class="zLive"><div class="zDot"></div>Live &middot; {now}</div>
    <div class="zPill">FY 2025-26</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── DATA CHECK ───────────────────────────────────────────────────
df = df_main.copy() if not df_main.empty else pd.DataFrame()
if df.empty:
    st.markdown(f"""
<div style="background:rgba(229,62,62,0.08);border:1px solid rgba(229,62,62,0.25);
border-radius:12px;padding:24px;margin:24px;text-align:center;">
<div style="font-size:18px;color:#fc8181;font-weight:700;margin-bottom:8px;">Sheet Not Connected</div>
<div style="font-size:14px;color:#888;">{load_err or 'Unknown error'}</div>
</div>""", unsafe_allow_html=True)
    st.stop()

# ── FILTERS TOP ROW ─────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns([1,1,1,1,0.4])
with c1:
    sel_bu = st.selectbox('BU',
        ['All BU'] + sorted([b for b in df['BU'].dropna().unique() if b]), key='f_bu')
with c2:
    co = ['All Category']
    if 'Category' in df.columns: co += sorted([c for c in df['Category'].dropna().unique() if c])
    sel_cat = st.selectbox('Category', co, key='f_cat')
with c3:
    bo = ['All Buyers']
    if 'Handled by' in df.columns: bo += sorted([b for b in df['Handled by'].dropna().unique() if b])
    sel_buyer = st.selectbox('Buyer', bo, key='f_buyer')
with c4:
    stcol = next((c for c in ['Supplier type','Supplier Type','SUPPLIER TYPE'] if c in df.columns), None)
    so = ['All Types']
    if stcol: so += sorted([s for s in df[stcol].dropna().unique() if str(s).strip()])
    sel_stype = st.selectbox('Supplier Type', so, key='f_stype')
with c5:
    st.markdown("<div style='padding-top:22px;'>", unsafe_allow_html=True)
    if st.button("Refresh", help="Reload data from Google Sheets"):
        st.cache_data.clear()
        st.session_state.pop('df', None)
        st.session_state.pop('loaded', None)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

dff = df.copy()
if sel_bu != 'All BU': dff = dff[dff['BU'] == sel_bu]
if sel_cat != 'All Category' and 'Category' in dff.columns: dff = dff[dff['Category'] == sel_cat]
if sel_buyer != 'All Buyers' and 'Handled by' in dff.columns: dff = dff[dff['Handled by'] == sel_buyer]
if sel_stype != 'All Types' and stcol: dff = dff[dff[stcol] == sel_stype]

# ── KPIs ─────────────────────────────────────────────────────────
total_pos   = len(dff[dff['PO Basic Value'] > 0]) if 'PO Basic Value' in dff.columns else len(dff)
total_spend = dff['PO Basic Value'].sum() / 1e7 if 'PO Basic Value' in dff.columns else 0
total_sav   = dff['Savings Value'].sum() / 1e7 if 'Savings Value' in dff.columns else 0
sav_pct     = (total_sav / total_spend * 100) if total_spend > 0 else 0
avg_tat     = 0
if 'PR - PO TAT' in dff.columns:
    tv = pd.to_numeric(dff['PR - PO TAT'], errors='coerce').dropna()
    avg_tat = float(tv[tv > 0].mean()) if len(tv[tv > 0]) > 0 else 0

comp_df = pd.DataFrame()
if 'Delivery Status' in dff.columns:
    comp_df = dff[dff['Delivery Status'].str.strip().str.lower().isin(['completed','shortclose'])]

otif_pct = otd_pct = otif_base = otd_base = 0
otd_col  = next((c for c in dff.columns if c.strip().upper() == 'OTD'),  None)
otif_col = next((c for c in dff.columns if c.strip().upper() == 'OTIF'), None)
if otd_col and len(comp_df) > 0:
    ov = pd.to_numeric(comp_df[otd_col].astype(str).str.replace('%','').str.replace(',',''), errors='coerce').dropna()
    ov = ov[ov > 0]; otd_base = len(ov)
    if otd_base > 0: otd_pct = (ov <= 100.0).sum() / otd_base * 100
if otif_col and len(comp_df) > 0:
    ov2 = pd.to_numeric(comp_df[otif_col].astype(str).str.replace('%','').str.replace(',',''), errors='coerce').dropna()
    ov2 = ov2[ov2 > 0]; otif_base = len(ov2)
    if otif_base > 0: otif_pct = (ov2 <= 105.0).sum() / otif_base * 100

nv_pct = nv_count = 0
if stcol and stcol in dff.columns:
    nm = dff[stcol].str.upper().str.contains('NV', na=False)
    nv_count = int(nm.sum())
    nv_pct = (nv_count / len(dff) * 100) if len(dff) > 0 else 0

wce = None
if 'Payment Score' in dff.columns and 'PO Basic Value' in dff.columns:
    sc = dff[dff['Payment Score'].notna() & (dff['PO Basic Value'] > 0)]
    if len(sc) > 0:
        wce = (sc['Payment Score'] * sc['PO Basic Value']).sum() / sc['PO Basic Value'].sum()

# ── CHART THEME ──────────────────────────────────────────────────
DARK = dict(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="#888", size=13),
    xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#444", linecolor="#333"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#444", linecolor="#333"),
    margin=dict(l=8, r=8, t=36, b=8),
)
R="#e53e3e"; G="#38a169"; A="#d69e2e"

def kcard(val, label, sub, delta="", delta_cls="", color_cls="kBlue"):
    return f"""<div class="kCard {color_cls}">
  <div class="kLabel">{label}</div>
  <div class="kVal">{val}</div>
  <div class="kSub">{sub}</div>
  {f'<div class="kDelta {delta_cls}">{delta}</div>' if delta else ''}
</div>"""

# ── TABS ─────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Overview", "Spend & Savings", "TAT & OTIF",
    "Working Capital", "New Vendor Dev", "MFC Tracker", "Ongoing POs"
])

# ════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════
with tab1:
    cat_n = dff['Category'].nunique() if 'Category' in dff.columns else 0
    sup_n = dff['Supplier Name'].nunique() if 'Supplier Name' in dff.columns else 0

    st.markdown(f"""
<div class="kGrid k5">
{kcard(str(total_pos), "Total POs", "FY 2025-26", "", "", "kBlue")}
{kcard(f"Rs {total_spend:.1f} Cr", "Total Spend", "PO Basic Value", "", "", "kGreen")}
{kcard(f"Rs {total_sav:.2f} Cr", "Savings", f"{sav_pct:.1f}% of spend",
    ("Above 4.5% target" if sav_pct>=4.5 else "Below 4.5% target"),
    ("kUp" if sav_pct>=4.5 else "kWarn"),
    ("kGreen" if sav_pct>=4.5 else "kAmber"))}
{kcard(f"{avg_tat:.0f}d", "Avg PR-PO TAT", "Target: 90 days",
    ("On track" if avg_tat and avg_tat<=90 else "Above target"),
    ("kUp" if avg_tat and avg_tat<=90 else "kDown"),
    ("kGreen" if avg_tat and avg_tat<=90 else "kRed"))}
{kcard(f"{wce:.2f}" if wce else "—", "WC Score", "Target: 4.5",
    ("Above target" if wce and wce>=4.5 else "Below target" if wce else "Fill payment terms"),
    ("kUp" if wce and wce>=4.5 else "kDown" if wce else ""),
    ("kGreen" if wce and wce>=4.5 else "kRed" if wce else "kPurple"))}
</div>
<div class="kGrid k4" style="padding-top:12px;">
{kcard(f"{otif_pct:.1f}%", "OTIF", f"OTD: {otd_pct:.1f}% | {otif_base} completed POs",
    ("Above 75% target" if otif_pct>=75 else "Below 75% target"),
    ("kUp" if otif_pct>=75 else "kDown"),
    ("kGreen" if otif_pct>=75 else "kRed"))}
{kcard(f"{nv_pct:.1f}%", "New Vendor Dev", f"{nv_count} NV of {len(dff)} POs",
    "Target: 10-15%", ("kUp" if 10<=nv_pct<=15 else "kWarn"),
    ("kGreen" if 10<=nv_pct<=15 else "kAmber"))}
{kcard(str(cat_n), "Categories Active", "Unique categories", "", "", "kTeal")}
{kcard(str(sup_n), "Suppliers Used", "Unique suppliers", "", "", "kPurple")}
</div>
""", unsafe_allow_html=True)

    st.markdown('<div class="secH"><div class="secTitle">BU Performance</div><div class="secTag">Live · FY26</div></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        bg = dff.groupby('BU').agg(spend=('PO Basic Value','sum'), savings=('Savings Value','sum')).reset_index()
        bg['sc'] = bg['spend']/1e7; bg['svc'] = bg['savings']/1e7
        fig = go.Figure()
        fig.add_trace(go.Bar(name='Spend', x=bg['BU'], y=bg['sc'], marker_color=R, marker_line_width=0))
        fig.add_trace(go.Bar(name='Savings', x=bg['BU'], y=bg['svc'], marker_color='rgba(56,161,105,0.7)', marker_line_width=0))
        fig.update_layout(**DARK, height=300, barmode='group', title_text='Spend & Savings by BU (Rs Cr)',
            legend=dict(orientation='h',y=1.15,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=12)))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        if 'Category' in dff.columns:
            cg = dff.groupby('Category')['PO Basic Value'].sum().sort_values(ascending=False).head(8).reset_index()
            cg['sc'] = cg['PO Basic Value']/1e7
            fig2 = go.Figure(go.Bar(y=cg['Category'], x=cg['sc'], orientation='h', marker_color=R, marker_line_width=0,
                text=cg['sc'].apply(lambda x:f'Rs {x:.1f}Cr'), textposition='outside', textfont=dict(color='#888',size=12)))
            fig2.update_layout(**DARK, height=300, title_text='Top Categories by Spend', xaxis_title='Rs Crore')
            st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════
# TAB 2 — SPEND & SAVINGS
# ════════════════════════════════════════════════
with tab2:
    best_bu = "—"
    if len(dff) > 0 and 'PO Basic Value' in dff.columns:
        bg2 = dff.groupby('BU').apply(lambda x: x['Savings Value'].sum()/x['PO Basic Value'].sum()*100 if x['PO Basic Value'].sum()>0 else 0)
        if len(bg2) > 0: best_bu = str(bg2.idxmax())
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("Total Spend", f"Rs {total_spend:.2f} Cr")
    with c2: st.metric("Total Savings", f"Rs {total_sav:.2f} Cr", f"{sav_pct:.1f}%")
    with c3: st.metric("vs Target 4.5%", f"{sav_pct:.1f}%", f"{sav_pct-4.5:.1f}pp")
    with c4: st.metric("Best Savings BU", best_bu)
    c1,c2 = st.columns(2)
    with c1:
        if 'Month_str' in dff.columns:
            mo = dff.groupby('Month_str').agg(spend=('PO Basic Value','sum'),savings=('Savings Value','sum')).reset_index()
            mo['sc']=mo['spend']/1e7; mo['svc']=mo['savings']/1e7
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(name='Spend',x=mo['Month_str'],y=mo['sc'],marker_color='rgba(229,62,62,0.25)',marker_line_width=0))
            fig3.add_trace(go.Scatter(name='Savings',x=mo['Month_str'],y=mo['svc'],line=dict(color=G,width=2.5),mode='lines+markers',marker=dict(size=6),yaxis='y2'))
            _d = {k:v for k,v in DARK.items() if k not in ('yaxis','legend')}
            fig3.update_layout(**_d,height=320,title_text='Monthly Spend vs Savings',
                yaxis=dict(title='Spend Rs Cr',gridcolor='rgba(255,255,255,0.05)'),
                yaxis2=dict(title='Savings Rs Cr',overlaying='y',side='right',gridcolor='rgba(0,0,0,0)'),
                legend=dict(orientation='h',y=1.15,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=12)))
            st.plotly_chart(fig3, use_container_width=True)
    with c2:
        bs = dff.groupby('BU').agg(spend=('PO Basic Value','sum'),savings=('Savings Value','sum'),count=('PO Basic Value','count')).reset_index()
        bs['sp'] = (bs['savings']/bs['spend']*100).fillna(0)
        rows=""
        for _,r in bs.sort_values('spend',ascending=False).iterrows():
            pill="pg" if r['sp']>=4.5 else ("pr" if r['sp']<0 else "pa")
            rows+=f'<tr><td><b style="color:#eee">{r["BU"]}</b></td><td class="mono">Rs {r["spend"]/1e7:.2f} Cr</td><td class="mono">Rs {r["savings"]/1e7:.2f} Cr</td><td><span class="{pill}">{r["sp"]:.1f}%</span></td><td class="mono">{int(r["count"])}</td></tr>'
        st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:8px 0;"><table class="zTbl"><thead><tr><th>BU</th><th>Spend</th><th>Savings</th><th>%</th><th>POs</th></tr></thead><tbody>{rows}</tbody></table></div>',unsafe_allow_html=True)

# ════════════════════════════════════════════════
# TAB 3 — TAT & OTIF
# ════════════════════════════════════════════════
with tab3:
    nc = len(comp_df)
    nong = len(dff[dff['Delivery Status'].str.strip().str.lower()=='ongoing']) if 'Delivery Status' in dff.columns else 0
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("Avg PR-PO TAT", f"{avg_tat:.0f} days", f"{avg_tat-90:.0f}d vs 90d target")
    with c2: st.metric("OTIF", f"{otif_pct:.1f}%", f"{otif_base} completed POs" if otif_base>0 else "No data yet")
    with c3: st.metric("OTD", f"{otd_pct:.1f}%", f"{otd_base} completed POs" if otd_base>0 else "No data yet")
    with c4: st.metric("Completed / Ongoing", f"{nc} / {nong}")
    c1,c2 = st.columns(2)
    with c1:
        if 'PR - PO TAT' in dff.columns:
            bt = dff.groupby('BU').apply(lambda x: pd.to_numeric(x['PR - PO TAT'],errors='coerce').mean()).reset_index()
            bt.columns=['BU','Avg TAT']; bt=bt.dropna()
            if len(bt)>0:
                fig4 = go.Figure(go.Bar(x=bt['BU'],y=bt['Avg TAT'],
                    marker_color=[G if v<=90 else R for v in bt['Avg TAT']],marker_line_width=0,
                    text=bt['Avg TAT'].apply(lambda x:f'{x:.0f}d'),textposition='outside',textfont=dict(color='#888',size=12)))
                fig4.add_hline(y=90,line_dash='dash',line_color=A,annotation_text='90d target',annotation_font_color=A)
                fig4.update_layout(**DARK,height=300,title_text='Avg PR-PO TAT by BU',showlegend=False)
                st.plotly_chart(fig4,use_container_width=True)
    with c2:
        if otif_col and len(comp_df)>0:
            rows2=[]
            for _bu in dff['BU'].dropna().unique():
                _s=comp_df[comp_df['BU']==_bu] if 'BU' in comp_df.columns else pd.DataFrame()
                if len(_s)==0: continue
                _v=pd.to_numeric(_s[otif_col].astype(str).str.replace('%','').str.replace(',',''),errors='coerce').dropna()
                _v=_v[_v>0]
                if len(_v)>0: rows2.append({'BU':_bu,'OTIF%':(_v<=105.0).sum()/len(_v)*100})
            if rows2:
                bo2=pd.DataFrame(rows2)
                fig5=go.Figure(go.Bar(x=bo2['BU'],y=bo2['OTIF%'],
                    marker_color=[G if v>=75 else R for v in bo2['OTIF%']],marker_line_width=0,
                    text=bo2['OTIF%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#888',size=12)))
                fig5.add_hline(y=75,line_dash='dash',line_color=A,annotation_text='75% target',annotation_font_color=A)
                fig5.update_layout(**DARK,height=300,title_text='OTIF % by BU (Completed only)',showlegend=False,yaxis_range=[0,115])
                st.plotly_chart(fig5,use_container_width=True)
        else:
            st.info("OTIF data will appear once POs are marked Completed.")
    if otd_col and len(comp_df)>0:
        rows3=[]
        for _bu in dff['BU'].dropna().unique():
            _s=comp_df[comp_df['BU']==_bu] if 'BU' in comp_df.columns else pd.DataFrame()
            if len(_s)==0: continue
            _v=pd.to_numeric(_s[otd_col].astype(str).str.replace('%','').str.replace(',',''),errors='coerce').dropna()
            _v=_v[_v>0]
            if len(_v)>0: rows3.append({'BU':_bu,'OTD%':(_v<=100.0).sum()/len(_v)*100})
        if rows3:
            bo3=pd.DataFrame(rows3)
            fig6=go.Figure(go.Bar(x=bo3['BU'],y=bo3['OTD%'],
                marker_color=[G if v>=75 else R for v in bo3['OTD%']],marker_line_width=0,
                text=bo3['OTD%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#888',size=12)))
            fig6.add_hline(y=75,line_dash='dash',line_color=A,annotation_text='75% target',annotation_font_color=A)
            fig6.update_layout(**DARK,height=300,title_text='OTD % by BU (Completed only)',showlegend=False,yaxis_range=[0,115])
            st.plotly_chart(fig6,use_container_width=True)

# ════════════════════════════════════════════════
# TAB 4 — WORKING CAPITAL
# ════════════════════════════════════════════════
with tab4:
    st.markdown("""<div style="background:rgba(229,62,62,0.06);border:1px solid rgba(229,62,62,0.18);
border-radius:10px;padding:14px 18px;margin:8px 0 16px;">
<div style="font-size:13px;color:#fc8181;font-weight:600;">Score = Sum(Payment Term Score x PO Value) / Total PO Value &nbsp;|&nbsp; Target: 4.5 &nbsp;|&nbsp; Higher = better</div>
<div style="font-size:12px;color:#666;margin-top:4px;">Advance = -2 &nbsp;|&nbsp; IBC 90 = 1 &nbsp;|&nbsp; IFC 90 = 6 &nbsp;|&nbsp; Clean Credit 90 = 10</div>
</div>""", unsafe_allow_html=True)
    if 'Payment Score' in dff.columns and 'PAYMENT TERMS' in dff.columns:
        sc = dff[dff['Payment Score'].notna() & (dff['PO Basic Value']>0)].copy()
        adv = len(sc[sc['Payment Score']<0])/len(sc)*100 if len(sc)>0 else 0
        good = len(sc[sc['Payment Score']>=5])/len(sc)*100 if len(sc)>0 else 0
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("Overall WC Score", f"{wce:.2f}" if wce else "—", f"{'Above' if wce and wce>=4.5 else 'Below'} 4.5")
        with c2: st.metric("POs with Terms", f"{len(sc)}/{total_pos}")
        with c3: st.metric("Advance %", f"{adv:.1f}%", "Lower is better")
        with c4: st.metric("IFC/CC Terms %", f"{good:.1f}%", "Higher is better")
        if len(sc)>0 and 'Month_str' in sc.columns:
            mw = sc.groupby('Month_str').apply(lambda x:(x['Payment Score']*x['PO Basic Value']).sum()/x['PO Basic Value'].sum() if x['PO Basic Value'].sum()>0 else 0).reset_index()
            mw.columns=['Month','Score']
            ms = sc.groupby('Month_str')['PO Basic Value'].sum().reset_index(); ms.columns=['Month','Spend']
            c1,c2 = st.columns(2)
            with c1:
                fig7=go.Figure()
                fig7.add_trace(go.Bar(x=ms['Month'],y=ms['Spend']/1e7,name='Spend',marker_color='rgba(229,62,62,0.2)',marker_line_width=0))
                fig7.add_trace(go.Scatter(x=mw['Month'],y=mw['Score'],name='WC Score',line=dict(color=R,width=2.5),mode='lines+markers',marker=dict(size=6),yaxis='y2'))
                fig7.add_hline(y=4.5,line_dash='dash',line_color=A,annotation_text='Target 4.5',annotation_font_color=A)
                _d2={k:v for k,v in DARK.items() if k not in ('yaxis','legend')}
                fig7.update_layout(**_d2,height=320,title_text='Monthly WC Score vs Spend',
                    yaxis=dict(title='Spend Rs Cr',gridcolor='rgba(255,255,255,0.05)'),
                    yaxis2=dict(title='Score',overlaying='y',side='right',gridcolor='rgba(0,0,0,0)'),
                    legend=dict(orientation='h',y=1.15,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=12)))
                st.plotly_chart(fig7,use_container_width=True)
            with c2:
                ptg=sc.groupby('PAYMENT TERMS').agg(count=('PO Basic Value','count'),value=('PO Basic Value','sum'),score=('Payment Score','first')).reset_index().sort_values('value',ascending=False).head(10)
                rows=""
                for _,r in ptg.iterrows():
                    s=r['score']; pill="pg" if s>=5 else ("pr" if s<0 else "pa")
                    rows+=f'<tr><td style="color:#ccc">{r["PAYMENT TERMS"]}</td><td class="mono">{int(r["count"])}</td><td class="mono">Rs {r["value"]/1e7:.2f}Cr</td><td><span class="{pill}">{s:.0f}</span></td></tr>'
                st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:8px 0;"><table class="zTbl"><thead><tr><th>Term</th><th>POs</th><th>Value</th><th>Score</th></tr></thead><tbody>{rows}</tbody></table></div>',unsafe_allow_html=True)
    else:
        st.info("Payment terms not filled. Run fillPaymentTermsByPORef in Apps Script.")

# ════════════════════════════════════════════════
# TAB 5 — NEW VENDOR DEV
# ════════════════════════════════════════════════
with tab5:
    if stcol and stcol in dff.columns:
        avl = len(dff[dff[stcol].str.upper().str.contains('AVL',na=False)])
        nvs = dff[dff[stcol].str.upper().str.contains('NV',na=False)]['PO Basic Value'].sum()/1e7
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("Overall NVD%", f"{nv_pct:.1f}%", "On target" if 10<=nv_pct<=15 else "Off target")
        with c2: st.metric("New Vendor POs", str(nv_count))
        with c3: st.metric("AVL POs", str(avl))
        with c4: st.metric("NV Spend", f"Rs {nvs:.2f} Cr")
        bn = dff.groupby('BU').apply(lambda x: pd.Series({
            'Total':len(x), 'NV':x[stcol].str.upper().str.contains('NV',na=False).sum(),
            'AVL':x[stcol].str.upper().str.contains('AVL',na=False).sum()})).reset_index()
        bn['NV%'] = (bn['NV']/bn['Total']*100).fillna(0)
        c1,c2 = st.columns(2)
        with c1:
            fig8=go.Figure(go.Bar(x=bn['BU'],y=bn['NV%'],
                marker_color=[G if 10<=v<=15 else (A if v<10 else R) for v in bn['NV%']],
                marker_line_width=0, text=bn['NV%'].apply(lambda x:f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#888',size=12)))
            fig8.add_hrect(y0=10,y1=15,fillcolor="rgba(56,161,105,0.07)",line_width=0,
                annotation_text="Target 10-15%",annotation_font_color="#38a169",annotation_font_size=12)
            fig8.update_layout(**DARK,height=300,title_text='NVD % by BU',showlegend=False,
                yaxis_range=[0,max(float(bn['NV%'].max())*1.3,20)])
            st.plotly_chart(fig8,use_container_width=True)
        with c2:
            rows4=""
            for _,r in bn.iterrows():
                pill="pg" if 10<=r['NV%']<=15 else ("pa" if r['NV%']<10 else "pr")
                rows4+=f'<tr><td><b style="color:#eee">{r["BU"]}</b></td><td class="mono">{int(r["Total"])}</td><td class="mono">{int(r["NV"])}</td><td class="mono">{int(r["AVL"])}</td><td><span class="{pill}">{r["NV%"]:.1f}%</span></td></tr>'
            st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:8px 0;"><table class="zTbl"><thead><tr><th>BU</th><th>Total</th><th>NV</th><th>AVL</th><th>NV%</th></tr></thead><tbody>{rows4}</tbody></table></div>',unsafe_allow_html=True)
    else:
        cols_available = ', '.join(list(df.columns[:25]))
        st.warning(f"Supplier Type column not found. Available columns: {cols_available}")

# ════════════════════════════════════════════════
# TAB 6 — MFC TRACKER (Ongoing only)
# ════════════════════════════════════════════════
with tab6:
    st.markdown("### MFC Delivery Tracker")
    # Use FULL unfiltered sheet data — same as email alert, no FY/BU filter
    mfc_full = df_main.copy()
    # Re-parse numeric columns that may not have been parsed
    for _col in mfc_full.columns:
        if _col.strip().upper() in ('OTD','OTIF'):
            mfc_full[_col] = pd.to_numeric(mfc_full[_col].astype(str).str.replace('%','').str.replace(',',''), errors='coerce')
    today = pd.Timestamp(date.today())
    mc = next((c for c in ["MFC Dt.","MFC Date"] if c in mfc_full.columns), None)
    # Column name may contain newline — check all variants
    dc = next((c for c in mfc_full.columns 
               if 'delivery time' in c.lower() and 'mfc' in c.lower()), None)
    if not mc or not dc:
        st.warning("MFC Dt. or Delivery Time from MFC columns not found.")
    else:
        # Only ongoing — exclude completed/shortclose, same logic as email
        mfc_src = mfc_full.copy()
        if 'Delivery Status' in mfc_src.columns:
            mfc_src = mfc_src[~mfc_src['Delivery Status'].str.strip().str.lower().isin(['completed','shortclose'])]
        keep = [c for c in ["SN","BU","Project Name","Items","Category","Supplier Name","PO/ OD Ref.","PO Dt.",mc,dc,"Delivery Status","Current Status"] if c in mfc_src.columns]
        mf = mfc_src[keep].copy()
        mf[mc] = pd.to_datetime(mf[mc], dayfirst=True, errors='coerce')
        mf[dc] = pd.to_numeric(mf[dc], errors='coerce')
        mf = mf.dropna(subset=[mc,dc]); mf = mf[mf[dc]>0]
        if mf.empty:
            st.info("No ongoing POs with valid MFC date and delivery days found.")
        else:
            mf["Expected"] = mf.apply(lambda r: r[mc]+timedelta(days=int(r[dc])), axis=1)
            mf["Days Left"] = (mf["Expected"]-today).dt.days
            mf["Threshold"] = np.ceil(mf[dc]/3).astype(int)
            def clf(r):
                if r["Days Left"]<=0: return "OVERDUE"
                elif r["Days Left"]<=r["Threshold"]: return "RED"
                elif r["Days Left"]<=30: return "AMBER"
                else: return "GREEN"
            mf["Alert"] = mf.apply(clf, axis=1)
            cnt = mf["Alert"].value_counts()
            st.markdown(f"""
<div class="kGrid k4" style="padding:12px 0 0;">
{kcard(str(cnt.get("GREEN",0)), "On Track", "", "", "", "kGreen")}
{kcard(str(cnt.get("AMBER",0)), "Amber Alert", "", "", "", "kAmber")}
{kcard(str(cnt.get("RED",0)), "Red Alert", "", "", "", "kRed")}
{kcard(str(cnt.get("OVERDUE",0)), "Overdue", "", "", "", "kPurple")}
</div>""", unsafe_allow_html=True)
            red = mf[mf["Alert"].isin(["RED","OVERDUE"])]
            if not red.empty:
                st.markdown(f'<div style="background:#2a0000;border-left:4px solid #ff4444;padding:12px 16px;border-radius:8px;color:#ff9999;margin:12px 0;font-size:14px;"><b>{len(red)} PO(s) are RED or OVERDUE.</b> Immediate action required. Weekly email sent to ayushkamle16@gmail.com every Monday 8AM.</div>', unsafe_allow_html=True)
            af = st.multiselect("Filter by Alert", ["OVERDUE","RED","AMBER","GREEN"], default=["OVERDUE","RED","AMBER"])
            disp = mf[mf["Alert"].isin(af)].copy() if af else mf.copy()
            ds = disp.copy()
            ds[mc] = ds[mc].dt.strftime("%d-%b-%Y")
            ds["Expected"] = ds["Expected"].dt.strftime("%d-%b-%Y")
            if "PO Dt." in ds.columns:
                ds["PO Dt."] = pd.to_datetime(ds["PO Dt."],errors='coerce').dt.strftime("%d-%b-%Y")
            def hl(row):
                s = {"OVERDUE":"background-color:#2a0000;color:#ff9999;font-weight:bold;font-size:14px",
                     "RED":"background-color:#1a0000;color:#ff6666;font-weight:bold;font-size:14px",
                     "AMBER":"background-color:#1a1000;color:#ffcc66;font-size:13px",
                     "GREEN":"background-color:#001a00;color:#66cc66;font-size:13px"}.get(row["Alert"],"")
                return [s]*len(row)
            st.markdown(f'**{len(disp)} POs shown**', unsafe_allow_html=False)
            st.dataframe(ds.style.apply(hl,axis=1), use_container_width=True, height=min(40*len(disp)+50, 800))

# ════════════════════════════════════════════════
# TAB 7 — ONGOING POs (from carry-forward sheet)
# ════════════════════════════════════════════════
with tab7:
    if df_ongoing.empty:
        st.info("Ongoing sheet not loaded. Check tab name: 'ongoing updated with realized27'")
    else:
        st.markdown(f"**{len(df_ongoing)} ongoing / carry-forward POs**")

        # Refresh button
        if st.button("Refresh Ongoing Data", key="ref_ongoing"):
            load_ongoing_sheet.clear()
            st.session_state.pop('df_ongoing', None)
            df_ongoing2, _ = load_ongoing_sheet()
            st.session_state['df_ongoing'] = df_ongoing2
            st.rerun()

        # Find key columns
        val_col = next((c for c in df_ongoing.columns
                        if 'value' in c.lower() and ('po' in c.lower() or 'gst' in c.lower())), None)
        sav_col = next((c for c in df_ongoing.columns if 'saving' in c.lower()), None)

        # Summary KPIs
        total_ong = len(df_ongoing)
        total_val = df_ongoing[val_col].sum() / 1e7 if val_col else 0
        total_sav_ong = df_ongoing[sav_col].sum() / 1e7 if sav_col else 0

        # BU filter
        bu_list_ong = ['All BU']
        if 'BU' in df_ongoing.columns:
            bu_list_ong += sorted([b for b in df_ongoing['BU'].dropna().unique() if b])
        sel_bu_ong = st.selectbox('Filter by BU', bu_list_ong, key='ong_bu')
        df_ong_f = df_ongoing.copy()
        if sel_bu_ong != 'All BU': df_ong_f = df_ong_f[df_ong_f['BU'] == sel_bu_ong]

        # KPI cards
        st.markdown(f"""
<div class="kGrid k4" style="padding:8px 0;">
  <div class="kc blue">
    <div class="kLabel">Total Ongoing POs</div>
    <div class="kVal">{len(df_ong_f)}</div>
    <div class="kSub">Carry-forward FY 25-26</div>
  </div>
  <div class="kc red">
    <div class="kLabel">PO Value (incl. GST)</div>
    <div class="kVal">{"Rs " + f"{df_ong_f[val_col].sum()/1e7:.1f} Cr" if val_col else "—"}</div>
    <div class="kSub">Yet to be delivered</div>
  </div>
  <div class="kc {"green" if total_sav_ong > 0 else "amber"}">
    <div class="kLabel">Realized Savings</div>
    <div class="kVal">{"Rs " + f"{df_ong_f[sav_col].sum()/1e7:.2f} Cr" if sav_col else "—"}</div>
    <div class="kSub">FY 26-27</div>
  </div>
  <div class="kc teal">
    <div class="kLabel">BUs Covered</div>
    <div class="kVal">{df_ong_f["BU"].nunique() if "BU" in df_ong_f.columns else "—"}</div>
    <div class="kSub">Business units</div>
  </div>
</div>
""", unsafe_allow_html=True)

        # BU breakdown
        if 'BU' in df_ong_f.columns and val_col:
            bu_ong = df_ong_f.groupby('BU').agg(
                pos=(val_col, 'count'),
                val=(val_col, 'sum')
            ).reset_index()
            bu_ong['val_cr'] = bu_ong['val'] / 1e7
            rows_ong = ""
            for _, r in bu_ong.sort_values('val_cr', ascending=False).iterrows():
                rows_ong += f'<tr><td><b style="color:#eee">{r["BU"]}</b></td><td class="mono">{int(r["pos"])}</td><td class="mono">Rs {r["val_cr"]:.2f} Cr</td></tr>'
            st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:8px 0;margin-bottom:12px;"><table class="zTbl"><thead><tr><th>BU</th><th>POs</th><th>Value</th></tr></thead><tbody>{rows_ong}</tbody></table></div>', unsafe_allow_html=True)

        # Full table
        st.markdown("**All Ongoing POs**")
        # Format date columns for display
        display_df = df_ong_f.copy()
        for col in display_df.columns:
            if pd.api.types.is_datetime64_any_dtype(display_df[col]):
                display_df[col] = display_df[col].dt.strftime("%d-%b-%Y")
            elif pd.api.types.is_float_dtype(display_df[col]):
                display_df[col] = display_df[col].apply(
                    lambda x: f"{x:,.0f}" if pd.notna(x) and x != 0 else "")
        st.dataframe(display_df, use_container_width=True,
                     height=min(40*len(df_ong_f)+50, 600))

# ── FOOTER ───────────────────────────────────────────────────────
st.markdown(f"""
<div style="padding:14px 24px;border-top:1px solid rgba(255,255,255,0.05);margin-top:24px;
display:flex;justify-content:space-between;align-items:center;">
<div style="font-size:12px;color:#444;">Zetwerk CPT &middot; CAT-2 &middot; Live Dashboard</div>
<div style="font-size:11px;color:#333;font-family:'DM Mono',monospace;">Updated: {now} &middot; Auto-refresh: 5 min</div>
</div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════
# CAT 2 BUDDY — pure JS floating widget
# no streamlit buttons/inputs bleeding into page
# ════════════════════════════════════════════════
chat_html = ""
for msg in st.session_state.buddy_msgs[-12:]:
    if msg['role']=='user':
        chat_html += f'<div class="bmUser">{msg["content"]}</div>'
    else:
        chat_html += f'<div class="bmBot">{msg["content"]}</div>'

# Handle buddy ask via a hidden form
if 'buddy_ask' in st.session_state and st.session_state.buddy_ask:
    q = st.session_state.buddy_ask
    st.session_state.buddy_ask = ""
    st.session_state.buddy_msgs.append({"role":"user","content":q})
    with st.spinner(""):
        reply = chat_with_buddy(q, dff)
    st.session_state.buddy_msgs.append({"role":"assistant","content":reply})
    st.session_state.buddy_open = True
    st.rerun()

buddy_visible = "flex" if st.session_state.buddy_open else "none"

# Build buddy HTML with proper JS execution via components.html
buddy_html_full = f"""<!DOCTYPE html>
<html>
<head>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'DM Sans',Arial,sans-serif;}}
body{{background:transparent;overflow:hidden;}}
#buddyFab{{
  position:fixed;bottom:20px;right:20px;z-index:9999;
  width:52px;height:52px;border-radius:50%;
  background:linear-gradient(135deg,#e53e3e,#fc4f4f);
  display:flex;align-items:center;justify-content:center;
  cursor:pointer;box-shadow:0 4px 20px rgba(229,62,62,0.5);
  font-size:22px;border:none;color:white;
  transition:transform 0.2s;
}}
#buddyFab:hover{{transform:scale(1.1);}}
#buddyPanel{{
  position:fixed;bottom:82px;right:20px;z-index:9998;
  width:340px;background:#13131a;
  border:1px solid rgba(229,62,62,0.3);border-radius:16px;
  box-shadow:0 8px 32px rgba(0,0,0,0.8);
  display:none;flex-direction:column;overflow:hidden;
}}
#buddyHeader{{
  background:linear-gradient(135deg,#1a0505,#220808);
  border-bottom:1px solid rgba(229,62,62,0.2);
  padding:12px 16px;display:flex;align-items:center;gap:10px;
}}
#buddyAvatar{{
  width:34px;height:34px;background:linear-gradient(135deg,#e53e3e,#fc4f4f);
  border-radius:9px;display:flex;align-items:center;justify-content:center;
  font-size:16px;font-weight:900;color:white;flex-shrink:0;
}}
#buddyName{{font-size:13px;font-weight:700;color:#fff;}}
#buddyStatus{{font-size:10px;color:#38a169;}}
#buddyMsgs{{
  padding:12px;display:flex;flex-direction:column;
  height:260px;overflow-y:auto;gap:6px;
}}
.bmUser{{
  background:rgba(229,62,62,0.12);border:1px solid rgba(229,62,62,0.2);
  border-radius:10px 10px 2px 10px;padding:8px 12px;
  font-size:12px;color:#eee;max-width:85%;align-self:flex-end;margin-left:auto;
}}
.bmBot{{
  background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.09);
  border-radius:10px 10px 10px 2px;padding:8px 12px;
  font-size:12px;color:#ccc;max-width:90%;
}}
#buddyInputRow{{
  padding:8px 12px;border-top:1px solid rgba(255,255,255,0.06);
  display:flex;gap:6px;
}}
#buddyInput{{
  flex:1;background:rgba(255,255,255,0.06);
  border:1px solid rgba(255,255,255,0.1);border-radius:8px;
  padding:8px 10px;color:#fff;font-size:12px;outline:none;
}}
#buddyInput:focus{{border-color:rgba(229,62,62,0.4);}}
#buddySend{{
  background:#e53e3e;border:none;border-radius:8px;
  padding:8px 14px;color:white;font-size:12px;
  cursor:pointer;font-weight:600;
}}
#buddySend:hover{{background:#c53030;}}
</style>
</head>
<body>
<div id="buddyPanel">
  <div id="buddyHeader">
    <div id="buddyAvatar">C</div>
    <div>
      <div id="buddyName">CAT 2 Buddy</div>
      <div id="buddyStatus">Online</div>
    </div>
  </div>
  <div id="buddyMsgs">{chat_html}</div>
  <div id="buddyInputRow">
    <input id="buddyInput" type="text" placeholder="Ask anything about your data..." />
    <button id="buddySend">Send</button>
  </div>
</div>
<button id="buddyFab">&#128172;</button>
<script>
var panel = document.getElementById('buddyPanel');
var fab   = document.getElementById('buddyFab');
var inp   = document.getElementById('buddyInput');
var send  = document.getElementById('buddySend');
var msgs  = document.getElementById('buddyMsgs');

// Open by default if was open
{'panel.style.display="flex";' if st.session_state.buddy_open else ''}
if (msgs) msgs.scrollTop = msgs.scrollHeight;

fab.addEventListener('click', function() {{
  var open = panel.style.display === 'flex';
  panel.style.display = open ? 'none' : 'flex';
  fab.innerHTML = open ? '&#128172;' : '&#10005;';
  if (!open && msgs) setTimeout(function(){{msgs.scrollTop=msgs.scrollHeight;}},50);
}});

function doSend() {{
  var val = inp.value.trim();
  if (!val) return;
  inp.value = '';
  // Navigate parent window with query param
  window.parent.location.href = window.parent.location.pathname + '?buddy_msg=' + encodeURIComponent(val);
}}
send.addEventListener('click', doSend);
inp.addEventListener('keydown', function(e){{ if(e.key==='Enter') doSend(); }});
</script>
</body>
</html>"""

components.html(buddy_html_full, height=420, scrolling=False)

# Handle buddy message from URL query param
buddy_msg = st.query_params.get("buddy_msg", "")
if buddy_msg and buddy_msg.strip():
    st.query_params.clear()
    st.session_state.buddy_msgs.append({"role":"user","content":buddy_msg})
    with st.spinner(""):
        reply = chat_with_buddy(buddy_msg, dff)
    st.session_state.buddy_msgs.append({"role":"assistant","content":reply})
    st.session_state.buddy_open = True
    st.rerun()

# Simple text input at very bottom, hidden visually but functional
with st.container():
    st.markdown('<div style="position:fixed;bottom:-200px;left:-200px;opacity:0;pointer-events:none;">', unsafe_allow_html=True)
    buddy_q = st.text_input("buddy_hidden", key="buddy_hidden_input", label_visibility="hidden")
    st.markdown('</div>', unsafe_allow_html=True)
