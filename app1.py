"""
Zetwerk CPT CAT-2 Dashboard — FY 2026-27
Sheet: PO TRACKER  27  +  ongoing updated with realized27

Verified data facts (from Excel inspection Apr 2026):
- 126 real rows (BU col non-empty); filter by BU != empty
- Supplier type is in col AO (_SupplierType), NOT col O (VLOOKUP returns None live)
- TAT col M = integer days, BUT T&D rows have no PR date → TAT = Excel serial (~46000). Filter: 0 < TAT < 1000
- Savings% col X stored as decimal (0.205 = 20.5%) → auto-detected and multiplied ×100
- OTIF col AF = 0 for all current rows (no completed deliveries)
- Delivery Status col AG = 'Ongoing' for all current POs
- MFC data only exists for T&D rows currently
- gspread FORMATTED_VALUE returns computed cell values (not formulas)
- Dates come back as strings: "11/02/2026" or "02-Feb-2026"
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import date, datetime
from google.oauth2.service_account import Credentials
import gspread

st.set_page_config(
    page_title="Zetwerk CPT Dashboard",
    page_icon="Z", layout="wide",
    initial_sidebar_state="collapsed"
)

SHEET_ID = "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU"
SCOPES   = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

SCORE_MAP = {
    "advance": -2, "on dispatch": 0, "pdc": 0,
    "ibc 90": 1, "ibc 60": 2,
    "vfs": 3, "clean credit 15": 3,
    "ibc 45": 4, "rxil": 4,
    "ifc 30": 5, "ifc 45": 5, "ifc 60": 5, "clean credit 30": 5,
    "lc 90": 5, "lc": 4,
    "ifc 90": 6, "clean credit 45": 7, "clean credit 60": 8, "clean credit 90": 10
}

def calc_score(term):
    if not term or str(term).strip() in ('', 'nan', 'None'): return None
    t = str(term).lower()
    for k, v in SCORE_MAP.items():
        if k in t: return float(v)
    return None

def gclient():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.authorize(creds)

def parse_dates(series):
    raw = series.astype(str).str.strip()
    out = pd.to_datetime(raw, format='%d/%m/%Y', errors='coerce')
    mask = out.isna() & ~raw.isin(['', 'nan', 'None', 'NaT'])
    if mask.any():
        out[mask] = pd.to_datetime(raw[mask], format='mixed', dayfirst=True, errors='coerce')
    return out

def safe_num(series):
    return pd.to_numeric(
        series.astype(str).str.replace(',','',regex=False)
                          .str.replace('%','',regex=False).str.strip(),
        errors='coerce')

@st.cache_data(ttl=60, show_spinner=False)
def load_po_tracker():
    try:
        gc = gclient()
        sh = gc.open_by_key(SHEET_ID)
        ws = None
        for tab in ["PO TRACKER  27","PO TRACKER ' 27","PO TRACKER '27","PO TRACKER"]:
            try: ws = sh.worksheet(tab); break
            except: continue
        if not ws:
            return pd.DataFrame(), f"Tab not found. Available: {[s.title for s in sh.worksheets()]}"
        data = ws.get_all_values(value_render_option='FORMATTED_VALUE')
        if len(data) < 2: return pd.DataFrame(), "Sheet is empty"

        raw_h = [str(h).strip() if h else '' for h in data[0]]
        seen = {}
        headers = []
        for h in raw_h:
            if not h: h = f'_col_{len(headers)}'
            if h in seen: seen[h] += 1; h = f'{h}_{seen[h]}'
            else: seen[h] = 0
            headers.append(h)
        df = pd.DataFrame(data[1:], columns=headers)

        # Filter real rows by BU
        bu_col = next((c for c in df.columns if c.strip().upper()=='BU'), None)
        if not bu_col: return pd.DataFrame(), "BU column not found"
        bu_s = df[bu_col].astype(str).str.strip()
        df = df[bu_s.ne('') & bu_s.ne('nan') & bu_s.ne('None')].copy().reset_index(drop=True)

        # Dates
        date_kw = ['dt.','dt ',' dt','date','dt\n','\ndt']
        date_cols = [c for c in df.columns if any(x in c.lower() for x in date_kw)]
        for c in date_cols:
            df[c] = parse_dates(df[c])

        # Numerics (skip date cols)
        num_kw = ['value','gst','saving','tat','delivery time','otif','delivered','yet to be','actual delivery','days']
        for c in df.columns:
            if c in date_cols: continue
            if any(x in c.lower() for x in num_kw):
                df[c] = safe_num(df[c])

        # TAT: filter Excel date serials (valid TAT = 1-999 days)
        tat_col = next((c for c in df.columns if 'pr' in c.lower() and 'po' in c.lower() and 'tat' in c.lower()), None)
        if tat_col:
            df[tat_col] = safe_num(df[tat_col])
            df[tat_col] = df[tat_col].where((df[tat_col]>0) & (df[tat_col]<1000))

        # Savings%: stored as decimal 0.205 → convert to 20.5
        sav_pct_col = next((c for c in df.columns if 'saving' in c.lower() and '%' in c), None)
        if sav_pct_col:
            df[sav_pct_col] = safe_num(df[sav_pct_col])
            mx = df[sav_pct_col].dropna().abs().max()
            if pd.notna(mx) and mx < 2:
                df[sav_pct_col] = df[sav_pct_col] * 100

        # Supplier type: col O (VLOOKUP, often None) + col AO (_SupplierType)
        # Merge: use col O when filled, fill gaps from col AO
        sup_o  = next((c for c in df.columns if c.strip().lower()=='supplier type'), None)
        sup_ao = next((c for c in df.columns if '_suppliertype' in c.lower().replace(' ','')), None)
        if sup_o and sup_ao:
            # Fill col O gaps from col AO
            mask_empty = df[sup_o].astype(str).str.strip().isin(['','nan','None'])
            df.loc[mask_empty, sup_o] = df.loc[mask_empty, sup_ao].values
        elif sup_ao and not sup_o:
            df['Supplier type'] = df[sup_ao]
            sup_o = 'Supplier type'
        # Also fill col AO gaps from col O (so both are complete)
        if sup_o and sup_ao:
            mask_ao_empty = df[sup_ao].astype(str).str.strip().isin(['','nan','None'])
            df.loc[mask_ao_empty, sup_ao] = df.loc[mask_ao_empty, sup_o].values

        # Payment score
        pay_col = next((c for c in df.columns if 'payment' in c.lower() and 'term' in c.lower()), None)
        if pay_col:
            df['_PayScore'] = df[pay_col].apply(calc_score)

        return df, None
    except Exception as e:
        import traceback
        return pd.DataFrame(), f"{e}\n{traceback.format_exc()}"

@st.cache_data(ttl=60, show_spinner=False)
def load_ongoing():
    try:
        gc = gclient()
        sh = gc.open_by_key(SHEET_ID)
        ws = None
        for tab in ["ongoing updated with realized27","ongoing"]:
            try: ws = sh.worksheet(tab); break
            except: continue
        if not ws: return pd.DataFrame(), "Ongoing tab not found"
        data = ws.get_all_values(value_render_option='FORMATTED_VALUE')
        if len(data) < 3: return pd.DataFrame(), "Empty"

        # Row 0 = title, Row 1 = headers — deduplicate blank/duplicate names
        raw_headers = [str(h).strip() if h else '' for h in data[1]]
        headers = []
        seen = {}
        for h in raw_headers:
            if not h:
                h = f'_col_{len(headers)}'
            if h in seen:
                seen[h] += 1
                h = f'{h}_{seen[h]}'
            else:
                seen[h] = 0
            headers.append(h)

        df = pd.DataFrame(data[2:], columns=headers)

        # Filter real rows by BU
        bu_col = next((c for c in df.columns if c.strip().upper() == 'BU'), None)
        if bu_col:
            bu_s = df[bu_col].astype(str).str.strip()
            df = df[bu_s.ne('') & bu_s.ne('nan') & bu_s.ne('None')].copy()
        df = df.reset_index(drop=True)

        # Parse each column safely — skip helper/blank cols
        # Note: ongoing sheet has duplicate header at col 10 (renamed to _col_10)
        # "deliver" keyword matches both YTD and delivered cols — handle both
        for c in df.columns:
            if c.startswith('_col_'):
                continue
            cl = c.lower().replace('\n', ' ')
            try:
                if any(x in cl for x in ['value', 'saving', 'amount', 'delivered in', 'yet to']):
                    df[c] = safe_num(df[c]).fillna(0)
                elif any(x in cl for x in ['date', 'dt']):
                    df[c] = parse_dates(df[c])
            except Exception:
                pass

        return df, None
    except Exception as e:
        import traceback
        return pd.DataFrame(), f"{e} | {traceback.format_exc()}"

def fc(df, *kws):
    for c in df.columns:
        cl = c.lower()
        if all(k.lower() in cl for k in kws): return c
    return None

def buddy_chat(question, df_po, df_ong):
    try:
        import anthropic
        key = None
        for k in ["ANTHROPIC_API_KEY","anthropic_api_key"]:
            try:
                v = st.secrets.get(k)
                if v: key = v; break
            except: pass
        if not key: return "API key not found. Add ANTHROPIC_API_KEY to Streamlit Secrets (outside [gcp_service_account])."
        c_pov = fc(df_po,'po','basic','value')
        c_sav = fc(df_po,'savings','value') or fc(df_po,'saving')
        spend   = float(df_po[c_pov].sum()/1e7) if c_pov else 0
        savings = float(df_po[c_sav].sum()/1e7) if c_sav else 0
        bu_sp = {}
        if c_pov and 'BU' in df_po.columns:
            bu_sp = {str(k):round(float(v)/1e7,2) for k,v in df_po.groupby('BU')[c_pov].sum().items()}
        ctx = (f"You are CAT 2 Buddy, procurement AI for Zetwerk CPT CAT-2. Never mention Claude/Anthropic.\n"
               f"FY 2026-27: {len(df_po)} POs, Rs {spend:.2f}Cr spend, Rs {savings:.2f}Cr savings.\n"
               f"BU spend(Cr): {bu_sp}. Carry-forward POs: {len(df_ong)}.\nAnswer concisely in Rs Crores.")
        client = anthropic.Anthropic(api_key=key)
        r = client.messages.create(model="claude-sonnet-4-6", max_tokens=400,
            messages=[{"role":"user","content":ctx+"\n\nQ: "+question}])
        return r.content[0].text
    except ImportError: return "anthropic package missing — add to requirements.txt"
    except Exception as e: return f"Error: {e}"

# Load
with st.spinner("Loading…"):
    df_raw, po_err = load_po_tracker()
    df_ong, ong_err = load_ongoing()

if 'buddy_msgs' not in st.session_state:
    st.session_state.buddy_msgs = [{"role":"bot","text":"Hi! I'm CAT 2 Buddy. Ask me anything about CAT-2 procurement."}]

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap');
*{font-family:'DM Sans',sans-serif!important;box-sizing:border-box;}
[data-testid="stAppViewContainer"]{background:#0d0d1a!important;}
[data-testid="stMainBlockContainer"],[data-testid="stAppViewBlockContainer"],section[data-testid="stMain"]>div,.block-container{max-width:100%!important;width:100%!important;padding:0 20px!important;padding-top:0!important;}
/* Kill the white header bar and Share button Streamlit injects */
[data-testid="stHeader"]{display:none!important;height:0!important;}
header[data-testid="stHeader"]{display:none!important;height:0!important;}
[data-testid="stToolbar"]{display:none!important;}
#MainMenu{display:none!important;}
footer{display:none!important;}
.stDeployButton{display:none!important;}
[data-testid="stDecoration"]{display:none!important;}
[data-testid="stStatusWidget"]{display:none!important;}-testid="stHeader"]{display:none!important;}
.stAppDeployButton{display:none!important;}
div[data-testid="stToolbar"]{display:none!important;}
[data-testid="stSidebar"]{display:none!important;}
[data-testid="stHorizontalBlock"]{gap:10px!important;}

/* ── NAVBAR ── */
.zN{background:#13131a;border-bottom:1px solid rgba(255,255,255,.07);padding:0 24px;display:flex;align-items:center;justify-content:space-between;height:52px;margin:0 -20px 8px;}
.zNL{display:flex;align-items:center;gap:10px;}
.zLogo{width:36px;height:36px;border-radius:8px;overflow:hidden;display:flex;align-items:center;justify-content:center;}
.zLogo img{width:36px;height:36px;object-fit:cover;border-radius:8px;}
.zB{font-size:14px;font-weight:700;color:white;}.zS{font-size:10px;color:#aaa;}
.zR{display:flex;align-items:center;gap:10px;}
.zP{background:rgba(229,62,62,.12);border:1px solid rgba(229,62,62,.3);color:#fc4f4f;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;}
.zL{display:flex;align-items:center;gap:5px;font-size:11px;color:#38a169;}
.zD{width:7px;height:7px;background:#38a169;border-radius:50%;animation:p 2s infinite;}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}

/* ── LOADING OVERLAY — pure CSS, auto-hides after 1.5s ── */
#zetwerk-loader{position:fixed;inset:0;background:#0d0d1a;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;animation:loaderFade 0.5s ease 1.5s forwards;}
@keyframes loaderFade{0%{opacity:1;pointer-events:all;}100%{opacity:0;pointer-events:none;visibility:hidden;}}
.loader-logo{width:80px;height:80px;border-radius:18px;overflow:hidden;animation:spin 1.2s linear infinite;}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
.loader-title{font-size:22px;font-weight:800;color:#fff;margin-top:20px;letter-spacing:-.01em;}
.loader-sub{font-size:12px;color:rgba(255,255,255,.35);margin-top:6px;letter-spacing:.1em;text-transform:uppercase;}

/* ── KPI CARDS ── */
.kG{display:grid;gap:10px;padding:4px 0;}
.k5{grid-template-columns:repeat(5,1fr)}.k4{grid-template-columns:repeat(4,1fr)}.k3{grid-template-columns:repeat(3,1fr)}
.kC{background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:14px 16px;position:relative;overflow:hidden;}
.kC::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;border-radius:12px 12px 0 0;}
.cR::before{background:#e53e3e}.cG::before{background:#38a169}.cB::before{background:#3182ce}.cA::before{background:#d69e2e}.cP::before{background:#805ad5}.cT::before{background:#2c7a7b}
.kL{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.06em;}
.kV{font-size:24px;font-weight:800;color:#fff;line-height:1.1;margin:3px 0;font-family:'DM Mono',monospace!important;}
.kS{font-size:10px;color:#666;}.kD{font-size:10px;font-weight:600;margin-top:3px;}
.up{color:#68d391}.dn{color:#fc8181}.wn{color:#f6e05e}

/* ── TABS — white text, visible ── */
[data-testid="stTabs"] button[role="tab"]{font-size:12px!important;font-weight:600!important;color:#aaa!important;}
[data-testid="stTabs"] button[role="tab"]:hover{color:#fff!important;}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#fff!important;border-bottom:2px solid #e53e3e!important;}

/* ── FILTERS — white labels and values ── */
[data-testid="stSelectbox"] label{font-size:10px!important;color:#ccc!important;font-weight:700!important;text-transform:uppercase;}
[data-testid="stSelectbox"]>div>div{background:#13131a!important;border:1px solid rgba(255,255,255,.15)!important;border-radius:8px!important;color:#fff!important;font-size:13px!important;}

/* ── METRICS ── */
[data-testid="stMetric"]{background:#13131a!important;border-radius:10px!important;padding:12px!important;border:1px solid rgba(255,255,255,.07)!important;}
[data-testid="stMetricValue"]{font-size:22px!important;font-weight:800!important;color:#fff!important;font-family:'DM Mono',monospace!important;}
[data-testid="stMetricLabel"]{font-size:10px!important;color:#aaa!important;text-transform:uppercase;}
[data-testid="stMetricDelta"]{font-size:11px!important;}

/* ── TABLES ── */
.zT{width:100%;border-collapse:collapse;font-size:12px;}
.zT th{text-align:left;padding:8px 12px;font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid rgba(255,255,255,.07);}
.zT td{padding:8px 12px;color:#ccc;border-bottom:1px solid rgba(255,255,255,.03);}
.zT tr:hover td{background:rgba(255,255,255,.02);}
.mn{font-family:'DM Mono',monospace!important;font-size:11px;}
.pg{background:rgba(56,161,105,.15);color:#68d391;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.pr{background:rgba(229,62,62,.15);color:#fc8181;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.pa{background:rgba(214,158,46,.15);color:#f6e05e;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.info-box{font-size:12px;color:#888;background:rgba(255,255,255,.03);padding:10px 14px;border-radius:8px;border-left:3px solid #444;margin:4px 0;}

/* ── PIPELINE label fix — white text ── */
.pip-label{font-size:10px;color:#aaa !important;text-transform:uppercase;letter-spacing:.05em;margin-top:2px;}

/* ── CHATBOT — compact, collapsible ── */
.buddy-wrap{background:#13131a;border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:10px 16px;margin-top:12px;}
.buddy-header{display:flex;align-items:center;gap:8px;margin-bottom:6px;}
.buddy-icon{width:24px;height:24px;background:linear-gradient(135deg,#e53e3e,#fc4f4f);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:900;color:white;}
.buddy-title{font-size:12px;font-weight:700;color:#eee;}
.buddy-status{font-size:9px;color:#38a169;}

/* Shrink chat messages */
[data-testid="stChatMessage"]{padding:6px 10px!important;margin:2px 0!important;}
[data-testid="stChatMessageContent"] p{font-size:12px!important;line-height:1.4!important;}
[data-testid="stChatInput"]{margin-top:4px!important;}
[data-testid="stChatInput"] textarea{font-size:12px!important;padding:8px 12px!important;min-height:36px!important;}
</style>""", unsafe_allow_html=True)

ts = datetime.now().strftime("%d %b %Y %H:%M")

# Zetwerk logo — embedded as base64 so it works on Streamlit Cloud
_LOGO_B64 = "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"
_logo_src = f"data:image/png;base64,{_LOGO_B64}"

# Spinning loader shown on first render, hides after 1.5s
st.markdown(f"""
<div id="zetwerk-loader">
  {'<img class="loader-logo" src="'+_logo_src+'" alt="Zetwerk"/>' if _logo_src else '<div class="loader-logo" style="background:linear-gradient(135deg,#1e3a7a,#2d5dbf);display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:900;color:white;border-radius:18px;">Z</div>'}
  <div class="loader-title">CAT-2 · Zetwerk</div>
  <div class="loader-sub">Central Procurement Team</div>
</div>

<div class="zN"><div class="zNL">
  <div class="zLogo">{'<img src="'+_logo_src+'" alt="Zetwerk" style="width:36px;height:36px;object-fit:cover;border-radius:8px;"/>' if _logo_src else '<div style="width:36px;height:36px;background:linear-gradient(135deg,#1e3a7a,#2d5dbf);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:900;color:white;">Z</div>'}</div>
  <div>
    <div class="zB">CAT-2 · Zetwerk</div>
    <div class="zS">Central Procurement Team · FY 2026-27</div>
  </div>
</div>
<div class="zR"><div class="zL"><div class="zD"></div>Live · {ts}</div><div class="zP">FY 2026-27</div></div>
</div>""", unsafe_allow_html=True)

if df_raw.empty:
    st.error(f"Could not load sheet: {po_err}")
    st.stop()

# Column refs
C_BU      = 'BU'
C_PR_DT   = fc(df_raw,'pr','dt')
C_REV_PR  = fc(df_raw,'rev','pr')
C_NFA_DT  = fc(df_raw,'nfa','dt')
C_NFA_APP = fc(df_raw,'nfa','app')
C_PO_DT   = fc(df_raw,'po','dt') or fc(df_raw,'po dt')
C_PO_VAL  = fc(df_raw,'po','basic','value')
C_SAV     = fc(df_raw,'savings','value') or fc(df_raw,'saving')
C_SAV_PCT = fc(df_raw,'saving','%')
C_TAT     = fc(df_raw,'pr','po','tat')
# Supplier type: prefer _SupplierType (col AO, reliable) over col O (VLOOKUP, often None)
C_STYPE   = next((c for c in df_raw.columns if '_suppliertype' in c.lower().replace(' ','')),
            fc(df_raw,'supplier','type'))
C_PAY     = fc(df_raw,'payment','term')
C_MFC_DT  = fc(df_raw,'mfc','dt')
C_MFC_DAYS= fc(df_raw,'delivery time') or fc(df_raw,'mfc','days')
C_DELIVERED=fc(df_raw,'delivered','value') or fc(df_raw,'po delivered')
C_YTD     = fc(df_raw,'yet to be') or fc(df_raw,'yet to','deliver')
C_OTIF    = fc(df_raw,'otif')
C_DEL_ST  = fc(df_raw,'delivery','status')
C_CUR_ST  = fc(df_raw,'current','status')
C_SUPPLIER= fc(df_raw,'supplier','name')
C_CAT     = 'Category' if 'Category' in df_raw.columns else None
C_HANDLER = fc(df_raw,'handled by')
C_ITEMS   = 'Items' if 'Items' in df_raw.columns else None

# Filters — 6 columns: BU, Category, Buyer, Supplier Type, Month, Refresh
c1,c2,c3,c4,c5,c6 = st.columns([1,1,1,1,1,.25])
with c1:
    bu_opts = ['All']+sorted(df_raw[C_BU].astype(str).str.strip().replace({'':'nan'}).pipe(lambda s: s[s.ne('nan')]).unique().tolist())
    sel_bu = st.selectbox('BU', bu_opts, key='f_bu')
with c2:
    cat_opts = ['All']+(sorted(df_raw[C_CAT].dropna().unique().tolist()) if C_CAT else [])
    sel_cat = st.selectbox('Category', cat_opts, key='f_cat')
with c3:
    buyer_opts = ['All']+(sorted(df_raw[C_HANDLER].dropna().unique().tolist()) if C_HANDLER else [])
    sel_buyer = st.selectbox('Buyer', buyer_opts, key='f_buyer')
with c4:
    stype_opts = ['All']
    if C_STYPE and C_STYPE in df_raw.columns:
        stype_opts += sorted([s for s in df_raw[C_STYPE].dropna().unique() if str(s).strip() not in ('','nan','None')])
    sel_st = st.selectbox('Supplier Type', stype_opts, key='f_st')
with c5:
    month_opts = ['All']
    if C_PO_DT and C_PO_DT in df_raw.columns:
        po_dates_all = pd.to_datetime(df_raw[C_PO_DT], errors='coerce')
        months_avail = (po_dates_all.dropna()
                        .dt.to_period('M').sort_values().unique().astype(str).tolist())
        month_opts += months_avail
    sel_month = st.selectbox('PO Month', month_opts, key='f_month')
with c6:
    st.markdown("<div style='padding-top:22px;text-align:center;'>", unsafe_allow_html=True)
    if st.button("⟳", help="Refresh data"): st.cache_data.clear(); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ── Apply BU / Category / Buyer / Supplier Type filters to ALL rows ──────────
# Month filter applies ONLY to PO rows (rows with PO date filled).
# PR counts and unclosed counts are NOT affected by month filter.
dff = df_raw.copy()
if sel_bu    != 'All': dff = dff[dff[C_BU]==sel_bu]
if sel_cat   != 'All' and C_CAT: dff = dff[dff[C_CAT]==sel_cat]
if sel_buyer != 'All' and C_HANDLER: dff = dff[dff[C_HANDLER]==sel_buyer]
if sel_st    != 'All' and C_STYPE and C_STYPE in dff.columns: dff = dff[dff[C_STYPE]==sel_st]

# Compute PR/unclosed subsets BEFORE month filter (PRs don't have PO dates)
has_pr_all = pd.notna(dff[C_PR_DT]) if C_PR_DT else pd.Series(False, index=dff.index)
has_po_all = pd.notna(dff[C_PO_DT]) if C_PO_DT else pd.Series(False, index=dff.index)
df_prs      = dff[has_pr_all].copy()
df_unclosed = dff[has_pr_all & ~has_po_all].copy()
n_prs       = len(df_prs)
n_unclosed  = len(df_unclosed)

# Now apply month filter — ONLY to PO rows
dff_po_base = dff[has_po_all].copy()
if sel_month != 'All' and C_PO_DT and C_PO_DT in dff_po_base.columns:
    po_dt_s = pd.to_datetime(dff_po_base[C_PO_DT], errors='coerce')
    dff_po_base = dff_po_base[po_dt_s.dt.to_period('M').astype(str) == sel_month]

df_pos  = dff_po_base.copy()
n_pos   = len(df_pos)

def ssum(df,col):
    if col and col in df.columns:
        return float(pd.to_numeric(df[col],errors='coerce').fillna(0).sum())
    return 0.0

spend   = ssum(df_pos, C_PO_VAL)/1e7
savings = ssum(df_pos, C_SAV)/1e7
sav_pct = (savings/spend*100) if spend>0 else 0.0

# TAT: valid range only
avg_tat = 0.0
if C_TAT and C_TAT in df_pos.columns:
    tv = pd.to_numeric(df_pos[C_TAT],errors='coerce')
    tv = tv[(tv>0)&(tv<1000)].dropna()
    avg_tat = float(tv.mean()) if len(tv)>0 else 0.0

# Delivery status
if C_DEL_ST and C_DEL_ST in df_pos.columns:
    ds_l = df_pos[C_DEL_ST].fillna('').astype(str).str.strip().str.lower()
    df_completed = df_pos[ds_l.isin(['completed','shortclose'])]
    df_ongoing   = df_pos[ds_l=='ongoing']
    n_completed, n_ongoing = len(df_completed), len(df_ongoing)
else:
    df_completed = pd.DataFrame(columns=df_pos.columns)
    df_ongoing   = df_pos.copy()
    n_completed, n_ongoing = 0, n_pos

# OTIF
otif_pct, otif_n = 0.0, 0
if C_OTIF and C_OTIF in df_completed.columns and len(df_completed)>0:
    ov = pd.to_numeric(df_completed[C_OTIF].astype(str).str.replace('%',''), errors='coerce').dropna()
    if len(ov)>0 and ov.max()>2: ov = ov/100
    ov = ov[ov>0]; otif_n = len(ov)
    if otif_n>0: otif_pct = float((ov<=1.05).sum()/otif_n*100)

# NVD — only count rows where supplier type is filled (not None/blank)
nv_n, nv_pct = 0, 0.0
if C_STYPE and C_STYPE in df_pos.columns:
    stype_s = df_pos[C_STYPE].astype(str).str.strip().replace({'nan':'','None':''})
    stype_filled_mask = stype_s.ne('')
    n_stype_filled = int(stype_filled_mask.sum())
    nv_mask = stype_s.str.upper().str.contains('NV', na=False)
    nv_n    = int(nv_mask.sum())
    nv_pct  = nv_n / n_stype_filled * 100 if n_stype_filled > 0 else 0.0

# WC Score
wc_score = None
if '_PayScore' in df_pos.columns and C_PO_VAL and C_PO_VAL in df_pos.columns:
    wcs = df_pos[df_pos['_PayScore'].notna()].copy()
    pv  = pd.to_numeric(wcs[C_PO_VAL],errors='coerce').fillna(0)
    ok  = pv>0
    if ok.sum()>0: wc_score = float((wcs['_PayScore']*pv)[ok].sum()/pv[ok].sum())

cn = dff[C_CAT].nunique() if C_CAT and C_CAT in dff.columns else 0
sn = dff[C_SUPPLIER].nunique() if C_SUPPLIER and C_SUPPLIER in dff.columns else 0

DK = dict(plot_bgcolor='rgba(0,0,0,0)',paper_bgcolor='rgba(0,0,0,0)',
    font=dict(family='DM Sans',color='#ddd',size=12),
    xaxis=dict(gridcolor='rgba(255,255,255,.08)',tickcolor='#aaa',linecolor='#444',tickfont=dict(color='#ddd',size=11)),
    yaxis=dict(gridcolor='rgba(255,255,255,.08)',tickcolor='#aaa',linecolor='#444',tickfont=dict(color='#ddd',size=11)),
    margin=dict(l=8,r=8,t=36,b=8))
RED,GRN,AMB,BLU,PUR='#e53e3e','#38a169','#d69e2e','#3182ce','#805ad5'

def kc(val,lbl,sub='',delta='',dc='',cc='cB'):
    d=f'<div class="kD {dc}">{delta}</div>' if delta else ''
    return f'<div class="kC {cc}"><div class="kL">{lbl}</div><div class="kV">{val}</div><div class="kS">{sub}</div>{d}</div>'

def apply_dk(fig, **kw):
    fig.update_layout(**DK, **kw); return fig

t1,t2,t3,t4,t5,t6,t7,t8 = st.tabs(["Overview","Spend & Savings","TAT & OTIF","Working Capital","New Vendor Dev","MFC Tracker","Ongoing POs","PR-PO Unclosed"])

# ════ TAB 1 — OVERVIEW ═══════════════════════════════════════
with t1:
    wc_v  = f"{wc_score:.2f}" if wc_score else "—"
    wc_d  = ("Above 4.5" if wc_score>=4.5 else "Below 4.5") if wc_score else "No data"
    wc_dc = "up" if wc_score and wc_score>=4.5 else "wn"
    wc_cc = "cG" if wc_score and wc_score>=4.5 else ("cR" if wc_score else "cP")

    st.markdown(f"""<div class="kG k5">
{kc(str(n_pos),"POs Placed",f"{n_prs} PRs · {n_unclosed} unclosed","","","cB")}
{kc(f"Rs {spend:.2f} Cr","Total Spend","PO Basic Value","","","cG")}
{kc(f"Rs {savings:.2f} Cr","Savings",f"{sav_pct:.1f}% of spend","≥4.5% ✓" if sav_pct>=4.5 else "<4.5%","up" if sav_pct>=4.5 else "wn","cG" if sav_pct>=4.5 else "cA")}
{kc(f"{avg_tat:.0f}d" if avg_tat>0 else "—","Avg PR-PO TAT","Target: 90 days","On track" if 0<avg_tat<=90 else ("Above target" if avg_tat>90 else "No data"),"up" if 0<avg_tat<=90 else "dn","cG" if 0<avg_tat<=90 else ("cR" if avg_tat>90 else "cP"))}
{kc(wc_v,"WC Score","Target: 4.5",wc_d,wc_dc,wc_cc)}
</div><div class="kG k4" style="margin-top:8px;">
{kc(f"{otif_pct:.1f}%" if otif_n>0 else "—","OTIF",f"{otif_n} completed POs" if otif_n>0 else "No completions yet","≥75%" if otif_pct>=75 else ("<75%" if otif_n>0 else ""),"up" if otif_pct>=75 else "dn","cG" if otif_pct>=75 else ("cR" if otif_n>0 else "cP"))}
{kc(f"{nv_pct:.1f}%","New Vendor Dev",f"{nv_n} NV of {n_pos} POs","10–15% target","up" if 10<=nv_pct<=15 else "wn","cG" if 10<=nv_pct<=15 else "cA")}
{kc(str(cn),"Categories","Unique","","","cT")}
{kc(str(sn),"Suppliers","Unique","","","cP")}
</div>""", unsafe_allow_html=True)

    c1,c2 = st.columns(2)
    with c1:
        if C_PO_VAL and len(df_pos)>0:
            bg = df_pos.groupby(C_BU).agg(sp=(C_PO_VAL,'sum'),sv=(C_SAV,'sum') if C_SAV else (C_PO_VAL,'count')).reset_index()
            bg['sc']=bg['sp']/1e7; bg['svc']=bg['sv']/1e7 if C_SAV else 0
            fig=go.Figure()
            fig.add_trace(go.Bar(name='Spend',x=bg[C_BU],y=bg['sc'],marker_color=RED,marker_line_width=0))
            if C_SAV: fig.add_trace(go.Bar(name='Savings',x=bg[C_BU],y=bg['svc'],marker_color='rgba(56,161,105,.7)',marker_line_width=0))
            apply_dk(fig,height=280,barmode='group',title_text='Spend & Savings by BU (Rs Cr)',
                legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#ddd',size=11)))
            st.plotly_chart(fig, width='stretch')
        else:
            st.markdown('<div class="info-box">No POs placed yet.</div>', unsafe_allow_html=True)
    with c2:
        if C_CAT and C_CAT in dff.columns:
            if C_PO_VAL and len(df_pos)>0:
                cg=df_pos.groupby(C_CAT)[C_PO_VAL].sum().sort_values(ascending=False).head(10).reset_index()
                cg['v']=cg[C_PO_VAL]/1e7; lbl='Spend by Category (Rs Cr)'; txt=cg['v'].apply(lambda x:f'Rs {x:.2f}Cr')
            else:
                cg=dff[C_CAT].value_counts().head(10).reset_index(); cg.columns=[C_CAT,'v']
                lbl='PRs by Category'; txt=cg['v'].astype(str)
            fig2=go.Figure(go.Bar(y=cg[C_CAT],x=cg['v'],orientation='h',marker_color=RED,marker_line_width=0,
                text=txt,textposition='outside',textfont=dict(color='#ddd',size=10)))
            apply_dk(fig2,height=280,title_text=lbl,showlegend=False)
            st.plotly_chart(fig2, width='stretch')

    st.markdown("#### Procurement Pipeline")
    c1,c2,c3,c4,c5 = st.columns(5)
    nfa_sub = int(dff[C_NFA_DT].notna().sum()) if C_NFA_DT and C_NFA_DT in dff.columns else 0
    nfa_app = int(dff[C_NFA_APP].notna().sum()) if C_NFA_APP and C_NFA_APP in dff.columns else 0
    for col_w,lbl2,cnt2,clr2 in [(c1,"PRs Raised",n_prs,BLU),(c2,"NFA Submitted",nfa_sub,PUR),(c3,"NFA Approved",nfa_app,AMB),(c4,"POs Placed",n_pos,GRN),(c5,"Delivered",n_completed,'#2c7a7b')]:
        with col_w:
            st.markdown(f'<div class="kC" style="border-top:2px solid {clr2};text-align:center;"><div class="kL">{lbl2}</div><div class="kV" style="font-size:28px;color:{clr2};">{cnt2}</div></div>', unsafe_allow_html=True)

# ════ TAB 2 — SPEND & SAVINGS ════════════════════════════════
with t2:
    c1,c2,c3,c4=st.columns(4)
    with c1: st.metric("Total Spend",f"Rs {spend:.2f} Cr")
    with c2: st.metric("Total Savings",f"Rs {savings:.2f} Cr",f"{sav_pct:.1f}%")
    with c3: st.metric("vs Target 4.5%",f"{sav_pct:.1f}%",f"{sav_pct-4.5:+.1f}pp")
    with c4: st.metric("POs / PRs",f"{n_pos} / {n_prs}")
    c1,c2=st.columns(2)
    with c1:
        if C_PO_DT and C_PO_VAL and len(df_pos)>0:
            tmp=df_pos.copy(); tmp['_m']=pd.to_datetime(tmp[C_PO_DT],errors='coerce').dt.to_period('M').astype(str)
            mo=tmp.groupby('_m').agg(sp=(C_PO_VAL,'sum'),sv=(C_SAV,'sum') if C_SAV else (C_PO_VAL,'count')).reset_index().sort_values('_m')
            mo['sc']=mo['sp']/1e7; mo['svc']=mo['sv']/1e7 if C_SAV else 0
            fig3=go.Figure()
            fig3.add_trace(go.Bar(name='Spend',x=mo['_m'],y=mo['sc'],marker_color='rgba(229,62,62,.3)',marker_line_width=0))
            if C_SAV: fig3.add_trace(go.Scatter(name='Savings',x=mo['_m'],y=mo['svc'],line=dict(color=GRN,width=2.5),mode='lines+markers',marker=dict(size=5),yaxis='y2'))
            dk2={k:v for k,v in DK.items() if k!='yaxis'}
            fig3.update_layout(**dk2,height=300,title_text='Monthly PO Trend',
                yaxis=dict(title='Spend Cr',gridcolor='rgba(255,255,255,.04)'),
                yaxis2=dict(title='Savings Cr',overlaying='y',side='right'),
                legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#ddd',size=11)))
            st.plotly_chart(fig3, width='stretch')
        else:
            st.markdown('<div class="info-box">Monthly trend will appear once PO dates are entered.</div>', unsafe_allow_html=True)
    with c2:
        if C_PO_VAL and len(df_pos)>0:
            bs=df_pos.groupby(C_BU).agg(n=(C_PO_VAL,'count'),sp=(C_PO_VAL,'sum'),sv=(C_SAV,'sum') if C_SAV else (C_PO_VAL,'count')).reset_index()
            bs['pct']=(bs['sv']/bs['sp']*100).fillna(0) if C_SAV else 0
            rh=""
            for _,r in bs.sort_values('sp',ascending=False).iterrows():
                pill="pg" if r['pct']>=4.5 else ("pr" if r['pct']<0 else "pa")
                sv_s=f"Rs {r['sv']/1e7:.2f}Cr" if C_SAV else "—"
                rh+=(f'<tr><td><b style="color:#eee">{r[C_BU]}</b></td><td class="mn">Rs {r["sp"]/1e7:.2f}Cr</td>'
                     f'<td class="mn">{sv_s}</td><td><span class="{pill}">{r["pct"]:.1f}%</span></td><td class="mn">{int(r["n"])}</td></tr>')
            st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:6px 0;"><table class="zT"><thead><tr><th>BU</th><th>Spend</th><th>Savings</th><th>%</th><th>POs</th></tr></thead><tbody>{rh}</tbody></table></div>', unsafe_allow_html=True)
    if C_SAV and C_PO_VAL and C_CAT and len(df_pos)>0:
        cg=df_pos.groupby(C_CAT).agg(sp=(C_PO_VAL,'sum'),sv=(C_SAV,'sum')).reset_index()
        cg['pct']=(cg['sv']/cg['sp']*100).fillna(0); cg=cg[cg['sp']>0].sort_values('pct',ascending=False)
        if len(cg)>0:
            fig_c=go.Figure(go.Bar(x=cg[C_CAT],y=cg['pct'],marker_color=[GRN if v>=4.5 else RED for v in cg['pct']],marker_line_width=0,text=cg['pct'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#ddd',size=10)))
            fig_c.add_hline(y=4.5,line_dash='dash',line_color=AMB,annotation_text='4.5%',annotation_font_color=AMB)
            apply_dk(fig_c,height=260,title_text='Savings % by Category',showlegend=False)
            st.plotly_chart(fig_c, width='stretch')

# ════ TAB 3 — TAT & OTIF ════════════════════════════════════
with t3:
    c1,c2,c3,c4=st.columns(4)
    with c1: st.metric("Avg TAT",f"{avg_tat:.0f}d" if avg_tat>0 else "—",f"{avg_tat-90:+.0f}d vs 90d" if avg_tat>0 else "No valid TAT yet")
    with c2: st.metric("OTIF",f"{otif_pct:.1f}%" if otif_n>0 else "—",f"{otif_n} completed POs" if otif_n>0 else "Awaiting completions")
    with c3: st.metric("Completed POs",str(n_completed))
    with c4: st.metric("Ongoing POs",str(n_ongoing))
    c1,c2=st.columns(2)
    with c1:
        if C_TAT and len(df_pos)>0:
            tat_s=pd.to_numeric(df_pos[C_TAT],errors='coerce')
            tat_s=tat_s[(tat_s>0)&(tat_s<1000)]
            tf=df_pos[[C_BU]].copy(); tf['_t']=tat_s; tf=tf.dropna(subset=['_t'])
            if len(tf)>0:
                bt=tf.groupby(C_BU)['_t'].mean().reset_index(); bt.columns=['BU','TAT']
                fig4=go.Figure(go.Bar(x=bt['BU'],y=bt['TAT'],marker_color=[GRN if v<=90 else RED for v in bt['TAT']],marker_line_width=0,text=bt['TAT'].apply(lambda x:f'{x:.0f}d'),textposition='outside',textfont=dict(color='#ddd',size=11)))
                fig4.add_hline(y=90,line_dash='dash',line_color=AMB,annotation_text='90d',annotation_font_color=AMB)
                apply_dk(fig4,height=280,title_text='Avg TAT by BU (days)',showlegend=False)
                st.plotly_chart(fig4, width='stretch')
            else:
                st.markdown('<div class="info-box">TAT available once POs with valid PR dates are placed. T&D BU POs have no PR date so TAT is excluded.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="info-box">TAT will appear once POs are placed.</div>', unsafe_allow_html=True)
    with c2:
        if C_TAT and len(df_pos)>0:
            tv=pd.to_numeric(df_pos[C_TAT],errors='coerce'); tv=tv[(tv>0)&(tv<1000)].dropna()
            if len(tv)>=2:
                fig_h=go.Figure(go.Histogram(x=tv,nbinsx=15,marker_color='rgba(49,130,206,.6)',marker_line_color='rgba(49,130,206,.9)',marker_line_width=1))
                fig_h.add_vline(x=90,line_dash='dash',line_color=AMB,annotation_text='90d',annotation_font_color=AMB)
                apply_dk(fig_h,height=280,title_text='TAT Distribution',showlegend=False)
                st.plotly_chart(fig_h, width='stretch')
        elif C_PR_DT and len(df_unclosed)>0:
            today=pd.Timestamp(date.today())
            ages=(today-pd.to_datetime(df_unclosed[C_PR_DT],errors='coerce')).dt.days.dropna()
            ages=ages[ages>=0]
            if len(ages)>=2:
                fig_a=go.Figure(go.Histogram(x=ages,nbinsx=12,marker_color='rgba(214,158,46,.6)',marker_line_color=AMB,marker_line_width=1))
                fig_a.add_vline(x=90,line_dash='dash',line_color=RED,annotation_text='90d',annotation_font_color=RED)
                apply_dk(fig_a,height=280,title_text='Unclosed PR Age (days)',showlegend=False)
                st.plotly_chart(fig_a, width='stretch')
    if n_completed>0 and C_OTIF and C_OTIF in df_completed.columns:
        rows=[]
        for bu in df_completed[C_BU].dropna().unique():
            s=df_completed[df_completed[C_BU]==bu]
            v=pd.to_numeric(s[C_OTIF].astype(str).str.replace('%',''),errors='coerce').dropna()
            if len(v)>0 and v.max()>2: v=v/100
            v=v[v>0]
            if len(v): rows.append({'BU':bu,'OTIF%':float((v<=1.05).sum()/len(v)*100)})
        if rows:
            bo=pd.DataFrame(rows)
            fig5=go.Figure(go.Bar(x=bo['BU'],y=bo['OTIF%'],marker_color=[GRN if v>=75 else RED for v in bo['OTIF%']],marker_line_width=0,text=bo['OTIF%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#ddd',size=11)))
            fig5.add_hline(y=75,line_dash='dash',line_color=AMB,annotation_text='75%',annotation_font_color=AMB)
            apply_dk(fig5,height=260,title_text='OTIF % by BU',showlegend=False,yaxis_range=[0,115])
            st.plotly_chart(fig5, width='stretch')
    else:
        st.markdown('<div class="info-box" style="margin-top:12px;">OTIF calculated once Delivery Status = Completed. All current POs are Ongoing.</div>', unsafe_allow_html=True)

# ════ TAB 4 — WORKING CAPITAL ════════════════════════════════
with t4:
    if '_PayScore' in df_pos.columns and C_PAY and len(df_pos)>0:
        wcs=df_pos[df_pos['_PayScore'].notna()].copy()
        pv_all = pd.to_numeric(df_pos[C_PO_VAL],errors='coerce').fillna(0) if C_PO_VAL else pd.Series(0,index=df_pos.index)
        pv_wcs = pd.to_numeric(wcs[C_PO_VAL],errors='coerce').fillna(0) if C_PO_VAL else pd.Series(dtype=float)
        n_terms = len(wcs)
        n_high  = int((wcs['_PayScore']>=5).sum())

        # Advance value vs total
        adv_mask = wcs['_PayScore'] < 0
        adv_val  = float(pv_wcs[adv_mask.values].sum()) / 1e7
        total_val_wcs = float(pv_wcs.sum()) / 1e7
        adv_pct  = adv_val / total_val_wcs * 100 if total_val_wcs > 0 else 0

        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("WC Score", f"{wc_score:.2f}" if wc_score else "—",
                            f"{'≥4.5 ✓' if wc_score and wc_score>=4.5 else '<4.5 ✗'}")
        with c2: st.metric("POs with Terms", f"{n_terms}/{n_pos}")
        with c3: st.metric("Advance Payment Value",
                            f"Rs {adv_val:.2f} Cr",
                            f"{adv_pct:.1f}% of Rs {total_val_wcs:.2f} Cr")
        with c4: st.metric("High WC (≥5)", str(n_high))
        c1,c2=st.columns(2)
        with c1:
            pt=df_pos[C_PAY].dropna().astype(str).str.strip(); pt=pt[pt.ne('')].value_counts().head(12).reset_index(); pt.columns=['Term','Count']
            if len(pt):
                fig_pt=go.Figure(go.Bar(y=pt['Term'],x=pt['Count'],orientation='h',marker_color=BLU,marker_line_width=0,text=pt['Count'],textposition='outside',textfont=dict(color='#ddd',size=10)))
                apply_dk(fig_pt,height=340,title_text='Payment Terms Distribution',showlegend=False)
                st.plotly_chart(fig_pt, width='stretch')
        with c2:
            sv=wcs['_PayScore'].value_counts().sort_index().reset_index(); sv.columns=['Score','Count']
            lm={-2:'Advance',0:'On Dispatch/PDC',1:'IBC 90',2:'IBC 60',3:'VFS/CC15',4:'IBC 45/RXIL',5:'IFC/CC30/LC90',6:'IFC 90',7:'CC 45',8:'CC 60',10:'CC 90'}
            sv['Label']=sv['Score'].apply(lambda s:lm.get(int(s),str(s)))
            fig_sc=go.Figure(go.Bar(x=sv['Label'],y=sv['Count'],marker_color=[RED if s<0 else (AMB if s<4 else GRN) for s in sv['Score']],marker_line_width=0,text=sv['Count'],textposition='outside',textfont=dict(color='#ddd',size=10)))
            apply_dk(fig_sc,height=340,title_text='POs by WC Score Band',showlegend=False)
            st.plotly_chart(fig_sc, width='stretch')
    else:
        st.markdown('<div class="info-box">Working capital data will populate once POs with payment terms are placed.</div>', unsafe_allow_html=True)

# ════ TAB 5 — NEW VENDOR DEV ════════════════════════════════
with t5:
    if C_STYPE and C_STYPE in df_pos.columns and len(df_pos)>0:
        # Only count rows where supplier type is actually filled
        stype_filled = df_pos[C_STYPE].astype(str).str.strip().replace({'nan':'','None':''})
        df_pos_stype = df_pos[stype_filled.ne('')].copy()
        n_stype_total = len(df_pos_stype)

        avl_oem = int(df_pos_stype[C_STYPE].str.upper().str.contains('AVL OEM', na=False).sum())
        avl_trd = int(df_pos_stype[C_STYPE].str.upper().str.contains('TRADER', na=False).sum())
        nv_mask_filled = df_pos_stype[C_STYPE].astype(str).str.upper().str.contains('NV', na=False)
        nv_n_filled    = int(nv_mask_filled.sum())
        nv_pct_filled  = nv_n_filled / n_stype_total * 100 if n_stype_total > 0 else 0.0

        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("NVD %", f"{nv_pct_filled:.1f}%",
                            "On target" if 10<=nv_pct_filled<=15 else ("Below" if nv_pct_filled<10 else "Above"))
        with c2: st.metric("NV POs", str(nv_n_filled), f"of {n_stype_total} POs with type filled")
        with c3: st.metric("AVL OEM", str(avl_oem))
        with c4: st.metric("AVL Trader", str(avl_trd))
        c1,c2 = st.columns(2)
        with c1:
            nv_bu = (df_pos_stype.groupby(C_BU)
                     .apply(lambda x: pd.Series({
                         'Total': len(x),
                         'NV': int(x[C_STYPE].astype(str).str.upper().str.contains('NV',na=False).sum())
                     })).reset_index())
            nv_bu['NV%'] = (nv_bu['NV'] / nv_bu['Total'] * 100).fillna(0)
            fig8 = go.Figure(go.Bar(
                x=nv_bu[C_BU], y=nv_bu['NV%'],
                marker_color=[GRN if 10<=v<=15 else AMB for v in nv_bu['NV%']],
                marker_line_width=0,
                text=nv_bu['NV%'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#ddd', size=11)
            ))
            fig8.add_hrect(y0=10, y1=15, fillcolor='rgba(56,161,105,.06)', line_width=0)
            apply_dk(fig8, height=280, title_text='NVD % by BU (filled rows only)',
                     showlegend=False, yaxis_range=[0, max(float(nv_bu['NV%'].max())*1.3, 20)])
            st.plotly_chart(fig8, width='stretch')
        with c2:
            sv2 = df_pos_stype[C_STYPE].value_counts().reset_index()
            sv2.columns = ['Type', 'Count']
            sv2 = sv2[sv2['Type'].ne('')]
            if len(sv2):
                fp2 = go.Figure(go.Pie(
                    labels=sv2['Type'], values=sv2['Count'], hole=0.4,
                    marker_colors=[GRN, BLU, RED, PUR, AMB],
                    textfont=dict(color='white', size=11)
                ))
                fp2.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#ddd'), margin=dict(l=8,r=8,t=36,b=8),
                    title_text='Supplier Type Mix', legend=dict(font=dict(color='#ddd',size=11), bgcolor='rgba(0,0,0,0)')
                )
                st.plotly_chart(fp2, width='stretch')
    else:
        st.markdown('<div class="info-box">Supplier type data will populate once POs are placed.</div>', unsafe_allow_html=True)

# ════ TAB 6 — MFC TRACKER ═══════════════════════════════════
with t6:
    st.markdown("### MFC Delivery Tracker")
    today=pd.Timestamp(date.today())
    mfc_df=df_raw.copy()
    if sel_bu!='All': mfc_df=mfc_df[mfc_df[C_BU]==sel_bu]
    if not C_MFC_DT or C_MFC_DT not in mfc_df.columns:
        st.error(f"MFC date column not found. Cols: {[c for c in mfc_df.columns if 'mfc' in c.lower()]}")
    elif not C_MFC_DAYS or C_MFC_DAYS not in mfc_df.columns:
        st.error(f"Delivery days col not found. Cols: {[c for c in mfc_df.columns if 'deliver' in c.lower() or 'day' in c.lower()]}")
    else:
        mfc_df['_mfc']=pd.to_datetime(mfc_df[C_MFC_DT],errors='coerce')
        mfc_df['_days']=pd.to_numeric(mfc_df[C_MFC_DAYS].astype(str).str.replace(',','').str.strip(),errors='coerce')
        if C_DEL_ST and C_DEL_ST in mfc_df.columns:
            dl=mfc_df[C_DEL_ST].fillna('').astype(str).str.strip().str.lower()
            mfc_df=mfc_df[~dl.isin(['completed','shortclose'])]
        mfc_df=mfc_df.dropna(subset=['_mfc','_days']); mfc_df=mfc_df[mfc_df['_days']>0].copy()
        if mfc_df.empty:
            st.info("No ongoing POs with MFC dates and delivery days. Fill MFC Dt. (col Z) and Delivery Time from MFC (col AA).")
        else:
            mfc_df['Expected']=mfc_df['_mfc']+pd.to_timedelta(mfc_df['_days'].astype(int),unit='D')
            mfc_df['Days Left']=(mfc_df['Expected']-today).dt.days
            mfc_df['Threshold']=np.ceil(mfc_df['_days']/3).astype(int)
            def clf(r):
                if r['Days Left']<=0: return 'OVERDUE'
                if r['Days Left']<=r['Threshold']: return 'RED'
                if r['Days Left']<=30: return 'AMBER'
                return 'GREEN'
            mfc_df['Alert']=mfc_df.apply(clf,axis=1)
            cnt=mfc_df['Alert'].value_counts()
            if 'mfc_f' not in st.session_state: st.session_state.mfc_f='ALL'
            cols5=st.columns(5)
            for col_w,lbl3,key3,count3,clr3 in [(cols5[0],'GREEN','GREEN',int(cnt.get('GREEN',0)),'#38a169'),(cols5[1],'AMBER','AMBER',int(cnt.get('AMBER',0)),'#d69e2e'),(cols5[2],'RED','RED',int(cnt.get('RED',0)),'#e53e3e'),(cols5[3],'OVERDUE','OVERDUE',int(cnt.get('OVERDUE',0)),'#ff4444'),(cols5[4],'ALL','ALL',len(mfc_df),'#666')]:
                sel3=st.session_state.mfc_f==key3
                with col_w:
                    st.markdown(f'<div style="background:{"rgba(255,255,255,.08)" if sel3 else "rgba(255,255,255,.02)"};border:{"2" if sel3 else "1"}px solid {clr3};border-radius:10px;padding:10px;text-align:center;"><div style="font-size:9px;font-weight:700;color:{clr3};text-transform:uppercase;">{lbl3}</div><div style="font-size:28px;font-weight:800;color:{"#fff" if sel3 else clr3};font-family:DM Mono,monospace;">{count3}</div></div>', unsafe_allow_html=True)
                    if st.button(f"{'● ' if sel3 else ''}{lbl3}",key=f"mfc_{key3}",use_container_width=True):
                        st.session_state.mfc_f=key3 if not sel3 else 'ALL'; st.rerun()
            disp=mfc_df if st.session_state.mfc_f=='ALL' else mfc_df[mfc_df['Alert']==st.session_state.mfc_f]
            show=[c for c in ['SN',C_BU,'Project Name',C_ITEMS,C_CAT,C_SUPPLIER,C_HANDLER,'PO/OD Ref.'] if c and c in disp.columns]+['_mfc','_days','Expected','Days Left','Alert']
            ds=disp[[c for c in show if c in disp.columns]].copy().rename(columns={'_mfc':'MFC Date','_days':'Del Days'})
            ds['MFC Date']=ds['MFC Date'].dt.strftime('%d-%b-%Y'); ds['Expected']=ds['Expected'].dt.strftime('%d-%b-%Y')
            ast={'OVERDUE':'background:#2a0000;color:#ff9999;font-weight:700;','RED':'background:#1a0000;color:#ff6666;font-weight:700;','AMBER':'background:#1a1000;color:#ffcc66;','GREEN':'background:#001a00;color:#66cc66;'}
            def hl_m(row): s=ast.get(row.get('Alert',''),'')+';font-size:13px;'; return [s]*len(row)
            st.markdown(f"**{len(ds)} POs**")
            st.dataframe(ds.style.apply(hl_m,axis=1),width='stretch',height=min(40*len(ds)+60,700))

# ════ TAB 7 — ONGOING POs ════════════════════════════════════
with t7:
    if df_ong.empty:
        st.info(f"Ongoing sheet: {ong_err}")
    else:
        oc_pv=fc(df_ong,'po value'); oc_ytd=fc(df_ong,'yet to'); oc_sav=fc(df_ong,'realized','saving')
        oc_del=fc(df_ong,'delivered in'); oc_bu='BU' if 'BU' in df_ong.columns else None
        n_still=int((pd.to_numeric(df_ong[oc_ytd],errors='coerce').fillna(0)>0).sum()) if oc_ytd else 0
        n_done =int((pd.to_numeric(df_ong[oc_ytd],errors='coerce').fillna(0)<=0).sum()) if oc_ytd else 0
        tot_pv=ssum(df_ong,oc_pv)/1e7; tot_ytd=ssum(df_ong,oc_ytd)/1e7
        tot_del=ssum(df_ong,oc_del)/1e7; tot_sav=ssum(df_ong,oc_sav)/1e7
        c1,c2,c3,c4=st.columns(4)
        with c1: st.metric("Carry-Fwd POs",str(len(df_ong)),f"Ongoing:{n_still} | Delivered:{n_done}")
        with c2: st.metric("PO Value (incl GST)",f"Rs {tot_pv:.2f} Cr")
        with c3: st.metric("Yet to Deliver",f"Rs {tot_ytd:.2f} Cr",f"Rs {tot_pv-tot_ytd:.2f} Cr delivered")
        with c4: st.metric("Realized Savings FY27",f"Rs {tot_sav:.4f} Cr" if tot_sav else "—")
        bu_o2=['All']+(sorted(df_ong[oc_bu].dropna().unique().tolist()) if oc_bu else [])
        sel_bu_o=st.selectbox('BU',bu_o2,key='ong_bu')
        dfo=df_ong[df_ong[oc_bu]==sel_bu_o].copy() if sel_bu_o!='All' and oc_bu else df_ong.copy()
        if oc_bu and oc_pv and oc_ytd and len(dfo)>0:
            bg2=dfo.groupby(oc_bu).agg(n=(oc_pv,'count'),pv=(oc_pv,'sum'),yt=(oc_ytd,'sum')).reset_index()
            if oc_sav: bg2['sv']=dfo.groupby(oc_bu)[oc_sav].sum().values
            rh2=""
            for _,r in bg2.sort_values('pv',ascending=False).iterrows():
                rem=float(r['yt']/r['pv']*100) if r['pv']>0 else 0
                pill="pr" if rem>70 else ("pa" if rem>30 else "pg")
                sv_s=f"Rs {r['sv']/1e7:.4f}Cr" if oc_sav and 'sv' in bg2.columns else "—"
                rh2+=(f'<tr><td><b style="color:#eee">{r[oc_bu]}</b></td><td class="mn">{int(r["n"])}</td>'
                      f'<td class="mn">Rs {r["pv"]/1e7:.2f}Cr</td><td class="mn">Rs {r["yt"]/1e7:.2f}Cr</td>'
                      f'<td><span class="{pill}">{rem:.0f}%</span></td><td class="mn">{sv_s}</td></tr>')
            st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:6px 0;"><table class="zT"><thead><tr><th>BU</th><th>POs</th><th>PO Value</th><th>Yet to Deliver</th><th>Remaining%</th><th>Realized Savings</th></tr></thead><tbody>{rh2}</tbody></table></div>', unsafe_allow_html=True)
        st.markdown(f"**{len(dfo)} carry-forward POs**")
        dfo2=dfo.copy()
        for c in dfo2.columns:
            if pd.api.types.is_datetime64_any_dtype(dfo2[c]): dfo2[c]=dfo2[c].dt.strftime('%d-%b-%Y')
        st.dataframe(dfo2,width='stretch',height=min(40*len(dfo)+50,600))

# ════ TAB 8 — PR-PO UNCLOSED ════════════════════════════════
with t8:
    st.markdown("### PRs Not Yet Converted to PO")
    if df_unclosed.empty:
        st.success("✓ All PRs have been converted to POs.")
    else:
        today2=pd.Timestamp(date.today())
        uc=df_unclosed.copy()
        pr_s=pd.to_datetime(uc[C_PR_DT],errors='coerce') if C_PR_DT else pd.Series(dtype='datetime64[ns]')
        uc['_age']=(today2-pr_s).dt.days
        if C_REV_PR and C_REV_PR in uc.columns:
            uc['_rev_delay']=(pd.to_datetime(uc[C_REV_PR],errors='coerce')-pr_s).dt.days
        else:
            uc['_rev_delay']=np.nan
        n_tot=len(uc); n_rev=int(uc[C_REV_PR].notna().sum()) if C_REV_PR and C_REV_PR in uc.columns else 0
        avg_age=float(uc['_age'].dropna().mean()) if uc['_age'].notna().any() else 0
        max_age=float(uc['_age'].dropna().max()) if uc['_age'].notna().any() else 0
        n_stale=int((uc['_age']>90).sum()) if uc['_age'].notna().any() else 0
        c1,c2,c3,c4=st.columns(4)
        with c1: st.metric("Unclosed PRs",str(n_tot),f"{n_tot/n_prs*100:.0f}% of all PRs" if n_prs else "")
        with c2: st.metric("PRs Revised",str(n_rev),f"{n_tot-n_rev} unrevised")
        with c3: st.metric("Avg PR Age",f"{avg_age:.0f}d" if avg_age else "—",f"Max: {max_age:.0f}d")
        with c4: st.metric("Stale PRs (>90d)",str(n_stale),"⚠ Action needed" if n_stale else "All within 90d")
        c1,c2=st.columns(2)
        with c1: sel_bu_pr=st.selectbox('BU',['All']+sorted(uc[C_BU].dropna().unique().tolist()),key='pr_bu')
        with c2:
            cat_pr=['All']+(sorted(uc[C_CAT].dropna().unique().tolist()) if C_CAT and C_CAT in uc.columns else [])
            sel_cat_pr=st.selectbox('Category',cat_pr,key='pr_cat')
        fp=uc.copy()
        if sel_bu_pr!='All': fp=fp[fp[C_BU]==sel_bu_pr]
        if sel_cat_pr!='All' and C_CAT and C_CAT in fp.columns: fp=fp[fp[C_CAT]==sel_cat_pr]
        c1,c2=st.columns(2)
        with c1:
            bd=fp.groupby(C_BU).size().reset_index(name='Count').sort_values('Count',ascending=False)
            f_p1=go.Figure(go.Bar(x=bd[C_BU],y=bd['Count'],marker_color=RED,marker_line_width=0,text=bd['Count'],textposition='outside',textfont=dict(color='#ddd',size=11)))
            apply_dk(f_p1,height=260,title_text='Unclosed PRs by BU',showlegend=False)
            st.plotly_chart(f_p1, width='stretch')
        with c2:
            if C_CUR_ST and C_CUR_ST in fp.columns:
                sd=fp[C_CUR_ST].fillna('(Blank)').value_counts().head(10).reset_index(); sd.columns=['Status','Count']
                f_p2=go.Figure(go.Bar(y=sd['Status'],x=sd['Count'],orientation='h',marker_color=AMB,marker_line_width=0,text=sd['Count'],textposition='outside',textfont=dict(color='#ddd',size=10)))
                apply_dk(f_p2,height=260,title_text='By Current Status',showlegend=False)
                st.plotly_chart(f_p2, width='stretch')
        if fp['_age'].notna().any():
            bins=[-1,30,60,90,180,9999]; lbls=['0-30d','31-60d','61-90d','91-180d','>180d']
            clrs=[GRN,AMB,AMB,RED,'#ff0000']
            fp=fp.copy(); fp['_bucket']=pd.cut(fp['_age'],bins=bins,labels=lbls)
            ab=fp['_bucket'].value_counts().reindex(lbls,fill_value=0).reset_index(); ab.columns=['Bucket','Count']
            f_ab=go.Figure(go.Bar(x=ab['Bucket'],y=ab['Count'],marker_color=clrs,marker_line_width=0,text=ab['Count'],textposition='outside',textfont=dict(color='#ddd',size=11)))
            apply_dk(f_ab,height=240,title_text='PR Age Buckets',showlegend=False)
            st.plotly_chart(f_ab, width='stretch')
        show_c=[c for c in ['SN',C_BU,'Project Name',C_ITEMS,C_CAT,C_HANDLER,C_PR_DT,C_REV_PR,C_NFA_DT,C_NFA_APP,C_CUR_ST,'_rev_delay','_age'] if c and c in fp.columns]
        ds2=fp[show_c].copy().rename(columns={'_rev_delay':'Rev Delay(d)','_age':'PR Age(d)'})
        for c in ds2.columns:
            if pd.api.types.is_datetime64_any_dtype(ds2[c]): ds2[c]=ds2[c].dt.strftime('%d-%b-%Y')
        def hl_pr(row):
            a=row.get('PR Age(d)',0)
            if pd.notna(a) and a>90: s='background:#2a0000;color:#ff9999;font-weight:700;font-size:13px;'
            elif pd.notna(a) and a>45: s='background:#1a1000;color:#ffcc66;font-size:13px;'
            else: s='color:#ccc;font-size:13px;'
            return [s]*len(row)
        st.markdown(f"**{len(ds2)} unclosed PRs**")
        st.dataframe(ds2.style.apply(hl_pr,axis=1),width='stretch',height=min(40*len(ds2)+50,700))

# Footer
st.markdown(f'<div style="padding:12px 0;border-top:1px solid rgba(255,255,255,.04);margin-top:16px;display:flex;justify-content:space-between;"><div style="font-size:11px;color:#333;">Zetwerk CPT · CAT-2 · FY 2026-27</div><div style="font-size:10px;color:#222;font-family:DM Mono,monospace;">{ts} · TTL 60s</div></div>', unsafe_allow_html=True)

# CAT 2 BUDDY — disabled
