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
    "advance": -2, "on dispatch": 0, "pdc": 2,
    "vfs": 0,
    "ibc 15": 1, "ibc 30": 2, "ibc 45": 3, "ibc 60": 4, "ibc 90": 4,
    "rxil": 4, "lc": 4, "lc 90": 5,
    "ifc 15": 4, "ifc 30": 5, "ifc 45": 5, "ifc 60": 6, "ifc 90": 6,
    "clean credit 15": 7, "clean credit 30": 8,
    "clean credit 45": 9, "clean credit 60": 9, "clean credit 90": 10,
}

def calc_score(term):
    if not term or str(term).strip() in ('', 'nan', 'None'): return None
    t = str(term).lower()
    for k, v in SCORE_MAP.items():
        if k in t: return float(v)
    return None

# Prior-year (FY25-26) actuals from CPT CAT-2 PR-RFQ-PO-Delivery Tracker (02Apr2026).
# Used for YoY comparison in Spend & Savings tab. Values in Rs Crore.
# BU name mapping: ZAP91->ZAP 91. O&G existed last year (not this year). E&R is new this year.
PREV_YEAR = {"fy_total":{"spend":515.1473,"savings":29.5982,"pos":590},"bu_total":{"O&G":{"spend":179.3521,"savings":6.6605,"pos":271},"Water":{"spend":213.421,"savings":16.761,"pos":100},"Railways":{"spend":66.6823,"savings":5.1632,"pos":170},"ZAP91":{"spend":25.3602,"savings":0.822,"pos":33},"GFB":{"spend":26.186,"savings":0.6212,"pos":12},"T&D":{"spend":4.1456,"savings":-0.4297,"pos":4}},"bu_month":{"O&G":{"04":{"spend":1.7522,"savings":-0.009,"pos":14},"10":{"spend":12.1427,"savings":-0.0674,"pos":17},"05":{"spend":7.5541,"savings":-0.5526,"pos":11},"03":{"spend":19.2703,"savings":0.0,"pos":44},"08":{"spend":35.3137,"savings":0.2919,"pos":18},"06":{"spend":3.9379,"savings":0.4702,"pos":9},"07":{"spend":6.0857,"savings":0.2398,"pos":13},"09":{"spend":9.3671,"savings":0.8374,"pos":25},"11":{"spend":37.9937,"savings":1.3641,"pos":33},"02":{"spend":7.3299,"savings":0.0731,"pos":37},"12":{"spend":30.9806,"savings":3.7814,"pos":27},"01":{"spend":7.6242,"savings":0.2316,"pos":23}},"Water":{"04":{"spend":38.0936,"savings":6.5428,"pos":9},"05":{"spend":160.526,"savings":9.3777,"pos":17},"09":{"spend":0.6212,"savings":0.0,"pos":6},"02":{"spend":2.1535,"savings":0.0,"pos":8},"12":{"spend":3.5421,"savings":0.0,"pos":11},"03":{"spend":0.839,"savings":0.0,"pos":5},"07":{"spend":0.9438,"savings":0.1088,"pos":7},"08":{"spend":0.4906,"savings":0.2625,"pos":3},"01":{"spend":2.8774,"savings":0.0,"pos":11},"06":{"spend":2.4557,"savings":0.2011,"pos":11},"11":{"spend":0.5624,"savings":0.1181,"pos":5},"10":{"spend":0.3157,"savings":0.15,"pos":7}},"Railways":{"06":{"spend":14.277,"savings":2.4319,"pos":22},"09":{"spend":5.887,"savings":2.103,"pos":14},"04":{"spend":2.6079,"savings":0.1742,"pos":23},"07":{"spend":2.1588,"savings":-0.169,"pos":13},"05":{"spend":1.566,"savings":0.0372,"pos":15},"08":{"spend":1.6325,"savings":0.1144,"pos":7},"10":{"spend":7.7903,"savings":-1.533,"pos":12},"11":{"spend":3.0303,"savings":0.8422,"pos":12},"12":{"spend":2.1894,"savings":0.6107,"pos":9},"01":{"spend":19.763,"savings":-0.9539,"pos":16},"02":{"spend":3.0365,"savings":0.8152,"pos":14},"03":{"spend":2.7435,"savings":0.6903,"pos":13}},"ZAP91":{"10":{"spend":12.672,"savings":-0.195,"pos":5},"11":{"spend":4.7893,"savings":1.017,"pos":15},"12":{"spend":0.6162,"savings":0.0,"pos":3},"01":{"spend":1.9012,"savings":0.0,"pos":4},"02":{"spend":0.6145,"savings":0.0,"pos":1},"03":{"spend":4.767,"savings":0.0,"pos":5}},"GFB":{"01":{"spend":18.7372,"savings":0.29,"pos":4},"02":{"spend":5.52,"savings":-0.08,"pos":3},"03":{"spend":1.9288,"savings":0.4112,"pos":5}}}}

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
    import time
    last_err = ""
    for _attempt in range(3):   # retry transient Google API hiccups
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
            if len(data) < 2:
                last_err = "Sheet returned no data"; time.sleep(1.2); continue
            break
        except Exception as e:
            last_err = str(e); time.sleep(1.2)
    else:
        return pd.DataFrame(), f"Could not read sheet after 3 tries: {last_err}"
    try:
        # (the sheet sometimes has a blank/title row above the headers)
        hdr_idx = 0
        for idx in range(min(5, len(data))):
            row_vals = [str(x).strip().upper() for x in data[idx]]
            if 'BU' in row_vals and ('SN' in row_vals or 'PROJECT NAME' in row_vals):
                hdr_idx = idx
                break

        raw_h = [str(h).strip() if h else '' for h in data[hdr_idx]]
        seen = {}
        headers = []
        for h in raw_h:
            if not h: h = f'_col_{len(headers)}'
            if h in seen: seen[h] += 1; h = f'{h}_{seen[h]}'
            else: seen[h] = 0
            headers.append(h)
        df = pd.DataFrame(data[hdr_idx+1:], columns=headers)

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

        # Normalize supplier type spellings: NV OEM / NV-OEM / NV–OEM → "NV-OEM",
        # NV TRADER / NV - TRADER → "NV-TRADER", same for AVL. Collapses dropdown variants.
        def _norm_stype(v):
            if v is None: return ''
            s = str(v).strip().upper().replace('–','-').replace('—','-')
            s = ' '.join(s.split())  # collapse whitespace
            if not s or s in ('NAN','NONE'): return ''
            if 'NV' in s and 'TRADER' in s: return 'NV-TRADER'
            if 'NV' in s and 'OEM' in s:    return 'NV-OEM'
            if 'AVL' in s and 'TRADER' in s:return 'AVL-TRADER'
            if 'AVL' in s and 'OEM' in s:   return 'AVL-OEM'
            if 'CIVIL' in s:                return 'Civil Contractor'
            return str(v).strip()  # keep original if unrecognized
        for _sc in [c for c in (sup_o, sup_ao) if c and c in df.columns]:
            df[_sc] = df[_sc].apply(_norm_stype)

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
# A PO is "placed" if it has a PO Date OR a PO Basic Value filled — this
# captures rows where the buyer entered the value but not yet the date,
# so totals match the sheet's own SUM exactly.
has_pr_all = pd.notna(dff[C_PR_DT]) if C_PR_DT else pd.Series(False, index=dff.index)
has_podate = pd.notna(dff[C_PO_DT]) if C_PO_DT else pd.Series(False, index=dff.index)
has_poval  = (pd.to_numeric(dff[C_PO_VAL], errors='coerce').fillna(0) > 0) if C_PO_VAL else pd.Series(False, index=dff.index)
has_po_all = has_podate | has_poval
df_prs      = dff[has_pr_all].copy()
df_unclosed = dff[has_pr_all & ~has_po_all].copy()
n_prs       = len(df_prs)
n_unclosed  = len(df_unclosed)

# Now apply month filter — ONLY to PO rows (by PO date)
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

# OTIF — average of the OTIF column values that are filled in.
# (a delivery has happened and OTIF was measured), regardless of whether the
# Delivery Status label still says "Ongoing" (partial deliveries count too).
# Example: one row with OTIF 0.92 → shows 92.0%.
otif_pct, otif_n = 0.0, 0
if C_OTIF and C_OTIF in df_pos.columns and len(df_pos) > 0:
    ov = pd.to_numeric(df_pos[C_OTIF].astype(str).str.replace('%', ''), errors='coerce').dropna()
    if len(ov) > 0 and ov.max() > 2: ov = ov / 100   # handle 0-100 vs 0-1 scale
    ov = ov[ov > 0]                                    # only rows with a real OTIF
    otif_n = len(ov)
    if otif_n > 0:
        otif_pct = float(ov.mean() * 100)              # average of filled OTIF values

# Subset of POs that have a real (positive) OTIF value — used for BU breakdown
if C_OTIF and C_OTIF in df_pos.columns:
    _otif_vals = pd.to_numeric(df_pos[C_OTIF].astype(str).str.replace('%', ''), errors='coerce')
    df_otif = df_pos[_otif_vals.fillna(0) > 0].copy()
else:
    df_otif = pd.DataFrame(columns=df_pos.columns)

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

t1,t2,t3,t4,t5,t6,t7,t8,t9,t10 = st.tabs(["Overview","Spend & Savings","TAT & OTIF","Working Capital","New Vendor Dev","MFC Tracker","Ongoing POs","PR-PO Unclosed","Vendor Concentration","Ask Data"])

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
    # ── Header metrics row ────────────────────────────────────
    # Prior-year total for the active scope (full-year or same month last year)
    if sel_month != 'All':
        _mm = sel_month.split('-')[1] if '-' in sel_month else None
        _py_sp = sum(PREV_YEAR['bu_month'][b][_mm]['spend']
                     for b in PREV_YEAR['bu_month'] if _mm in PREV_YEAR['bu_month'][b]) if _mm else 0.0
        _py_sv = sum(PREV_YEAR['bu_month'][b][_mm]['savings']
                     for b in PREV_YEAR['bu_month'] if _mm in PREV_YEAR['bu_month'][b]) if _mm else 0.0
        _py_lbl = f"FY26 {sel_month.split('-')[1]} (same mo.)"
    else:
        _py_sp = PREV_YEAR['fy_total']['spend']
        _py_sv = PREV_YEAR['fy_total']['savings']
        _py_lbl = "FY26 full year"
    _py_pct = (_py_sv / _py_sp * 100) if _py_sp > 0 else 0.0

    st.markdown(f"""<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:14px 20px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;">
<div style="font-size:10px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.1em;">FY'27 Actuals &nbsp;|&nbsp; All values Rs Crores</div>
<div style="display:flex;gap:32px;">
  <div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.08em;">Total Spend</div><div style="font-size:20px;font-weight:800;color:#fff;font-family:'DM Mono',monospace;">Rs {spend:.2f} Cr</div></div>
  <div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.08em;">Total Savings</div><div style="font-size:20px;font-weight:800;color:#68d391;font-family:'DM Mono',monospace;">Rs {savings:.2f} Cr</div></div>
  <div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.08em;">Savings Rate</div><div style="font-size:20px;font-weight:800;color:{'#68d391' if sav_pct>=4.5 else '#fc8181'};font-family:'DM Mono',monospace;">{sav_pct:.2f}%</div></div>
  <div style="text-align:center;border-left:1px solid rgba(255,255,255,.08);padding-left:24px;"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:.08em;">{_py_lbl}</div><div style="font-size:14px;font-weight:700;color:#888;font-family:'DM Mono',monospace;margin-top:3px;">Rs {_py_sp:.2f} Cr · {_py_pct:.1f}%</div></div>
  <div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.08em;">POs Placed</div><div style="font-size:20px;font-weight:800;color:#fff;font-family:'DM Mono',monospace;">{n_pos}</div></div>
</div></div>""", unsafe_allow_html=True)

    # ── BU cards ──────────────────────────────────────────────
    if C_PO_VAL and len(df_pos) > 0:
        bu_list = sorted(df_pos[C_BU].dropna().unique().tolist())
        cols = st.columns(len(bu_list)) if len(bu_list) <= 5 else st.columns(4)

        for i, bu in enumerate(bu_list):
            bu_df = df_pos[df_pos[C_BU] == bu]
            bu_sp  = ssum(bu_df, C_PO_VAL) / 1e7
            bu_sv  = ssum(bu_df, C_SAV)    / 1e7
            bu_pct = (bu_sv / bu_sp * 100) if bu_sp > 0 else 0.0
            bu_n   = len(bu_df)

            # ── Prior-year (FY25-26) comparison ──────────────────
            # Map current BU name to prior-year key (ZAP 91 -> ZAP91).
            _py_key = bu.replace(' ', '') if bu.replace(' ', '') in PREV_YEAR['bu_total'] else bu
            py = None
            if sel_month != 'All':
                # Month-wise: compare same calendar month of prior year.
                mm = sel_month.split('-')[1] if '-' in sel_month else None
                if mm and _py_key in PREV_YEAR['bu_month'] and mm in PREV_YEAR['bu_month'][_py_key]:
                    py = PREV_YEAR['bu_month'][_py_key][mm]
            else:
                py = PREV_YEAR['bu_total'].get(_py_key)

            yoy_html = ''
            if py:
                py_sp, py_sv = py['spend'], py['savings']
                py_pct = (py_sv / py_sp * 100) if py_sp > 0 else 0.0
                def _arrow(cur, prev):
                    if prev == 0: return '<span style="color:#63b3ed;">NEW</span>'
                    d = cur - prev
                    c = '#68d391' if d >= 0 else '#fc8181'
                    sym = '▲' if d >= 0 else '▼'
                    return f'<span style="color:{c};">{sym}</span>'
                period_lbl = 'vs prior yr' if sel_month == 'All' else 'vs same mo. PY'
                yoy_html = f'''<div style="border-top:1px solid rgba(255,255,255,.05);padding-top:9px;margin-top:9px;">
<div style="font-size:8px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;">YoY — {period_lbl} (FY26)</div>
<table style="width:100%;border-collapse:collapse;">
<tr><td style="font-size:10px;color:#999;padding:2px 0;">PO Value</td>
<td style="font-size:10px;color:#888;font-family:'DM Mono',monospace;text-align:right;padding:2px 6px;">Rs {py_sp:.2f}</td>
<td style="text-align:center;font-size:9px;">→</td>
<td style="font-size:10px;color:#fff;font-family:'DM Mono',monospace;text-align:right;padding:2px 0;">Rs {bu_sp:.2f} {_arrow(bu_sp,py_sp)}</td></tr>
<tr><td style="font-size:10px;color:#999;padding:2px 0;">Savings</td>
<td style="font-size:10px;color:#888;font-family:'DM Mono',monospace;text-align:right;padding:2px 6px;">Rs {py_sv:.2f}</td>
<td style="text-align:center;font-size:9px;">→</td>
<td style="font-size:10px;color:#fff;font-family:'DM Mono',monospace;text-align:right;padding:2px 0;">Rs {bu_sv:.2f} {_arrow(bu_sv,py_sv)}</td></tr>
<tr><td style="font-size:10px;color:#999;padding:2px 0;">Savings %</td>
<td style="font-size:10px;color:#888;font-family:'DM Mono',monospace;text-align:right;padding:2px 6px;">{py_pct:.1f}%</td>
<td style="text-align:center;font-size:9px;">→</td>
<td style="font-size:10px;color:#fff;font-family:'DM Mono',monospace;text-align:right;padding:2px 0;">{bu_pct:.1f}% {_arrow(bu_pct,py_pct)}</td></tr>
</table></div>'''
            else:
                yoy_html = '''<div style="border-top:1px solid rgba(255,255,255,.05);padding-top:9px;margin-top:9px;">
<div style="font-size:9px;color:#63b3ed;font-weight:600;">● NEW vertical in FY27 — no prior-year data</div></div>'''

            # Status pill
            if bu_pct >= 4.5:
                pill_color, pill_bg, pill_txt = '#68d391', 'rgba(56,161,105,.15)', 'ON TARGET'
                bar_color = '#38a169'
            elif bu_pct > 0:
                pill_color, pill_bg, pill_txt = '#f6e05e', 'rgba(214,158,46,.15)', 'WATCH'
                bar_color = '#d69e2e'
            elif bu_pct < 0:
                pill_color, pill_bg, pill_txt = '#fc8181', 'rgba(229,62,62,.15)', 'AT RISK'
                bar_color = '#e53e3e'
            else:
                pill_color, pill_bg, pill_txt = '#63b3ed', 'rgba(49,130,206,.15)', 'NEW'
                bar_color = '#3182ce'

            # Category breakdown
            cat_html = ''
            if C_CAT and C_CAT in bu_df.columns and C_SAV and C_SAV in bu_df.columns:
                cat_grp = bu_df.groupby(C_CAT).agg(
                    sp=(C_PO_VAL,'sum'), sv=(C_SAV,'sum')
                ).reset_index().sort_values('sp', ascending=False).head(4)
                for _, row in cat_grp.iterrows():
                    cp = (row['sv']/row['sp']*100) if row['sp']>0 else 0
                    cc = '#68d391' if cp>=4.5 else ('#fc8181' if cp<0 else '#f6e05e')
                    cat_html += f'''<tr>
<td style="padding:5px 0;font-size:11px;color:#ccc;">{row[C_CAT]}</td>
<td style="padding:5px 0;font-size:11px;color:#fff;font-family:'DM Mono',monospace;text-align:right;">Rs {row['sp']/1e7:.2f}Cr</td>
<td style="padding:5px 0;font-size:11px;font-family:'DM Mono',monospace;text-align:right;color:{cc};">{cp:.1f}%</td>
</tr>'''

            with cols[i % len(cols)]:
                st.markdown(f"""<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:16px;border-top:3px solid {bar_color};height:100%;">
<!-- BU header -->
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
  <div style="font-size:18px;font-weight:800;color:#fff;">{bu}</div>
  <div style="background:{pill_bg};color:{pill_color};border:1px solid {pill_color}33;padding:3px 10px;border-radius:5px;font-size:9px;font-weight:800;letter-spacing:.1em;">{pill_txt}</div>
</div>
<!-- Key metrics -->
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:14px;">
  <div style="background:rgba(255,255,255,.03);border-radius:8px;padding:8px 10px;">
    <div style="font-size:8px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;">PO Spend</div>
    <div style="font-size:16px;font-weight:800;color:#fff;font-family:'DM Mono',monospace;">Rs {bu_sp:.2f}Cr</div>
  </div>
  <div style="background:rgba(255,255,255,.03);border-radius:8px;padding:8px 10px;">
    <div style="font-size:8px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;">Savings</div>
    <div style="font-size:16px;font-weight:800;color:{bar_color};font-family:'DM Mono',monospace;">Rs {bu_sv:.2f}Cr</div>
  </div>
  <div style="background:rgba(255,255,255,.03);border-radius:8px;padding:8px 10px;">
    <div style="font-size:8px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;">Rate</div>
    <div style="font-size:16px;font-weight:800;color:{pill_color};font-family:'DM Mono',monospace;">{bu_pct:.1f}%</div>
  </div>
</div>
<!-- Savings progress bar -->
<div style="margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
    <span style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.06em;">Savings Rate</span>
    <span style="font-size:9px;color:#555;">Target 4.5%</span>
  </div>
  <div style="background:rgba(255,255,255,.06);border-radius:3px;height:5px;overflow:hidden;">
    <div style="width:{min(bu_pct/10*100,100):.0f}%;height:100%;background:{bar_color};border-radius:3px;transition:width 1s ease;"></div>
  </div>
</div>
<!-- Category table -->
{f'<div style="border-top:1px solid rgba(255,255,255,.05);padding-top:10px;"><table style="width:100%;border-collapse:collapse;"><thead><tr><th style="font-size:8px;color:#555;text-transform:uppercase;letter-spacing:.06em;padding:0 0 5px 0;text-align:left;">Category</th><th style="font-size:8px;color:#555;text-transform:uppercase;letter-spacing:.06em;padding:0 0 5px 0;text-align:right;">Spend</th><th style="font-size:8px;color:#555;text-transform:uppercase;letter-spacing:.06em;padding:0 0 5px 0;text-align:right;">Savings%</th></tr></thead><tbody>{cat_html}</tbody></table></div>' if cat_html else ''}
{yoy_html}
<!-- PO count footer -->
<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,.04);font-size:9px;color:#555;">{bu_n} PO{'s' if bu_n!=1 else ''} placed</div>
</div>""", unsafe_allow_html=True)

    else:
        st.markdown('<div class="info-box">No POs placed yet — spend data will appear once PO dates are filled.</div>', unsafe_allow_html=True)

    # ── Monthly trend ─────────────────────────────────────────
    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    if C_PO_DT and C_PO_VAL and len(df_pos) > 0:
        tmp = df_pos.copy()
        tmp['_m'] = pd.to_datetime(tmp[C_PO_DT], errors='coerce').dt.to_period('M').astype(str)
        mo = tmp.groupby('_m').agg(
            sp=(C_PO_VAL,'sum'),
            sv=(C_SAV,'sum') if C_SAV else (C_PO_VAL,'count')
        ).reset_index().sort_values('_m')
        mo['sc'] = mo['sp']/1e7
        mo['svc'] = mo['sv']/1e7 if C_SAV else 0
        mo['sav_pct'] = (mo['sv']/mo['sp']*100).fillna(0) if C_SAV else 0

        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            name='Spend', x=mo['_m'], y=mo['sc'],
            marker_color='rgba(229,62,62,.35)', marker_line_width=0,
            text=mo['sc'].apply(lambda x: f'Rs {x:.2f}Cr'),
            textposition='outside', textfont=dict(color='#ddd', size=10)
        ))
        if C_SAV:
            fig3.add_trace(go.Scatter(
                name='Savings %', x=mo['_m'], y=mo['sav_pct'],
                line=dict(color=GRN, width=2.5),
                mode='lines+markers', marker=dict(size=6, color=GRN),
                yaxis='y2',
                text=mo['sav_pct'].apply(lambda x: f'{x:.1f}%'),
                textposition='top center', textfont=dict(color=GRN, size=10)
            ))
        dk2 = {k: v for k, v in DK.items() if k != 'yaxis'}
        fig3.update_layout(
            **dk2, height=280, title_text='Monthly PO Spend & Savings Rate',
            yaxis=dict(title=dict(text='Spend (Rs Cr)', font=dict(color='#ddd')),
                       gridcolor='rgba(255,255,255,.08)',
                       tickfont=dict(color='#ddd')),
            yaxis2=dict(title=dict(text='Savings %', font=dict(color=GRN)),
                        overlaying='y', side='right',
                        tickfont=dict(color=GRN), showgrid=False),
            legend=dict(orientation='h', y=1.12, x=1, xanchor='right',
                        bgcolor='rgba(0,0,0,0)', font=dict(color='#ddd', size=11))
        )
        st.plotly_chart(fig3, width='stretch')

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
    if len(df_otif)>0 and C_OTIF and C_OTIF in df_otif.columns:
        rows=[]
        for bu in df_otif[C_BU].dropna().unique():
            s=df_otif[df_otif[C_BU]==bu]
            v=pd.to_numeric(s[C_OTIF].astype(str).str.replace('%',''),errors='coerce').dropna()
            if len(v)>0 and v.max()>2: v=v/100
            v=v[v>0]
            if len(v): rows.append({'BU':bu,'OTIF%':float(v.mean()*100)})
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

        su_norm = df_pos_stype[C_STYPE].astype(str).str.upper()
        # After _norm_stype values are AVL-OEM / AVL-TRADER / NV-OEM / NV-TRADER / Civil Contractor
        avl_oem = int((su_norm.str.contains('AVL', na=False) & su_norm.str.contains('OEM', na=False)).sum())
        avl_trd = int((su_norm.str.contains('AVL', na=False) & su_norm.str.contains('TRADER', na=False)).sum())
        nv_mask_filled = su_norm.str.contains('NV', na=False)
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
                _type_color = {
                    'AVL-OEM': GRN, 'AVL-TRADER': BLU, 'NV-TRADER': RED,
                    'NV-OEM': PUR, 'Civil Contractor': AMB,
                }
                pie_colors = [_type_color.get(t, '#888') for t in sv2['Type']]
                fp2 = go.Figure(go.Pie(
                    labels=sv2['Type'], values=sv2['Count'], hole=0.4,
                    marker_colors=pie_colors,
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
                    if st.button(f"{'● ' if sel3 else ''}{lbl3}",key=f"mfc_{key3}",width='stretch'):
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

# ════ TAB 9 — VENDOR CONCENTRATION ══════════════════════════
with t9:
    try:
        st.markdown("### Vendor Concentration & Spend Risk")
        if C_SUPPLIER and C_SUPPLIER in df_pos.columns and C_PO_VAL and len(df_pos) > 0:
            vdf = df_pos.copy()
            vdf['_sp'] = pd.to_numeric(vdf[C_PO_VAL], errors='coerce').fillna(0)
            vdf['_sv'] = pd.to_numeric(vdf[C_SAV], errors='coerce').fillna(0) if C_SAV else 0
            vdf = vdf[vdf[C_SUPPLIER].astype(str).str.strip().replace({'nan': '', 'None': ''}).ne('')]

            vc = vdf.groupby(C_SUPPLIER).agg(
                spend=('_sp', 'sum'), savings=('_sv', 'sum'), pos=('_sp', 'count')
            ).reset_index().sort_values('spend', ascending=False)
            total_sp = vc['spend'].sum()
            vc['pct'] = vc['spend'] / total_sp * 100 if total_sp > 0 else 0

            top5_pct = vc.head(5)['pct'].sum()
            top10_pct = vc.head(10)['pct'].sum()
            n_vendors = len(vc)
            hhi = ((vc['pct']) ** 2).sum()
            conc_label = 'HIGH' if top5_pct >= 70 else ('MODERATE' if top5_pct >= 50 else 'LOW')
            conc_color = '#e53e3e' if top5_pct >= 70 else ('#d69e2e' if top5_pct >= 50 else '#38a169')

            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Total Vendors", str(n_vendors))
            with c2: st.metric("Top 5 Spend Share", f"{top5_pct:.1f}%", conc_label)
            with c3: st.metric("Top 10 Spend Share", f"{top10_pct:.1f}%")
            with c4: st.metric("Concentration (HHI)", f"{hhi:.0f}", "Concentrated" if hhi > 2500 else "Diversified")

            st.markdown(
                '<div class="info-box" style="border-left-color:' + conc_color + ';margin:8px 0 14px;">'
                + '<b style="color:' + conc_color + ';">' + conc_label + ' concentration.</b> '
                + 'Top 5 vendors carry ' + f'{top5_pct:.1f}' + '% of total spend (Rs '
                + f'{vc.head(5)["spend"].sum()/1e7:.1f}' + ' Cr of Rs ' + f'{total_sp/1e7:.1f}'
                + ' Cr). A delay or price move from any top vendor has outsized impact.</div>',
                unsafe_allow_html=True)

            # ── HHI professional insight panel ──
            if hhi >= 2500:
                hhi_band, hhi_col, hhi_msg = "Highly Concentrated", "#e53e3e", "A few vendors dominate spend. Single-vendor disruption (delay, price hike, quality issue, insolvency) would hit a large share of procurement. Diversification is advisable for critical categories."
            elif hhi >= 1500:
                hhi_band, hhi_col, hhi_msg = "Moderately Concentrated", "#d69e2e", "Spend leans on a handful of vendors. Manageable, but worth monitoring — developing backup vendors for the top spend categories reduces exposure."
            else:
                hhi_band, hhi_col, hhi_msg = "Diversified", "#38a169", "Spend is well spread across many vendors. Low dependency risk — no single vendor failure would materially disrupt procurement."

            top1_name = str(vc.iloc[0][C_SUPPLIER])[:30] if len(vc) else "—"
            top1_pct  = vc.iloc[0]['pct'] if len(vc) else 0
            top2_pct  = vc.iloc[:2]['pct'].sum() if len(vc) >= 2 else top1_pct

            st.markdown(
                '<div style="background:#13131a;border:1px solid rgba(255,255,255,.08);border-left:3px solid ' + hhi_col + ';border-radius:14px;padding:18px 22px;margin:4px 0 16px;">'
                + '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">'
                + '<span style="font-size:13px;font-weight:700;color:#fff;">Herfindahl-Hirschman Index (HHI)</span>'
                + '<span style="font-size:13px;font-weight:800;color:' + hhi_col + ';font-family:DM Mono,monospace;">' + f'{hhi:.0f}' + ' · ' + hhi_band + '</span></div>'
                + '<div style="font-size:12px;color:#aaa;line-height:1.65;margin-bottom:12px;">'
                + '<b style="color:#ddd;">What it is:</b> HHI is the standard measure of market concentration used by economists and competition regulators. It is the sum of every vendor\'s squared share of total spend. Squaring means large vendors count far more heavily, so the index rises sharply when few vendors dominate.</div>'
                + '<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">'
                + '<div style="flex:1;min-width:120px;text-align:center;padding:8px;border-radius:8px;background:rgba(56,161,105,' + ('.18' if hhi<1500 else '.05') + ');border:1px solid rgba(56,161,105,.2);"><div style="font-size:15px;font-weight:800;color:#68d391;font-family:DM Mono,monospace;">&lt; 1500</div><div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-top:2px;">Diversified</div></div>'
                + '<div style="flex:1;min-width:120px;text-align:center;padding:8px;border-radius:8px;background:rgba(214,158,46,' + ('.18' if 1500<=hhi<2500 else '.05') + ');border:1px solid rgba(214,158,46,.2);"><div style="font-size:15px;font-weight:800;color:#f6e05e;font-family:DM Mono,monospace;">1500–2500</div><div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-top:2px;">Moderate</div></div>'
                + '<div style="flex:1;min-width:120px;text-align:center;padding:8px;border-radius:8px;background:rgba(229,62,62,' + ('.18' if hhi>=2500 else '.05') + ');border:1px solid rgba(229,62,62,.2);"><div style="font-size:15px;font-weight:800;color:#fc8181;font-family:DM Mono,monospace;">&gt; 2500</div><div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-top:2px;">Concentrated</div></div></div>'
                + '<div style="font-size:12px;color:#aaa;line-height:1.65;"><b style="color:' + hhi_col + ';">Impact for Cat-2:</b> ' + hhi_msg + '</div>'
                + '<div style="font-size:12px;color:#888;line-height:1.6;margin-top:8px;border-top:1px solid rgba(255,255,255,.05);padding-top:10px;">'
                + 'Your score is driven mainly by <b style="color:#ddd;">' + top1_name + '</b> (' + f'{top1_pct:.0f}' + '% of spend)'
                + (', and your top 2 vendors together = <b style="color:#ddd;">' + f'{top2_pct:.0f}' + '%</b>.' if len(vc)>=2 else '.') + '</div></div>',
                unsafe_allow_html=True)

            c1, c2 = st.columns([1.3, 1])
            with c1:
                top = vc.head(12).copy()
                top['label'] = top[C_SUPPLIER].astype(str).str[:26]
                fig_v = go.Figure(go.Bar(
                    y=top['label'][::-1], x=top['spend'][::-1] / 1e7, orientation='h',
                    marker_color=[('#e53e3e' if p >= 15 else ('#d69e2e' if p >= 5 else BLU)) for p in top['pct'][::-1]],
                    marker_line_width=0,
                    text=[f'Rs {s/1e7:.1f}Cr ({p:.0f}%)' for s, p in zip(top['spend'][::-1], top['pct'][::-1])],
                    textposition='outside', textfont=dict(color='#ddd', size=10)))
                apply_dk(fig_v, height=400, title_text='Top Vendors by Spend', showlegend=False)
                fig_v.update_xaxes(range=[0, float(top['spend'].max() / 1e7) * 1.28])
                st.plotly_chart(fig_v, width='stretch')
            with c2:
                vc_sorted = vc.sort_values('spend', ascending=False).reset_index(drop=True)
                vc_sorted['cum_pct'] = vc_sorted['pct'].cumsum()
                fig_p = go.Figure()
                fig_p.add_trace(go.Scatter(
                    x=list(range(1, len(vc_sorted) + 1)), y=vc_sorted['cum_pct'],
                    mode='lines', line=dict(color=RED, width=2.5), fill='tozeroy',
                    fillcolor='rgba(229,62,62,.08)'))
                fig_p.add_hline(y=80, line_dash='dash', line_color=AMB,
                                annotation_text='80% of spend', annotation_font_color=AMB)
                apply_dk(fig_p, height=400, title_text='Cumulative Spend (Pareto)', showlegend=False)
                fig_p.update_xaxes(title_text='Vendors (ranked)')
                fig_p.update_yaxes(title_text='% of total spend')
                st.plotly_chart(fig_p, width='stretch')

            # DRILL-DOWN
            st.markdown("#### Drill down — select a vendor to see their POs")
            # Precompute display labels once (avoids per-render lookups that can crash)
            vc_lbl = vc.copy()
            vc_lbl['_label'] = vc_lbl.apply(
                lambda r: f"{str(r[C_SUPPLIER])[:40]}  —  Rs {r['spend']/1e7:.2f}Cr  ({int(r['pos'])} POs)", axis=1)
            label_to_vendor = dict(zip(vc_lbl['_label'], vc_lbl[C_SUPPLIER]))
            sel_label = st.selectbox("Vendor", vc_lbl['_label'].tolist(), label_visibility="collapsed", key="vendor_drill")
            sel_v = label_to_vendor.get(sel_label)
            if sel_v is not None:
                vg = vdf[vdf[C_SUPPLIER] == sel_v]
                sp = vg['_sp'].sum() / 1e7
                sv = vg['_sv'].sum() / 1e7
                share = vg['_sp'].sum() / total_sp * 100 if total_sp > 0 else 0
                nproj = vg['Project Name'].nunique() if 'Project Name' in vg.columns else 0
                nbu = vg[C_BU].nunique() if C_BU in vg.columns else 0
                m1, m2, m3, m4, m5 = st.columns(5)
                with m1: st.metric("POs", str(len(vg)))
                with m2: st.metric("Total Spend", f"Rs {sp:.2f}Cr")
                with m3: st.metric("Savings", f"Rs {sv:.2f}Cr")
                with m4: st.metric("% of Cat-2 Spend", f"{share:.1f}%")
                with m5: st.metric("Projects / BUs", f"{nproj} / {nbu}")

                show_v = [c for c in ['SN', C_BU, 'Project Name', C_ITEMS, C_CAT, C_HANDLER, 'PO/OD Ref.', C_PO_VAL, C_SAV, C_SAV_PCT, C_CUR_ST] if c and c in vg.columns]
                vgd = vg[show_v].copy()
                # Force every column to a clean string so Streamlit/Arrow never crashes on mixed types
                for c in vgd.columns:
                    if pd.api.types.is_datetime64_any_dtype(vgd[c]):
                        vgd[c] = vgd[c].dt.strftime('%d-%b-%Y')
                    else:
                        vgd[c] = vgd[c].astype(str).replace({'nan': '', 'None': '', 'NaT': ''})
                st.dataframe(vgd, width='stretch', height=min(40 * len(vgd) + 50, 420))

            neg = vdf[vdf['_sv'] < 0]
            if len(neg) > 0:
                neg_val = abs(neg['_sv'].sum()) / 1e7
                st.markdown(
                    '<div class="info-box" style="border-left-color:#e53e3e;margin-top:12px;">'
                    + '<b style="color:#fc8181;">Savings leakage:</b> ' + str(len(neg))
                    + ' PO(s) placed <b>above</b> baseline, totalling Rs ' + f'{neg_val:.2f}'
                    + ' Cr over benchmark.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="info-box">Vendor data will populate once POs with supplier names are placed.</div>', unsafe_allow_html=True)

    except Exception as _e:
        st.error("This tab hit an error: " + str(_e))
# ════ TAB 10 — ASK DATA (conversational, no LLM) ════════════
with t10:
    try:
        st.markdown("### Ask the Data")
        st.markdown('<div style="font-size:13px;color:#888;margin-bottom:14px;">Ask about any BU, buyer, vendor, or category — or try a question. No AI, just instant answers computed live from your data.</div>', unsafe_allow_html=True)

        chip_html = (
            '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;">'
            '<span style="background:rgba(108,99,255,.12);border:1px solid rgba(108,99,255,.25);color:#a78bfa;padding:5px 12px;border-radius:16px;font-size:12px;">Try: top vendors</span>'
            '<span style="background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);color:#68d391;padding:5px 12px;border-radius:16px;font-size:12px;">who saved the most</span>'
            '<span style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);color:#fc8181;padding:5px 12px;border-radius:16px;font-size:12px;">overdue</span>'
            '<span style="background:rgba(234,179,8,.1);border:1px solid rgba(234,179,8,.25);color:#f6e05e;padding:5px 12px;border-radius:16px;font-size:12px;">Water</span>'
            '<span style="background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.25);color:#63b3ed;padding:5px 12px;border-radius:16px;font-size:12px;">negative savings</span>'
            '</div>')
        st.markdown(chip_html, unsafe_allow_html=True)

        q = st.text_input("Search", placeholder="Ask anything — e.g. 'how much did we spend on Water', 'top vendors', 'who has most overdue'", label_visibility="collapsed", key="ask_q")

        def bubble(title, body_html, color='#6c63ff'):
            st.markdown(
                '<div style="background:#13131a;border:1px solid rgba(255,255,255,.08);border-left:3px solid '
                + color + ';border-radius:14px;padding:18px 22px;margin-top:12px;">'
                + '<div style="font-size:11px;font-weight:700;color:' + color
                + ';text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;">' + title + '</div>'
                + body_html + '</div>', unsafe_allow_html=True)

        def safe_table(dfx, maxh=320):
            """Render any dataframe as clean strings so Arrow never crashes on mixed types."""
            d = dfx.copy()
            for c in d.columns:
                if pd.api.types.is_datetime64_any_dtype(d[c]):
                    d[c] = d[c].dt.strftime('%d-%b-%Y')
                else:
                    d[c] = d[c].astype(str).replace({'nan': '', 'None': '', 'NaT': ''})
            st.dataframe(d, width='stretch', height=min(40 * len(d) + 50, maxh))

        def big_metrics(pairs):
            cells = ''.join(
                '<div style="flex:1;min-width:90px;"><div style="font-size:10px;color:#666;text-transform:uppercase;letter-spacing:.06em;">'
                + l + '</div><div style="font-size:22px;font-weight:800;color:' + c
                + ';font-family:DM Mono,monospace;line-height:1.3;">' + v + '</div></div>'
                for l, v, c in pairs)
            return '<div style="display:flex;gap:24px;flex-wrap:wrap;">' + cells + '</div>'

        def row_line(left, right, lcolor='#ddd', rcolor='#fff'):
            return ('<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.05);">'
                    + '<span style="color:' + lcolor + ';font-size:13px;">' + left + '</span>'
                    + '<span style="color:' + rcolor + ';font-family:DM Mono,monospace;font-size:13px;">' + right + '</span></div>')

        if q and q.strip():
            ql = q.strip().lower()
            adf = df_pos.copy()
            adf['_sp'] = pd.to_numeric(adf[C_PO_VAL], errors='coerce').fillna(0) if C_PO_VAL else 0
            adf['_sv'] = pd.to_numeric(adf[C_SAV], errors='coerce').fillna(0) if C_SAV else 0
            total_sp = adf['_sp'].sum()
            answered = False

            if any(k in ql for k in ['top vendor', 'biggest vendor', 'largest vendor', 'which vendor', 'vendor']):
                if C_SUPPLIER:
                    answered = True
                    vg = adf[adf[C_SUPPLIER].astype(str).str.strip().ne('')].groupby(C_SUPPLIER)['_sp'].agg(['sum', 'count']).sort_values('sum', ascending=False).head(5)
                    rows = ''
                    for i, (name, r) in enumerate(vg.iterrows(), 1):
                        share = r['sum'] / total_sp * 100
                        rows += row_line(f'{i}. {str(name)[:38]}', f'Rs {r["sum"]/1e7:.2f}Cr · {share:.0f}% · {int(r["count"])} POs')
                    top5share = vg['sum'].sum() / total_sp * 100
                    bubble("Top 5 Vendors by Spend", rows + '<div style="margin-top:10px;font-size:12px;color:#888;">These 5 vendors account for <b style="color:#fc8181;">' + f'{top5share:.0f}' + '%</b> of total Cat-2 spend.</div>', '#6c63ff')

            elif any(k in ql for k in ['saved the most', 'most saving', 'best saving', 'highest saving', 'who saved', 'top saving']):
                answered = True
                grp_col = C_HANDLER if any(k in ql for k in ['buyer', 'who']) else C_BU
                gg = adf.groupby(grp_col)['_sv'].sum().sort_values(ascending=False).head(5)
                rows = ''
                for i, (name, val) in enumerate(gg.items(), 1):
                    rows += row_line(f'{i}. {name}', f'Rs {val/1e7:.2f}Cr', rcolor='#68d391')
                bubble(f"Top Savings by {'Buyer' if grp_col==C_HANDLER else 'BU'}", rows, '#22c55e')

            elif any(k in ql for k in ['overdue', 'late deliver', 'delayed']):
                answered = True
                if C_MFC_DT and C_MFC_DAYS:
                    m = adf.copy()
                    m['_mfc'] = pd.to_datetime(m[C_MFC_DT], errors='coerce')
                    m['_days'] = pd.to_numeric(m[C_MFC_DAYS].astype(str).str.replace(',', ''), errors='coerce')
                    m = m.dropna(subset=['_mfc', '_days'])
                    m = m[m['_days'] > 0]
                    m['_exp'] = m['_mfc'] + pd.to_timedelta(m['_days'].astype(int), unit='D')
                    m['_left'] = (m['_exp'] - pd.Timestamp(date.today())).dt.days
                    od = m[m['_left'] <= 0]
                    val = od['_sp'].sum() / 1e7
                    worst = f'{int(abs(od["_left"].min()))}d' if len(od) else '—'
                    bubble("Overdue Deliveries", big_metrics([('Overdue POs', str(len(od)), '#fc8181'), ('Value at Risk', f'Rs {val:.2f}Cr', '#fc8181'), ('Worst delay', worst, '#fc8181')]), '#e53e3e')
                    if len(od):
                        sc = [c for c in [C_BU, 'Project Name', C_ITEMS, C_SUPPLIER, C_HANDLER, C_PO_VAL] if c and c in od.columns]
                        safe_table(od.sort_values('_left')[sc], 320)
                else:
                    bubble("Overdue", "MFC delivery data not available yet.", '#e53e3e')

            elif any(k in ql for k in ['negative saving', 'leakage', 'above baseline', 'over baseline', 'loss']):
                answered = True
                neg = adf[adf['_sv'] < 0]
                val = abs(neg['_sv'].sum()) / 1e7
                bubble("Negative Savings (paid above baseline)", big_metrics([('POs', str(len(neg)), '#fc8181'), ('Over baseline', f'Rs {val:.2f}Cr', '#fc8181')]), '#e53e3e')
                if len(neg):
                    sc = [c for c in [C_BU, 'Project Name', C_ITEMS, C_SUPPLIER, C_HANDLER, C_PO_VAL, C_SAV] if c and c in neg.columns]
                    safe_table(neg[sc], 300)

            elif any(k in ql for k in ['how many po', 'total po', 'number of po', 'count']):
                answered = True
                bubble("PO Count", big_metrics([('Total POs Placed', str(len(adf)), '#63b3ed'), ('Total Spend', f'Rs {total_sp/1e7:.1f}Cr', '#fff'), ('Total Savings', f'Rs {adf["_sv"].sum()/1e7:.2f}Cr', '#68d391')]), '#3b82f6')

            if not answered:
                for col, lbl, clr in [(C_BU, 'BU', '#63b3ed'), (C_HANDLER, 'Buyer', '#a78bfa'), (C_SUPPLIER, 'Vendor', '#f6e05e'), (C_CAT, 'Category', '#68d391')]:
                    if col and col in adf.columns:
                        matches = [x for x in adf[col].dropna().unique() if ql in str(x).lower()]
                        if matches:
                            answered = True
                            for mv in matches[:4]:
                                g = adf[adf[col] == mv]
                                sp = g['_sp'].sum() / 1e7
                                sv = g['_sv'].sum() / 1e7
                                pct = sv / sp * 100 if sp > 0 else 0
                                share = g['_sp'].sum() / total_sp * 100 if total_sp > 0 else 0
                                extra = ''
                                if col == C_SUPPLIER:
                                    np_ = g['Project Name'].nunique() if 'Project Name' in g.columns else 0
                                    extra = '<div style="margin-top:8px;font-size:12px;color:#888;">Across ' + str(np_) + ' project(s) · ' + f'{share:.1f}' + '% of total Cat-2 spend</div>'
                                bubble(f"{lbl}: {mv}",
                                       big_metrics([('POs', str(len(g)), '#63b3ed'), ('Spend', f'Rs {sp:.2f}Cr', '#fff'), ('Savings', f'Rs {sv:.2f}Cr', '#68d391'), ('Rate', f'{pct:.1f}%', '#68d391' if pct >= 4.5 else '#f6e05e')]) + extra, clr)
                                other = C_CAT if col == C_SUPPLIER else C_SUPPLIER
                                sc = [c for c in [C_BU, 'Project Name', C_ITEMS, other, C_HANDLER, 'PO/OD Ref.', C_PO_VAL, C_CUR_ST] if c and c in g.columns]
                                safe_table(g[sc], 300)
                            break

            if not answered:
                st.markdown('<div class="info-box">I could not match that. Try a BU (Water, E&R), a buyer or vendor name, a category, or questions like <b>top vendors</b>, <b>who saved the most</b>, <b>overdue</b>, <b>negative savings</b>.</div>', unsafe_allow_html=True)

    except Exception as _e:
        st.error("This tab hit an error: " + str(_e))
# Footer
st.markdown(f'<div style="padding:12px 0;border-top:1px solid rgba(255,255,255,.04);margin-top:16px;display:flex;justify-content:space-between;"><div style="font-size:11px;color:#333;">Zetwerk CPT · CAT-2 · FY 2026-27</div><div style="font-size:10px;color:#222;font-family:DM Mono,monospace;">{ts} · TTL 60s</div></div>', unsafe_allow_html=True)

# CAT 2 BUDDY — disabled
