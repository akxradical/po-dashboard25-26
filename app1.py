# ============================================================
# Zetwerk CPT CAT-2 Dashboard  –  app1.py
# Updated: reads PO TRACKER + "yet to be delivered" sheets
# Tabs: Overview | Spend & Savings | TAT & OTIF | Working Capital
#       NVD | MFC Delivery Tracker
# ============================================================

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# ── PAGE CONFIG ──────────────────────────────────────────────
st.set_page_config(
    page_title="Zetwerk CPT CAT-2 Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CUSTOM CSS ───────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #0d0d1a; }
  [data-testid="stSidebar"] { background: #10102a; }
  h1,h2,h3,h4 { color: #e0e6ff !important; }
  .metric-card {
    background: linear-gradient(135deg,#1a1a3e,#2a2a5e);
    border: 1px solid #3a3a6e; border-radius: 12px;
    padding: 20px; text-align: center; margin: 4px;
  }
  .metric-val  { font-size: 2rem; font-weight: 800; color: #7eb8f7; }
  .metric-lbl  { font-size: 0.85rem; color: #8899cc; margin-top: 4px; }
  .alert-red   { background:#3a0000; border-left:4px solid #ff4444; padding:10px; border-radius:6px; color:#ff9999; font-size:0.95rem; }
  .alert-amber { background:#2a1a00; border-left:4px solid #ffaa00; padding:10px; border-radius:6px; color:#ffcc66; font-size:0.95rem; }
  .stDataFrame { border-radius:8px; }
</style>
""", unsafe_allow_html=True)

# ── GOOGLE SHEETS CONNECTION ──────────────────────────────────
SHEET_ID   = "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU"
SHEET_PO   = "PO TRACKER"
SHEET_YTD  = "yet to be delivered"
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    try:
        creds  = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=SCOPES)
        gc     = gspread.authorize(creds)
        book   = gc.open_by_key(SHEET_ID)

        # ── PO TRACKER ────────────────────────────────────────
        ws_po  = book.worksheet(SHEET_PO)
        raw_po = ws_po.get_all_values()
        if len(raw_po) < 2:
            return pd.DataFrame(), pd.DataFrame(), "PO TRACKER is empty"
        df_po  = pd.DataFrame(raw_po[1:], columns=raw_po[0])

        # ── YET TO BE DELIVERED ───────────────────────────────
        try:
            ws_ytd  = book.worksheet(SHEET_YTD)
            raw_ytd = ws_ytd.get_all_values()
            df_ytd  = pd.DataFrame(raw_ytd[1:], columns=raw_ytd[0]) if len(raw_ytd)>1 else pd.DataFrame()
        except Exception:
            df_ytd = pd.DataFrame()

        return df_po, df_ytd, None

    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), str(e)


def clean_po(df_raw: pd.DataFrame) -> pd.DataFrame:
    if df_raw.empty:
        return df_raw
    df = df_raw.copy()

    # Numeric cols
    num_cols = [
        "PO Basic Value", "GST", "PO Value with GST",
        "PCA Basic Value", "PCA Value with GST",
        "Savings Value", "Savings %",
        "PO Delivered Value (incl. GST)", "PO Yet to Deliver (incl. GST)",
        "Actual Delivery TAT (Days)", "OTD", "OTIF",
        "Realized Saving", "Realized PO Value (Basic)",
        "Delivery Time from MFC (Days)",
        "Payment Score",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", "").str.replace("%", ""), errors="coerce"
            )

    # Date cols
    date_cols = ["PO Dt.", "MFC Dt.", "Delivery Date at Site",
                 "NFA Dt.", "NFA App. Dt", "PR Dt."]
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], dayfirst=True, errors="coerce")

    # FY filter Apr-2025 → Feb-2026
    if "PO Dt." in df.columns:
        df = df[
            (df["PO Dt."] >= pd.Timestamp("2025-04-01")) &
            (df["PO Dt."] <= pd.Timestamp("2026-02-28"))
        ]

    return df


def clean_ytd(df_raw: pd.DataFrame) -> pd.DataFrame:
    if df_raw.empty:
        return df_raw
    df = df_raw.copy()
    for c in ["PO Value with GST", "PO Yet to Deliver (incl. GST)",
              "O Value (incl. GST)", "be Delivered (incl. GST)"]:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", ""), errors="coerce"
            )
    if "PO Date" in df.columns:
        df["PO Date"] = pd.to_datetime(df["PO Date"], dayfirst=True, errors="coerce")
    return df


# ── PAYMENT SCORE MAP ─────────────────────────────────────────
PAYMENT_SCORE = {
    "advance": 1, "lc": 2, "ibc": 3, "bank": 3,
    "vfs": 4, "clean credit": 5, "on dispatch": 5, "ifc": 5,
}
def score_payment(term: str) -> float:
    if not term or str(term).strip() == "":
        return np.nan
    t = str(term).lower()
    for k, v in PAYMENT_SCORE.items():
        if k in t:
            return float(v)
    return np.nan


# ── SIDEBAR ───────────────────────────────────────────────────
def sidebar_filters(df: pd.DataFrame):
    st.sidebar.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/Zetwerk_logo.svg/512px-Zetwerk_logo.svg.png",
        width=160
    )
    st.sidebar.markdown("### 🔍 Filters")

    def opts(col):
        if col not in df.columns:
            return ["All"]
        return ["All"] + sorted(df[col].dropna().astype(str).unique().tolist())

    bu    = st.sidebar.multiselect("BU",           opts("BU")[1:],           default=[])
    cat   = st.sidebar.multiselect("Category",     opts("Category")[1:],     default=[])
    buyer = st.sidebar.multiselect("Buyer",         opts("Handled by")[1:],   default=[])
    stype = st.sidebar.multiselect("Supplier Type", opts("Supplier type")[1:], default=[])

    filtered = df.copy()
    if bu:    filtered = filtered[filtered["BU"].isin(bu)]
    if cat:   filtered = filtered[filtered["Category"].isin(cat)]
    if buyer: filtered = filtered[filtered["Handled by"].isin(buyer)]
    if stype: filtered = filtered[filtered["Supplier type"].isin(stype)]

    st.sidebar.markdown("---")
    st.sidebar.caption(f"📋 {len(filtered)} / {len(df)} POs shown")
    return filtered


def metric(val, lbl):
    return f'<div class="metric-card"><div class="metric-val">{val}</div><div class="metric-lbl">{lbl}</div></div>'


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    # ── Splash ────────────────────────────────────────────────
    splash = st.empty()
    with splash.container():
        st.markdown("""
        <div style="text-align:center;padding:80px 0;">
          <div style="font-size:4rem;">⚡</div>
          <h1 style="color:#7eb8f7;font-size:2.5rem;">Zetwerk CPT CAT-2</h1>
          <p style="color:#8899cc;font-size:1.1rem;">Loading dashboard…</p>
        </div>""", unsafe_allow_html=True)

    with st.spinner("Connecting to Google Sheets…"):
        df_raw, df_ytd_raw, err = load_data()

    splash.empty()

    if err:
        st.error(f"❌ Connection error: {err}")
        st.info("Check your `gcp_service_account` secret and sheet permissions.")
        return

    df  = clean_po(df_raw)
    ytd = clean_ytd(df_ytd_raw)

    if df.empty:
        st.warning("⚠️ No data in FY range (Apr 2025 – Feb 2026). Check sheet.")
        return

    # Add payment score if missing
    if "Payment Score" not in df.columns or df["Payment Score"].isna().all():
        pt_col = next((c for c in ["PAYMENT TERMS","Payment Terms"] if c in df.columns), None)
        if pt_col:
            df["Payment Score"] = df[pt_col].apply(score_payment)

    df_f = sidebar_filters(df)

    # ── TAB LAYOUT ────────────────────────────────────────────
    tabs = st.tabs([
        "📊 Overview",
        "💰 Spend & Savings",
        "🚚 TAT & OTIF",
        "🏦 Working Capital",
        "🆕 New Vendor Dev",
        "📅 MFC Tracker",
    ])

    # ════════════════════════════════════════════════
    # TAB 1 — OVERVIEW
    # ════════════════════════════════════════════════
    with tabs[0]:
        st.markdown("## 📊 Overview — FY 2025-26 (Apr–Feb)")

        total_val  = df_f["PO Value with GST"].sum() / 1e7 if "PO Value with GST" in df_f else 0
        total_sav  = df_f["Savings Value"].sum() / 1e7 if "Savings Value" in df_f else 0
        n_po       = len(df_f)
        n_supp     = df_f["Supplier Name"].nunique() if "Supplier Name" in df_f else 0
        n_bu       = df_f["BU"].nunique() if "BU" in df_f else 0

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.markdown(metric(f"₹{total_val:.1f} Cr", "Total PO Value"), unsafe_allow_html=True)
        c2.markdown(metric(f"₹{total_sav:.1f} Cr", "Total Savings"), unsafe_allow_html=True)
        c3.markdown(metric(str(n_po),  "Total POs"),     unsafe_allow_html=True)
        c4.markdown(metric(str(n_supp),"Suppliers"),     unsafe_allow_html=True)
        c5.markdown(metric(str(n_bu),  "Business Units"), unsafe_allow_html=True)

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            # PO count by BU
            if "BU" in df_f.columns:
                bu_cnt = df_f.groupby("BU").size().reset_index(name="POs")
                fig = px.bar(bu_cnt, x="BU", y="POs",
                             title="PO Count by BU",
                             color="BU", color_discrete_sequence=px.colors.qualitative.Bold,
                             template="plotly_dark")
                fig.update_layout(showlegend=False, paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            # Delivery Status donut
            if "Delivery Status" in df_f.columns:
                stat_cnt = df_f["Delivery Status"].value_counts().reset_index()
                stat_cnt.columns = ["Status","Count"]
                colors = {"Completed":"#4caf50","Ongoing":"#ff9800","Shortclose":"#2196f3"}
                fig2 = px.pie(stat_cnt, names="Status", values="Count",
                              title="Delivery Status Distribution",
                              color="Status", color_discrete_map=colors,
                              hole=0.45, template="plotly_dark")
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig2, use_container_width=True)

        # PO Value trend by month
        if "PO Dt." in df_f.columns and "PO Value with GST" in df_f.columns:
            st.markdown("### 📈 Monthly PO Value Trend")
            trend = df_f.copy()
            trend["Month"] = trend["PO Dt."].dt.to_period("M").astype(str)
            monthly = trend.groupby("Month")["PO Value with GST"].sum().div(1e7).reset_index()
            monthly.columns = ["Month","PO Value (Cr)"]
            monthly = monthly.sort_values("Month")
            fig3 = px.line(monthly, x="Month", y="PO Value (Cr)",
                           title="Monthly PO Value (₹ Cr)",
                           markers=True, template="plotly_dark",
                           color_discrete_sequence=["#7eb8f7"])
            fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig3, use_container_width=True)

        # YTD sheet summary
        if not ytd.empty:
            st.markdown("### 🔄 Yet to Be Delivered (Ongoing POs)")
            ytd_val_col = next((c for c in ytd.columns if "deliver" in c.lower() and "yet" in c.lower()), None)
            if ytd_val_col:
                ytd_total = ytd[ytd_val_col].sum() / 1e7
                st.info(f"💰 Total PO value yet to be delivered: **₹{ytd_total:.2f} Cr** across **{len(ytd)} ongoing POs**")
            st.dataframe(ytd.head(20), use_container_width=True, height=300)

    # ════════════════════════════════════════════════
    # TAB 2 — SPEND & SAVINGS
    # ════════════════════════════════════════════════
    with tabs[1]:
        st.markdown("## 💰 Spend & Savings Analysis")

        if "Savings Value" in df_f.columns and "PO Value with GST" in df_f.columns:
            sav_total = df_f["Savings Value"].sum() / 1e7
            pov_total = df_f["PO Value with GST"].sum() / 1e7
            pca_total = df_f["PCA Value with GST"].sum() / 1e7 if "PCA Value with GST" in df_f else 0
            sav_pct   = (df_f["Savings Value"].sum() / df_f["PCA Value with GST"].sum() * 100
                         if "PCA Value with GST" in df_f and df_f["PCA Value with GST"].sum() > 0 else 0)

            c1,c2,c3,c4 = st.columns(4)
            c1.markdown(metric(f"₹{pov_total:.1f} Cr","PO Value (GST)"), unsafe_allow_html=True)
            c2.markdown(metric(f"₹{pca_total:.1f} Cr","PCA Value (GST)"), unsafe_allow_html=True)
            c3.markdown(metric(f"₹{sav_total:.1f} Cr","Total Savings"),   unsafe_allow_html=True)
            c4.markdown(metric(f"{sav_pct:.1f}%","Savings %"),            unsafe_allow_html=True)

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if "BU" in df_f.columns:
                    sav_bu = df_f.groupby("BU")["Savings Value"].sum().div(1e7).reset_index()
                    sav_bu.columns = ["BU","Savings (Cr)"]
                    fig = px.bar(sav_bu.sort_values("Savings (Cr)", ascending=True),
                                 x="Savings (Cr)", y="BU", orientation="h",
                                 title="Savings by BU (₹ Cr)",
                                 color="Savings (Cr)",
                                 color_continuous_scale="Blues",
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                if "Category" in df_f.columns:
                    sav_cat = df_f.groupby("Category")["Savings Value"].sum().div(1e7).reset_index()
                    sav_cat.columns = ["Category","Savings (Cr)"]
                    sav_cat = sav_cat[sav_cat["Savings (Cr)"] != 0].sort_values("Savings (Cr)", ascending=False).head(10)
                    fig = px.bar(sav_cat, x="Category", y="Savings (Cr)",
                                 title="Top 10 Categories by Savings",
                                 color="Savings (Cr)", color_continuous_scale="Greens",
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)

            # Realized vs Target Savings
            st.markdown("### ✅ Realized Savings")
            real_sav  = df_f["Realized Saving"].sum() / 1e7 if "Realized Saving" in df_f else 0
            real_pct  = (real_sav / sav_total * 100) if sav_total > 0 else 0

            c1,c2 = st.columns(2)
            c1.markdown(metric(f"₹{real_sav:.1f} Cr", "Realized Saving"), unsafe_allow_html=True)
            c2.markdown(metric(f"{real_pct:.0f}%", "% of Target Savings Realized"), unsafe_allow_html=True)

            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=real_pct,
                title={"text":"Savings Realization %","font":{"color":"white"}},
                gauge={"axis":{"range":[0,100]},
                       "bar":{"color":"#4caf50"},
                       "steps":[{"range":[0,50],"color":"#3a0000"},
                                {"range":[50,75],"color":"#2a1a00"},
                                {"range":[75,100],"color":"#1a3a1a"}],
                       "threshold":{"value":80,"line":{"color":"#7eb8f7","width":3}}},
                number={"suffix":"%","font":{"color":"#7eb8f7","size":36}},
            ))
            fig_gauge.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                    font_color="white", height=300)
            st.plotly_chart(fig_gauge, use_container_width=True)

    # ════════════════════════════════════════════════
    # TAB 3 — TAT & OTIF
    # ════════════════════════════════════════════════
    with tabs[2]:
        st.markdown("## 🚚 TAT & OTIF Analysis")

        comp = df_f[df_f.get("Delivery Status", pd.Series(dtype=str)).isin(
            ["Completed","Shortclose"])] if "Delivery Status" in df_f.columns else df_f

        otif_col = next((c for c in ["OTIF","Otif"] if c in comp.columns), None)
        otd_col  = next((c for c in ["OTD","Otd"]   if c in comp.columns), None)

        if otif_col and len(comp) > 0:
            otif_pct = (comp[otif_col].dropna() <= 1.05).mean() * 100
            otd_pct  = (comp[otd_col].dropna()  <= 1.0).mean()  * 100 if otd_col else 0
            tat_avg  = comp["Actual Delivery TAT (Days)"].dropna().mean() if "Actual Delivery TAT (Days)" in comp.columns else 0

            c1,c2,c3,c4 = st.columns(4)
            c1.markdown(metric(f"{otif_pct:.1f}%", "OTIF %"),              unsafe_allow_html=True)
            c2.markdown(metric(f"{otd_pct:.1f}%",  "OTD %"),               unsafe_allow_html=True)
            c3.markdown(metric(f"{tat_avg:.0f}d",  "Avg Delivery TAT"),    unsafe_allow_html=True)
            c4.markdown(metric(str(len(comp)),      "Completed POs"),       unsafe_allow_html=True)

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if "BU" in comp.columns and otif_col:
                    otif_bu = comp.groupby("BU")[otif_col].apply(
                        lambda x: (x.dropna() <= 1.05).mean() * 100
                    ).reset_index()
                    otif_bu.columns = ["BU","OTIF %"]
                    fig = px.bar(otif_bu.sort_values("OTIF %"),
                                 x="BU", y="OTIF %", title="OTIF % by BU",
                                 color="OTIF %",
                                 color_continuous_scale="RdYlGn",
                                 range_color=[50,100],
                                 template="plotly_dark")
                    fig.add_hline(y=95, line_dash="dash", line_color="#7eb8f7",
                                  annotation_text="Target 95%")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                if "Actual Delivery TAT (Days)" in comp.columns:
                    tat_dist = comp["Actual Delivery TAT (Days)"].dropna()
                    fig = px.histogram(tat_dist, nbins=30,
                                       title="Delivery TAT Distribution (Days)",
                                       color_discrete_sequence=["#7eb8f7"],
                                       template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No OTIF/OTD data available. Ensure columns exist in PO TRACKER.")

    # ════════════════════════════════════════════════
    # TAB 4 — WORKING CAPITAL
    # ════════════════════════════════════════════════
    with tabs[3]:
        st.markdown("## 🏦 Working Capital Efficiency")

        if "Payment Score" in df_f.columns:
            df_ps = df_f.dropna(subset=["Payment Score","PO Value with GST"])
            df_ps = df_ps[df_ps["PO Value with GST"] > 0]

            if len(df_ps) > 0:
                wt_score = (
                    (df_ps["Payment Score"] * df_ps["PO Value with GST"]).sum() /
                    df_ps["PO Value with GST"].sum()
                )
                c1,c2,c3 = st.columns(3)
                c1.markdown(metric(f"{wt_score:.2f}/5", "Weighted Payment Score"), unsafe_allow_html=True)
                c2.markdown(metric(str(len(df_ps)),    "POs with Payment Terms"), unsafe_allow_html=True)
                pct_fav = (df_ps["Payment Score"] >= 4).mean() * 100
                c3.markdown(metric(f"{pct_fav:.0f}%", "% Favourable Terms (≥4)"), unsafe_allow_html=True)

                st.markdown("---")
                col1, col2 = st.columns(2)

                with col1:
                    pt_col = next((c for c in ["PAYMENT TERMS","Payment Terms"] if c in df_ps.columns), None)
                    if pt_col:
                        pt_cnt = df_ps[pt_col].value_counts().head(10).reset_index()
                        pt_cnt.columns = ["Payment Term","Count"]
                        fig = px.bar(pt_cnt, x="Count", y="Payment Term",
                                     orientation="h", title="Top Payment Terms",
                                     color="Count",
                                     color_continuous_scale="Blues",
                                     template="plotly_dark")
                        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                          plot_bgcolor="rgba(0,0,0,0)")
                        st.plotly_chart(fig, use_container_width=True)

                with col2:
                    score_dist = df_ps["Payment Score"].value_counts().sort_index().reset_index()
                    score_dist.columns = ["Score","Count"]
                    score_map = {1:"Advance",2:"LC",3:"IBC/Bank",4:"VFS",5:"Clean Credit/IFC"}
                    score_dist["Label"] = score_dist["Score"].map(score_map)
                    fig = px.bar(score_dist, x="Label", y="Count",
                                 title="Payment Score Distribution",
                                 color="Score",
                                 color_continuous_scale="RdYlGn",
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Payment Score column not found. Ensure PAYMENT TERMS is in PO TRACKER.")

    # ════════════════════════════════════════════════
    # TAB 5 — NEW VENDOR DEVELOPMENT
    # ════════════════════════════════════════════════
    with tabs[4]:
        st.markdown("## 🆕 New Vendor Development")

        if "Supplier type" in df_f.columns:
            nv_mask  = df_f["Supplier type"].str.upper().str.contains("NV", na=False)
            nv_pct   = nv_mask.mean() * 100
            n_nv     = nv_mask.sum()
            nv_val   = df_f.loc[nv_mask, "PO Value with GST"].sum() / 1e7 if "PO Value with GST" in df_f else 0

            c1,c2,c3 = st.columns(3)
            c1.markdown(metric(f"{nv_pct:.1f}%", "NVD % (Target 10-15%)"), unsafe_allow_html=True)
            c2.markdown(metric(str(int(n_nv)),    "New Vendor POs"),         unsafe_allow_html=True)
            c3.markdown(metric(f"₹{nv_val:.1f} Cr","NV PO Value"),          unsafe_allow_html=True)

            if nv_pct < 10:
                st.markdown('<div class="alert-amber">⚠️ NVD below target (10%). Consider exploring new vendors.</div>', unsafe_allow_html=True)
            elif nv_pct > 15:
                st.markdown('<div class="alert-amber">⚠️ NVD above 15% — ensure quality controls are in place.</div>', unsafe_allow_html=True)
            else:
                st.success(f"✅ NVD at {nv_pct:.1f}% — within target range (10-15%)")

            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                if "BU" in df_f.columns:
                    nv_bu = df_f.groupby("BU").apply(
                        lambda x: (x["Supplier type"].str.upper().str.contains("NV", na=False)).mean() * 100
                    ).reset_index()
                    nv_bu.columns = ["BU","NVD %"]
                    fig = px.bar(nv_bu.sort_values("NVD %"),
                                 x="BU", y="NVD %", title="NVD % by BU",
                                 color="NVD %",
                                 color_continuous_scale="Viridis",
                                 template="plotly_dark")
                    fig.add_hline(y=10, line_dash="dash", line_color="#ff9800",
                                  annotation_text="Min 10%")
                    fig.add_hline(y=15, line_dash="dash", line_color="#4caf50",
                                  annotation_text="Max 15%")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                sup_type = df_f["Supplier type"].value_counts().reset_index()
                sup_type.columns = ["Type","Count"]
                fig = px.pie(sup_type, names="Type", values="Count",
                             title="Supplier Type Mix", hole=0.4,
                             template="plotly_dark",
                             color_discrete_sequence=px.colors.qualitative.Bold)
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

    # ════════════════════════════════════════════════
    # TAB 6 — MFC DELIVERY TRACKER
    # ════════════════════════════════════════════════
    with tabs[5]:
        st.markdown("## 📅 MFC Delivery Tracker")
        st.caption("Traffic light based on days remaining vs contracted delivery days from MFC date")

        today = pd.Timestamp(date.today())

        mfc_col  = next((c for c in ["MFC Dt.", "MFC Date"] if c in df_f.columns), None)
        days_col = next((c for c in ["Delivery Time from MFC (Days)",
                                      "Delivery Time from MFC"] if c in df_f.columns), None)

        if not mfc_col or not days_col:
            st.warning("⚠️ MFC Dt. or Delivery Time columns not found.\nRun **CPT Tools → Add Missing Cols** in Google Sheets first.")
        else:
            mfc_df = df_f[[
                col for col in [
                    "SN","BU","Project Name","Items","Category","Handled by",
                    "Supplier Name","PO/ OD Ref.","PO Dt.",
                    mfc_col, days_col,
                    "PO Yet to Deliver (incl. GST)","Delivery Status","Current Status"
                ] if col in df_f.columns
            ]].copy()

            # Parse dates
            mfc_df[mfc_col]  = pd.to_datetime(mfc_df[mfc_col],  dayfirst=True, errors="coerce")
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

                def classify(row):
                    rem = row["Days Remaining"]
                    thr = row["Red Threshold"]
                    if rem <= 0:       return "OVERDUE"
                    elif rem <= thr:   return "RED"
                    elif rem <= 30:    return "AMBER"
                    else:              return "GREEN"

                mfc_df["Alert"] = mfc_df.apply(classify, axis=1)

                # Summary counts
                counts = mfc_df["Alert"].value_counts()
                c1,c2,c3,c4 = st.columns(4)
                c1.markdown(metric(counts.get("GREEN",0),   "🟢 On Track"),     unsafe_allow_html=True)
                c2.markdown(metric(counts.get("AMBER",0),   "🟡 Amber Alert"),  unsafe_allow_html=True)
                c3.markdown(metric(counts.get("RED",0),     "🔴 Red Alert"),    unsafe_allow_html=True)
                c4.markdown(metric(counts.get("OVERDUE",0), "⛔ Overdue"),      unsafe_allow_html=True)

                # Alerts
                red_pos = mfc_df[mfc_df["Alert"].isin(["RED","OVERDUE"])]
                if not red_pos.empty:
                    st.markdown(
                        f'<div class="alert-red">🚨 <b>{len(red_pos)} PO(s)</b> are RED/OVERDUE! '
                        f'Immediate action required. Weekly email sent to ayushkamle16@gmail.com every Monday 8AM.</div>',
                        unsafe_allow_html=True)

                st.markdown("---")

                # Filter by alert
                alert_filter = st.multiselect(
                    "Filter by Alert Status",
                    ["OVERDUE","RED","AMBER","GREEN"],
                    default=["OVERDUE","RED","AMBER"],
                )
                disp = mfc_df[mfc_df["Alert"].isin(alert_filter)].copy() if alert_filter else mfc_df

                # Style and display
                def row_color(alert):
                    return {
                        "OVERDUE": "background-color:#3a0000;color:#ff9999;font-weight:bold;font-size:13px",
                        "RED":     "background-color:#2a0000;color:#ff6666;font-weight:bold;font-size:13px",
                        "AMBER":   "background-color:#2a1a00;color:#ffcc66;font-size:12px",
                        "GREEN":   "background-color:#0a2a0a;color:#66cc66;font-size:12px",
                    }.get(alert, "")

                # Format for display
                disp_show = disp.copy()
                disp_show[mfc_col]            = disp_show[mfc_col].dt.strftime("%d-%b-%Y")
                disp_show["Expected Delivery"] = disp_show["Expected Delivery"].dt.strftime("%d-%b-%Y")
                if "PO Dt." in disp_show.columns:
                    disp_show["PO Dt."] = pd.to_datetime(disp_show["PO Dt."], errors="coerce").dt.strftime("%d-%b-%Y")
                if "PO Yet to Deliver (incl. GST)" in disp_show.columns:
                    disp_show["PO Yet to Deliver (incl. GST)"] = disp_show["PO Yet to Deliver (incl. GST)"].apply(
                        lambda x: f"₹{x:,.0f}" if pd.notna(x) and x != "" else ""
                    )

                def highlight_row(row):
                    s = row_color(row["Alert"])
                    return [s] * len(row)

                st.dataframe(
                    disp_show.style.apply(highlight_row, axis=1),
                    use_container_width=True,
                    height=500
                )

                # Chart: BU breakdown
                col1, col2 = st.columns(2)
                with col1:
                    alert_bu = mfc_df.groupby(["BU","Alert"]).size().reset_index(name="Count")
                    fig = px.bar(alert_bu, x="BU", y="Count", color="Alert",
                                 title="MFC Alert Status by BU",
                                 color_discrete_map={
                                     "GREEN":"#4caf50","AMBER":"#ff9800",
                                     "RED":"#f44336","OVERDUE":"#9c0000"
                                 },
                                 template="plotly_dark")
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                      plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    alert_pie = mfc_df["Alert"].value_counts().reset_index()
                    alert_pie.columns = ["Alert","Count"]
                    fig2 = px.pie(alert_pie, names="Alert", values="Count",
                                  title="Alert Distribution",
                                  color="Alert",
                                  color_discrete_map={
                                      "GREEN":"#4caf50","AMBER":"#ff9800",
                                      "RED":"#f44336","OVERDUE":"#9c0000"
                                  },
                                  hole=0.4, template="plotly_dark")
                    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig2, use_container_width=True)

    # ── Footer ────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        f"⚡ Zetwerk CPT CAT-2 Dashboard  |  "
        f"FY 2025-26 (Apr–Feb)  |  "
        f"Data refreshes every 5 min  |  "
        f"Last loaded: {datetime.now().strftime('%d %b %Y %H:%M')}"
    )


if __name__ == "__main__":
    main()
