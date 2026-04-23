"""
Zetwerk CPT CAT-2 Dashboard — FY 2026-27
Reads: PO TRACKER ' 27 + ongoing updated with realized27

Data reality (verified from actual sheet):
- 115 real rows (filter by BU != empty)
- 111 have PR date, 9 have PO date, 0 completed deliveries yet
- Columns with formulas (PR-PO TAT, OTIF, Delivery Status, Savings) → use data_only=True when loading
- Supplier type comes from col O (formula VLOOKUP from _PT_LIST); may be None for new rows
- TAT col M is computed: PO Dt - (Rev PR Dt if exists, else PR Dt)
- OTIF stored as ratio (0.00), not percentage; ≤ 1.05 = on time
- Delivery Status auto-computed: if YTD < 1 → Completed, else Ongoing
- No Completed rows in current data (FY is new)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, date
from google.oauth2.service_account import Credentials
import gspread
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Zetwerk CPT Dashboard",
    page_icon="Z",
    layout="wide",
    initial_sidebar_state="collapsed"
)

SHEET_ID = "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# ── Payment Term Score Map ────────────────────────────────────
SCORE_MAP = {
    "advance": -2, "on dispatch": 0, "ibc 90": 1, "ibc 60": 2,
    "vfs": 3, "clean credit 15": 3, "ibc 45": 4, "rxil": 4,
    "ifc 30": 5, "ifc 45": 5, "ifc 60": 5, "clean credit 30": 5,
    "ifc 90": 6, "clean credit 45": 7, "clean credit 60": 8, "clean credit 90": 10
}

def calc_payment_score(term):
    """Extract payment score from payment terms string."""
    if not term or str(term).strip() in ('', 'nan', 'None'):
        return None
    t = str(term).lower()
    for k, v in SCORE_MAP.items():
        if k in t:
            return float(v)
    return None

def gclient():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds)

# ── Load PO Tracker Sheet ─────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_po_tracker():
    try:
        gc = gclient()
        sh = gc.open_by_key(SHEET_ID)
        ws = None
        tab_names = ["PO TRACKER  27", "PO TRACKER ' 27", "PO TRACKER '27", "PO TRACKER"]
        for tab in tab_names:
            try:
                ws = sh.worksheet(tab)
                break
            except Exception:
                continue
        if not ws:
            available = [s.title for s in sh.worksheets()]
            return pd.DataFrame(), f"Tab not found. Available: {available}"

        # FORMATTED_VALUE returns computed cell values, not raw formulas.
        # This is critical for columns like PR-PO TAT, OTIF, Delivery Status,
        # Savings Value, PO Value with GST — all of which are formula-driven.
        data = ws.get_all_values(value_render_option='FORMATTED_VALUE')
        if len(data) < 2:
            return pd.DataFrame(), "Empty sheet"

        headers = [str(c).strip() for c in data[0]]
        df = pd.DataFrame(data[1:], columns=headers)

        # ── CRITICAL: Filter real rows by BU column ──────────
        # Sheet has 989 rows; rows below ~115 are empty (with dropdown validators)
        # Real rows have a non-empty BU column
        bu_col = next((c for c in df.columns if c.strip().upper() == 'BU'), None)
        if bu_col:
            df = df[df[bu_col].astype(str).str.strip().ne('') &
                    df[bu_col].astype(str).str.strip().ne('nan') &
                    df[bu_col].astype(str).str.strip().ne('None')].copy()
        else:
            # Fallback: drop rows where first 4 cols are all empty
            df = df[df.iloc[:, :4].apply(
                lambda r: any(str(v).strip() not in ('', 'nan', 'None') for v in r), axis=1
            )].copy()

        # ── Parse dates ──────────────────────────────────────
        # FORMATTED_VALUE returns dates as display strings e.g. "07/02/2025", "07-Feb-2025"
        # pandas to_datetime with dayfirst=True handles both DD/MM/YYYY and DD-Mon-YYYY
        date_cols = [c for c in df.columns if any(x in c.lower() for x in ['dt.', 'dt ', ' dt', 'date'])]
        for c in date_cols:
            df[c] = pd.to_datetime(df[c].astype(str).str.strip(), errors='coerce', dayfirst=True)

        # ── Parse numeric columns ────────────────────────────
        # Only columns that should be numeric (value, savings, TAT, OTIF, delivered, etc.)
        num_cols = [c for c in df.columns if any(x in c.lower() for x in
                    ['value', 'gst', 'saving', 'tat', 'delivery time', 'otif',
                     'delivered', 'yet to be', 'actual delivery'])]
        for c in num_cols:
            if c not in date_cols:
                df[c] = pd.to_numeric(
                    df[c].astype(str).str.replace(',', '').str.replace('%', '').str.strip(),
                    errors='coerce'
                )

        # ── Also parse PR-PO TAT (col M) ────────────────────
        tat_col = next((c for c in df.columns if 'pr' in c.lower() and 'po' in c.lower() and 'tat' in c.lower()), None)
        if tat_col:
            df[tat_col] = pd.to_numeric(df[tat_col].astype(str).str.strip(), errors='coerce')

        # ── Payment score ────────────────────────────────────
        pt_col = next((c for c in df.columns if 'payment' in c.lower() and 'term' in c.lower()), None)
        if pt_col:
            df['_PayScore'] = df[pt_col].apply(calc_payment_score)

        # ── Normalize Delivery Status casing ────────────────
        del_st_col = next((c for c in df.columns if 'delivery' in c.lower() and 'status' in c.lower()), None)
        if del_st_col:
            df[del_st_col] = df[del_st_col].fillna('').astype(str).str.strip().str.title()
            # Values: Ongoing, Completed, Shortclose, (empty)

        # ── Normalize Supplier Type casing ───────────────────
        sup_type_col = next((c for c in df.columns if 'supplier' in c.lower() and 'type' in c.lower()), None)
        if sup_type_col:
            df[sup_type_col] = df[sup_type_col].fillna('').astype(str).str.strip()

        return df, None

    except Exception as e:
        return pd.DataFrame(), str(e)


# ── Load Ongoing Sheet ────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_ongoing():
    try:
        gc = gclient()
        sh = gc.open_by_key(SHEET_ID)
        ws = None
        for tab in ["ongoing updated with realized27", "ongoing"]:
            try:
                ws = sh.worksheet(tab)
                break
            except Exception:
                continue
        if not ws:
            return pd.DataFrame(), "Ongoing tab not found"

        data = ws.get_all_values(value_render_option='FORMATTED_VALUE')
        if len(data) < 3:
            return pd.DataFrame(), "Empty"

        # Row 0 = title row, Row 1 = headers, data from Row 2
        headers = [str(c).strip() for c in data[1]]
        df = pd.DataFrame(data[2:], columns=headers)

        # Filter real rows (has BU)
        bu_col = next((c for c in df.columns if c.strip().upper() == 'BU'), None)
        if bu_col:
            df = df[df[bu_col].astype(str).str.strip().ne('') &
                    df[bu_col].astype(str).str.strip().ne('nan')].copy()
        else:
            df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()

        # Parse numerics
        val_keywords = ['value', 'deliver', 'saving', 'amount']
        for c in df.columns:
            if any(x in c.lower() for x in val_keywords):
                df[c] = pd.to_numeric(
                    df[c].astype(str).str.replace(',', '').str.strip(),
                    errors='coerce'
                ).fillna(0)

        # Parse dates
        for c in df.columns:
            if any(x in c.lower() for x in ['date', 'dt']):
                df[c] = pd.to_datetime(df[c], errors='coerce', dayfirst=True)

        return df, None

    except Exception as e:
        return pd.DataFrame(), str(e)


# ── Column finder helper ──────────────────────────────────────
def fcol(df, *keywords):
    """Find first column matching all keywords (case-insensitive)."""
    for c in df.columns:
        cl = c.lower()
        if all(k.lower() in cl for k in keywords):
            return c
    return None


# ── CAT 2 Buddy chatbot ───────────────────────────────────────
def buddy_chat(question, df_po, df_ong):
    try:
        import anthropic
        key = None
        for k in ["ANTHROPIC_API_KEY", "anthropic_api_key", "ANTHROPIC_KEY"]:
            try:
                v = st.secrets.get(k)
                if v:
                    key = v
                    break
            except Exception:
                pass
        if not key:
            try:
                visible = list(st.secrets.keys())
            except Exception:
                visible = []
            return f"API key not found. Keys visible: {visible}. Add ANTHROPIC_API_KEY to Streamlit Secrets (outside the [gcp_service_account] block)."

        # Build data context
        n_po = len(df_po)
        n_pr = len(df_po)

        po_val_col = fcol(df_po, 'po', 'basic', 'value') or fcol(df_po, 'po basic')
        sav_col = fcol(df_po, 'savings', 'value') or fcol(df_po, 'saving')

        spend = 0
        if po_val_col and po_val_col in df_po.columns:
            spend = pd.to_numeric(df_po[po_val_col], errors='coerce').sum() / 1e7

        savings = 0
        if sav_col and sav_col in df_po.columns:
            savings = pd.to_numeric(df_po[sav_col], errors='coerce').sum() / 1e7

        bu_breakdown = {}
        if 'BU' in df_po.columns and po_val_col:
            bu_breakdown = {
                str(bu): round(float(val) / 1e7, 2)
                for bu, val in df_po.groupby('BU')[po_val_col].sum().items()
                if pd.notna(val)
            }

        ongoing_val = 0
        if not df_ong.empty:
            ytd_col = fcol(df_ong, 'yet to') or fcol(df_ong, 'deliver')
            if ytd_col:
                ongoing_val = pd.to_numeric(df_ong[ytd_col], errors='coerce').sum() / 1e7

        context = f"""You are CAT 2 Buddy, procurement assistant for Zetwerk CPT CAT-2 team. 
Never mention Claude or Anthropic. Answer in Rs Crores (Cr), be precise and concise.

Current FY 2026-27 snapshot:
- Total PRs raised: {n_pr}
- POs placed: {df_po[df_po[fcol(df_po,'po','dt') or 'PO Dt.'].notna()].shape[0] if fcol(df_po,'po','dt') else 'N/A'}
- Total spend (PO Basic Value): Rs {spend:.2f} Cr
- Savings achieved: Rs {savings:.2f} Cr ({savings/spend*100:.1f}% if spend else 0)
- Carry-forward POs yet to deliver: Rs {ongoing_val:.2f} Cr
- BU-wise spend (Cr): {bu_breakdown}

Answer the user's question based on this data."""

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": context + "\n\nQ: " + question}]
        )
        return resp.content[0].text

    except ImportError:
        return "anthropic package missing — add to requirements.txt"
    except Exception as e:
        return f"Error: {e}"


# ── Load data ─────────────────────────────────────────────────
with st.spinner(""):
    df_po, po_err = load_po_tracker()
    df_ong, ong_err = load_ongoing()

if 'buddy_msgs' not in st.session_state:
    st.session_state.buddy_msgs = [{"role": "bot", "text": "Hi! I am CAT 2 Buddy. Ask me anything about CAT-2 procurement."}]

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap');
*{font-family:'DM Sans',sans-serif!important;box-sizing:border-box;}
[data-testid="stAppViewContainer"]{background:#0d0d1a!important;}
[data-testid="stMainBlockContainer"],[data-testid="stAppViewBlockContainer"],
section[data-testid="stMain"]>div,.block-container{
  max-width:100%!important;width:100%!important;padding:0 20px!important;}
[data-testid="stSidebar"]{display:none!important;}
[data-testid="stHorizontalBlock"]{gap:10px!important;}
.zN{background:#13131a;border-bottom:1px solid rgba(255,255,255,0.07);padding:0 24px;
display:flex;align-items:center;justify-content:space-between;height:52px;margin:0 -20px 8px;}
.zNL{display:flex;align-items:center;gap:10px;}
.zZ{width:32px;height:32px;background:linear-gradient(135deg,#e53e3e,#fc4f4f);border-radius:8px;
display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:900;color:white;}
.zB{font-size:14px;font-weight:700;color:white;}
.zS{font-size:10px;color:#444;}
.zR{display:flex;align-items:center;gap:10px;}
.zP{background:rgba(229,62,62,0.12);border:1px solid rgba(229,62,62,0.3);color:#fc4f4f;
padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;}
.zL{display:flex;align-items:center;gap:5px;font-size:11px;color:#38a169;}
.zD{width:7px;height:7px;background:#38a169;border-radius:50%;animation:p 2s infinite;}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
.kG{display:grid;gap:10px;padding:4px 0;}
.k5{grid-template-columns:repeat(5,1fr)}.k4{grid-template-columns:repeat(4,1fr)}.k3{grid-template-columns:repeat(3,1fr)}
.kC{background:#13131a;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:14px 16px;
position:relative;overflow:hidden;}
.kC::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;border-radius:12px 12px 0 0;}
.cR::before{background:#e53e3e}.cG::before{background:#38a169}.cB::before{background:#3182ce}
.cA::before{background:#d69e2e}.cP::before{background:#805ad5}.cT::before{background:#2c7a7b}
.kL{font-size:10px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.06em;}
.kV{font-size:24px;font-weight:800;color:#fff;line-height:1.1;margin:3px 0;font-family:'DM Mono',monospace!important;}
.kS{font-size:10px;color:#555;}.kD{font-size:10px;font-weight:600;margin-top:3px;}
.up{color:#68d391}.dn{color:#fc8181}.wn{color:#f6e05e}
[data-testid="stTabs"] button[role="tab"]{font-size:12px!important;font-weight:500!important;color:#555!important;}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#fc4f4f!important;border-bottom:2px solid #e53e3e!important;}
[data-testid="stSelectbox"] label{font-size:10px!important;color:#666!important;font-weight:700!important;text-transform:uppercase;}
[data-testid="stSelectbox"]>div>div{background:#13131a!important;border:1px solid rgba(255,255,255,0.1)!important;
border-radius:8px!important;color:#ccc!important;font-size:13px!important;}
[data-testid="stMetric"]{background:#13131a!important;border-radius:10px!important;padding:12px!important;
border:1px solid rgba(255,255,255,0.07)!important;}
[data-testid="stMetricValue"]{font-size:22px!important;font-weight:800!important;color:#fff!important;font-family:'DM Mono',monospace!important;}
[data-testid="stMetricLabel"]{font-size:10px!important;color:#666!important;text-transform:uppercase;}
.zT{width:100%;border-collapse:collapse;font-size:12px;}
.zT th{text-align:left;padding:8px 12px;font-size:10px;font-weight:700;color:#555;text-transform:uppercase;
letter-spacing:.05em;border-bottom:1px solid rgba(255,255,255,0.07);}
.zT td{padding:8px 12px;color:#bbb;border-bottom:1px solid rgba(255,255,255,0.03);font-size:12px;}
.zT tr:hover td{background:rgba(255,255,255,0.02);}
.mn{font-family:'DM Mono',monospace!important;font-size:11px;}
.pg{background:rgba(56,161,105,.15);color:#68d391;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.pr{background:rgba(229,62,62,.15);color:#fc8181;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.pa{background:rgba(214,158,46,.15);color:#f6e05e;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.st-inf{font-size:12px;color:#888;background:rgba(255,255,255,.04);padding:10px 14px;border-radius:8px;border-left:3px solid #444;}
</style>""", unsafe_allow_html=True)


# ── Nav bar ───────────────────────────────────────────────────
now_str = datetime.now().strftime("%d %b %Y %H:%M")
st.markdown(f"""<div class="zN">
<div class="zNL">
  <div class="zZ">Z</div>
  <div><div class="zB">Zetwerk CPT</div><div class="zS">Central Procurement Team &middot; CAT-2</div></div>
</div>
<div class="zR">
  <div class="zL"><div class="zD"></div>Live &middot; {now_str}</div>
  <div class="zP">FY 2026-27</div>
</div>
</div>""", unsafe_allow_html=True)

if df_po.empty:
    st.error(f"Sheet load error: {po_err}")
    st.stop()


# ── Identify key columns ──────────────────────────────────────
C_BU        = 'BU'
C_PR_DT     = fcol(df_po, 'pr', 'dt') or fcol(df_po, 'pr dt')
C_REV_PR    = fcol(df_po, 'rev', 'pr') or fcol(df_po, 'rev. pr')
C_PO_DT     = fcol(df_po, 'po', 'dt') or fcol(df_po, 'po dt')
C_PO_VAL    = fcol(df_po, 'po', 'basic', 'value') or fcol(df_po, 'po basic')
C_PO_VAL_GST = fcol(df_po, 'po value', 'gst') or fcol(df_po, 'po value with gst')
C_PCA       = fcol(df_po, 'pca', 'basic') or fcol(df_po, 'pca basic')
C_SAV       = fcol(df_po, 'savings', 'value') or fcol(df_po, 'saving')
C_SAV_PCT   = fcol(df_po, 'savings', '%') or fcol(df_po, 'saving', '%')
C_TAT       = fcol(df_po, 'pr', 'po', 'tat') or fcol(df_po, 'pr - po')
C_STYPE     = fcol(df_po, 'supplier', 'type') or fcol(df_po, 'supplier type')
C_PAY       = fcol(df_po, 'payment', 'term') or fcol(df_po, 'payment term')
C_MFC_DT    = fcol(df_po, 'mfc', 'dt') or fcol(df_po, 'mfc dt')
C_MFC_DAYS  = fcol(df_po, 'delivery time', 'mfc') or fcol(df_po, 'mfc', 'days') or fcol(df_po, 'delivery time from mfc')
C_DEL_ST    = fcol(df_po, 'delivery', 'status') or fcol(df_po, 'delivery status')
C_OTIF      = fcol(df_po, 'otif')
C_CUR_ST    = fcol(df_po, 'current', 'status') or fcol(df_po, 'current status')
C_YTD       = fcol(df_po, 'yet to be') or fcol(df_po, 'yet to', 'deliver')
C_DELIVERED = fcol(df_po, 'delivered', 'value') or fcol(df_po, 'po delivered')
C_CATEGORY  = 'Category' if 'Category' in df_po.columns else None
C_HANDLER   = fcol(df_po, 'handled by') or 'Handled by'
C_NFA_DT    = fcol(df_po, 'nfa', 'dt') or fcol(df_po, 'nfa dt')
C_NFA_APP   = fcol(df_po, 'nfa', 'app') or fcol(df_po, 'nfa app')
C_SUPPLIER  = fcol(df_po, 'supplier', 'name') or 'Supplier Name'


# ── Global filters ────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.4])

with c1:
    bu_opts = ['All'] + sorted([b for b in df_po[C_BU].dropna().unique() if str(b).strip()])
    sel_bu = st.selectbox('BU', bu_opts, key='g_bu')

with c2:
    cat_opts = ['All']
    if C_CATEGORY and C_CATEGORY in df_po.columns:
        cat_opts += sorted([c for c in df_po[C_CATEGORY].dropna().unique() if str(c).strip()])
    sel_cat = st.selectbox('Category', cat_opts, key='g_cat')

with c3:
    buyer_opts = ['All']
    if C_HANDLER in df_po.columns:
        buyer_opts += sorted([h for h in df_po[C_HANDLER].dropna().unique() if str(h).strip()])
    sel_buyer = st.selectbox('Buyer', buyer_opts, key='g_buyer')

with c4:
    stype_opts = ['All']
    if C_STYPE and C_STYPE in df_po.columns:
        stype_opts += sorted([s for s in df_po[C_STYPE].dropna().unique() if str(s).strip()])
    sel_st = st.selectbox('Supplier Type', stype_opts, key='g_st')

with c5:
    st.markdown("<div style='padding-top:18px;'>", unsafe_allow_html=True)
    if st.button("⟳ Refresh"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# ── Apply filters ─────────────────────────────────────────────
dff = df_po.copy()
if sel_bu != 'All':
    dff = dff[dff[C_BU] == sel_bu]
if sel_cat != 'All' and C_CATEGORY and C_CATEGORY in dff.columns:
    dff = dff[dff[C_CATEGORY] == sel_cat]
if sel_buyer != 'All' and C_HANDLER in dff.columns:
    dff = dff[dff[C_HANDLER] == sel_buyer]
if sel_st != 'All' and C_STYPE and C_STYPE in dff.columns:
    dff = dff[dff[C_STYPE] == sel_st]


# ── Derived subsets ───────────────────────────────────────────
# All PRs = rows with PR date filled
if C_PR_DT and C_PR_DT in dff.columns:
    pr_dates = pd.to_datetime(dff[C_PR_DT], errors='coerce')
else:
    pr_dates = pd.Series(dtype='datetime64[ns]', index=dff.index)

# All POs = rows with PO date filled
if C_PO_DT and C_PO_DT in dff.columns:
    po_dates = pd.to_datetime(dff[C_PO_DT], errors='coerce')
else:
    po_dates = pd.Series(dtype='datetime64[ns]', index=dff.index)

has_pr = pr_dates.notna()
has_po = po_dates.notna()

df_prs = dff[has_pr].copy()         # All PRs (with PR date)
df_pos = dff[has_po].copy()         # All POs (with PO date)
df_unclosed = dff[has_pr & ~has_po].copy()  # PRs not yet converted to PO

n_prs = len(df_prs)
n_pos = len(df_pos)
n_unclosed = len(df_unclosed)

# ── KPI calculations ──────────────────────────────────────────
def safe_sum(df, col):
    if col and col in df.columns:
        return pd.to_numeric(df[col], errors='coerce').fillna(0).sum()
    return 0.0

def safe_mean(df, col, positive_only=True):
    if col and col in df.columns:
        s = pd.to_numeric(df[col], errors='coerce').dropna()
        if positive_only:
            s = s[s > 0]
        return float(s.mean()) if len(s) > 0 else 0.0
    return 0.0

spend     = safe_sum(df_pos, C_PO_VAL) / 1e7
savings   = safe_sum(df_pos, C_SAV) / 1e7
sav_pct   = (savings / spend * 100) if spend > 0 else 0.0
avg_tat   = safe_mean(df_pos, C_TAT, positive_only=True)

# Delivery status (Ongoing / Completed / Shortclose)
if C_DEL_ST and C_DEL_ST in df_pos.columns:
    del_status_series = df_pos[C_DEL_ST].fillna('').astype(str).str.strip().str.lower()
    df_completed   = df_pos[del_status_series.isin(['completed', 'shortclose'])]
    df_ongoing_po  = df_pos[del_status_series == 'ongoing']
    n_completed    = len(df_completed)
    n_ongoing_po   = len(df_ongoing_po)
else:
    df_completed  = pd.DataFrame(columns=df_pos.columns)
    df_ongoing_po = df_pos.copy()  # all POs are ongoing if no status
    n_completed   = 0
    n_ongoing_po  = n_pos

# OTIF — only from completed POs
# Sheet formula =AC/T returns a ratio (e.g. 0.95 = 95%, 1.23 = 123%).
# FORMATTED_VALUE may return "95%" (percent-formatted cell) or "0.95" (number-formatted).
# Normalise: strip %, parse, then if value > 2 assume it was already a percentage → divide by 100.
otif_pct = 0.0
otif_n   = 0
if C_OTIF and C_OTIF in df_completed.columns and len(df_completed) > 0:
    raw = df_completed[C_OTIF].astype(str).str.replace(',', '').str.strip()
    is_pct_fmt = raw.str.endswith('%')
    ov = pd.to_numeric(raw.str.replace('%', ''), errors='coerce').dropna()
    # If cell was %-formatted, FORMATTED_VALUE already multiplied by 100 → divide back
    ov = ov.copy()
    ov[is_pct_fmt[ov.index]] = ov[is_pct_fmt[ov.index]] / 100
    ov = ov[ov > 0]
    otif_n = len(ov)
    if otif_n > 0:
        otif_pct = float((ov <= 1.05).sum() / otif_n * 100)

# New Vendor Development
nv_n   = 0
nv_pct = 0.0
if C_STYPE and C_STYPE in df_pos.columns:
    nv_mask = df_pos[C_STYPE].astype(str).str.upper().str.contains('NV', na=False)
    nv_n    = int(nv_mask.sum())
    nv_pct  = (nv_n / n_pos * 100) if n_pos > 0 else 0.0

# WC Score = Σ(PayScore × PO Basic Value) / Σ(PO Basic Value)
wc_score = None
if '_PayScore' in df_pos.columns and C_PO_VAL and C_PO_VAL in df_pos.columns:
    wcs = df_pos[df_pos['_PayScore'].notna() & (pd.to_numeric(df_pos[C_PO_VAL], errors='coerce') > 0)].copy()
    if len(wcs) > 0:
        pv = pd.to_numeric(wcs[C_PO_VAL], errors='coerce').fillna(0)
        wc_score = float((wcs['_PayScore'] * pv).sum() / pv.sum()) if pv.sum() > 0 else None

cn = dff[C_CATEGORY].nunique() if C_CATEGORY and C_CATEGORY in dff.columns else 0
sn = dff[C_SUPPLIER].nunique() if C_SUPPLIER in dff.columns else 0


# ── Chart theme ───────────────────────────────────────────────
DK = dict(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="#888", size=12),
    xaxis=dict(gridcolor="rgba(255,255,255,0.04)", tickcolor="#444", linecolor="#333"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.04)", tickcolor="#444", linecolor="#333"),
    margin=dict(l=8, r=8, t=32, b=8)
)
CLR_RED   = "#e53e3e"
CLR_GREEN = "#38a169"
CLR_AMBER = "#d69e2e"
CLR_BLUE  = "#3182ce"
CLR_PURP  = "#805ad5"


def kc(val, lbl, sub="", delta="", dcls="", ccls="cB"):
    d = f'<div class="kD {dcls}">{delta}</div>' if delta else ''
    return f'<div class="kC {ccls}"><div class="kL">{lbl}</div><div class="kV">{val}</div><div class="kS">{sub}</div>{d}</div>'


# ═══════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════
t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
    "Overview", "Spend & Savings", "TAT & OTIF",
    "Working Capital", "New Vendor Dev", "MFC Tracker",
    "Ongoing POs", "PR-PO Unclosed"
])


# ════ TAB 1: OVERVIEW ════════════════════════════════════════
with t1:
    wc_disp   = f"{wc_score:.2f}" if wc_score else "—"
    wc_delta  = "Above 4.5" if wc_score and wc_score >= 4.5 else ("Below 4.5" if wc_score else "No data")
    wc_dcls   = "up" if wc_score and wc_score >= 4.5 else "wn"
    wc_ccls   = "cG" if wc_score and wc_score >= 4.5 else "cR" if wc_score else "cP"

    st.markdown(f"""<div class="kG k5">
{kc(str(n_pos), "POs Placed", f"{n_prs} PRs &middot; {n_unclosed} unclosed", "", "", "cB")}
{kc(f"Rs {spend:.1f} Cr", "Total Spend", "PO Basic Value", "", "", "cG")}
{kc(f"Rs {savings:.2f} Cr", "Savings", f"{sav_pct:.1f}% of spend",
    "≥ 4.5%" if sav_pct >= 4.5 else "< 4.5%", "up" if sav_pct >= 4.5 else "wn",
    "cG" if sav_pct >= 4.5 else "cA")}
{kc(f"{avg_tat:.0f}d" if avg_tat > 0 else "—", "Avg PR-PO TAT", "Target: 90 days",
    "On track" if 0 < avg_tat <= 90 else ("Above target" if avg_tat > 90 else "No data"),
    "up" if 0 < avg_tat <= 90 else "dn", "cG" if 0 < avg_tat <= 90 else ("cR" if avg_tat > 90 else "cP"))}
{kc(wc_disp, "WC Score", "Target: 4.5", wc_delta, wc_dcls, wc_ccls)}
</div>

<div class="kG k4" style="margin-top:8px;">
{kc(f"{otif_pct:.1f}%" if otif_n > 0 else "—", "OTIF",
    f"{otif_n} completed POs" if otif_n > 0 else "No completed POs yet",
    "≥ 75%" if otif_pct >= 75 else ("< 75%" if otif_n > 0 else ""),
    "up" if otif_pct >= 75 else "dn", "cG" if otif_pct >= 75 else ("cR" if otif_n > 0 else "cP"))}
{kc(f"{nv_pct:.1f}%", "New Vendor Dev", f"{nv_n} NV of {n_pos} POs",
    "Target 10–15%", "up" if 10 <= nv_pct <= 15 else "wn",
    "cG" if 10 <= nv_pct <= 15 else "cA")}
{kc(str(cn), "Categories", "Unique categories", "", "", "cT")}
{kc(str(sn), "Suppliers", "Unique suppliers", "", "", "cP")}
</div>""", unsafe_allow_html=True)

    # Charts
    c1, c2 = st.columns(2)

    with c1:
        if C_PO_VAL and C_PO_VAL in df_pos.columns and len(df_pos) > 0:
            bg = df_pos.groupby(C_BU).agg(
                spend=(C_PO_VAL, 'sum'),
                saves=(C_SAV, 'sum') if C_SAV and C_SAV in df_pos.columns else (C_PO_VAL, 'count')
            ).reset_index()
            bg['spend_cr'] = bg['spend'] / 1e7
            bg['save_cr']  = bg['saves'] / 1e7 if C_SAV else 0
            fig = go.Figure()
            fig.add_trace(go.Bar(name='Spend', x=bg[C_BU], y=bg['spend_cr'],
                                 marker_color=CLR_RED, marker_line_width=0))
            if C_SAV and C_SAV in df_pos.columns:
                fig.add_trace(go.Bar(name='Savings', x=bg[C_BU], y=bg['save_cr'],
                                     marker_color='rgba(56,161,105,0.7)', marker_line_width=0))
            fig.update_layout(**DK, height=280, barmode='group',
                              title_text='Spend & Savings by BU (Rs Cr)',
                              legend=dict(orientation='h', y=1.12, x=1, xanchor='right',
                                          bgcolor='rgba(0,0,0,0)', font=dict(color='#888', size=11)))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.markdown('<div class="st-inf">No PO data for spend chart.</div>', unsafe_allow_html=True)

    with c2:
        if C_CATEGORY and C_CATEGORY in df_pos.columns and C_PO_VAL and C_PO_VAL in df_pos.columns and len(df_pos) > 0:
            cg = df_pos.groupby(C_CATEGORY)[C_PO_VAL].sum().sort_values(ascending=False).head(10).reset_index()
            cg['sc'] = cg[C_PO_VAL] / 1e7
            fig2 = go.Figure(go.Bar(
                y=cg[C_CATEGORY], x=cg['sc'], orientation='h',
                marker_color=CLR_RED, marker_line_width=0,
                text=cg['sc'].apply(lambda x: f'Rs {x:.1f}Cr'),
                textposition='outside', textfont=dict(color='#888', size=11)
            ))
            fig2.update_layout(**DK, height=280, title_text='Top Categories by Spend')
            st.plotly_chart(fig2, use_container_width=True)
        else:
            # Show category distribution of PRs instead
            if C_CATEGORY and C_CATEGORY in dff.columns:
                cg2 = dff[C_CATEGORY].value_counts().head(10).reset_index()
                cg2.columns = ['Category', 'Count']
                fig2 = go.Figure(go.Bar(
                    y=cg2['Category'], x=cg2['Count'], orientation='h',
                    marker_color='rgba(49,130,206,0.7)', marker_line_width=0,
                    text=cg2['Count'], textposition='outside',
                    textfont=dict(color='#888', size=11)
                ))
                fig2.update_layout(**DK, height=280, title_text='PRs by Category (all)')
                st.plotly_chart(fig2, use_container_width=True)

    # Pipeline funnel
    st.markdown("#### Procurement Pipeline")
    c1, c2, c3, c4, c5 = st.columns(5)
    stages = [
        ("PRs Raised", n_prs, "#3182ce"),
        ("TQR Done", int(df_prs[C_REV_PR if C_REV_PR and C_REV_PR in df_prs.columns else C_PR_DT].notna().sum()) if C_REV_PR and C_REV_PR in df_prs.columns else 0, "#805ad5"),
        ("NFA Submitted", int(df_prs[C_NFA_DT].notna().sum()) if C_NFA_DT and C_NFA_DT in df_prs.columns else 0, "#d69e2e"),
        ("POs Placed", n_pos, "#38a169"),
        ("Delivered", n_completed, "#2c7a7b"),
    ]
    for col, (label, count, color) in zip([c1, c2, c3, c4, c5], stages):
        with col:
            st.markdown(f"""<div class="kC" style="border-top:2px solid {color};text-align:center;">
<div class="kL">{label}</div>
<div class="kV" style="font-size:28px;color:{color};">{count}</div>
</div>""", unsafe_allow_html=True)


# ════ TAB 2: SPEND & SAVINGS ════════════════════════════════
with t2:
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Total Spend", f"Rs {spend:.2f} Cr")
    with c2: st.metric("Total Savings", f"Rs {savings:.2f} Cr", f"{sav_pct:.1f}%")
    with c3: st.metric("vs Target 4.5%", f"{sav_pct:.1f}%", f"{sav_pct - 4.5:+.1f}pp")
    with c4: st.metric("POs / PRs", f"{n_pos} / {n_prs}")

    c1, c2 = st.columns(2)

    with c1:
        # Monthly trend by PO date
        if C_PO_DT and C_PO_DT in df_pos.columns and len(df_pos) > 0:
            dft = df_pos.copy()
            dft['_pod'] = pd.to_datetime(dft[C_PO_DT], errors='coerce')
            dft = dft[dft['_pod'].notna()]
            dft['Month'] = dft['_pod'].dt.to_period('M').astype(str)
            mo = dft.groupby('Month').agg(
                spend=(C_PO_VAL, 'sum'),
                saves=(C_SAV, 'sum') if C_SAV and C_SAV in dft.columns else (C_PO_VAL, 'count'),
                count=(C_PO_VAL, 'count')
            ).reset_index()
            mo['sc'] = mo['spend'] / 1e7
            mo['svc'] = mo['saves'] / 1e7 if C_SAV else 0
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(name='Spend', x=mo['Month'], y=mo['sc'],
                                  marker_color='rgba(229,62,62,.3)', marker_line_width=0))
            if C_SAV and C_SAV in dft.columns:
                fig3.add_trace(go.Scatter(
                    name='Savings', x=mo['Month'], y=mo['svc'],
                    line=dict(color=CLR_GREEN, width=2.5),
                    mode='lines+markers', marker=dict(size=5), yaxis='y2'
                ))
            d2 = {k: v for k, v in DK.items() if k not in ('yaxis',)}
            fig3.update_layout(
                **d2, height=300, title_text='Monthly PO Trend',
                yaxis=dict(title='Spend Rs Cr', gridcolor='rgba(255,255,255,0.04)'),
                yaxis2=dict(title='Savings Cr', overlaying='y', side='right',
                            gridcolor='rgba(0,0,0,0)'),
                legend=dict(orientation='h', y=1.12, x=1, xanchor='right',
                            bgcolor='rgba(0,0,0,0)', font=dict(color='#888', size=11))
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.markdown('<div class="st-inf">Monthly trend available once more POs are placed.</div>', unsafe_allow_html=True)

    with c2:
        # BU breakdown table
        if C_PO_VAL and C_PO_VAL in df_pos.columns and len(df_pos) > 0:
            bs = df_pos.groupby(C_BU).agg(
                n=(C_PO_VAL, 'count'),
                spend=(C_PO_VAL, 'sum'),
                saves=(C_SAV, 'sum') if C_SAV and C_SAV in df_pos.columns else (C_PO_VAL, 'count')
            ).reset_index()
            bs['sp_pct'] = (bs['saves'] / bs['spend'] * 100).fillna(0) if C_SAV else 0
            rows_html = ""
            for _, r in bs.sort_values('spend', ascending=False).iterrows():
                pill = "pg" if r['sp_pct'] >= 4.5 else ("pr" if r['sp_pct'] < 0 else "pa")
                sav_str = f"Rs {r['saves']/1e7:.2f}Cr" if C_SAV else "—"
                rows_html += f'<tr><td><b style="color:#eee">{r[C_BU]}</b></td><td class="mn">Rs {r["spend"]/1e7:.2f}Cr</td><td class="mn">{sav_str}</td><td><span class="{pill}">{r["sp_pct"]:.1f}%</span></td><td class="mn">{int(r["n"])}</td></tr>'
            st.markdown(f'''<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:6px 0;">
<table class="zT"><thead><tr><th>BU</th><th>Spend</th><th>Savings</th><th>%</th><th>POs</th></tr></thead>
<tbody>{rows_html}</tbody></table></div>''', unsafe_allow_html=True)
        else:
            st.markdown('<div class="st-inf">No POs placed yet — spend data will appear once PO dates are filled.</div>', unsafe_allow_html=True)

    # Savings by category
    if C_CATEGORY and C_CATEGORY in df_pos.columns and C_SAV and C_SAV in df_pos.columns and len(df_pos) > 0:
        cg = df_pos.groupby(C_CATEGORY).agg(
            spend=(C_PO_VAL, 'sum'), saves=(C_SAV, 'sum')
        ).reset_index()
        cg['sp_pct'] = (cg['saves'] / cg['spend'] * 100).fillna(0)
        cg = cg[cg['spend'] > 0].sort_values('sp_pct', ascending=False)
        if len(cg) > 0:
            fig_cat = go.Figure(go.Bar(
                x=cg[C_CATEGORY], y=cg['sp_pct'],
                marker_color=[CLR_GREEN if v >= 4.5 else CLR_RED for v in cg['sp_pct']],
                marker_line_width=0,
                text=cg['sp_pct'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#888', size=11)
            ))
            fig_cat.add_hline(y=4.5, line_dash='dash', line_color=CLR_AMBER,
                              annotation_text='4.5%', annotation_font_color=CLR_AMBER)
            fig_cat.update_layout(**DK, height=260, title_text='Savings % by Category',
                                  showlegend=False)
            st.plotly_chart(fig_cat, use_container_width=True)


# ════ TAB 3: TAT & OTIF ════════════════════════════════════
with t3:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Avg PR-PO TAT", f"{avg_tat:.0f}d" if avg_tat > 0 else "—",
                  f"{avg_tat - 90:+.0f}d vs 90d target" if avg_tat > 0 else "No POs yet")
    with c2:
        st.metric("OTIF", f"{otif_pct:.1f}%" if otif_n > 0 else "—",
                  f"{otif_n} completed POs" if otif_n > 0 else "Awaiting completions")
    with c3:
        st.metric("Completed POs", str(n_completed),
                  f"{n_completed/n_pos*100:.0f}% of POs" if n_pos > 0 else "—")
    with c4:
        st.metric("Ongoing POs", str(n_ongoing_po))

    c1, c2 = st.columns(2)

    with c1:
        # TAT by BU
        if C_TAT and C_TAT in df_pos.columns and len(df_pos) > 0:
            bt = df_pos.groupby(C_BU).apply(
                lambda x: pd.to_numeric(x[C_TAT], errors='coerce').dropna()
            )
            bt_summary = []
            for bu_name, vals in bt.items():
                vals_pos = vals[vals > 0]
                if len(vals_pos) > 0:
                    bt_summary.append({'BU': bu_name, 'TAT': float(vals_pos.mean()), 'n': len(vals_pos)})
            if bt_summary:
                bt_df = pd.DataFrame(bt_summary)
                fig4 = go.Figure(go.Bar(
                    x=bt_df['BU'], y=bt_df['TAT'],
                    marker_color=[CLR_GREEN if v <= 90 else CLR_RED for v in bt_df['TAT']],
                    marker_line_width=0,
                    text=bt_df['TAT'].apply(lambda x: f'{x:.0f}d'),
                    textposition='outside', textfont=dict(color='#888', size=11)
                ))
                fig4.add_hline(y=90, line_dash='dash', line_color=CLR_AMBER,
                               annotation_text='90d target', annotation_font_color=CLR_AMBER)
                fig4.update_layout(**DK, height=280, title_text='Avg TAT by BU', showlegend=False)
                st.plotly_chart(fig4, use_container_width=True)
            else:
                st.markdown('<div class="st-inf">TAT data available once POs are placed.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="st-inf">TAT data available once POs are placed.</div>', unsafe_allow_html=True)

    with c2:
        # TAT distribution histogram
        if C_TAT and C_TAT in df_pos.columns and len(df_pos) > 0:
            tat_vals = pd.to_numeric(df_pos[C_TAT], errors='coerce').dropna()
            tat_vals = tat_vals[tat_vals > 0]
            if len(tat_vals) > 1:
                fig_tat = go.Figure(go.Histogram(
                    x=tat_vals, nbinsx=20,
                    marker_color='rgba(49,130,206,0.6)',
                    marker_line_color='rgba(49,130,206,0.9)',
                    marker_line_width=1
                ))
                fig_tat.add_vline(x=90, line_dash='dash', line_color=CLR_AMBER,
                                  annotation_text='90d', annotation_font_color=CLR_AMBER)
                fig_tat.update_layout(**DK, height=280, title_text='TAT Distribution (days)',
                                      showlegend=False)
                st.plotly_chart(fig_tat, use_container_width=True)
        else:
            # Show PR pipeline aging instead
            if C_PR_DT and C_PR_DT in df_unclosed.columns and len(df_unclosed) > 0:
                today = pd.Timestamp(date.today())
                pr_ages = (today - pd.to_datetime(df_unclosed[C_PR_DT], errors='coerce')).dt.days.dropna()
                pr_ages = pr_ages[pr_ages >= 0]
                if len(pr_ages) > 0:
                    fig_age = go.Figure(go.Histogram(
                        x=pr_ages, nbinsx=15,
                        marker_color='rgba(214,158,46,0.6)',
                        marker_line_color=CLR_AMBER, marker_line_width=1
                    ))
                    fig_age.add_vline(x=90, line_dash='dash', line_color=CLR_RED,
                                      annotation_text='90d', annotation_font_color=CLR_RED)
                    fig_age.update_layout(**DK, height=280,
                                          title_text='Unclosed PR Age Distribution (days)',
                                          showlegend=False)
                    st.plotly_chart(fig_age, use_container_width=True)

    # OTIF by BU (only if completions exist)
    if n_completed > 0 and C_OTIF and C_OTIF in df_completed.columns:
        otif_bu = []
        for bu_name in df_completed[C_BU].dropna().unique():
            s = df_completed[df_completed[C_BU] == bu_name]
            v = pd.to_numeric(s[C_OTIF].astype(str).str.replace('%', ''), errors='coerce').dropna()
            v = v[v > 0]
            if len(v) > 0:
                otif_bu.append({'BU': bu_name, 'OTIF%': float((v <= 1.05).sum() / len(v) * 100)})
        if otif_bu:
            bo = pd.DataFrame(otif_bu)
            fig5 = go.Figure(go.Bar(
                x=bo['BU'], y=bo['OTIF%'],
                marker_color=[CLR_GREEN if v >= 75 else CLR_RED for v in bo['OTIF%']],
                marker_line_width=0,
                text=bo['OTIF%'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#888', size=11)
            ))
            fig5.add_hline(y=75, line_dash='dash', line_color=CLR_AMBER,
                           annotation_text='75% target', annotation_font_color=CLR_AMBER)
            fig5.update_layout(**DK, height=260, title_text='OTIF % by BU',
                               showlegend=False, yaxis_range=[0, 115])
            st.plotly_chart(fig5, use_container_width=True)
    else:
        st.markdown('<div class="st-inf" style="margin-top:12px;">OTIF will be calculated once deliveries are completed (Delivery Status = Completed).</div>', unsafe_allow_html=True)


# ════ TAB 4: WORKING CAPITAL ════════════════════════════════
with t4:
    if '_PayScore' in df_pos.columns and C_PAY and C_PAY in df_pos.columns:
        wcs_df = df_pos[df_pos['_PayScore'].notna()].copy()
        wcs_df['_PV'] = pd.to_numeric(wcs_df[C_PO_VAL], errors='coerce').fillna(0) if C_PO_VAL else 0

        n_with_terms = int(wcs_df['_PayScore'].notna().sum())
        n_advance = int((wcs_df['_PayScore'] < 0).sum())
        adv_pct = (n_advance / len(wcs_df) * 100) if len(wcs_df) > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("WC Score", f"{wc_score:.2f}" if wc_score else "—",
                      f"{'≥ 4.5 ✓' if wc_score and wc_score >= 4.5 else '< 4.5 ✗'}")
        with c2:
            st.metric("POs with Terms", f"{n_with_terms} / {n_pos}")
        with c3:
            st.metric("Advance Payment POs", str(n_advance), f"{adv_pct:.1f}%")
        with c4:
            high_wc = int((wcs_df['_PayScore'] >= 5).sum())
            st.metric("High WC Score (≥5)", str(high_wc), f"{high_wc/len(wcs_df)*100:.0f}% of POs" if len(wcs_df) > 0 else "")

        # Payment terms distribution
        if C_PAY and len(df_pos) > 0:
            pt_vc = df_pos[C_PAY].dropna().astype(str).str.strip()
            pt_vc = pt_vc[pt_vc.ne('')].value_counts().head(10).reset_index()
            pt_vc.columns = ['Term', 'Count']
            if len(pt_vc) > 0:
                fig_pt = go.Figure(go.Bar(
                    y=pt_vc['Term'], x=pt_vc['Count'], orientation='h',
                    marker_color=CLR_BLUE, marker_line_width=0,
                    text=pt_vc['Count'], textposition='outside',
                    textfont=dict(color='#888', size=11)
                ))
                fig_pt.update_layout(**DK, height=300, title_text='Payment Terms Distribution',
                                     showlegend=False)
                st.plotly_chart(fig_pt, use_container_width=True)

        # Score distribution
        if '_PayScore' in wcs_df.columns and len(wcs_df) > 0:
            score_counts = wcs_df['_PayScore'].value_counts().sort_index().reset_index()
            score_counts.columns = ['Score', 'Count']
            score_counts['Label'] = score_counts['Score'].apply(
                lambda s: {-2: 'Advance', 0: 'On Dispatch', 1: 'IBC 90', 2: 'IBC 60',
                           3: 'VFS/CC15', 4: 'IBC 45/RXIL', 5: 'IFC/CC30',
                           6: 'IFC 90', 7: 'CC 45', 8: 'CC 60', 10: 'CC 90'}.get(int(s), str(s))
            )
            fig_sc = go.Figure(go.Bar(
                x=score_counts['Label'], y=score_counts['Count'],
                marker_color=[CLR_RED if s < 0 else (CLR_AMBER if s < 4 else CLR_GREEN)
                              for s in score_counts['Score']],
                marker_line_width=0,
                text=score_counts['Count'], textposition='outside',
                textfont=dict(color='#888', size=11)
            ))
            fig_sc.update_layout(**DK, height=260, title_text='WC Score Breakdown by Term',
                                 showlegend=False)
            st.plotly_chart(fig_sc, use_container_width=True)
    else:
        if n_pos == 0:
            st.markdown('<div class="st-inf">Working capital data will be available once POs are placed with payment terms.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="st-inf">Payment terms column not found or no scored terms yet.</div>', unsafe_allow_html=True)


# ════ TAB 5: NEW VENDOR DEVELOPMENT ════════════════════════
with t5:
    if C_STYPE and C_STYPE in df_pos.columns and len(df_pos) > 0:
        avl_n = int(df_pos[C_STYPE].astype(str).str.upper().str.contains('AVL', na=False).sum())
        avl_oem = int(df_pos[C_STYPE].astype(str).str.upper().str.contains('AVL OEM', na=False).sum())
        avl_trd = int(df_pos[C_STYPE].astype(str).str.upper().str.contains('TRADER|AVL - TRADER', na=False).sum())

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("NVD %", f"{nv_pct:.1f}%",
                      "On target" if 10 <= nv_pct <= 15 else "Below target" if nv_pct < 10 else "Above target")
        with c2:
            st.metric("NV POs", str(nv_n), f"of {n_pos} POs")
        with c3:
            st.metric("AVL OEM", str(avl_oem))
        with c4:
            st.metric("AVL Trader", str(avl_trd))

        c1, c2 = st.columns(2)
        with c1:
            bn = df_pos.groupby(C_BU).apply(
                lambda x: pd.Series({
                    'Total': len(x),
                    'NV': x[C_STYPE].astype(str).str.upper().str.contains('NV', na=False).sum()
                })
            ).reset_index()
            bn['NV%'] = (bn['NV'] / bn['Total'] * 100).fillna(0)
            fig8 = go.Figure(go.Bar(
                x=bn[C_BU], y=bn['NV%'],
                marker_color=[CLR_GREEN if 10 <= v <= 15 else CLR_AMBER for v in bn['NV%']],
                marker_line_width=0,
                text=bn['NV%'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside', textfont=dict(color='#888', size=11)
            ))
            fig8.add_hrect(y0=10, y1=15, fillcolor="rgba(56,161,105,.06)", line_width=0)
            ymax = max(float(bn['NV%'].max()) * 1.3, 20) if len(bn) > 0 else 20
            fig8.update_layout(**DK, height=280, title_text='NVD % by BU',
                               showlegend=False, yaxis_range=[0, ymax])
            st.plotly_chart(fig8, use_container_width=True)

        with c2:
            # Supplier type pie
            st_vc = df_pos[C_STYPE].value_counts().reset_index()
            st_vc.columns = ['Type', 'Count']
            st_vc = st_vc[st_vc['Type'].ne('')]
            if len(st_vc) > 0:
                fig_pie = go.Figure(go.Pie(
                    labels=st_vc['Type'], values=st_vc['Count'],
                    hole=0.4,
                    marker_colors=[CLR_GREEN, CLR_BLUE, CLR_RED, CLR_PURP, CLR_AMBER],
                    textfont=dict(color='white', size=11)
                ))
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color='#888'),
                    margin=dict(l=8, r=8, t=32, b=8),
                    title_text='Supplier Type Mix',
                    legend=dict(font=dict(color='#888', size=11), bgcolor='rgba(0,0,0,0)')
                )
                st.plotly_chart(fig_pie, use_container_width=True)
    else:
        if n_pos == 0:
            st.markdown('<div class="st-inf">Supplier type data will populate once POs are placed.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="st-inf">Supplier type column not found. Columns: {list(dff.columns[:15])}</div>', unsafe_allow_html=True)


# ════ TAB 6: MFC TRACKER ═══════════════════════════════════
with t6:
    st.markdown("### MFC Delivery Tracker")
    today_ts = pd.Timestamp(date.today())

    # Use full df_po (not filtered) for MFC to see all — but apply BU filter
    mfc_df = df_po.copy()
    if sel_bu != 'All':
        mfc_df = mfc_df[mfc_df[C_BU] == sel_bu]

    if not C_MFC_DT or C_MFC_DT not in mfc_df.columns:
        st.error(f"MFC date column not found. Columns: {[c for c in mfc_df.columns if 'mfc' in c.lower() or 'delivery' in c.lower()]}")
    elif not C_MFC_DAYS or C_MFC_DAYS not in mfc_df.columns:
        st.error(f"MFC days column not found. Columns: {[c for c in mfc_df.columns if 'day' in c.lower() or 'delivery' in c.lower()]}")
    else:
        mfc_df['_mfc'] = pd.to_datetime(mfc_df[C_MFC_DT], errors='coerce')
        mfc_df['_days'] = pd.to_numeric(
            mfc_df[C_MFC_DAYS].astype(str).str.replace(',', '').str.strip(),
            errors='coerce'
        )

        # Only ongoing POs with MFC data
        if C_DEL_ST and C_DEL_ST in mfc_df.columns:
            del_st_lower = mfc_df[C_DEL_ST].fillna('').astype(str).str.strip().str.lower()
            mfc_df = mfc_df[~del_st_lower.isin(['completed', 'shortclose'])]

        mfc_df = mfc_df.dropna(subset=['_mfc', '_days'])
        mfc_df = mfc_df[mfc_df['_days'] > 0]

        if mfc_df.empty:
            st.info("No ongoing POs with valid MFC dates and delivery days. Fill MFC Dt. (col Z) and Delivery Time from MFC (col AA) in the sheet.")
        else:
            mfc_df['Expected'] = mfc_df['_mfc'] + pd.to_timedelta(mfc_df['_days'].astype(int), unit='D')
            mfc_df['Days Left'] = (mfc_df['Expected'] - today_ts).dt.days
            mfc_df['Threshold'] = np.ceil(mfc_df['_days'] / 3).astype(int)

            def classify_mfc(r):
                if r['Days Left'] <= 0:         return 'OVERDUE'
                elif r['Days Left'] <= r['Threshold']: return 'RED'
                elif r['Days Left'] <= 30:       return 'AMBER'
                else:                            return 'GREEN'

            mfc_df['Alert'] = mfc_df.apply(classify_mfc, axis=1)
            cnt = mfc_df['Alert'].value_counts()

            if 'mfc_filter' not in st.session_state:
                st.session_state.mfc_filter = 'ALL'

            cg, ca, cr, co, cl = st.columns(5)
            for col_w, label, key, count, color in [
                (cg, "GREEN",   "GREEN",   int(cnt.get('GREEN', 0)),   "#38a169"),
                (ca, "AMBER",   "AMBER",   int(cnt.get('AMBER', 0)),   "#d69e2e"),
                (cr, "RED",     "RED",     int(cnt.get('RED', 0)),     "#e53e3e"),
                (co, "OVERDUE", "OVERDUE", int(cnt.get('OVERDUE', 0)), "#ff4444"),
                (cl, "ALL",     "ALL",     len(mfc_df),                "#666"),
            ]:
                sel_mfc = st.session_state.mfc_filter == key
                with col_w:
                    st.markdown(f'''<div style="background:{"rgba(255,255,255,.08)" if sel_mfc else "rgba(255,255,255,.02)"};
border:{"2" if sel_mfc else "1"}px solid {color};border-radius:10px;padding:10px;text-align:center;">
<div style="font-size:9px;font-weight:700;color:{color};text-transform:uppercase;">{label}</div>
<div style="font-size:28px;font-weight:800;color:{"#fff" if sel_mfc else color};font-family:DM Mono,monospace;">{count}</div>
</div>''', unsafe_allow_html=True)
                    if st.button(f"{'● ' if sel_mfc else ''}{label}", key=f"mfc_{key}", use_container_width=True):
                        st.session_state.mfc_filter = key if not sel_mfc else 'ALL'
                        st.rerun()

            sel_mfc_filter = st.session_state.mfc_filter
            disp = mfc_df if sel_mfc_filter == 'ALL' else mfc_df[mfc_df['Alert'] == sel_mfc_filter]

            show = [c for c in ['SN', C_BU, 'Project Name', 'Items', C_CATEGORY, C_SUPPLIER, 'PO/OD Ref.']
                    if c and c in disp.columns]
            show += ['_mfc', '_days', 'Expected', 'Days Left', 'Alert']
            ds = disp[[c for c in show if c in disp.columns]].copy()
            ds = ds.rename(columns={'_mfc': 'MFC Date', '_days': 'Del Days'})
            ds['MFC Date'] = ds['MFC Date'].dt.strftime('%d-%b-%Y')
            ds['Expected'] = ds['Expected'].dt.strftime('%d-%b-%Y')

            alert_styles = {
                'OVERDUE': 'background-color:#2a0000;color:#ff9999;font-weight:700;',
                'RED':     'background-color:#1a0000;color:#ff6666;font-weight:700;',
                'AMBER':   'background-color:#1a1000;color:#ffcc66;',
                'GREEN':   'background-color:#001a00;color:#66cc66;',
            }

            def hl_mfc(row):
                s = alert_styles.get(row.get('Alert', ''), '') + 'font-size:13px;'
                return [s] * len(row)

            st.markdown(f"**{len(ds)} POs**")
            st.dataframe(ds.style.apply(hl_mfc, axis=1), use_container_width=True,
                         height=min(40 * len(ds) + 60, 700))


# ════ TAB 7: ONGOING POs ═══════════════════════════════════
with t7:
    if df_ong.empty:
        st.info(f"Ongoing sheet not loaded: {ong_err}")
    else:
        # Find columns in ongoing sheet
        ong_po_val  = fcol(df_ong, 'po value')
        ong_ytd     = fcol(df_ong, 'yet to') or fcol(df_ong, 'yet to be')
        ong_sav     = fcol(df_ong, 'realized', 'saving') or fcol(df_ong, 'realized saving')
        ong_del     = fcol(df_ong, 'delivered in') or fcol(df_ong, 'delivered')
        ong_status  = fcol(df_ong, 'delivery', 'status') or fcol(df_ong, 'status')
        ong_bu      = 'BU' if 'BU' in df_ong.columns else None

        # Ongoing = YTD > 0; delivered in FY = YTD <= 0 (or Delivered In FY26-27 > 0)
        n_ong_still = int((pd.to_numeric(df_ong[ong_ytd], errors='coerce').fillna(0) > 0).sum()) if ong_ytd else 0
        n_ong_done  = int((pd.to_numeric(df_ong[ong_ytd], errors='coerce').fillna(0) <= 0).sum()) if ong_ytd else 0

        total_po_val = safe_sum(df_ong, ong_po_val) / 1e7 if ong_po_val else 0
        total_ytd    = safe_sum(df_ong, ong_ytd)    / 1e7 if ong_ytd    else 0
        total_del_fy = safe_sum(df_ong, ong_del)    / 1e7 if ong_del    else 0
        total_sav    = safe_sum(df_ong, ong_sav)    / 1e7 if ong_sav    else 0

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Carry-Fwd POs", str(len(df_ong)), f"Ongoing: {n_ong_still} | Delivered: {n_ong_done}")
        with c2:
            st.metric("PO Value (incl. GST)", f"Rs {total_po_val:.2f} Cr")
        with c3:
            st.metric("Yet to Deliver", f"Rs {total_ytd:.2f} Cr",
                      f"Rs {total_po_val - total_ytd:.2f} Cr delivered" if total_po_val > 0 else "")
        with c4:
            st.metric("Realized Savings FY27", f"Rs {total_sav:.4f} Cr" if total_sav > 0 else "—")

        # BU filter
        bu_ong_opts = ['All']
        if ong_bu:
            bu_ong_opts += sorted([b for b in df_ong[ong_bu].dropna().unique() if str(b).strip()])
        sel_bu_ong = st.selectbox('BU', bu_ong_opts, key='ong_bu')

        dfo = df_ong.copy()
        if sel_bu_ong != 'All' and ong_bu:
            dfo = dfo[dfo[ong_bu] == sel_bu_ong]

        # BU breakdown table
        if ong_bu and ong_po_val and ong_ytd and len(dfo) > 0:
            bg2 = dfo.groupby(ong_bu).agg(
                n=(ong_po_val, 'count'),
                pv=(ong_po_val, 'sum'),
                yt=(ong_ytd, 'sum'),
                **({'sv': (ong_sav, 'sum')} if ong_sav else {})
            ).reset_index()
            rows_html = ""
            for _, r in bg2.sort_values('pv', ascending=False).iterrows():
                sv_str = f"Rs {r['sv']/1e7:.4f}Cr" if ong_sav and 'sv' in r else "—"
                remaining_pct = float(r['yt'] / r['pv'] * 100) if r['pv'] > 0 else 0
                pill = "pr" if remaining_pct > 70 else ("pa" if remaining_pct > 30 else "pg")
                rows_html += f'<tr><td><b style="color:#eee">{r[ong_bu]}</b></td><td class="mn">{int(r["n"])}</td><td class="mn">Rs {r["pv"]/1e7:.2f}Cr</td><td class="mn">Rs {r["yt"]/1e7:.2f}Cr</td><td><span class="{pill}">{remaining_pct:.0f}%</span></td><td class="mn">{sv_str}</td></tr>'
            st.markdown(f'''<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:6px 0;">
<table class="zT"><thead><tr><th>BU</th><th>POs</th><th>PO Value</th><th>Yet to Deliver</th><th>Remaining%</th><th>Realized Savings</th></tr></thead>
<tbody>{rows_html}</tbody></table></div>''', unsafe_allow_html=True)

        # Full table
        st.markdown(f"**{len(dfo)} carry-forward POs**")
        disp_o = dfo.copy()
        for c in disp_o.columns:
            if pd.api.types.is_datetime64_any_dtype(disp_o[c]):
                disp_o[c] = disp_o[c].dt.strftime("%d-%b-%Y")
        st.dataframe(disp_o, use_container_width=True, height=min(40 * len(dfo) + 50, 600))


# ════ TAB 8: PR-PO UNCLOSED ═══════════════════════════════
with t8:
    st.markdown("### PRs Not Yet Converted to PO")

    if df_unclosed.empty:
        st.success("All PRs have been converted to POs!")
    else:
        today_ts2 = pd.Timestamp(date.today())

        # Age since PR
        df_unclosed = df_unclosed.copy()
        if C_PR_DT and C_PR_DT in df_unclosed.columns:
            pr_dt_p = pd.to_datetime(df_unclosed[C_PR_DT], errors='coerce')
            df_unclosed['_age'] = (today_ts2 - pr_dt_p).dt.days
        else:
            df_unclosed['_age'] = np.nan

        # Revision delay = Rev PR Dt - PR Dt
        if C_REV_PR and C_REV_PR in df_unclosed.columns and C_PR_DT and C_PR_DT in df_unclosed.columns:
            rev_p = pd.to_datetime(df_unclosed[C_REV_PR], errors='coerce')
            pr_p  = pd.to_datetime(df_unclosed[C_PR_DT],  errors='coerce')
            df_unclosed['_rev_delay'] = (rev_p - pr_p).dt.days
        else:
            df_unclosed['_rev_delay'] = np.nan

        n_total    = len(df_unclosed)
        n_revised  = int(df_unclosed[C_REV_PR].notna().sum()) if C_REV_PR and C_REV_PR in df_unclosed.columns else 0
        avg_age    = float(df_unclosed['_age'].dropna().mean()) if df_unclosed['_age'].notna().any() else 0
        max_age    = float(df_unclosed['_age'].dropna().max())  if df_unclosed['_age'].notna().any() else 0
        n_stale    = int((df_unclosed['_age'] > 90).sum())      if df_unclosed['_age'].notna().any() else 0
        avg_rev    = float(df_unclosed['_rev_delay'].dropna().mean()) if df_unclosed['_rev_delay'].notna().any() else 0

        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Unclosed PRs", str(n_total), f"{n_total/n_prs*100:.0f}% of all PRs" if n_prs > 0 else "")
        with c2: st.metric("PRs Revised", str(n_revised), f"{n_total - n_revised} unrevised")
        with c3: st.metric("Avg Age", f"{avg_age:.0f}d" if avg_age > 0 else "—", f"Max: {max_age:.0f}d")
        with c4: st.metric("Stale PRs (>90d)", str(n_stale), "⚠️ Action needed" if n_stale > 0 else "All within 90d")

        # Filters
        c1, c2 = st.columns(2)
        with c1:
            bu_pr_opts = ['All'] + sorted([b for b in df_unclosed[C_BU].dropna().unique() if str(b).strip()])
            sel_bu_pr = st.selectbox('BU', bu_pr_opts, key='pr_bu')
        with c2:
            cat_pr_opts = ['All']
            if C_CATEGORY and C_CATEGORY in df_unclosed.columns:
                cat_pr_opts += sorted([c for c in df_unclosed[C_CATEGORY].dropna().unique() if str(c).strip()])
            sel_cat_pr = st.selectbox('Category', cat_pr_opts, key='pr_cat')

        dfp = df_unclosed.copy()
        if sel_bu_pr != 'All':
            dfp = dfp[dfp[C_BU] == sel_bu_pr]
        if sel_cat_pr != 'All' and C_CATEGORY and C_CATEGORY in dfp.columns:
            dfp = dfp[dfp[C_CATEGORY] == sel_cat_pr]

        # Charts
        c1, c2 = st.columns(2)
        with c1:
            bd = dfp.groupby(C_BU).size().reset_index(name='Count').sort_values('Count', ascending=False)
            fig_pr1 = go.Figure(go.Bar(
                x=bd[C_BU], y=bd['Count'],
                marker_color=CLR_RED, marker_line_width=0,
                text=bd['Count'], textposition='outside',
                textfont=dict(color='#888', size=11)
            ))
            fig_pr1.update_layout(**DK, height=260, title_text='Unclosed PRs by BU', showlegend=False)
            st.plotly_chart(fig_pr1, use_container_width=True)

        with c2:
            if C_CUR_ST and C_CUR_ST in dfp.columns:
                sd = dfp[C_CUR_ST].fillna('(Empty)').value_counts().head(10).reset_index()
                sd.columns = ['Status', 'Count']
                fig_pr2 = go.Figure(go.Bar(
                    y=sd['Status'], x=sd['Count'], orientation='h',
                    marker_color=CLR_AMBER, marker_line_width=0,
                    text=sd['Count'], textposition='outside',
                    textfont=dict(color='#888', size=11)
                ))
                fig_pr2.update_layout(**DK, height=260, title_text='By Current Status', showlegend=False)
                st.plotly_chart(fig_pr2, use_container_width=True)

        # Age buckets
        if dfp['_age'].notna().any():
            age_bins   = [-1, 30, 60, 90, 180, 9999]
            age_labels = ['0-30d', '31-60d', '61-90d', '91-180d', '>180d']
            age_colors = [CLR_GREEN, CLR_AMBER, CLR_AMBER, CLR_RED, '#ff0000']
            dfp = dfp.copy()
            dfp['_age_bucket'] = pd.cut(dfp['_age'], bins=age_bins, labels=age_labels)
            ab = dfp['_age_bucket'].value_counts().reindex(age_labels, fill_value=0).reset_index()
            ab.columns = ['Bucket', 'Count']
            fig_age2 = go.Figure(go.Bar(
                x=ab['Bucket'], y=ab['Count'],
                marker_color=age_colors, marker_line_width=0,
                text=ab['Count'], textposition='outside',
                textfont=dict(color='#888', size=11)
            ))
            fig_age2.update_layout(**DK, height=240, title_text='PR Age Distribution', showlegend=False)
            st.plotly_chart(fig_age2, use_container_width=True)

        # Table
        show_cols = [c for c in ['SN', C_BU, 'Project Name', 'Items', C_CATEGORY, C_HANDLER,
                                  C_PR_DT, C_REV_PR, C_NFA_DT, C_NFA_APP, C_CUR_ST,
                                  '_rev_delay', '_age']
                     if c and c in dfp.columns]
        ds = dfp[show_cols].copy()
        ds = ds.rename(columns={'_rev_delay': 'Rev Delay (d)', '_age': 'PR Age (d)'})
        for c in ds.columns:
            if pd.api.types.is_datetime64_any_dtype(ds[c]):
                ds[c] = ds[c].dt.strftime("%d-%b-%Y")

        def hl_pr(row):
            age = row.get('PR Age (d)', 0)
            if pd.notna(age) and age > 90:
                s = "background-color:#2a0000;color:#ff9999;font-weight:700;font-size:13px;"
            elif pd.notna(age) and age > 45:
                s = "background-color:#1a1000;color:#ffcc66;font-size:13px;"
            else:
                s = "color:#ccc;font-size:13px;"
            return [s] * len(row)

        st.markdown(f"**{len(ds)} unclosed PRs**")
        st.dataframe(ds.style.apply(hl_pr, axis=1), use_container_width=True,
                     height=min(40 * len(ds) + 50, 700))


# ── Footer ────────────────────────────────────────────────────
st.markdown(f'''<div style="padding:12px 0;border-top:1px solid rgba(255,255,255,.04);margin-top:16px;
display:flex;justify-content:space-between;">
<div style="font-size:11px;color:#333;">Zetwerk CPT &middot; CAT-2 &middot; FY 2026-27</div>
<div style="font-size:10px;color:#222;font-family:DM Mono,monospace;">{now_str} &middot; Cache: 60s</div>
</div>''', unsafe_allow_html=True)


# ════ CAT 2 BUDDY (floating chatbot) ══════════════════════
chat_html = ""
for m in st.session_state.buddy_msgs[-10:]:
    if m['role'] == 'user':
        chat_html += f'<div style="background:rgba(229,62,62,.12);border:1px solid rgba(229,62,62,.2);border-radius:10px 10px 2px 10px;padding:8px 12px;margin:4px 0;font-size:12px;color:#eee;max-width:85%;align-self:flex-end;margin-left:auto;">{m["text"]}</div>'
    else:
        chat_html += f'<div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:10px 10px 10px 2px;padding:8px 12px;margin:4px 0;font-size:12px;color:#ccc;max-width:90%;">{m["text"]}</div>'

buddy_open = st.session_state.get('buddy_open', False)
components.html(f"""<!DOCTYPE html><html><head><style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'DM Sans',Arial,sans-serif;}}
body{{background:transparent;overflow:visible;height:auto;}}
#fab{{position:fixed;bottom:20px;right:20px;z-index:9999;width:52px;height:52px;border-radius:50%;
background:linear-gradient(135deg,#e53e3e,#fc4f4f);display:flex;align-items:center;justify-content:center;
cursor:pointer;box-shadow:0 4px 20px rgba(229,62,62,.5);font-size:22px;border:none;color:white;}}
#fab:hover{{transform:scale(1.1);transition:transform 0.15s;}}
#panel{{position:fixed;bottom:82px;right:20px;z-index:9998;width:340px;background:#13131a;
border:1px solid rgba(229,62,62,.3);border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,.8);
display:{'flex' if buddy_open else 'none'};flex-direction:column;overflow:hidden;}}
#hdr{{background:linear-gradient(135deg,#1a0505,#220808);border-bottom:1px solid rgba(229,62,62,.2);
padding:12px 16px;display:flex;align-items:center;gap:10px;}}
#av{{width:34px;height:34px;background:linear-gradient(135deg,#e53e3e,#fc4f4f);border-radius:9px;
display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:900;color:white;}}
#msgs{{padding:12px;display:flex;flex-direction:column;height:260px;overflow-y:auto;gap:4px;}}
#irow{{padding:8px 12px;border-top:1px solid rgba(255,255,255,.06);display:flex;gap:6px;}}
#inp{{flex:1;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:8px;
padding:8px 10px;color:#fff;font-size:12px;outline:none;}}
#inp:focus{{border-color:rgba(229,62,62,.4);}}
#sbtn{{background:#e53e3e;border:none;border-radius:8px;padding:8px 14px;color:white;
font-size:12px;cursor:pointer;font-weight:600;}}
#sbtn:hover{{background:#fc4f4f;}}
</style></head><body>
<div id="panel">
  <div id="hdr">
    <div id="av">C</div>
    <div><div style="font-size:13px;font-weight:700;color:#fff;">CAT 2 Buddy</div>
    <div style="font-size:10px;color:#38a169;">● Online</div></div>
  </div>
  <div id="msgs">{chat_html}</div>
  <div id="irow">
    <input id="inp" placeholder="Ask anything about CAT-2 procurement..." />
    <button id="sbtn">Send</button>
  </div>
</div>
<button id="fab">&#128172;</button>
<script>
var panel=document.getElementById('panel'),fab=document.getElementById('fab'),
    inp=document.getElementById('inp'),sbtn=document.getElementById('sbtn'),
    msgs=document.getElementById('msgs');
if(msgs) msgs.scrollTop=msgs.scrollHeight;
fab.addEventListener('click',function(){{
  var o=panel.style.display==='flex';
  panel.style.display=o?'none':'flex';
  fab.innerHTML=o?'&#128172;':'&#10005;';
  if(!o&&msgs) setTimeout(function(){{msgs.scrollTop=msgs.scrollHeight;}},50);
}});
function doSend(){{
  var v=inp.value.trim();if(!v)return;inp.value='';
  window.parent.location.href=window.parent.location.pathname+'?buddy_msg='+encodeURIComponent(v);
}}
sbtn.addEventListener('click',doSend);
inp.addEventListener('keydown',function(e){{if(e.key==='Enter')doSend();}});
</script></body></html>""", height=420 if buddy_open else 80, scrolling=False)

# Handle buddy message from query param
buddy_msg = st.query_params.get("buddy_msg", "")
if buddy_msg and buddy_msg.strip():
    st.query_params.clear()
    st.session_state.buddy_msgs.append({"role": "user", "text": buddy_msg})
    st.session_state.buddy_open = True
    with st.spinner(""):
        reply = buddy_chat(buddy_msg, df_pos, df_ong)
    st.session_state.buddy_msgs.append({"role": "bot", "text": reply})
    st.rerun()
