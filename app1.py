"""
Zetwerk CPT — Central Procurement Dashboard
Live Google Sheets + CAT 2 Buddy AI Chatbot
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests, json, time
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Zetwerk CPT Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Score map (from Excel logic) ─────────────────────────────────────────────
SCORE_MAP = {
    "advance": -2,
    "on dispatch": 0,
    "ibc 90": 1,
    "ibc 60": 2,
    "ibc 60, ifc 30": 3, "ibc 60+ifc 30": 3,
    "vfs": 3,
    "clean credit 15": 3,
    "ibc 45, ifc 45": 4, "ibc 45+ifc 45": 4,
    "rxil": 4,
    "ifc 30": 5, "ifc 45": 5, "ifc 60": 5,
    "ibc 30, ifc 60": 5, "ibc 30+ifc 60": 5,
    "clean credit 30": 5,
    "ifc 90": 6,
    "clean credit 45": 7,
    "clean credit 60": 8,
    "clean credit 90": 10,
}

def get_score_for_term(term):
    """Calculate weighted score from payment term string"""
    if not term or str(term).strip() in ['', '0', 'nan']:
        return None
    term_lower = str(term).lower()
    parts = term_lower.replace('+', '|').split('|')
    total_score = 0.0
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
                best = val
                break
        total_score += (pct / 100.0) * best
    return round(total_score, 3)

# ── Load Google Sheet data ────────────────────────────────────────────────────
@st.cache_data(ttl=300)  # Refresh every 5 minutes
def load_sheet_data():
    try:
        # Check secrets exist
        if "gcp_service_account" not in st.secrets:
            st.error("❌ Missing secret: gcp_service_account. Please add it in Streamlit Cloud → App Settings → Secrets.")
            return pd.DataFrame()

        creds_dict = dict(st.secrets["gcp_service_account"])
        scopes = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        SHEET_ID = "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU"
        sh = client.open_by_key(SHEET_ID)

        # Try multiple possible sheet tab names
        ws = None
        for tab_name in ["PO TRACKER", "Sheet1", "PR Tracker"]:
            try:
                ws = sh.worksheet(tab_name)
                break
            except:
                continue

        if ws is None:
            available = [s.title for s in sh.worksheets()]
            st.error(f"❌ Could not find sheet tab. Available tabs: {available}")
            return pd.DataFrame()

        data = ws.get_all_values()

        if len(data) < 2:
            st.warning("⚠ Sheet appears empty.")
            return pd.DataFrame()

        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)

        # Clean columns
        df.columns = [c.strip() for c in df.columns]

        # Remove completely empty rows
        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()

        # Parse dates
        for col in ['PR Dt.', 'PO Dt.']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)

        # Parse numbers
        for col in ['PO Basic Value', 'PO Value with GST', 'PCA Basic Value',
                    'Savings Value', 'PR - PO TAT']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(',',''), errors='coerce').fillna(0)

        # Filter FY 2025-26 by PO Dt.
        if 'PO Dt.' in df.columns:
            df_fy = df[
                (df['PO Dt.'] >= pd.Timestamp('2025-04-01')) &
                (df['PO Dt.'] <= pd.Timestamp('2026-03-31'))
            ].copy()
        else:
            df_fy = df.copy()

        # Find payment terms column (check multiple names)
        pt_col = None
        for pt_name in ['PAYMENT TERMS', 'PO Payment Terms', 'Payment Terms']:
            if pt_name in df_fy.columns:
                pt_col = pt_name
                break

        if pt_col and pt_col != 'PAYMENT TERMS':
            df_fy = df_fy.rename(columns={pt_col: 'PAYMENT TERMS'})
            pt_col = 'PAYMENT TERMS'

        if pt_col:
            df_fy['Payment Score'] = df_fy['PAYMENT TERMS'].apply(get_score_for_term)

        # Month-Year column
        if 'PO Dt.' in df_fy.columns:
            df_fy['Month'] = df_fy['PO Dt.'].dt.to_period('M')
            df_fy['Month_str'] = df_fy['PO Dt.'].dt.strftime("%b\'%y")

        return df_fy

    except Exception as e:
        import traceback
        st.error(f"❌ Sheet error: {str(e)}")
        st.code(traceback.format_exc())
        return pd.DataFrame()

# ── CAT 2 Buddy chatbot ───────────────────────────────────────────────────────
def build_context(df):
    """Build data context string for CAT 2 Buddy"""
    if df.empty:
        return "No data available."
    
    ctx = f"""You are CAT 2 Buddy, the AI procurement assistant for Zetwerk Central Procurement Team (CAT-2).
You are helpful, sharp, and professional. Answer questions about procurement data precisely.
Never mention Claude or Anthropic. You are CAT 2 Buddy.

=== FY 2025-26 PROCUREMENT DATA SUMMARY ===
Total POs: {len(df)}
Total Spend (Basic): ₹{df['PO Basic Value'].sum()/1e7:.2f} Cr
Total Savings: ₹{df['Savings Value'].sum()/1e7:.2f} Cr

BU Breakdown:
"""
    for bu in df['BU'].unique():
        if bu and str(bu).strip():
            sub = df[df['BU']==bu]
            ctx += f"  {bu}: {len(sub)} POs, ₹{sub['PO Basic Value'].sum()/1e7:.2f} Cr spend\n"
    
    ctx += "\nPayment Terms Distribution:\n"
    pt_col = 'PAYMENT TERMS'
    if pt_col in df.columns:
        pt_counts = df[pt_col].value_counts().head(10)
        for term, cnt in pt_counts.items():
            if term and str(term).strip() not in ['', '0']:
                val = df[df[pt_col]==term]['PO Basic Value'].sum()
                ctx += f"  {term}: {cnt} POs (₹{val/1e7:.2f} Cr)\n"
    
    ctx += "\nSupplier Types:\n"
    if 'Supplier type' in df.columns:
        st_counts = df['Supplier type'].value_counts()
        for stype, cnt in st_counts.items():
            if stype:
                ctx += f"  {stype}: {cnt} POs\n"
    
    ctx += "\nMonth-wise PO count:\n"
    monthly = df.groupby('Month_str').agg(
        count=('PO Basic Value','count'),
        spend=('PO Basic Value','sum')
    ).reset_index()
    for _, row in monthly.iterrows():
        ctx += f"  {row['Month_str']}: {int(row['count'])} POs, ₹{row['spend']/1e7:.2f} Cr\n"
    
    ctx += "\nCategory breakdown:\n"
    if 'Category' in df.columns:
        cat = df.groupby('Category')['PO Basic Value'].sum().sort_values(ascending=False).head(10)
        for c, v in cat.items():
            if c:
                ctx += f"  {c}: ₹{v/1e7:.2f} Cr\n"
    
    if 'Payment Score' in df.columns:
        scored = df[df['Payment Score'].notna()]
        if len(scored) > 0:
            ctx += f"\nWorking Capital Efficiency (Credit Metric):\n"
            ctx += f"  POs with payment terms filled: {len(scored)}\n"
            monthly_score = scored.groupby('Month_str').apply(
                lambda x: (x['Payment Score'] * x['PO Basic Value']).sum() / x['PO Basic Value'].sum()
                if x['PO Basic Value'].sum() > 0 else 0
            )
            for m, s in monthly_score.items():
                ctx += f"  {m}: Score {s:.2f} (Target: 4.5)\n"
    
    ctx += "\nAnswer questions based on this data. Be precise with numbers. Always show ₹ in Crores."
    return ctx

def chat_with_buddy(messages, df):
    """Call Claude API for CAT 2 Buddy responses"""
    context = build_context(df)
    
    api_messages = [{"role": "user", "content": context + "\n\nUser question: " + messages[0]['content']}]
    if len(messages) > 1:
        api_messages = []
        for i, msg in enumerate(messages):
            if i == 0:
                api_messages.append({
                    "role": "user",
                    "content": context + "\n\n" + msg['content']
                })
            else:
                api_messages.append(msg)
    
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": api_messages,
            },
            timeout=30
        )
        data = resp.json()
        if 'content' in data:
            return data['content'][0]['text']
        return "Sorry, I couldn't process that. Try again!"
    except Exception as e:
        return f"Connection error: {str(e)}"

# ── SPLASH SCREEN ─────────────────────────────────────────────────────────────
if 'loaded' not in st.session_state:
    splash = st.empty()
    with splash.container():
        st.markdown("""
        <style>
        @keyframes spin { to{transform:rotate(360deg)} }
        @keyframes fadeUp { from{opacity:0;transform:translateY(16px)} to{opacity:1;transform:translateY(0)} }
        @keyframes shimmer { 0%{background-position:-400px 0} 100%{background-position:400px 0} }
        .splash {
            position:fixed; inset:0; background:#0e0e12;
            display:flex; align-items:center; justify-content:center;
            flex-direction:column; z-index:9999;
        }
        .splash-ring {
            width:72px; height:72px;
            border:2px solid rgba(229,62,62,0.3);
            border-top:2px solid #e53e3e;
            border-radius:50%;
            animation:spin 1.2s linear infinite;
            position:relative; margin-bottom:28px;
        }
        .splash-z {
            position:absolute; top:50%; left:50%;
            transform:translate(-50%,-50%);
            width:50px; height:50px;
            background:linear-gradient(135deg,#e53e3e,#fc4f4f);
            border-radius:12px;
            display:flex; align-items:center; justify-content:center;
            font-size:22px; font-weight:900; color:white;
            font-family:'DM Sans',sans-serif;
        }
        .splash-title {
            font-family:'DM Sans',sans-serif; font-size:22px;
            font-weight:700; color:#fff; letter-spacing:-0.03em;
            animation:fadeUp 0.6s ease 0.2s both;
        }
        .splash-sub {
            font-family:'DM Sans',sans-serif; font-size:12px;
            color:#444; text-transform:uppercase; letter-spacing:0.1em;
            animation:fadeUp 0.6s ease 0.4s both; margin-top:6px;
        }
        .splash-bar {
            width:280px; height:3px;
            background:rgba(255,255,255,0.06);
            border-radius:99px; overflow:hidden;
            margin-top:28px; animation:fadeUp 0.6s ease 0.5s both;
        }
        .splash-bar-inner {
            height:100%;
            background:linear-gradient(90deg,transparent,#e53e3e,#fc8181,#e53e3e,transparent);
            background-size:400px 100%;
            animation:shimmer 1.4s ease infinite;
        }
        .splash-status {
            font-family:'DM Sans',sans-serif; font-size:11px;
            color:#333; margin-top:14px; letter-spacing:0.06em;
        }
        </style>
        <div class="splash">
          <div class="splash-ring"><div class="splash-z">Z</div></div>
          <div class="splash-title">Zetwerk CPT</div>
          <div class="splash-sub">Central Procurement · CAT-2</div>
          <div class="splash-bar"><div class="splash-bar-inner"></div></div>
          <div class="splash-status">Loading live data from Google Sheets...</div>
        </div>
        """, unsafe_allow_html=True)
    
    df_main = load_sheet_data()
    time.sleep(1)
    splash.empty()
    st.session_state['loaded'] = True
    st.session_state['df'] = df_main
else:
    df_main = st.session_state.get('df', pd.DataFrame())

# ── GLOBAL CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
*, html, body { font-family:'DM Sans',sans-serif !important; }
[data-testid="stAppViewBlockContainer"],[data-testid="stMain"] {
    background:#0e0e12 !important; padding:0 !important; max-width:100% !important;
}
[data-testid="stSidebar"] { display:none !important; }
[data-testid="stMainBlockContainer"] { padding:0 !important; max-width:100% !important; }

/* NAV */
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
.nav-sub-text { font-size:10px; color:#444; }
.nav-tabs { display:flex; gap:2px; }
.ntab {
    padding:5px 14px; border-radius:6px; font-size:12px;
    font-weight:500; color:#666; cursor:pointer;
}
.ntab.active { background:#e53e3e; color:white; }
.nav-right { display:flex; align-items:center; gap:10px; }
.fy-pill {
    background:rgba(229,62,62,0.12); border:1px solid rgba(229,62,62,0.25);
    color:#fc4f4f; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:600;
}
.live-dot {
    display:flex; align-items:center; gap:5px;
    font-size:11px; color:#38a169;
}
.dot { width:7px; height:7px; background:#38a169; border-radius:50%; animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

/* KPI cards */
.krow { display:grid; gap:10px; padding:14px 20px 0; }
.k4 { grid-template-columns:repeat(4,1fr); }
.k5 { grid-template-columns:repeat(5,1fr); }
.k3 { grid-template-columns:repeat(3,1fr); }

.kcard {
    background:#13131a; border:1px solid rgba(255,255,255,0.07);
    border-radius:12px; padding:16px 18px; position:relative; overflow:hidden;
    transition:border-color 0.2s, transform 0.15s;
}
.kcard:hover { border-color:rgba(255,255,255,0.14); transform:translateY(-1px); }
.kcard::before {
    content:''; position:absolute; top:0; left:0; right:0; height:2px; border-radius:12px 12px 0 0;
}
.kc-red::before   { background:linear-gradient(90deg,#e53e3e,#fc8181); }
.kc-green::before { background:linear-gradient(90deg,#38a169,#68d391); }
.kc-blue::before  { background:linear-gradient(90deg,#3182ce,#63b3ed); }
.kc-amber::before { background:linear-gradient(90deg,#d69e2e,#f6e05e); }
.kc-purple::before{ background:linear-gradient(90deg,#805ad5,#b794f4); }
.kc-teal::before  { background:linear-gradient(90deg,#2c7a7b,#4fd1c5); }

.klabel { font-size:10px; color:#555; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; }
.kvalue { font-size:26px; font-weight:700; color:#fff; line-height:1.1; margin:4px 0 2px; letter-spacing:-0.03em; font-family:'DM Mono',monospace; }
.ksub   { font-size:10px; color:#444; }
.kdelta { font-size:11px; font-weight:600; margin-top:5px; }
.kup   { color:#68d391; }
.kdown { color:#fc8181; }
.kwarn { color:#f6e05e; }

/* Section header */
.sec { display:flex; align-items:center; justify-content:space-between; padding:18px 20px 8px; }
.sec-title { font-size:13px; font-weight:700; color:#bbb; }
.sec-tag { font-size:10px; color:#444; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07); padding:3px 8px; border-radius:5px; }

/* Chart wrapper */
.cwrap { padding:0 20px; }
.ccard { background:#13131a; border:1px solid rgba(255,255,255,0.07); border-radius:12px; overflow:hidden; }
.ccard-head { padding:12px 16px 0; display:flex; align-items:center; justify-content:space-between; }
.ccard-title { font-size:12px; font-weight:600; color:#888; }

/* Table */
.tbl { width:100%; border-collapse:collapse; font-size:12px; }
.tbl th { text-align:left; padding:9px 12px; font-size:10px; font-weight:600; color:#555; text-transform:uppercase; letter-spacing:0.06em; border-bottom:1px solid rgba(255,255,255,0.07); }
.tbl td { padding:9px 12px; color:#bbb; border-bottom:1px solid rgba(255,255,255,0.04); }
.tbl tr:hover td { background:rgba(255,255,255,0.02); }
.mono { font-family:'DM Mono',monospace; font-size:11px; }
.pg  { background:rgba(56,161,105,0.15); color:#68d391; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600; }
.pr  { background:rgba(229,62,62,0.15);  color:#fc8181; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600; }
.pa  { background:rgba(214,158,46,0.15); color:#f6e05e; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600; }

/* CAT 2 Buddy chat */
.buddy-wrap {
    position:fixed; bottom:24px; right:24px; z-index:999;
    display:flex; flex-direction:column; align-items:flex-end; gap:10px;
}
.buddy-btn {
    width:52px; height:52px;
    background:linear-gradient(135deg,#e53e3e,#fc4f4f);
    border-radius:50%; display:flex; align-items:center; justify-content:center;
    font-size:20px; cursor:pointer; box-shadow:0 4px 20px rgba(229,62,62,0.4);
    border:none; transition:transform 0.2s;
}
.buddy-btn:hover { transform:scale(1.1); }
.buddy-panel {
    width:380px; background:#13131a;
    border:1px solid rgba(229,62,62,0.25);
    border-radius:16px; overflow:hidden;
    box-shadow:0 8px 40px rgba(0,0,0,0.6);
}
.buddy-header {
    background:linear-gradient(135deg,#1a0f0f,#200808);
    border-bottom:1px solid rgba(229,62,62,0.2);
    padding:14px 16px; display:flex; align-items:center; gap:10px;
}
.buddy-avatar {
    width:36px; height:36px;
    background:linear-gradient(135deg,#e53e3e,#fc4f4f);
    border-radius:10px; display:flex; align-items:center;
    justify-content:center; font-size:18px; font-weight:900; color:white;
}
.buddy-name { font-size:13px; font-weight:700; color:#fff; }
.buddy-status { font-size:10px; color:#38a169; display:flex; align-items:center; gap:4px; }
.buddy-msgs {
    height:320px; overflow-y:auto; padding:14px;
    display:flex; flex-direction:column; gap:10px;
}
.msg-user {
    align-self:flex-end; background:rgba(229,62,62,0.15);
    border:1px solid rgba(229,62,62,0.2); border-radius:12px 12px 2px 12px;
    padding:8px 12px; font-size:12px; color:#eee; max-width:80%;
}
.msg-bot {
    align-self:flex-start; background:rgba(255,255,255,0.05);
    border:1px solid rgba(255,255,255,0.08); border-radius:12px 12px 12px 2px;
    padding:8px 12px; font-size:12px; color:#ccc; max-width:85%;
}
.buddy-input-wrap {
    padding:10px 12px; border-top:1px solid rgba(255,255,255,0.07);
    display:flex; gap:8px;
}
.buddy-input {
    flex:1; background:rgba(255,255,255,0.06);
    border:1px solid rgba(255,255,255,0.1); border-radius:8px;
    padding:8px 12px; color:#fff; font-size:12px; outline:none;
    font-family:'DM Sans',sans-serif;
}
.buddy-send {
    background:#e53e3e; border:none; border-radius:8px;
    padding:8px 14px; color:white; font-size:12px; cursor:pointer; font-weight:600;
}

/* Filters */
.filter-row { padding:8px 20px 0; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
.filter-label { font-size:11px; color:#555; font-weight:600; }

/* Streamlit widget overrides */
div[data-testid="stTabs"] button[role="tab"] { font-size:12px !important; font-weight:500 !important; color:#555 !important; }
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color:#fc4f4f !important; border-bottom:2px solid #e53e3e !important; }
.stSelectbox>div { background:#13131a !important; border:1px solid rgba(255,255,255,0.1) !important; border-radius:8px !important; }
</style>
""", unsafe_allow_html=True)

# ── NAV ───────────────────────────────────────────────────────────────────────
now = datetime.now().strftime("%d %b %Y %H:%M")
st.markdown(f"""
<div class="nav">
  <div class="nav-logo">
    <div class="nav-z">Z</div>
    <div>
      <div class="nav-brand">Zetwerk CPT</div>
      <div class="nav-sub-text">Central Procurement Team</div>
    </div>
  </div>
  <div class="nav-tabs">
    <div class="ntab active">Dashboard</div>
    <div class="ntab">PO Tracker</div>
    <div class="ntab">Suppliers</div>
    <div class="ntab">Analytics</div>
  </div>
  <div class="nav-right">
    <div class="live-dot"><div class="dot"></div>Live · {now}</div>
    <div class="fy-pill">FY 2025–26</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── DATA CHECKS ───────────────────────────────────────────────────────────────
df = df_main.copy() if not df_main.empty else pd.DataFrame()

if df.empty:
    st.markdown("""
    <div style="background:rgba(229,62,62,0.1);border:1px solid rgba(229,62,62,0.3);
    border-radius:10px;padding:20px;margin:20px;text-align:center;">
      <div style="font-size:16px;color:#fc8181;font-weight:700;">⚠ Google Sheet Not Connected</div>
      <div style="font-size:13px;color:#888;margin-top:8px;">
        Please ensure:<br><br>
        1. The <b style="color:#ccc">gcp_service_account</b> secret is added in Streamlit Cloud<br>
        &nbsp;&nbsp;&nbsp;(App Settings → Secrets)<br><br>
        2. The service account email has <b style="color:#ccc">Viewer access</b> to the sheet<br><br>
        3. The sheet has a tab named <b style="color:#ccc">PO TRACKER</b>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── FILTER ROW ────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([1,1,1,1,3])

with col_f1:
    bu_options = ['All BU'] + sorted([b for b in df['BU'].dropna().unique() if b])
    sel_bu = st.selectbox('BU', bu_options, key='f_bu')

with col_f2:
    cat_options = ['All Category'] + sorted([c for c in df['Category'].dropna().unique() if c])
    sel_cat = st.selectbox('Category', cat_options, key='f_cat')

with col_f3:
    buyer_options = ['All Buyers'] + sorted([b for b in df['Handled by'].dropna().unique() if b])
    sel_buyer = st.selectbox('Buyer', buyer_options, key='f_buyer')

with col_f4:
    stype_options = ['All Supplier Types']
    if 'Supplier type' in df.columns:
        stype_options += sorted([s for s in df['Supplier type'].dropna().unique() if s])
    sel_stype = st.selectbox('Supplier Type', stype_options, key='f_stype')

# Apply filters
dff = df.copy()
if sel_bu != 'All BU': dff = dff[dff['BU']==sel_bu]
if sel_cat != 'All Category': dff = dff[dff['Category']==sel_cat]
if sel_buyer != 'All Buyers': dff = dff[dff['Handled by']==sel_buyer]
if sel_stype != 'All Supplier Types' and 'Supplier type' in dff.columns:
    dff = dff[dff['Supplier type']==sel_stype]

# ── COMPUTE KPIs ──────────────────────────────────────────────────────────────
total_pos = len(dff[dff['PO Basic Value']>0])
total_spend = dff['PO Basic Value'].sum() / 1e7
total_savings = dff['Savings Value'].sum() / 1e7
savings_pct = (total_savings / total_spend * 100) if total_spend > 0 else 0

tat_vals = pd.to_numeric(dff['PR - PO TAT'], errors='coerce')
avg_tat = tat_vals[tat_vals > 0].mean()

# OTIF
otif_pct = 0
if 'OTIF' in dff.columns:
    otif_vals = pd.to_numeric(dff['OTIF'], errors='coerce').dropna()
    if len(otif_vals) > 0:
        otif_pct = otif_vals.mean() * 100

# New Vendor Development
nv_pct = 0
nv_count = 0
total_count = len(dff)
if 'Supplier type' in dff.columns:
    nv_mask = dff['Supplier type'].str.contains('NV', case=False, na=False)
    nv_count = nv_mask.sum()
    nv_pct = (nv_count / total_count * 100) if total_count > 0 else 0

# Working Capital Efficiency (Credit Metric)
wce_score = None
if 'Payment Score' in dff.columns:
    scored = dff[dff['Payment Score'].notna() & (dff['PO Basic Value']>0)]
    if len(scored) > 0:
        wce_score = (scored['Payment Score'] * scored['PO Basic Value']).sum() / scored['PO Basic Value'].sum()

# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    " Overview ", " Spend & Savings ", " TAT & OTIF ",
    " Working Capital ", " New Vendor Dev "
])

# ══════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════
with tab1:
    # KPI Row 1
    st.markdown(f"""
    <div class="krow k5">
      <div class="kcard kc-blue">
        <div class="klabel">Total POs</div>
        <div class="kvalue">{total_pos}</div>
        <div class="ksub">FY 2025-26</div>
      </div>
      <div class="kcard kc-green">
        <div class="klabel">Total Spend</div>
        <div class="kvalue">₹{total_spend:.1f} Cr</div>
        <div class="ksub">PO Basic Value</div>
      </div>
      <div class="kcard kc-{'green' if savings_pct >= 4.5 else 'amber'}">
        <div class="klabel">Savings</div>
        <div class="kvalue">₹{total_savings:.2f} Cr</div>
        <div class="ksub">{savings_pct:.1f}% of spend</div>
        <div class="kdelta {'kup' if savings_pct >= 4.5 else 'kwarn'}">{'✓ Above' if savings_pct >= 4.5 else '⚠ Below'} 4.5% target</div>
      </div>
      <div class="kcard kc-{'green' if avg_tat <= 90 else 'red'}">
        <div class="klabel">Avg PR-PO TAT</div>
        <div class="kvalue">{avg_tat:.0f}d</div>
        <div class="ksub">Target: 90 days</div>
        <div class="kdelta {'kup' if avg_tat <= 90 else 'kdown'}">{'✓ On track' if avg_tat <= 90 else '▲ Above target'}</div>
      </div>
      <div class="kcard kc-{'green' if wce_score and wce_score >= 4.5 else 'red' if wce_score else 'purple'}">
        <div class="klabel">Working Capital Score</div>
        <div class="kvalue">{f"{wce_score:.2f}" if wce_score else "—"}</div>
        <div class="ksub">Target: 4.5 (higher = better)</div>
        <div class="kdelta {'kup' if wce_score and wce_score >= 4.5 else 'kdown' if wce_score else ''}">{'✓ Above target' if wce_score and wce_score >= 4.5 else '▼ Below target' if wce_score else 'Fill payment terms'}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Row 2
    st.markdown(f"""
    <div class="krow k4">
      <div class="kcard kc-{'green' if otif_pct >= 75 else 'red'}">
        <div class="klabel">OTIF</div>
        <div class="kvalue">{otif_pct:.1f}%</div>
        <div class="ksub">Target: 75%</div>
        <div class="kdelta {'kup' if otif_pct >= 75 else 'kdown'}">{'✓ On target' if otif_pct >= 75 else '▼ Below target'}</div>
      </div>
      <div class="kcard kc-{'green' if 10 <= nv_pct <= 15 else 'amber'}">
        <div class="klabel">New Vendor Dev</div>
        <div class="kvalue">{nv_pct:.1f}%</div>
        <div class="ksub">{nv_count} NV out of {total_count} POs</div>
        <div class="kdelta {'kup' if 10 <= nv_pct <= 15 else 'kwarn'}">Target: 10–15%</div>
      </div>
      <div class="kcard kc-teal">
        <div class="klabel">Categories Active</div>
        <div class="kvalue">{dff['Category'].nunique()}</div>
        <div class="ksub">Unique categories</div>
      </div>
      <div class="kcard kc-purple">
        <div class="klabel">Suppliers Used</div>
        <div class="kvalue">{dff['Supplier Name'].nunique()}</div>
        <div class="ksub">Unique suppliers</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Charts Row
    st.markdown('<div class="sec"><div class="sec-title">BU Performance</div><div class="sec-tag">Live · FY26</div></div>', unsafe_allow_html=True)
    
    DARK = dict(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="#666", size=11),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#333", linecolor="#333"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickcolor="#333", linecolor="#333"),
        margin=dict(l=8,r=8,t=30,b=8),
    )
    RED="#e53e3e"; GREEN="#38a169"; BLUE="#3182ce"; AMBER="#d69e2e"

    c1, c2 = st.columns(2)
    
    with c1:
        bu_grp = dff.groupby('BU').agg(
            spend=('PO Basic Value','sum'),
            savings=('Savings Value','sum'),
            count=('PO Basic Value','count')
        ).reset_index()
        bu_grp['spend_cr'] = bu_grp['spend']/1e7
        bu_grp['savings_cr'] = bu_grp['savings']/1e7
        bu_grp['sav_pct'] = (bu_grp['savings_cr']/bu_grp['spend_cr']*100).fillna(0)
        
        fig = go.Figure()
        fig.add_trace(go.Bar(name='Spend', x=bu_grp['BU'], y=bu_grp['spend_cr'],
                             marker_color=RED, marker_line_width=0))
        fig.add_trace(go.Bar(name='Savings', x=bu_grp['BU'], y=bu_grp['savings_cr'],
                             marker_color='rgba(56,161,105,0.7)', marker_line_width=0))
        fig.update_layout(**DARK, height=280, barmode='group', title_text='Spend & Savings by BU (₹ Cr)',
                          legend=dict(orientation='h', y=1.12, x=1, xanchor='right', bgcolor='rgba(0,0,0,0)', font=dict(color='#888',size=10)))
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        cat_grp = dff.groupby('Category')['PO Basic Value'].sum().sort_values(ascending=False).head(8).reset_index()
        cat_grp['spend_cr'] = cat_grp['PO Basic Value']/1e7
        fig2 = go.Figure(go.Bar(
            y=cat_grp['Category'], x=cat_grp['spend_cr'],
            orientation='h', marker_color=RED, marker_line_width=0,
            text=cat_grp['spend_cr'].apply(lambda x: f'₹{x:.1f}Cr'),
            textposition='outside', textfont=dict(color='#888', size=10)
        ))
        fig2.update_layout(**DARK, height=280, title_text='Top Categories by Spend',
                           xaxis_title='₹ Crore')
        st.plotly_chart(fig2, use_container_width=True)

# ══════════════════════════════════════════════════════════════
# TAB 2 — SPEND & SAVINGS
# ══════════════════════════════════════════════════════════════
with tab2:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Spend", f"₹{total_spend:.2f} Cr")
    with c2:
        st.metric("Total Savings", f"₹{total_savings:.2f} Cr", f"{savings_pct:.1f}%")
    with c3:
        st.metric("Target Savings%", "4.5%", f"{savings_pct - 4.5:.1f}pp vs target")
    with c4:
        best_bu = dff.groupby('BU').apply(
            lambda x: x['Savings Value'].sum()/x['PO Basic Value'].sum()*100
            if x['PO Basic Value'].sum() > 0 else 0
        ).idxmax() if len(dff) > 0 else "—"
        st.metric("Best Savings BU", best_bu)
    
    c1, c2 = st.columns(2)
    
    with c1:
        # Monthly spend trend
        monthly = dff.groupby('Month_str').agg(
            spend=('PO Basic Value','sum'),
            savings=('Savings Value','sum')
        ).reset_index()
        monthly['spend_cr'] = monthly['spend']/1e7
        monthly['sav_cr'] = monthly['savings']/1e7
        
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(name='Spend', x=monthly['Month_str'], y=monthly['spend_cr'],
                              marker_color='rgba(229,62,62,0.3)', marker_line_width=0))
        fig3.add_trace(go.Scatter(name='Savings', x=monthly['Month_str'], y=monthly['sav_cr'],
                                  line=dict(color=GREEN, width=2.5), mode='lines+markers',
                                  marker=dict(size=5), yaxis='y2'))
        _dark3 = {k:v for k,v in DARK.items() if k not in ('yaxis','legend')}
        fig3.update_layout(**_dark3, height=300, title_text='Monthly Spend vs Savings',
                           barmode='group',
                           yaxis=dict(title='Spend ₹Cr', gridcolor='rgba(255,255,255,0.05)', tickcolor='#333', linecolor='#333'),
                           yaxis2=dict(title='Savings ₹Cr', overlaying='y', side='right', gridcolor='rgba(0,0,0,0)'),
                           legend=dict(orientation='h', y=1.12, x=1, xanchor='right', bgcolor='rgba(0,0,0,0)', font=dict(color='#888',size=10)))
        st.plotly_chart(fig3, use_container_width=True)
    
    with c2:
        # Savings % by BU table
        bu_sav = dff.groupby('BU').agg(
            spend=('PO Basic Value','sum'),
            savings=('Savings Value','sum'),
            count=('PO Basic Value','count')
        ).reset_index()
        bu_sav['sav_pct'] = (bu_sav['savings']/bu_sav['spend']*100).fillna(0)
        bu_sav = bu_sav.sort_values('spend', ascending=False)
        
        rows = ""
        for _, row in bu_sav.iterrows():
            pill = "pg" if row['sav_pct'] >= 4.5 else ("pr" if row['sav_pct'] < 0 else "pa")
            rows += f"""<tr>
              <td><b style="color:#eee">{row['BU']}</b></td>
              <td class="mono">₹{row['spend']/1e7:.2f} Cr</td>
              <td class="mono">₹{row['savings']/1e7:.2f} Cr</td>
              <td><span class="{pill}">{row['sav_pct']:.1f}%</span></td>
              <td class="mono">{int(row['count'])}</td>
            </tr>"""
        
        st.markdown(f"""
        <div class="ccard" style="padding:4px 0 8px;">
          <div class="ccard-head"><span class="ccard-title">BU Savings Summary</span></div>
          <table class="tbl" style="margin-top:8px">
            <thead><tr><th>BU</th><th>Spend</th><th>Savings</th><th>Savings%</th><th>POs</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# TAB 3 — TAT & OTIF
# ══════════════════════════════════════════════════════════════
with tab3:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Avg PR-PO TAT", f"{avg_tat:.0f} days", f"{avg_tat-90:.0f}d vs 90d target")
    with c2:
        st.metric("OTIF", f"{otif_pct:.1f}%", f"{otif_pct-75:.1f}pp vs 75% target")
    with c3:
        on_time = len(dff[pd.to_numeric(dff['PR - PO TAT'], errors='coerce') <= 90])
        st.metric("POs within TAT", f"{on_time}/{total_pos}")
    with c4:
        if 'Delivery Status' in dff.columns:
            completed = len(dff[dff['Delivery Status'].str.contains('Completed', case=False, na=False)])
            st.metric("Completed Deliveries", str(completed))
    
    c1, c2 = st.columns(2)
    
    with c1:
        bu_tat = dff.groupby('BU').apply(
            lambda x: pd.to_numeric(x['PR - PO TAT'], errors='coerce').mean()
        ).reset_index()
        bu_tat.columns = ['BU','Avg TAT']
        bu_tat = bu_tat.dropna()
        
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(
            x=bu_tat['BU'], y=bu_tat['Avg TAT'],
            marker_color=[GREEN if v <= 90 else RED for v in bu_tat['Avg TAT']],
            marker_line_width=0,
            text=bu_tat['Avg TAT'].apply(lambda x: f'{x:.0f}d'),
            textposition='outside', textfont=dict(color='#888',size=10)
        ))
        fig4.add_hline(y=90, line_dash='dash', line_color=AMBER,
                       annotation_text='90d target', annotation_font_color=AMBER)
        fig4.update_layout(**DARK, height=280, title_text='Avg PR-PO TAT by BU', showlegend=False)
        st.plotly_chart(fig4, use_container_width=True)
    
    with c2:
        if 'OTIF' in dff.columns:
            bu_otif = dff.groupby('BU').apply(
                lambda x: pd.to_numeric(x['OTIF'], errors='coerce').mean() * 100
            ).reset_index()
            bu_otif.columns = ['BU','OTIF%']
            bu_otif = bu_otif.dropna()
            
            fig5 = go.Figure()
            fig5.add_trace(go.Bar(
                x=bu_otif['BU'], y=bu_otif['OTIF%'],
                marker_color=[GREEN if v >= 75 else RED for v in bu_otif['OTIF%']],
                marker_line_width=0,
                text=bu_otif['OTIF%'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#888',size=10)
            ))
            fig5.add_hline(y=75, line_dash='dash', line_color=AMBER,
                           annotation_text='75% target', annotation_font_color=AMBER)
            fig5.update_layout(**DARK, height=280, title_text='OTIF by BU', showlegend=False, yaxis_range=[0,100])
            st.plotly_chart(fig5, use_container_width=True)

# ══════════════════════════════════════════════════════════════
# TAB 4 — WORKING CAPITAL EFFICIENCY (CREDIT METRIC)
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("""
    <div style="background:rgba(229,62,62,0.08);border:1px solid rgba(229,62,62,0.2);border-radius:10px;padding:12px 16px;margin:10px 20px 0;">
      <div style="font-size:12px;color:#fc8181;font-weight:600;">How Working Capital Score is Calculated</div>
      <div style="font-size:11px;color:#666;margin-top:4px;">
        Score = Σ(Payment Term Score × PO Value) ÷ Total PO Value &nbsp;|&nbsp; Target: 4.5 &nbsp;|&nbsp; 
        Higher score = better working capital for Zetwerk<br>
        Advance = -2 &nbsp;|&nbsp; IBC 90 = 1 &nbsp;|&nbsp; IFC 90 = 6 &nbsp;|&nbsp; Clean Credit 90 = 10 &nbsp;|&nbsp; 
        Updates automatically as payment terms are filled in col X
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    if 'Payment Score' in dff.columns and 'PAYMENT TERMS' in dff.columns:
        scored = dff[dff['Payment Score'].notna() & (dff['PO Basic Value']>0)].copy()
        
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Overall WC Score", f"{wce_score:.2f}" if wce_score else "—",
                      f"{'Above' if wce_score and wce_score >= 4.5 else 'Below'} 4.5 target")
        with c2:
            st.metric("POs with Terms", f"{len(scored)}/{total_pos}")
        with c3:
            adv_pct = len(scored[scored['Payment Score']<0]) / len(scored) * 100 if len(scored) > 0 else 0
            st.metric("Advance %", f"{adv_pct:.1f}%", "Lower is better")
        with c4:
            good_pct = len(scored[scored['Payment Score']>=5]) / len(scored) * 100 if len(scored) > 0 else 0
            st.metric("IFC/CC Terms %", f"{good_pct:.1f}%", "Higher is better")
        
        # Monthly WCE chart
        if len(scored) > 0:
            monthly_wce = scored.groupby('Month_str').apply(
                lambda x: (x['Payment Score'] * x['PO Basic Value']).sum() / x['PO Basic Value'].sum()
                if x['PO Basic Value'].sum() > 0 else 0
            ).reset_index()
            monthly_wce.columns = ['Month','Score']
            monthly_spend = scored.groupby('Month_str')['PO Basic Value'].sum().reset_index()
            monthly_spend.columns = ['Month','Spend']
            
            c1, c2 = st.columns(2)
            
            with c1:
                fig6 = go.Figure()
                fig6.add_trace(go.Bar(
                    x=monthly_spend['Month'], y=monthly_spend['Spend']/1e7,
                    name='PO Spend', marker_color='rgba(229,62,62,0.2)', marker_line_width=0
                ))
                fig6.add_trace(go.Scatter(
                    x=monthly_wce['Month'], y=monthly_wce['Score'],
                    name='WC Score', line=dict(color=RED, width=2.5),
                    mode='lines+markers', marker=dict(size=6), yaxis='y2'
                ))
                fig6.add_hline(y=4.5, line_dash='dash', line_color=AMBER,
                               annotation_text='Target 4.5', annotation_font_color=AMBER)
                _dark6 = {k:v for k,v in DARK.items() if k not in ('yaxis','legend')}
                fig6.update_layout(**_dark6, height=300,
                                   title_text='Monthly WC Score vs PO Spend',
                                   yaxis=dict(title='Spend ₹Cr', gridcolor='rgba(255,255,255,0.05)', tickcolor='#333', linecolor='#333'),
                                   yaxis2=dict(title='Score', overlaying='y', side='right',
                                               gridcolor='rgba(0,0,0,0)'),
                                   legend=dict(orientation='h', y=1.12, x=1, xanchor='right',
                                               bgcolor='rgba(0,0,0,0)', font=dict(color='#888',size=10)))
                st.plotly_chart(fig6, use_container_width=True)
            
            with c2:
                # Payment terms breakdown
                pt_grp = scored.groupby('PAYMENT TERMS').agg(
                    count=('PO Basic Value','count'),
                    value=('PO Basic Value','sum'),
                    score=('Payment Score','first')
                ).reset_index().sort_values('value', ascending=False).head(10)
                
                rows = ""
                for _, row in pt_grp.iterrows():
                    s = row['score']
                    pill = "pg" if s >= 5 else ("pr" if s < 0 else "pa")
                    rows += f"""<tr>
                      <td style="color:#ccc;font-size:11px">{row['PAYMENT TERMS']}</td>
                      <td class="mono">{int(row['count'])}</td>
                      <td class="mono">₹{row['value']/1e7:.2f} Cr</td>
                      <td><span class="{pill}">{s:.0f}</span></td>
                    </tr>"""
                
                st.markdown(f"""
                <div class="ccard" style="padding:4px 0 8px;">
                  <div class="ccard-head"><span class="ccard-title">Payment Terms Breakdown</span></div>
                  <table class="tbl" style="margin-top:8px">
                    <thead><tr><th>Term</th><th>POs</th><th>Value</th><th>Score</th></tr></thead>
                    <tbody>{rows}</tbody>
                  </table>
                </div>
                """, unsafe_allow_html=True)
            
            # BU-wise WCE
            bu_wce = scored.groupby('BU').apply(
                lambda x: (x['Payment Score'] * x['PO Basic Value']).sum() / x['PO Basic Value'].sum()
                if x['PO Basic Value'].sum() > 0 else 0
            ).reset_index()
            bu_wce.columns = ['BU','Score']
            
            fig7 = go.Figure(go.Bar(
                x=bu_wce['BU'], y=bu_wce['Score'],
                marker_color=[GREEN if v >= 4.5 else RED for v in bu_wce['Score']],
                marker_line_width=0,
                text=bu_wce['Score'].apply(lambda x: f'{x:.2f}'),
                textposition='outside', textfont=dict(color='#888',size=10)
            ))
            fig7.add_hline(y=4.5, line_dash='dash', line_color=AMBER,
                           annotation_text='Target 4.5', annotation_font_color=AMBER)
            fig7.update_layout(**DARK, height=260, title_text='Working Capital Score by BU', showlegend=False)
            st.plotly_chart(fig7, use_container_width=True)
    else:
        st.info("Payment terms not yet filled in col X of PO TRACKER. Run `fillPaymentTermsByPORef` in Apps Script to populate, then this tab will auto-update.")

# ══════════════════════════════════════════════════════════════
# TAB 5 — NEW VENDOR DEVELOPMENT
# ══════════════════════════════════════════════════════════════
with tab5:
    st.markdown("""
    <div style="background:rgba(49,130,206,0.08);border:1px solid rgba(49,130,206,0.2);border-radius:10px;padding:12px 16px;margin:10px 20px 0;">
      <div style="font-size:12px;color:#63b3ed;font-weight:600;">New Vendor Development (NVD) Target: 10–15% of POs</div>
      <div style="font-size:11px;color:#666;margin-top:4px;">
        AVL = Approved Vendor List &nbsp;|&nbsp; NV = New Vendor &nbsp;|&nbsp; 
        Calculated as % of total POs placed with new vendors per BU
      </div>
    </div>
    """, unsafe_allow_html=True)
    
    if 'Supplier type' in dff.columns:
        # Overall
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Overall NVD%", f"{nv_pct:.1f}%",
                      f"{'✓ On target' if 10<=nv_pct<=15 else 'Off target'}")
        with c2:
            st.metric("New Vendor POs", str(nv_count))
        with c3:
            avl_count = len(dff[dff['Supplier type'].str.contains('AVL', case=False, na=False)])
            st.metric("AVL POs", str(avl_count))
        with c4:
            nv_spend = dff[dff['Supplier type'].str.contains('NV', case=False, na=False)]['PO Basic Value'].sum()/1e7
            st.metric("NV Spend", f"₹{nv_spend:.2f} Cr")
        
        # BU-wise NVD
        bu_nv = dff.groupby('BU').apply(lambda x: pd.Series({
            'Total': len(x),
            'NV': x['Supplier type'].str.contains('NV', case=False, na=False).sum(),
            'AVL': x['Supplier type'].str.contains('AVL', case=False, na=False).sum(),
        })).reset_index()
        bu_nv['NV%'] = (bu_nv['NV'] / bu_nv['Total'] * 100).fillna(0)
        
        c1, c2 = st.columns(2)
        
        with c1:
            fig8 = go.Figure()
            fig8.add_trace(go.Bar(
                name='NV %', x=bu_nv['BU'], y=bu_nv['NV%'],
                marker_color=[GREEN if 10<=v<=15 else (AMBER if v<10 else RED) for v in bu_nv['NV%']],
                marker_line_width=0,
                text=bu_nv['NV%'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#888',size=10)
            ))
            fig8.add_hrect(y0=10, y1=15, fillcolor="rgba(56,161,105,0.08)",
                           line_width=0, annotation_text="Target 10-15%",
                           annotation_font_color="#38a169", annotation_font_size=10)
            fig8.update_layout(**DARK, height=280, title_text='New Vendor Development % by BU',
                               showlegend=False, yaxis_range=[0, max(bu_nv['NV%'].max()*1.3, 20)])
            st.plotly_chart(fig8, use_container_width=True)
        
        with c2:
            rows = ""
            for _, row in bu_nv.iterrows():
                pill = "pg" if 10<=row['NV%']<=15 else ("pa" if row['NV%']<10 else "pr")
                rows += f"""<tr>
                  <td><b style="color:#eee">{row['BU']}</b></td>
                  <td class="mono">{int(row['Total'])}</td>
                  <td class="mono">{int(row['NV'])}</td>
                  <td class="mono">{int(row['AVL'])}</td>
                  <td><span class="{pill}">{row['NV%']:.1f}%</span></td>
                </tr>"""
            
            st.markdown(f"""
            <div class="ccard" style="padding:4px 0 8px;">
              <div class="ccard-head"><span class="ccard-title">NVD by BU</span></div>
              <table class="tbl" style="margin-top:8px">
                <thead><tr><th>BU</th><th>Total POs</th><th>NV POs</th><th>AVL POs</th><th>NV%</th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </div>
            """, unsafe_allow_html=True)
        
        # NV Supplier list
        nv_list = dff[dff['Supplier type'].str.contains('NV', case=False, na=False)]
        if len(nv_list) > 0:
            st.markdown('<div class="sec"><div class="sec-title">New Vendors This FY</div></div>', unsafe_allow_html=True)
            nv_display = nv_list.groupby('Supplier Name').agg(
                BU=('BU','first'),
                Category=('Category','first'),
                POs=('PO Basic Value','count'),
                Spend=('PO Basic Value','sum')
            ).reset_index().sort_values('Spend', ascending=False)
            
            rows = ""
            for _, row in nv_display.iterrows():
                rows += f"""<tr>
                  <td style="color:#ccc">{row['Supplier Name']}</td>
                  <td>{row['BU']}</td>
                  <td>{row['Category']}</td>
                  <td class="mono">{int(row['POs'])}</td>
                  <td class="mono">₹{row['Spend']/1e7:.2f} Cr</td>
                </tr>"""
            
            st.markdown(f"""
            <div class="cwrap"><div class="ccard" style="padding:4px 0 8px;">
              <table class="tbl" style="margin-top:8px">
                <thead><tr><th>Supplier</th><th>BU</th><th>Category</th><th>POs</th><th>Spend</th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </div></div>
            """, unsafe_allow_html=True)
    else:
        st.info("Supplier type column (col O) not found in sheet.")

# ── FOOTER ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="padding:12px 20px; border-top:1px solid rgba(255,255,255,0.05); margin-top:20px; display:flex; justify-content:space-between; align-items:center;">
  <div style="font-size:11px; color:#333;">⚡ Zetwerk CPT · CAT-2 · Live Dashboard</div>
  <div style="font-size:10px; color:#222; font-family:'DM Mono',monospace;">Updated: {now} · Auto-refresh: 5 min</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# CAT 2 BUDDY — FLOATING CHATBOT
# ══════════════════════════════════════════════════════════════
if 'buddy_open' not in st.session_state:
    st.session_state.buddy_open = False
if 'buddy_msgs' not in st.session_state:
    st.session_state.buddy_msgs = [
        {"role": "assistant", "content": "Hi! I'm CAT 2 Buddy 👋\nAsk me anything about your procurement data — spend, savings, TAT, payment terms, suppliers, or any metric!"}
    ]

with st.sidebar:
    st.markdown("### CAT 2 Buddy")
    st.markdown("*Your CPT AI Assistant*")
    
    # Chat history
    for msg in st.session_state.buddy_msgs:
        if msg['role'] == 'user':
            st.markdown(f"""<div style="background:rgba(229,62,62,0.1);border:1px solid rgba(229,62,62,0.2);border-radius:10px;padding:8px 12px;margin:4px 0;font-size:12px;color:#eee;">{msg['content']}</div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:8px 12px;margin:4px 0;font-size:12px;color:#ccc;">{msg['content']}</div>""", unsafe_allow_html=True)
    
    # Quick questions
    st.markdown("**Quick Questions:**")
    quick_qs = [
        "Total spend by BU?",
        "How many VFS payment POs?",
        "What is working capital score?",
        "Which BU has best savings?",
        "New vendor development %?",
        "Average TAT this FY?",
    ]
    
    for q in quick_qs:
        if st.button(q, key=f"qq_{q}", use_container_width=True):
            st.session_state.buddy_msgs.append({"role": "user", "content": q})
            with st.spinner("CAT 2 Buddy thinking..."):
                reply = chat_with_buddy(
                    [m for m in st.session_state.buddy_msgs if m['role']!='assistant' or st.session_state.buddy_msgs.index(m)==0],
                    dff
                )
            st.session_state.buddy_msgs.append({"role": "assistant", "content": reply})
            st.rerun()
    
    # Custom question input
    user_input = st.text_input("Ask CAT 2 Buddy:", placeholder="e.g. How many IFC 90 POs?", key="buddy_input")
    if st.button("Ask", type="primary", use_container_width=True) and user_input:
        st.session_state.buddy_msgs.append({"role": "user", "content": user_input})
        with st.spinner("CAT 2 Buddy thinking..."):
            reply = chat_with_buddy(
                [m for m in st.session_state.buddy_msgs if m['role']!='assistant' or st.session_state.buddy_msgs.index(m)==0],
                dff
            )
        st.session_state.buddy_msgs.append({"role": "assistant", "content": reply})
        st.rerun()
    
    if st.button("Clear Chat", use_container_width=True):
        st.session_state.buddy_msgs = [
            {"role": "assistant", "content": "Hi! I'm CAT 2 Buddy. Ask me anything about your procurement data!"}
        ]
        st.rerun()

# Re-enable sidebar for chatbot
st.markdown("""
<style>
[data-testid="stSidebar"] { 
    display:block !important;
    background:#0e0e12 !important;
    border-right:1px solid rgba(255,255,255,0.07) !important;
    min-width:320px !important;
    max-width:320px !important;
}
[data-testid="stSidebar"] * { font-family:'DM Sans',sans-serif !important; }
[data-testid="stSidebar"] .stButton button {
    background:rgba(255,255,255,0.04) !important;
    border:1px solid rgba(255,255,255,0.08) !important;
    color:#888 !important; font-size:11px !important;
    border-radius:6px !important; transition:all 0.15s !important;
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
[data-testid="stSidebar"] h3 { color:#fff !important; font-size:16px !important; }
[data-testid="stSidebar"] p { color:#666 !important; font-size:11px !important; }
[data-testid="stSidebar"] strong { color:#888 !important; font-size:11px !important; }
</style>
""", unsafe_allow_html=True)
