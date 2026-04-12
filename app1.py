# ============================================================
# Zetwerk CPT CAT-2 Dashboard  -  app1.py
# ============================================================

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import anthropic

st.set_page_config(
    page_title="Zetwerk CPT CAT-2 Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background:#0d0d1a; }
  [data-testid="stSidebar"]          { background:#10102a; }
  h1,h2,h3,h4                        { color:#e0e6ff !important; font-size:1.6rem !important; }
  p, li, label, div                  { font-size:1rem !important; }
  .metric-card {
    background:linear-gradient(135deg,#1a1a3e,#2a2a5e);
    border:1px solid #3a3a6e; border-radius:12px;
    padding:22px; text-align:center; margin:4px;
  }
  .metric-val { font-size:2.2rem !important; font-weight:800; color:#7eb8f7; }
  .metric-lbl { font-size:0.95rem !important; color:#8899cc; margin-top:6px; }
  .alert-red  { background:#3a0000; border-left:4px solid #ff4444;
                padding:12px; border-radius:6px; color:#ff9999;
                font-size:1rem !important; }
  .alert-amb  { background:#2a1a00; border-left:4px solid #ffaa00;
                padding:12px; border-radius:6px; color:#ffcc66;
                font-size:1rem !important; }
  .stDataFrame tbody td { font-size:0.95rem !important; }
  .stDataFrame thead th { font-size:0.95rem !important; font-weight:700; }
</style>
""", unsafe_allow_html=True)

SHEET_ID  = "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU"
SHEET_PO  = "PO TRACKER"
SHEET_YTD = "yet to be delivered"
SCOPES    = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=SCOPES)
        gc   = gspread.authorize(creds)
        book = gc.open_by_key(SHEET_ID)

        ws   = book.worksheet(SHEET_PO)
        raw  = ws.get_all_values()
        if len(raw) < 2:
            return pd.DataFrame(), pd.DataFrame(), "PO TRACKER is empty"
        df_po = pd.DataFrame(raw[1:], columns=raw[0])

        try:
            ws2     = book.worksheet(SHEET_YTD)
            raw2    = ws2.get_all_values()
            df_ytd  = pd.DataFrame(raw2[1:], columns=raw2[0]) if len(raw2) > 1 else pd.DataFrame()
        except Exception:
            df_ytd = pd.DataFrame()

        return df_po, df_ytd, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), str(e)


def clean_po(df_raw):
    if df_raw.empty:
        return df_raw
    df = df_raw.copy()
    num_cols = [
        "PO Basic Value","GST","PO Value with GST",
        "PCA Basic Value","PCA Value with GST",
        "Savings Value","Savings %",
        "PO Delivered Value (incl. GST)","PO Yet to Deliver (incl. GST)",
        "Actual Delivery TAT (Days)","OTD","OTIF",
        "Realized Saving","Realized PO Value (Basic)",
        "Delivery Time from MFC (Days)","Payment Score",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",","").str.replace("%",""),
                errors="coerce")
    date_cols = ["PO Dt.","MFC Dt.","Delivery Date at Site","NFA Dt.","NFA App. Dt","PR Dt."]
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], dayfirst=True, errors="coerce")
    if "PO Dt." in df.columns:
        df = df[
            (df["PO Dt."] >= pd.Timestamp("2025-04-01")) &
            (df["PO Dt."] <= pd.Timestamp("2026-02-28"))
        ]
    return df


def clean_ytd(df_raw):
    if df_raw.empty:
        return df_raw
    df = df_raw.copy()
    # Try to find the "yet to be delivered" value column
    for c in df.columns:
        if any(k in c.lower() for k in ["value","deliver","gst"]):
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",","").str.replace("₹",""),
                errors="coerce")
    return df


PAYMENT_SCORE = {
    "advance":1,"lc":2,"ibc":3,"bank":3,
    "vfs":4,"clean credit":5,"on dispatch":5,"ifc":5,
}
def score_payment(term):
    if not term or str(term).strip() == "":
        return np.nan
    t = str(term).lower()
    for k, v in PAYMENT_SCORE.items():
        if k in t:
            return float(v)
    return np.nan


def card(val, lbl):
    return f'<div class="metric-card"><div class="metric-val">{val}</div><div class="metric-lbl">{lbl}</div></div>'


def sidebar_filters(df):
    st.sidebar.markdown("## Zetwerk CPT CAT-2")
    st.sidebar.markdown("### Filters")

    def opts(col):
        if col not in df.columns:
            return []
        return sorted(df[col].dropna().astype(str).unique().tolist())

    bu    = st.sidebar.multiselect("BU",            opts("BU"),            default=[])
    cat   = st.sidebar.multiselect("Category",      opts("Category"),      default=[])
    buyer = st.sidebar.multiselect("Buyer",          opts("Handled by"),    default=[])
    stype = st.sidebar.multiselect("Supplier Type",  opts("Supplier type"), default=[])

    f = df.copy()
    if bu:    f = f[f["BU"].isin(bu)]
    if cat:   f = f[f["Category"].isin(cat)]
    if buyer: f = f[f["Handled by"].isin(buyer)]
    if stype: f = f[f["Supplier type"].isin(stype)]
    st.sidebar.markdown("---")
    st.sidebar.caption(f"{len(f)} / {len(df)} POs shown")
    return f


# ── CAT-2 BUDDY CHATBOT ───────────────────────────────────────
def buddy_sidebar(df):
    st.sidebar.markdown("---")
    st.sidebar.markdown("### CAT-2 Buddy")
    if "chat" not in st.session_state:
        st.session_state.chat = []

    for m in st.session_state.chat[-6:]:
        role = "You" if m["role"] == "user" else "Buddy"
        st.sidebar.markdown(f"**{role}:** {m['content']}")

    q = st.sidebar.text_input("Ask about your PO data", key="buddy_input")
    if st.sidebar.button("Send") and q.strip():
        summary = (
            f"FY Apr25-Feb26. Total POs: {len(df)}. "
            f"PO Value: Rs {df['PO Value with GST'].sum()/1e7:.1f} Cr. "
            f"Savings: Rs {df['Savings Value'].sum()/1e7:.1f} Cr. "
            f"Delivery Status counts: {df['Delivery Status'].value_counts().to_dict() if 'Delivery Status' in df.columns else 'N/A'}. "
            f"BUs: {df['BU'].value_counts().to_dict() if 'BU' in df.columns else 'N/A'}."
        ) if not df.empty else "No data loaded."

        st.session_state.chat.append({"role":"user","content":q})
        try:
            client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
            msgs = [{"role":"user","content":
                     f"You are CAT-2 Buddy, a procurement assistant for Zetwerk CPT CAT-2. "
                     f"Dashboard data: {summary}\n\nQuestion: {q}"}]
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                messages=msgs,
            )
            answer = resp.content[0].text
        except Exception as e:
            answer = f"Error: {e}"
        st.session_state.chat.append({"role":"assistant","content":answer})
        st.rerun()


def main():
    with st.spinner("Connecting to Google Sheets..."):
        df_raw, df_ytd_raw, err = load_data()

    if err:
        st.error(f"Connection error: {err}")
        return

    df  = clean_po(df_raw)
    ytd = clean_ytd(df_ytd_raw)

    if df.empty:
        st.warning("No data in FY range Apr 2025 - Feb 2026.")
        return

    if "Payment Score" not in df.columns or df["Payment Score"].isna().all():
        pt_col = next((c for c in ["PAYMENT TERMS","Payment Terms"] if c in df.columns), None)
        if pt_col:
            df["Payment Score"] = df[pt_col].apply(score_payment)

    df_f = sidebar_filters(df)
    buddy_sidebar(df_f)

    tabs = st.tabs([
        "Overview",
        "Spend and Savings",
        "TAT and OTIF",
        "Working Capital",
        "New Vendor Dev",
        "MFC Tracker",
    ])

    # ── TAB 1: OVERVIEW ──────────────────────────────────────
    with tabs[0]:
        st.markdown("## Overview — FY 2025-26 (Apr to Feb)")

        total_val = df_f["PO Value with GST"].sum() / 1e7 if "PO Value with GST" in df_f.columns else 0
        total_sav = df_f["Savings Value"].sum() / 1e7 if "Savings Value" in df_f.columns else 0
        n_po      = len(df_f)
        n_supp    = df_f["Supplier Name"].nunique() if "Supplier Name" in df_f.columns else 0
        n_bu      = df_f["BU"].nunique() if "BU" in df_f.columns else 0

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.markdown(card(f"Rs {total_val:.1f} Cr", "Total PO Value"),    unsafe_allow_html=True)
        c2.markdown(card(f"Rs {total_sav:.1f} Cr", "Total Savings"),     unsafe_allow_html=True)
        c3.markdown(card(str(n_po),                 "Total POs"),         unsafe_allow_html=True)
        c4.markdown(card(str(n_supp),               "Suppliers"),         unsafe_allow_html=True)
        c5.markdown(card(str(n_bu),                 "Business Units"),    unsafe_allow_html=True)

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            if "BU" in df_f.columns:
                bu_cnt = df_f.groupby("BU").size().reset_index(name="POs")
                fig = px.bar(bu_cnt, x="BU", y="POs", title="PO Count by BU",
                             color="BU",
                             color_discrete_sequence=px.colors.qualitative.Bold,
                             template="plotly_dark")
                fig.update_layout(showlegend=False,
                                  paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)",
                                  font=dict(size=14))
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            if "Delivery Status" in df_f.columns:
                sc = df_f["Delivery Status"].value_counts().reset_index()
                sc.columns = ["Status","Count"]
                cm = {"Completed":"#4caf50","Ongoing":"#ff9800","Shortclose":"#2196f3"}
                fig2 = px.pie(sc, names="Status", values="Count",
                              title="Delivery Status", color="Status",
                              color_discrete_map=cm, hole=0.45,
                              template="plotly_dark")
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                   font=dict(size=14))
                st.plotly_chart(fig2, use_container_width=True)

        if "PO Dt." in df_f.columns and "PO Value with GST" in df_f.columns:
            st.markdown("### Monthly PO Value Trend")
            tr = df_f.copy()
            tr["Month"] = tr["PO Dt."].dt.to_period("M").astype(str)
            mo = tr.groupby("Month")["PO Value with GST"].sum().div(1e7).reset_index()
            mo.columns = ["Month","PO Value (Cr)"]
            mo = mo.sort_values("Month")
            fig3 = px.line(mo, x="Month", y="PO Value (Cr)",
                           title="Monthly PO Value (Rs Cr)",
                           markers=True, template="plotly_dark",
                           color_discrete_sequence=["#7eb8f7"])
            fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                               plot_bgcolor="rgba(0,0,0,0)",
                               font=dict(size=14))
            st.plotly_chart(fig3, use_container_width=True)

        # Yet to be delivered section
        if not ytd.empty:
            st.markdown("### Yet to Be Delivered — Ongoing POs")
            # Find numeric column with "yet" or "deliver" in name
            ytd_val_col = None
            for c in ytd.columns:
                if "yet" in c.lower() or ("deliver" in c.lower() and "value" in c.lower()):
                    if pd.api.types.is_numeric_dtype(ytd[c]):
                        ytd_val_col = c
                        break
            if ytd_val_col:
                ytd_total = pd.to_numeric(ytd[ytd_val_col], errors="coerce").sum() / 1e7
                st.info(f"Total PO value yet to be delivered: Rs {ytd_total:.2f} Cr across {len(ytd)} ongoing POs")
            st.dataframe(ytd.head(25), use_container_width=True, height=320)

    # ── TAB 2: SPEND & SAVINGS ────────────────────────────────
    with tabs[1]:
        st.markdown("## Spend and Savings Analysis")

        if "Savings Value" in df_f.columns and "PO Value with GST" in df_f.columns:
            pov = df_f["PO Value with GST"].sum() / 1e7
            pca = df_f["PCA Value with GST"].sum() / 1e7 if "PCA Value with GST" in df_f.columns else 0
            sav = df_f["Savings Value"].sum() / 1e7
            pca_sum = df_f["PCA Value with GST"].sum() if "PCA Value with GST" in df_f.columns else 0
            sav_pct = (df_f["Savings Value"].sum() / pca_sum * 100) if pca_sum > 0 else 0

            c1,c2,c3,c4 = st.columns(4)
            c1.markdown(card(f"Rs {pov:.1f} Cr", "PO Value"),       unsafe_allow_html=True)
            c2.markdown(card(f"Rs {pca:.1f} Cr", "PCA Value"),       unsafe_allow_html=True)
            c3.markdown(card(f"Rs {sav:.1f} Cr", "Total Savings"),   unsafe_allow_html=True)
            c4.markdown(card(f"{sav_pct:.1f}%",  "Savings %"),       unsafe_allow_html=True)

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if "BU" in df_f.columns:
                    sb = df_f.groupby("BU")["Savings Value"].sum().div(1e7).reset_index()
                    sb.columns = ["BU","Savings (Cr)"]
                    fig = px.bar(sb.sort_values("Savings (Cr)", ascending=True),
                                 x="Savings (Cr)", y="BU", orientation="h",
                                 title="Savings by BU (Rs Cr)",
                                 color="Savings (Cr)",
                                 color_continuous_scale="Blues",
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                if "Category" in df_f.columns:
                    sc2 = df_f.groupby("Category")["Savings Value"].sum().div(1e7).reset_index()
                    sc2.columns = ["Category","Savings (Cr)"]
                    sc2 = sc2[sc2["Savings (Cr)"] != 0].sort_values("Savings (Cr)", ascending=False).head(10)
                    fig = px.bar(sc2, x="Category", y="Savings (Cr)",
                                 title="Top 10 Categories by Savings",
                                 color="Savings (Cr)",
                                 color_continuous_scale="Greens",
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)

            st.markdown("### Realized Savings")
            real = df_f["Realized Saving"].sum() / 1e7 if "Realized Saving" in df_f.columns else 0
            real_pct = (real / sav * 100) if sav > 0 else 0

            c1,c2 = st.columns(2)
            c1.markdown(card(f"Rs {real:.1f} Cr", "Realized Saving"),               unsafe_allow_html=True)
            c2.markdown(card(f"{real_pct:.0f}%",  "Pct of Target Savings Realized"), unsafe_allow_html=True)

            fig_g = go.Figure(go.Indicator(
                mode="gauge+number",
                value=real_pct,
                title={"text":"Savings Realization %","font":{"color":"white","size":18}},
                gauge={"axis":{"range":[0,100]},
                       "bar":{"color":"#4caf50"},
                       "steps":[{"range":[0,50],"color":"#3a0000"},
                                {"range":[50,75],"color":"#2a1a00"},
                                {"range":[75,100],"color":"#1a3a1a"}],
                       "threshold":{"value":80,"line":{"color":"#7eb8f7","width":3}}},
                number={"suffix":"%","font":{"color":"#7eb8f7","size":42}},
            ))
            fig_g.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white", height=320)
            st.plotly_chart(fig_g, use_container_width=True)

    # ── TAB 3: TAT & OTIF ────────────────────────────────────
    with tabs[2]:
        st.markdown("## TAT and OTIF Analysis")

        comp = df_f[df_f["Delivery Status"].isin(["Completed","Shortclose"])] \
               if "Delivery Status" in df_f.columns else df_f

        otif_col = next((c for c in ["OTIF"] if c in comp.columns), None)
        otd_col  = next((c for c in ["OTD"]  if c in comp.columns), None)

        if otif_col and len(comp) > 0:
            otif_pct = (comp[otif_col].dropna() <= 1.05).mean() * 100
            otd_pct  = (comp[otd_col].dropna()  <= 1.0).mean()  * 100 if otd_col else 0
            tat_avg  = comp["Actual Delivery TAT (Days)"].dropna().mean() \
                       if "Actual Delivery TAT (Days)" in comp.columns else 0

            c1,c2,c3,c4 = st.columns(4)
            c1.markdown(card(f"{otif_pct:.1f}%", "OTIF %"),           unsafe_allow_html=True)
            c2.markdown(card(f"{otd_pct:.1f}%",  "OTD %"),            unsafe_allow_html=True)
            c3.markdown(card(f"{tat_avg:.0f}d",  "Avg Delivery TAT"), unsafe_allow_html=True)
            c4.markdown(card(str(len(comp)),      "Completed POs"),    unsafe_allow_html=True)

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if "BU" in comp.columns:
                    ob = comp.groupby("BU")[otif_col].apply(
                        lambda x: (x.dropna() <= 1.05).mean() * 100
                    ).reset_index()
                    ob.columns = ["BU","OTIF %"]
                    fig = px.bar(ob.sort_values("OTIF %"),
                                 x="BU", y="OTIF %", title="OTIF % by BU",
                                 color="OTIF %",
                                 color_continuous_scale="RdYlGn",
                                 range_color=[50,100],
                                 template="plotly_dark")
                    fig.add_hline(y=95, line_dash="dash", line_color="#7eb8f7",
                                  annotation_text="Target 95%")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                if "Actual Delivery TAT (Days)" in comp.columns:
                    td = comp["Actual Delivery TAT (Days)"].dropna()
                    fig = px.histogram(td, nbins=30,
                                       title="Delivery TAT Distribution (Days)",
                                       color_discrete_sequence=["#7eb8f7"],
                                       template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No OTIF/OTD data. Ensure columns exist in PO TRACKER.")

    # ── TAB 4: WORKING CAPITAL ────────────────────────────────
    with tabs[3]:
        st.markdown("## Working Capital Efficiency")

        if "Payment Score" in df_f.columns:
            df_ps = df_f.dropna(subset=["Payment Score","PO Value with GST"])
            df_ps = df_ps[df_ps["PO Value with GST"] > 0]

            if len(df_ps) > 0:
                ws_score = (
                    (df_ps["Payment Score"] * df_ps["PO Value with GST"]).sum() /
                    df_ps["PO Value with GST"].sum()
                )
                pct_fav = (df_ps["Payment Score"] >= 4).mean() * 100

                c1,c2,c3 = st.columns(3)
                c1.markdown(card(f"{ws_score:.2f} / 5", "Weighted Payment Score"),    unsafe_allow_html=True)
                c2.markdown(card(str(len(df_ps)),        "POs with Payment Terms"),    unsafe_allow_html=True)
                c3.markdown(card(f"{pct_fav:.0f}%",      "Pct Favourable Terms (>=4)"), unsafe_allow_html=True)

                st.markdown("---")
                col1, col2 = st.columns(2)

                with col1:
                    pt_col = next((c for c in ["PAYMENT TERMS","Payment Terms"]
                                   if c in df_ps.columns), None)
                    if pt_col:
                        ptc = df_ps[pt_col].value_counts().head(10).reset_index()
                        ptc.columns = ["Payment Term","Count"]
                        fig = px.bar(ptc, x="Count", y="Payment Term",
                                     orientation="h", title="Top Payment Terms",
                                     color="Count",
                                     color_continuous_scale="Blues",
                                     template="plotly_dark")
                        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                          plot_bgcolor="rgba(0,0,0,0)",
                                          font=dict(size=14))
                        st.plotly_chart(fig, use_container_width=True)

                with col2:
                    sd = df_ps["Payment Score"].value_counts().sort_index().reset_index()
                    sd.columns = ["Score","Count"]
                    sm = {1:"Advance",2:"LC",3:"IBC/Bank",4:"VFS",5:"Clean Credit/IFC"}
                    sd["Label"] = sd["Score"].map(sm)
                    fig = px.bar(sd, x="Label", y="Count",
                                 title="Payment Score Distribution",
                                 color="Score",
                                 color_continuous_scale="RdYlGn",
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Payment Score column not found. Ensure PAYMENT TERMS is in PO TRACKER.")

    # ── TAB 5: NEW VENDOR DEVELOPMENT ────────────────────────
    with tabs[4]:
        st.markdown("## New Vendor Development")

        if "Supplier type" in df_f.columns:
            nv    = df_f["Supplier type"].str.upper().str.contains("NV", na=False)
            nv_p  = nv.mean() * 100
            nv_n  = nv.sum()
            nv_v  = df_f.loc[nv,"PO Value with GST"].sum() / 1e7 \
                    if "PO Value with GST" in df_f.columns else 0

            c1,c2,c3 = st.columns(3)
            c1.markdown(card(f"{nv_p:.1f}%",       "NVD % (Target 10-15%)"), unsafe_allow_html=True)
            c2.markdown(card(str(int(nv_n)),         "New Vendor POs"),        unsafe_allow_html=True)
            c3.markdown(card(f"Rs {nv_v:.1f} Cr",   "NV PO Value"),           unsafe_allow_html=True)

            if nv_p < 10:
                st.markdown('<div class="alert-amb">NVD below target (10%). Consider exploring new vendors.</div>',
                            unsafe_allow_html=True)
            elif nv_p > 15:
                st.markdown('<div class="alert-amb">NVD above 15% — ensure quality controls are in place.</div>',
                            unsafe_allow_html=True)
            else:
                st.success(f"NVD at {nv_p:.1f}% — within target range (10-15%)")

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if "BU" in df_f.columns:
                    nb = df_f.groupby("BU").apply(
                        lambda x: x["Supplier type"].str.upper().str.contains("NV", na=False).mean() * 100
                    ).reset_index()
                    nb.columns = ["BU","NVD %"]
                    fig = px.bar(nb.sort_values("NVD %"),
                                 x="BU", y="NVD %", title="NVD % by BU",
                                 color="NVD %",
                                 color_continuous_scale="Viridis",
                                 template="plotly_dark")
                    fig.add_hline(y=10, line_dash="dash", line_color="#ff9800",
                                  annotation_text="Min 10%")
                    fig.add_hline(y=15, line_dash="dash", line_color="#4caf50",
                                  annotation_text="Max 15%")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                st2 = df_f["Supplier type"].value_counts().reset_index()
                st2.columns = ["Type","Count"]
                fig = px.pie(st2, names="Type", values="Count",
                             title="Supplier Type Mix", hole=0.4,
                             template="plotly_dark",
                             color_discrete_sequence=px.colors.qualitative.Bold)
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                  font=dict(size=14))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Supplier type column not found.")

    # ── TAB 6: MFC TRACKER ───────────────────────────────────
    with tabs[5]:
        st.markdown("## MFC Delivery Tracker")
        st.caption("Traffic light: GREEN = >30 days | AMBER = 30 days or less | RED = 1/3 of delivery days or less | OVERDUE = past expected date")

        today    = pd.Timestamp(date.today())
        mfc_col  = next((c for c in ["MFC Dt.","MFC Date"] if c in df_f.columns), None)
        days_col = next((c for c in ["Delivery Time from MFC (Days)",
                                     "Delivery Time from MFC"] if c in df_f.columns), None)

        if not mfc_col or not days_col:
            st.warning("MFC Dt. or Delivery Time from MFC columns not found. Run CPT Tools > Add Missing Cols in Google Sheets first.")
        else:
            keep = [c for c in [
                "SN","BU","Project Name","Items","Category","Handled by",
                "Supplier Name","PO/ OD Ref.","PO Dt.",
                mfc_col, days_col,
                "PO Yet to Deliver (incl. GST)","Delivery Status","Current Status"
            ] if c in df_f.columns]

            mfc_df = df_f[keep].copy()
            mfc_df[mfc_col]  = pd.to_datetime(mfc_df[mfc_col], dayfirst=True, errors="coerce")
            mfc_df[days_col] = pd.to_numeric(mfc_df[days_col], errors="coerce")
            mfc_df = mfc_df.dropna(subset=[mfc_col, days_col])
            mfc_df = mfc_df[mfc_df[days_col] > 0]

            if mfc_df.empty:
                st.info("No rows with valid MFC date and delivery days found.")
            else:
                mfc_df["Expected Delivery"] = mfc_df.apply(
                    lambda r: r[mfc_col] + timedelta(days=int(r[days_col])), axis=1)
                mfc_df["Days Remaining"]    = (mfc_df["Expected Delivery"] - today).dt.days
                mfc_df["Red Threshold"]     = np.ceil(mfc_df[days_col] / 3).astype(int)

                def classify(r):
                    rem = r["Days Remaining"]; thr = r["Red Threshold"]
                    if rem <= 0:      return "OVERDUE"
                    elif rem <= thr:  return "RED"
                    elif rem <= 30:   return "AMBER"
                    else:             return "GREEN"

                mfc_df["Alert"] = mfc_df.apply(classify, axis=1)
                counts = mfc_df["Alert"].value_counts()

                c1,c2,c3,c4 = st.columns(4)
                c1.markdown(card(counts.get("GREEN",0),   "On Track"),    unsafe_allow_html=True)
                c2.markdown(card(counts.get("AMBER",0),   "Amber Alert"), unsafe_allow_html=True)
                c3.markdown(card(counts.get("RED",0),     "Red Alert"),   unsafe_allow_html=True)
                c4.markdown(card(counts.get("OVERDUE",0), "Overdue"),     unsafe_allow_html=True)

                red_pos = mfc_df[mfc_df["Alert"].isin(["RED","OVERDUE"])]
                if not red_pos.empty:
                    st.markdown(
                        f'<div class="alert-red"><b>{len(red_pos)} PO(s) are RED or OVERDUE.</b> '
                        f'Immediate action required. Weekly email sent to ayushkamle16@gmail.com every Monday 8AM.</div>',
                        unsafe_allow_html=True)

                st.markdown("---")
                af = st.multiselect(
                    "Filter by Alert Status",
                    ["OVERDUE","RED","AMBER","GREEN"],
                    default=["OVERDUE","RED","AMBER"],
                )
                disp = mfc_df[mfc_df["Alert"].isin(af)].copy() if af else mfc_df.copy()

                disp_show = disp.copy()
                disp_show[mfc_col]             = disp_show[mfc_col].dt.strftime("%d-%b-%Y")
                disp_show["Expected Delivery"] = disp_show["Expected Delivery"].dt.strftime("%d-%b-%Y")
                if "PO Dt." in disp_show.columns:
                    disp_show["PO Dt."] = pd.to_datetime(
                        disp_show["PO Dt."], errors="coerce").dt.strftime("%d-%b-%Y")
                ytd_c = "PO Yet to Deliver (incl. GST)"
                if ytd_c in disp_show.columns:
                    disp_show[ytd_c] = pd.to_numeric(
                        disp_show[ytd_c], errors="coerce"
                    ).apply(lambda x: f"Rs {x:,.0f}" if pd.notna(x) else "")

                def hl(row):
                    s = {
                        "OVERDUE": "background-color:#3a0000;color:#ff9999;font-weight:bold;font-size:14px",
                        "RED":     "background-color:#2a0000;color:#ff6666;font-weight:bold;font-size:14px",
                        "AMBER":   "background-color:#2a1a00;color:#ffcc66;font-size:13px",
                        "GREEN":   "background-color:#0a2a0a;color:#66cc66;font-size:13px",
                    }.get(row["Alert"],"")
                    return [s]*len(row)

                st.dataframe(
                    disp_show.style.apply(hl, axis=1),
                    use_container_width=True, height=520)

                col1, col2 = st.columns(2)
                with col1:
                    ab = mfc_df.groupby(["BU","Alert"]).size().reset_index(name="Count")
                    fig = px.bar(ab, x="BU", y="Count", color="Alert",
                                 title="MFC Alert Status by BU",
                                 color_discrete_map={
                                     "GREEN":"#4caf50","AMBER":"#ff9800",
                                     "RED":"#f44336","OVERDUE":"#9c0000"},
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      font=dict(size=14))
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    ap = mfc_df["Alert"].value_counts().reset_index()
                    ap.columns = ["Alert","Count"]
                    fig2 = px.pie(ap, names="Alert", values="Count",
                                  title="Alert Distribution",
                                  color="Alert",
                                  color_discrete_map={
                                      "GREEN":"#4caf50","AMBER":"#ff9800",
                                      "RED":"#f44336","OVERDUE":"#9c0000"},
                                  hole=0.4, template="plotly_dark")
                    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                       font=dict(size=14))
                    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.caption(
        f"Zetwerk CPT CAT-2 Dashboard  |  FY 2025-26 (Apr to Feb)  |  "
        f"Data refreshes every 5 min  |  "
        f"Last loaded: {datetime.now().strftime('%d %b %Y %H:%M')}"
    )


if __name__ == "__main__":
    main()
