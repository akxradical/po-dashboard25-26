"""
Zetwerk CPT CAT-2 Dashboard — FY 2026-27
Reads: PO TRACKER '27 + ongoing updated with realized27
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, date, timedelta
from google.oauth2.service_account import Credentials
import gspread
import streamlit.components.v1 as components

st.set_page_config(page_title="Zetwerk CPT Dashboard", page_icon="Z", layout="wide", initial_sidebar_state="collapsed")

SHEET_ID = "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU"
SCOPES   = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]

SCORE_MAP = {"advance":-2,"on dispatch":0,"ibc 90":1,"ibc 60":2,"vfs":3,"clean credit 15":3,
             "ibc 45":4,"rxil":4,"ifc 30":5,"ifc 45":5,"ifc 60":5,"clean credit 30":5,
             "ifc 90":6,"clean credit 45":7,"clean credit 60":8,"clean credit 90":10}

def calc_score(term):
    if not term or str(term).strip() in ['','0','nan']: return None
    t = str(term).lower()
    for k,v in SCORE_MAP.items():
        if k in t: return float(v)
    return None

def gclient():
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=60, show_spinner=False)
def load_po_tracker():
    try:
        gc = gclient()
        sh = gc.open_by_key(SHEET_ID)
        ws = None
        for tab in ["PO TRACKER ' 27","PO TRACKER '27","PO TRACKER"]:
            try: ws = sh.worksheet(tab); break
            except: continue
        if not ws: return pd.DataFrame(), f"Tab not found. Available: {[s.title for s in sh.worksheets()]}"
        data = ws.get_all_values()
        if len(data)<2: return pd.DataFrame(), "Empty sheet"
        df = pd.DataFrame(data[1:], columns=[c.strip() for c in data[0]])
        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()
        # Parse dates
        for c in df.columns:
            if any(x in c.lower() for x in ['dt.','dt ','date']):
                df[c] = pd.to_datetime(df[c], errors='coerce', dayfirst=True)
        # Parse numbers
        for c in df.columns:
            if any(x in c.lower() for x in ['value','gst','saving','tat','time from mfc','otif']):
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(',','').str.replace('%',''), errors='coerce')
        # PR-PO TAT
        tat_col = next((c for c in df.columns if 'pr' in c.lower() and 'po' in c.lower() and 'tat' in c.lower()), None)
        if tat_col: df[tat_col] = pd.to_numeric(df[tat_col], errors='coerce')
        # Payment score
        pt_col = next((c for c in df.columns if 'payment' in c.lower() and 'term' in c.lower()), None)
        if pt_col: df['_PayScore'] = df[pt_col].apply(calc_score)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)

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
        data = ws.get_all_values()
        if len(data)<3: return pd.DataFrame(), "Empty"
        # Row 1=title, Row 2=headers
        df = pd.DataFrame(data[2:], columns=[c.strip() for c in data[1]])
        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()
        for c in df.columns:
            if any(x in c.lower() for x in ['value','deliver','saving','amount']):
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(',',''), errors='coerce').fillna(0)
            if any(x in c.lower() for x in ['date','dt']):
                df[c] = pd.to_datetime(df[c], errors='coerce', dayfirst=True)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)

# ── Find columns helper ──────────────────────────────────────
def fcol(df, *keywords):
    """Find column by keyword matching"""
    for c in df.columns:
        cl = c.lower()
        if all(k in cl for k in keywords): return c
    return None

# ── Buddy chat ────────────────────────────────────────────────
def buddy_chat(question, df):
    try:
        import anthropic
        key = ""
        for k in ["ANTHROPIC_API_KEY","anthropic_api_key","ANTHROPIC_KEY"]:
            try:
                v = st.secrets[k]
                if v: key=v; break
            except: pass
        if not key:
            try: visible = list(st.secrets.keys())
            except: visible = []
            return f"API key not found. Keys in secrets: {visible}. Add ANTHROPIC_API_KEY at bottom of Streamlit Secrets."
        ctx = f"""You are CAT 2 Buddy, procurement assistant for Zetwerk CPT CAT-2. Never mention Claude/Anthropic.
Data: {len(df)} POs, Rs {df[fcol(df,'po','basic','value') or 'PO Basic Value'].sum()/1e7:.1f}Cr spend.
BUs: {dict(df.groupby('BU').size()) if 'BU' in df.columns else {}}
Answer in Rs Crores, be precise."""
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=400,
            messages=[{"role":"user","content":ctx+"\n\nQ: "+question}])
        return resp.content[0].text
    except ImportError: return "anthropic package missing in requirements.txt"
    except Exception as e: return f"Error: {e}"

# ── Load data ─────────────────────────────────────────────────
with st.spinner(""):
    df_po, po_err = load_po_tracker()
    df_ong, ong_err = load_ongoing()

if 'buddy_msgs' not in st.session_state:
    st.session_state.buddy_msgs = [{"role":"bot","text":"Hi! I am CAT 2 Buddy. Ask me anything."}]

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
/* Nav */
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
/* KPI */
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
/* Tab */
[data-testid="stTabs"] button[role="tab"]{font-size:12px!important;font-weight:500!important;color:#555!important;}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#fc4f4f!important;border-bottom:2px solid #e53e3e!important;}
/* Selectbox */
[data-testid="stSelectbox"] label{font-size:10px!important;color:#666!important;font-weight:700!important;text-transform:uppercase;}
[data-testid="stSelectbox"]>div>div{background:#13131a!important;border:1px solid rgba(255,255,255,0.1)!important;
border-radius:8px!important;color:#ccc!important;font-size:13px!important;}
/* Metric */
[data-testid="stMetric"]{background:#13131a!important;border-radius:10px!important;padding:12px!important;
border:1px solid rgba(255,255,255,0.07)!important;}
[data-testid="stMetricValue"]{font-size:22px!important;font-weight:800!important;color:#fff!important;font-family:'DM Mono',monospace!important;}
[data-testid="stMetricLabel"]{font-size:10px!important;color:#666!important;text-transform:uppercase;}
/* Table */
.zT{width:100%;border-collapse:collapse;font-size:12px;}
.zT th{text-align:left;padding:8px 12px;font-size:10px;font-weight:700;color:#555;text-transform:uppercase;
letter-spacing:.05em;border-bottom:1px solid rgba(255,255,255,0.07);}
.zT td{padding:8px 12px;color:#bbb;border-bottom:1px solid rgba(255,255,255,0.03);font-size:12px;}
.zT tr:hover td{background:rgba(255,255,255,0.02);}
.mn{font-family:'DM Mono',monospace!important;font-size:11px;}
.pg{background:rgba(56,161,105,.15);color:#68d391;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.pr{background:rgba(229,62,62,.15);color:#fc8181;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
.pa{background:rgba(214,158,46,.15);color:#f6e05e;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;}
</style>""", unsafe_allow_html=True)

# ── Nav ──────────────────────────────────────────────────────
now = datetime.now().strftime("%d %b %Y %H:%M")
st.markdown(f"""<div class="zN"><div class="zNL"><div class="zZ">Z</div><div><div class="zB">Zetwerk CPT</div>
<div class="zS">Central Procurement Team</div></div></div>
<div class="zR"><div class="zL"><div class="zD"></div>Live &middot; {now}</div><div class="zP">FY 2026-27</div></div></div>""", unsafe_allow_html=True)

if df_po.empty:
    st.error(f"Sheet error: {po_err}")
    st.stop()

# ── Columns ──────────────────────────────────────────────────
C_PO_VAL  = fcol(df_po,'po','basic','value') or 'PO Basic Value'
C_SAV     = fcol(df_po,'savings','value') or fcol(df_po,'saving') or 'Savings Value'
C_TAT     = fcol(df_po,'pr','po','tat') or 'PR - PO TAT'
C_OTIF    = fcol(df_po,'otif') or 'OTIF'
C_DEL_ST  = fcol(df_po,'delivery','status') or 'Delivery Status'
C_STYPE   = fcol(df_po,'supplier','type') or 'Supplier type'
C_MFC     = fcol(df_po,'mfc','dt') or fcol(df_po,'mfc','date') or 'MFC Dt.'
C_MFC_DAYS= fcol(df_po,'delivery','time','mfc') or 'Delivery Time from MFC (Days)'
C_PO_DT   = fcol(df_po,'po','dt') or fcol(df_po,'po','date') or 'PO Dt.'
C_PR_DT   = fcol(df_po,'pr','dt') or 'PR Dt.'
C_REV_PR  = fcol(df_po,'rev','pr') or 'Rev. PR Dt.'
C_CUR_ST  = fcol(df_po,'current','status') or 'Current Status'
C_YTD     = fcol(df_po,'yet to be','deliver') or fcol(df_po,'yet to','deliver') or 'PO YET TO BE DELIVERED (incl. GST)'

# ── Filters ──────────────────────────────────────────────────
c1,c2,c3,c4,c5 = st.columns([1,1,1,1,.4])
with c1: sel_bu = st.selectbox('BU',['All']+sorted([b for b in df_po['BU'].dropna().unique() if b]),key='bu')
with c2:
    co=['All']
    if 'Category' in df_po.columns: co+=sorted([c for c in df_po['Category'].dropna().unique() if c])
    sel_cat=st.selectbox('Category',co,key='cat')
with c3:
    ho=['All']
    if 'Handled by' in df_po.columns: ho+=sorted([h for h in df_po['Handled by'].dropna().unique() if h])
    sel_buyer=st.selectbox('Buyer',ho,key='buy')
with c4:
    so=['All']
    if C_STYPE in df_po.columns: so+=sorted([s for s in df_po[C_STYPE].dropna().unique() if str(s).strip()])
    sel_st=st.selectbox('Supplier Type',so,key='st')
with c5:
    st.markdown("<div style='padding-top:18px;'>",unsafe_allow_html=True)
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("</div>",unsafe_allow_html=True)

dff=df_po.copy()
if sel_bu!='All': dff=dff[dff['BU']==sel_bu]
if sel_cat!='All' and 'Category' in dff.columns: dff=dff[dff['Category']==sel_cat]
if sel_buyer!='All' and 'Handled by' in dff.columns: dff=dff[dff['Handled by']==sel_buyer]
if sel_st!='All' and C_STYPE in dff.columns: dff=dff[dff[C_STYPE]==sel_st]

# ── KPIs ─────────────────────────────────────────────────────
n_po = len(dff[dff[C_PO_VAL]>0]) if C_PO_VAL in dff.columns else len(dff)
spend = dff[C_PO_VAL].sum()/1e7 if C_PO_VAL in dff.columns else 0
sav = dff[C_SAV].sum()/1e7 if C_SAV in dff.columns else 0
sp = (sav/spend*100) if spend>0 else 0
tat_v = pd.to_numeric(dff[C_TAT],errors='coerce').dropna() if C_TAT in dff.columns else pd.Series()
avg_tat = float(tat_v[tat_v>0].mean()) if len(tat_v[tat_v>0])>0 else 0

comp = dff[dff[C_DEL_ST].str.strip().str.lower().isin(['completed','shortclose'])] if C_DEL_ST in dff.columns else pd.DataFrame()
n_comp = len(comp)
n_ong_po = len(dff[dff[C_DEL_ST].str.strip().str.lower()=='ongoing']) if C_DEL_ST in dff.columns else 0

otif_pct=0; otif_n=0
if C_OTIF in dff.columns and len(comp)>0:
    ov=pd.to_numeric(comp[C_OTIF].astype(str).str.replace('%','').str.replace(',',''),errors='coerce').dropna()
    ov=ov[ov>0]; otif_n=len(ov)
    if otif_n>0: otif_pct=(ov<=105.0).sum()/otif_n*100

nv_pct=nv_n=0
if C_STYPE in dff.columns:
    nm=dff[C_STYPE].str.upper().str.contains('NV',na=False)
    nv_n=int(nm.sum()); nv_pct=(nv_n/len(dff)*100) if len(dff)>0 else 0

wce=None
if '_PayScore' in dff.columns and C_PO_VAL in dff.columns:
    sc=dff[dff['_PayScore'].notna()&(dff[C_PO_VAL]>0)]
    if len(sc)>0: wce=(sc['_PayScore']*sc[C_PO_VAL]).sum()/sc[C_PO_VAL].sum()

# ── Chart theme ──────────────────────────────────────────────
DK=dict(plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans",color="#888",size=12),
    xaxis=dict(gridcolor="rgba(255,255,255,0.04)",tickcolor="#444",linecolor="#333"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.04)",tickcolor="#444",linecolor="#333"),
    margin=dict(l=8,r=8,t=32,b=8))
R="#e53e3e";G="#38a169";A="#d69e2e"

def kc(val,lbl,sub="",delta="",dcls="",ccls="cB"):
    d=f'<div class="kD {dcls}">{delta}</div>' if delta else ''
    return f'<div class="kC {ccls}"><div class="kL">{lbl}</div><div class="kV">{val}</div><div class="kS">{sub}</div>{d}</div>'

# ── TABS ─────────────────────────────────────────────────────
t1,t2,t3,t4,t5,t6,t7,t8 = st.tabs(["Overview","Spend & Savings","TAT & OTIF","Working Capital","New Vendor Dev","MFC Tracker","Ongoing POs","PR-PO Unclosed"])

# ════ TAB 1: OVERVIEW ════════════════════════════
with t1:
    cn=dff['Category'].nunique() if 'Category' in dff.columns else 0
    sn=dff['Supplier Name'].nunique() if 'Supplier Name' in dff.columns else 0
    st.markdown(f"""<div class="kG k5">
{kc(str(n_po),"Total POs","FY 26-27","","","cB")}
{kc(f"Rs {spend:.1f} Cr","Total Spend","PO Basic Value","","","cG")}
{kc(f"Rs {sav:.2f} Cr","Savings",f"{sp:.1f}%","Above 4.5%" if sp>=4.5 else "Below 4.5%","up" if sp>=4.5 else "wn","cG" if sp>=4.5 else "cA")}
{kc(f"{avg_tat:.0f}d","Avg PR-PO TAT","Target: 90d","On track" if avg_tat<=90 else "Above target","up" if avg_tat<=90 else "dn","cG" if avg_tat<=90 else "cR")}
{kc(f"{wce:.2f}" if wce else "—","WC Score","Target: 4.5","Above" if wce and wce>=4.5 else "Below" if wce else "","up" if wce and wce>=4.5 else "dn" if wce else "","cG" if wce and wce>=4.5 else "cR" if wce else "cP")}
</div><div class="kG k4" style="margin-top:8px;">
{kc(f"{otif_pct:.1f}%","OTIF",f"{otif_n} completed POs","Above 75%" if otif_pct>=75 else "Below 75%","up" if otif_pct>=75 else "dn","cG" if otif_pct>=75 else "cR")}
{kc(f"{nv_pct:.1f}%","New Vendor Dev",f"{nv_n} NV of {len(dff)} POs","Target 10-15%","up" if 10<=nv_pct<=15 else "wn","cG" if 10<=nv_pct<=15 else "cA")}
{kc(str(cn),"Categories","Unique","","","cT")}
{kc(str(sn),"Suppliers","Unique","","","cP")}
</div>""",unsafe_allow_html=True)

    c1,c2=st.columns(2)
    with c1:
        bg=dff.groupby('BU').agg(s=(C_PO_VAL,'sum'),sv=(C_SAV,'sum')).reset_index() if C_PO_VAL in dff.columns else pd.DataFrame()
        if not bg.empty:
            bg['sc']=bg['s']/1e7;bg['svc']=bg['sv']/1e7
            fig=go.Figure()
            fig.add_trace(go.Bar(name='Spend',x=bg['BU'],y=bg['sc'],marker_color=R,marker_line_width=0))
            fig.add_trace(go.Bar(name='Savings',x=bg['BU'],y=bg['svc'],marker_color='rgba(56,161,105,0.7)',marker_line_width=0))
            fig.update_layout(**DK,height=280,barmode='group',title_text='Spend & Savings by BU (Rs Cr)',
                legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=11)))
            st.plotly_chart(fig,use_container_width=True)
    with c2:
        if 'Category' in dff.columns and C_PO_VAL in dff.columns:
            cg=dff.groupby('Category')[C_PO_VAL].sum().sort_values(ascending=False).head(8).reset_index()
            cg['sc']=cg[C_PO_VAL]/1e7
            fig2=go.Figure(go.Bar(y=cg['Category'],x=cg['sc'],orientation='h',marker_color=R,marker_line_width=0,
                text=cg['sc'].apply(lambda x:f'Rs {x:.1f}Cr'),textposition='outside',textfont=dict(color='#888',size=11)))
            fig2.update_layout(**DK,height=280,title_text='Top Categories by Spend')
            st.plotly_chart(fig2,use_container_width=True)

# ════ TAB 2: SPEND & SAVINGS ═════════════════════
with t2:
    c1,c2,c3,c4=st.columns(4)
    with c1: st.metric("Total Spend",f"Rs {spend:.2f} Cr")
    with c2: st.metric("Savings",f"Rs {sav:.2f} Cr",f"{sp:.1f}%")
    with c3: st.metric("vs Target 4.5%",f"{sp:.1f}%",f"{sp-4.5:.1f}pp")
    with c4: st.metric("Completed / Ongoing",f"{n_comp} / {n_ong_po}")
    c1,c2=st.columns(2)
    with c1:
        if C_PO_DT in dff.columns:
            dff2=dff.copy();dff2['M']=dff2[C_PO_DT].dt.strftime("%b'%y")
            if 'M' in dff2.columns:
                mo=dff2.groupby('M').agg(s=(C_PO_VAL,'sum'),sv=(C_SAV,'sum')).reset_index()
                mo['sc']=mo['s']/1e7;mo['svc']=mo['sv']/1e7
                fig3=go.Figure()
                fig3.add_trace(go.Bar(name='Spend',x=mo['M'],y=mo['sc'],marker_color='rgba(229,62,62,.25)',marker_line_width=0))
                fig3.add_trace(go.Scatter(name='Savings',x=mo['M'],y=mo['svc'],line=dict(color=G,width=2.5),mode='lines+markers',marker=dict(size=5),yaxis='y2'))
                d2={k:v for k,v in DK.items() if k not in ('yaxis','legend')}
                fig3.update_layout(**d2,height=300,title_text='Monthly Trend',
                    yaxis=dict(title='Spend Rs Cr',gridcolor='rgba(255,255,255,0.04)'),
                    yaxis2=dict(title='Savings',overlaying='y',side='right',gridcolor='rgba(0,0,0,0)'),
                    legend=dict(orientation='h',y=1.12,x=1,xanchor='right',bgcolor='rgba(0,0,0,0)',font=dict(color='#888',size=11)))
                st.plotly_chart(fig3,use_container_width=True)
    with c2:
        bs=dff.groupby('BU').agg(s=(C_PO_VAL,'sum'),sv=(C_SAV,'sum'),n=(C_PO_VAL,'count')).reset_index() if C_PO_VAL in dff.columns else pd.DataFrame()
        if not bs.empty:
            bs['sp']=(bs['sv']/bs['s']*100).fillna(0)
            rows=""
            for _,r in bs.sort_values('s',ascending=False).iterrows():
                pill="pg" if r['sp']>=4.5 else ("pr" if r['sp']<0 else "pa")
                rows+=f'<tr><td><b style="color:#eee">{r["BU"]}</b></td><td class="mn">Rs {r["s"]/1e7:.2f}Cr</td><td class="mn">Rs {r["sv"]/1e7:.2f}Cr</td><td><span class="{pill}">{r["sp"]:.1f}%</span></td><td class="mn">{int(r["n"])}</td></tr>'
            st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:6px 0;"><table class="zT"><thead><tr><th>BU</th><th>Spend</th><th>Savings</th><th>%</th><th>POs</th></tr></thead><tbody>{rows}</tbody></table></div>',unsafe_allow_html=True)

# ════ TAB 3: TAT & OTIF ══════════════════════════
with t3:
    c1,c2,c3,c4=st.columns(4)
    with c1: st.metric("Avg TAT",f"{avg_tat:.0f}d",f"{avg_tat-90:.0f}d vs 90d")
    with c2: st.metric("OTIF",f"{otif_pct:.1f}%",f"{otif_n} completed")
    with c3: st.metric("Completed",str(n_comp))
    with c4: st.metric("Ongoing",str(n_ong_po))
    c1,c2=st.columns(2)
    with c1:
        if C_TAT in dff.columns:
            bt=dff.groupby('BU').apply(lambda x:pd.to_numeric(x[C_TAT],errors='coerce').mean()).reset_index()
            bt.columns=['BU','TAT'];bt=bt.dropna()
            if len(bt)>0:
                fig4=go.Figure(go.Bar(x=bt['BU'],y=bt['TAT'],
                    marker_color=[G if v<=90 else R for v in bt['TAT']],marker_line_width=0,
                    text=bt['TAT'].apply(lambda x:f'{x:.0f}d'),textposition='outside',textfont=dict(color='#888',size=11)))
                fig4.add_hline(y=90,line_dash='dash',line_color=A,annotation_text='90d',annotation_font_color=A)
                fig4.update_layout(**DK,height=280,title_text='TAT by BU',showlegend=False)
                st.plotly_chart(fig4,use_container_width=True)
    with c2:
        if C_OTIF in dff.columns and len(comp)>0:
            rows=[]
            for bu in dff['BU'].dropna().unique():
                s=comp[comp['BU']==bu] if 'BU' in comp.columns else pd.DataFrame()
                if len(s)==0: continue
                v=pd.to_numeric(s[C_OTIF].astype(str).str.replace('%',''),errors='coerce').dropna()
                v=v[v>0]
                if len(v)>0: rows.append({'BU':bu,'OTIF%':(v<=105).sum()/len(v)*100})
            if rows:
                bo=pd.DataFrame(rows)
                fig5=go.Figure(go.Bar(x=bo['BU'],y=bo['OTIF%'],
                    marker_color=[G if v>=75 else R for v in bo['OTIF%']],marker_line_width=0,
                    text=bo['OTIF%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#888',size=11)))
                fig5.add_hline(y=75,line_dash='dash',line_color=A,annotation_text='75%',annotation_font_color=A)
                fig5.update_layout(**DK,height=280,title_text='OTIF % by BU',showlegend=False,yaxis_range=[0,110])
                st.plotly_chart(fig5,use_container_width=True)

# ════ TAB 4: WORKING CAPITAL ═════════════════════
with t4:
    pt_col=fcol(df_po,'payment','term')
    if '_PayScore' in dff.columns and pt_col:
        sc=dff[dff['_PayScore'].notna()&(dff[C_PO_VAL]>0)].copy()
        c1,c2,c3=st.columns(3)
        with c1: st.metric("WC Score",f"{wce:.2f}" if wce else "—",f"{'Above' if wce and wce>=4.5 else 'Below'} 4.5")
        with c2: st.metric("POs with Terms",f"{len(sc)}/{n_po}")
        with c3:
            adv=len(sc[sc['_PayScore']<0])/len(sc)*100 if len(sc)>0 else 0
            st.metric("Advance %",f"{adv:.1f}%","Lower is better")
    else:
        st.info("Payment terms column not found.")

# ════ TAB 5: NVD ═════════════════════════════════
with t5:
    if C_STYPE in dff.columns:
        c1,c2,c3=st.columns(3)
        with c1: st.metric("NVD %",f"{nv_pct:.1f}%","On target" if 10<=nv_pct<=15 else "Off target")
        with c2: st.metric("NV POs",str(nv_n))
        with c3: st.metric("AVL POs",str(int(dff[C_STYPE].str.upper().str.contains('AVL',na=False).sum())))
        bn=dff.groupby('BU').apply(lambda x:pd.Series({
            'Total':len(x),'NV':x[C_STYPE].str.upper().str.contains('NV',na=False).sum()})).reset_index()
        bn['NV%']=(bn['NV']/bn['Total']*100).fillna(0)
        fig8=go.Figure(go.Bar(x=bn['BU'],y=bn['NV%'],
            marker_color=[G if 10<=v<=15 else A for v in bn['NV%']],marker_line_width=0,
            text=bn['NV%'].apply(lambda x:f'{x:.1f}%'),textposition='outside',textfont=dict(color='#888',size=11)))
        fig8.add_hrect(y0=10,y1=15,fillcolor="rgba(56,161,105,.06)",line_width=0)
        fig8.update_layout(**DK,height=280,title_text='NVD % by BU',showlegend=False,yaxis_range=[0,max(float(bn['NV%'].max())*1.3,20)])
        st.plotly_chart(fig8,use_container_width=True)
    else:
        st.warning(f"Supplier type column not found. Columns: {list(dff.columns[:15])}")

# ════ TAB 6: MFC TRACKER ════════════════════════
with t6:
    st.markdown("### MFC Delivery Tracker")
    today=pd.Timestamp(date.today())
    mc=fcol(df_po,'mfc','dt') or fcol(df_po,'mfc','date')
    dc=fcol(df_po,'delivery time','mfc') or fcol(df_po,'time from mfc')
    if not mc or not dc:
        st.error(f"MFC columns not found. Cols: {list(df_po.columns)}")
    else:
        mf=df_po.copy()
        # Parse MFC columns
        mf['_mfc']=pd.to_datetime(mf[mc],dayfirst=True,errors='coerce')
        mf['_days']=pd.to_numeric(mf[dc].astype(str).str.replace(',',''),errors='coerce')
        # Only ongoing
        if C_DEL_ST in mf.columns:
            mf=mf[~mf[C_DEL_ST].str.strip().str.lower().isin(['completed','shortclose'])]
        mf=mf.dropna(subset=['_mfc','_days']);mf=mf[mf['_days']>0]
        if mf.empty:
            st.info("No ongoing POs with valid MFC data.")
        else:
            mf['Expected']=mf['_mfc']+pd.to_timedelta(mf['_days'].astype(int),unit='D')
            mf['Days Left']=(mf['Expected']-today).dt.days
            mf['Threshold']=np.ceil(mf['_days']/3).astype(int)
            def clf(r):
                if r['Days Left']<=0: return 'OVERDUE'
                elif r['Days Left']<=r['Threshold']: return 'RED'
                elif r['Days Left']<=30: return 'AMBER'
                else: return 'GREEN'
            mf['Alert']=mf.apply(clf,axis=1)
            cnt=mf['Alert'].value_counts()
            # Interactive filter cards
            if 'mfc_f' not in st.session_state: st.session_state.mfc_f='ALL'
            cg,ca,cr,co,cl=st.columns(5)
            for col,label,key,count,color in [
                (cg,"GREEN","GREEN",int(cnt.get('GREEN',0)),"#38a169"),
                (ca,"AMBER","AMBER",int(cnt.get('AMBER',0)),"#d69e2e"),
                (cr,"RED","RED",int(cnt.get('RED',0)),"#e53e3e"),
                (co,"OVERDUE","OVERDUE",int(cnt.get('OVERDUE',0)),"#ff4444"),
                (cl,"ALL","ALL",len(mf),"#666")]:
                sel=st.session_state.mfc_f==key
                with col:
                    st.markdown(f'<div style="background:{"rgba(255,255,255,.08)" if sel else "rgba(255,255,255,.02)"};border:{"2" if sel else "1"}px solid {color};border-radius:10px;padding:10px;text-align:center;"><div style="font-size:9px;font-weight:700;color:{color};text-transform:uppercase;">{label}</div><div style="font-size:28px;font-weight:800;color:{"#fff" if sel else color};font-family:DM Mono,monospace;">{count}</div></div>',unsafe_allow_html=True)
                    if st.button(f"{'● ' if sel else ''}{label}",key=f"mfc_{key}",use_container_width=True):
                        st.session_state.mfc_f=key if not sel else 'ALL'
                        st.rerun()
            # Filter
            sel=st.session_state.mfc_f
            disp=mf if sel=='ALL' else mf[mf['Alert']==sel]
            # Show table
            show=[c for c in ['SN','BU','Project Name','Items','Category','Supplier Name','PO/OD Ref.'] if c in disp.columns]
            show+=['_mfc','_days','Expected','Days Left','Alert']
            ds=disp[show].copy()
            ds=ds.rename(columns={'_mfc':'MFC Date','_days':'Del Days'})
            ds['MFC Date']=ds['MFC Date'].dt.strftime('%d-%b-%Y')
            ds['Expected']=ds['Expected'].dt.strftime('%d-%b-%Y')
            colors={'OVERDUE':'background-color:#2a0000;color:#ff9999;font-weight:700;','RED':'background-color:#1a0000;color:#ff6666;font-weight:700;','AMBER':'background-color:#1a1000;color:#ffcc66;','GREEN':'background-color:#001a00;color:#66cc66;'}
            def hl(row): s=colors.get(row['Alert'],'')+';font-size:13px;'; return [s]*len(row)
            st.markdown(f"**{len(ds)} POs**")
            st.dataframe(ds.style.apply(hl,axis=1),use_container_width=True,height=min(40*len(ds)+60,700))

# ════ TAB 7: ONGOING POs ════════════════════════
with t7:
    if df_ong.empty:
        st.info(f"Ongoing sheet not loaded: {ong_err}")
    else:
        po_v=fcol(df_ong,'po value','gst') or fcol(df_ong,'po value')
        ytd_v=fcol(df_ong,'yet to','deliver') or fcol(df_ong,'yet to be')
        sav_v=fcol(df_ong,'realized','saving')
        del_v=fcol(df_ong,'delivered in')
        # Counts: YTD>0 = ongoing, YTD<=0 = delivered
        n_ong_o=int((df_ong[ytd_v]>0).sum()) if ytd_v else 0
        n_ong_c=int((df_ong[ytd_v]<=0).sum()) if ytd_v else 0
        c1,c2,c3,c4=st.columns(4)
        with c1: st.metric("Carry-Forward POs",str(len(df_ong)),f"Ongoing: {n_ong_o} | Delivered: {n_ong_c}")
        with c2: st.metric("PO Value",f"Rs {df_ong[po_v].sum()/1e7:.2f} Cr" if po_v else "—")
        with c3: st.metric("Yet to Deliver",f"Rs {df_ong[ytd_v].sum()/1e7:.2f} Cr" if ytd_v else "—")
        with c4: st.metric("Realized Savings",f"Rs {df_ong[sav_v].sum()/1e7:.2f} Cr" if sav_v else "—")
        # BU filter
        bu_o=['All']
        if 'BU' in df_ong.columns: bu_o+=sorted([b for b in df_ong['BU'].dropna().unique() if b])
        sel_bu_o=st.selectbox('BU',bu_o,key='ong_bu')
        dfo=df_ong.copy()
        if sel_bu_o!='All' and 'BU' in dfo.columns: dfo=dfo[dfo['BU']==sel_bu_o]
        # BU table
        if 'BU' in dfo.columns and po_v and ytd_v:
            bg2=dfo.groupby('BU').agg(n=(po_v,'count'),pv=(po_v,'sum'),yt=(ytd_v,'sum'),
                **({'sv':(sav_v,'sum')} if sav_v else {})).reset_index()
            rows=""
            for _,r in bg2.sort_values('pv',ascending=False).iterrows():
                svr=f"Rs {r['sv']/1e7:.2f}Cr" if sav_v and 'sv' in r else "—"
                rows+=f'<tr><td><b style="color:#eee">{r["BU"]}</b></td><td class="mn">{int(r["n"])}</td><td class="mn">Rs {r["pv"]/1e7:.2f}Cr</td><td class="mn">Rs {r["yt"]/1e7:.2f}Cr</td><td class="mn">{svr}</td></tr>'
            st.markdown(f'<div style="background:#13131a;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:6px 0;"><table class="zT"><thead><tr><th>BU</th><th>POs</th><th>PO Value</th><th>Yet to Deliver</th><th>Realized Savings</th></tr></thead><tbody>{rows}</tbody></table></div>',unsafe_allow_html=True)
        # Full table
        st.markdown(f"**All {len(dfo)} POs**")
        disp_o=dfo.copy()
        for c in disp_o.columns:
            if pd.api.types.is_datetime64_any_dtype(disp_o[c]): disp_o[c]=disp_o[c].dt.strftime("%d-%b-%Y")
        st.dataframe(disp_o,use_container_width=True,height=min(40*len(dfo)+50,600))

# ════ TAB 8: PR-PO UNCLOSED ═════════════════════
with t8:
    st.markdown("### PR Not Yet Converted to PO")
    # From PO TRACKER: rows where PO Dt is empty = PR raised but no PO yet
    if C_PO_DT in df_po.columns:
        unclosed=df_po[df_po[C_PO_DT].isna()].copy()
    else:
        unclosed=pd.DataFrame()
    if unclosed.empty:
        st.info("No unclosed PRs found (all PRs have PO dates).")
    else:
        # PR revision delay
        if C_PR_DT in unclosed.columns and C_REV_PR in unclosed.columns:
            unclosed['_rev_delay']=(unclosed[C_REV_PR]-unclosed[C_PR_DT]).dt.days
        else:
            unclosed['_rev_delay']=np.nan
        n_total=len(unclosed)
        n_rev=int(unclosed[C_REV_PR].notna().sum()) if C_REV_PR in unclosed.columns else 0
        avg_d=float(unclosed['_rev_delay'].dropna().mean()) if unclosed['_rev_delay'].notna().any() else 0
        max_d=float(unclosed['_rev_delay'].dropna().max()) if unclosed['_rev_delay'].notna().any() else 0
        # Days since PR raised
        if C_PR_DT in unclosed.columns:
            unclosed['_age']=(pd.Timestamp(date.today())-unclosed[C_PR_DT]).dt.days
        c1,c2,c3,c4=st.columns(4)
        with c1: st.metric("Unclosed PRs",str(n_total))
        with c2: st.metric("PRs Revised",str(n_rev),f"{n_total-n_rev} unrevised")
        with c3: st.metric("Avg Revision Delay",f"{avg_d:.0f}d" if avg_d>0 else "—")
        with c4: st.metric("Max Delay",f"{max_d:.0f}d" if max_d>0 else "—")
        # BU filter
        bu_pr=['All']
        if 'BU' in unclosed.columns: bu_pr+=sorted([b for b in unclosed['BU'].dropna().unique() if b])
        c1,c2=st.columns(2)
        with c1: sel_bu_pr=st.selectbox('BU',bu_pr,key='pr_bu')
        with c2:
            cat_pr=['All']
            if 'Category' in unclosed.columns: cat_pr+=sorted([c for c in unclosed['Category'].dropna().unique() if c])
            sel_cat_pr=st.selectbox('Category',cat_pr,key='pr_cat')
        dfp=unclosed.copy()
        if sel_bu_pr!='All': dfp=dfp[dfp['BU']==sel_bu_pr]
        if sel_cat_pr!='All' and 'Category' in dfp.columns: dfp=dfp[dfp['Category']==sel_cat_pr]
        # Charts
        c1,c2=st.columns(2)
        with c1:
            if 'BU' in dfp.columns:
                bd=dfp.groupby('BU').size().reset_index(name='Count').sort_values('Count',ascending=False)
                fig=go.Figure(go.Bar(x=bd['BU'],y=bd['Count'],marker_color=R,marker_line_width=0,
                    text=bd['Count'],textposition='outside',textfont=dict(color='#888',size=11)))
                fig.update_layout(**DK,height=260,title_text='Unclosed PRs by BU',showlegend=False)
                st.plotly_chart(fig,use_container_width=True)
        with c2:
            if C_CUR_ST in dfp.columns:
                sd=dfp[C_CUR_ST].value_counts().head(8).reset_index()
                sd.columns=['Status','Count']
                fig2=go.Figure(go.Bar(y=sd['Status'],x=sd['Count'],orientation='h',marker_color=A,marker_line_width=0,
                    text=sd['Count'],textposition='outside',textfont=dict(color='#888',size=11)))
                fig2.update_layout(**DK,height=260,title_text='By Current Status',showlegend=False)
                st.plotly_chart(fig2,use_container_width=True)
        # Table
        show_cols=[c for c in ['SN','BU','Project Name','Items','Category','Handled by',C_PR_DT,C_REV_PR,C_CUR_ST,'_rev_delay','_age'] if c in dfp.columns]
        ds=dfp[show_cols].copy()
        ds=ds.rename(columns={'_rev_delay':'Revision Delay (days)','_age':'Days Since PR'})
        for c in ds.columns:
            if pd.api.types.is_datetime64_any_dtype(ds[c]): ds[c]=ds[c].dt.strftime("%d-%b-%Y")
        def hl_pr(row):
            d=row.get('Days Since PR',0)
            if pd.notna(d) and d>90: s="background-color:#2a0000;color:#ff9999;font-weight:700;font-size:13px;"
            elif pd.notna(d) and d>45: s="background-color:#1a1000;color:#ffcc66;font-size:13px;"
            else: s="color:#ccc;font-size:13px;"
            return [s]*len(row)
        st.markdown(f"**{len(ds)} PRs**")
        st.dataframe(ds.style.apply(hl_pr,axis=1),use_container_width=True,height=min(40*len(ds)+50,600))

# ── Footer ────────────────────────────────────────────────────
st.markdown(f'<div style="padding:12px 0;border-top:1px solid rgba(255,255,255,.04);margin-top:16px;display:flex;justify-content:space-between;"><div style="font-size:11px;color:#333;">Zetwerk CPT &middot; CAT-2</div><div style="font-size:10px;color:#222;font-family:DM Mono,monospace;">{now} &middot; TTL 60s</div></div>',unsafe_allow_html=True)

# ════ CAT 2 BUDDY (floating) ═══════════════════
chat_html=""
for m in st.session_state.buddy_msgs[-10:]:
    if m['role']=='user':
        chat_html+=f'<div style="background:rgba(229,62,62,.12);border:1px solid rgba(229,62,62,.2);border-radius:10px 10px 2px 10px;padding:8px 12px;margin:4px 0;font-size:12px;color:#eee;max-width:85%;align-self:flex-end;margin-left:auto;">{m["text"]}</div>'
    else:
        chat_html+=f'<div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:10px 10px 10px 2px;padding:8px 12px;margin:4px 0;font-size:12px;color:#ccc;max-width:90%;">{m["text"]}</div>'

buddy_open = st.session_state.get('buddy_open', False)
components.html(f"""<!DOCTYPE html><html><head><style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'DM Sans',Arial,sans-serif;}}
body{{background:transparent;overflow:visible;height:auto;}}
#fab{{position:fixed;bottom:20px;right:20px;z-index:9999;width:52px;height:52px;border-radius:50%;
background:linear-gradient(135deg,#e53e3e,#fc4f4f);display:flex;align-items:center;justify-content:center;
cursor:pointer;box-shadow:0 4px 20px rgba(229,62,62,.5);font-size:22px;border:none;color:white;}}
#fab:hover{{transform:scale(1.1);}}
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
#sbtn{{background:#e53e3e;border:none;border-radius:8px;padding:8px 14px;color:white;
font-size:12px;cursor:pointer;font-weight:600;}}
</style></head><body>
<div id="panel"><div id="hdr"><div id="av">C</div><div><div style="font-size:13px;font-weight:700;color:#fff;">CAT 2 Buddy</div><div style="font-size:10px;color:#38a169;">Online</div></div></div>
<div id="msgs">{chat_html}</div>
<div id="irow"><input id="inp" placeholder="Ask anything..." /><button id="sbtn">Send</button></div></div>
<button id="fab">&#128172;</button>
<script>
var panel=document.getElementById('panel'),fab=document.getElementById('fab'),
    inp=document.getElementById('inp'),sbtn=document.getElementById('sbtn'),
    msgs=document.getElementById('msgs');
if(msgs)msgs.scrollTop=msgs.scrollHeight;
fab.addEventListener('click',function(){{
  var o=panel.style.display==='flex';
  panel.style.display=o?'none':'flex';
  fab.innerHTML=o?'&#128172;':'&#10005;';
  if(!o&&msgs)setTimeout(function(){{msgs.scrollTop=msgs.scrollHeight;}},50);
}});
function doSend(){{
  var v=inp.value.trim();if(!v)return;inp.value='';
  window.parent.location.href=window.parent.location.pathname+'?buddy_msg='+encodeURIComponent(v);
}}
sbtn.addEventListener('click',doSend);
inp.addEventListener('keydown',function(e){{if(e.key==='Enter')doSend();}});
</script></body></html>""", height=420 if buddy_open else 80, scrolling=False)

# Handle buddy message
buddy_msg=st.query_params.get("buddy_msg","")
if buddy_msg and buddy_msg.strip():
    st.query_params.clear()
    st.session_state.buddy_msgs.append({"role":"user","text":buddy_msg})
    st.session_state.buddy_open=True
    with st.spinner(""):
        reply=buddy_chat(buddy_msg,dff)
    st.session_state.buddy_msgs.append({"role":"bot","text":reply})
    st.rerun()
