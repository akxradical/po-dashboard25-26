"""
═══════════════════════════════════════════════════════════════════════════
  CAT-2 MFC DELIVERY ALERT MAILER
  Zetwerk Central Procurement Team
───────────────────────────────────────────────────────────────────────────
  Reads the live PO TRACKER Google Sheet, computes MFC delivery status for
  every PO, and emails sophisticated HTML reports via Gmail SMTP.

  BUYER MAIL  → their own POs. Priority order: OVERDUE → RED → AMBER → GREEN.
                Each PO shows item, project, value, OD/PO ref, vendor,
                MFC date, expected date, days left / days overdue.

  MANAGER MAIL → all POs, grouped by buyer. For each buyer, the same
                 OVERDUE → RED → AMBER → GREEN breakdown.

  Schedule with cron / Task Scheduler (e.g. Monday 8 AM).
═══════════════════════════════════════════════════════════════════════════

SETUP (one time)
  1. pip install gspread google-auth pandas
       (Python < 3.11 also needs:  pip install tomli)
  2. Keep secrets.toml in the SAME folder as this script.
     It holds your Gmail address, the App Password, and the Google
     service-account credentials. NEVER commit it to GitHub —
     add a line "secrets.toml" to your .gitignore.
  3. Make sure the Google Sheet is shared (Viewer) with the
     service-account email in secrets.toml:
     po-dashboard24-25@po-dashboard-24-25.iam.gserviceaccount.com

RUN
  python mfc_alert_mailer.py             # send for real
  python mfc_alert_mailer.py --dry-run   # print plan, send nothing
  python mfc_alert_mailer.py --test ayush.kamle@zetwerk.in   # full view to you
"""

import os
import sys
import math
import json
import smtplib
import datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# TOML reader (Python 3.11+ has tomllib built in; else pip install tomli)
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

# ════════════════════════════════════════════════════════════════════════
#  SECRETS
#  Priority 1: individual environment variables (GitHub Actions secrets)
#  Priority 2: a local secrets.toml file (for running on your own machine)
# ════════════════════════════════════════════════════════════════════════
def _load_secrets():
    # If the individual env vars are present (GitHub Actions), use them.
    gu = os.getenv("GMAIL_USER")
    gj = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if gu and gj:
        sa = json.loads(gj)
        return {
            "gmail_user":     gu,
            "gmail_app_pass": os.getenv("GMAIL_APP_PASS", ""),
            "gcp_service_account": sa,
        }
    # If we're clearly on a CI runner but env vars are missing, fail loudly.
    if os.getenv("GITHUB_ACTIONS") == "true":
        missing = [n for n in ("GMAIL_USER", "GMAIL_APP_PASS", "GCP_SERVICE_ACCOUNT_JSON")
                   if not os.getenv(n)]
        raise RuntimeError(
            "Running on GitHub Actions but these secrets are missing/empty: "
            + ", ".join(missing)
            + ". Add them under Settings → Secrets and variables → Actions, "
            + "with EXACTLY these names.")
    # Otherwise load the local secrets.toml file (for running on your own machine).
    path = os.getenv("SECRETS_PATH", "secrets.toml")
    with open(path, "rb") as f:
        return tomllib.load(f)


_S = _load_secrets()

GMAIL_USER     = _S["gmail_user"]
GMAIL_APP_PASS = _S["gmail_app_pass"]
SERVICE_INFO   = dict(_S["gcp_service_account"])
SENDER_NAME    = "CAT-2 Procurement Dashboard"

# ════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════
GSHEET_ID  = os.getenv("GSHEET_ID", "11iDCUUEry2YsokCyvqsp6w8yi295fcX7w-K23BrSHQU")
GSHEET_TAB = os.getenv("GSHEET_TAB", "PO TRACKER  27")          # note: TWO spaces

# Managers — receive consolidated mail (all buyers, grouped by buyer)
MANAGER_EMAILS = [
    "ramsundar.a@zetwerk.in",
    "santhosh.r@zetwerk.com",
]

# Buyer name (exactly as in "Handled by" column)  →  email
# Matching is case-insensitive, so "AYUSH" / "Ayush" both work.
BUYER_EMAILS = {
    "AYUSH": "ayush.kamle@zetwerk.in",
    # add more buyers here, e.g.  "Hari Kishore": "hari@zetwerk.in"
}

SEND_BUYER_MAILS = True

# Status order & colors
STATUS_ORDER = ["OVERDUE", "RED", "AMBER", "GREEN"]
STATUS_META  = {
    "OVERDUE": {"color": "#e53e3e", "label": "Overdue — Immediate Action", "icon": "🔴"},
    "RED":     {"color": "#dd6b20", "label": "Critical — Due Very Soon",    "icon": "🟠"},
    "AMBER":   {"color": "#d69e2e", "label": "Watch — Approaching",         "icon": "🟡"},
    "GREEN":   {"color": "#38a169", "label": "On Track",                    "icon": "🟢"},
}
DARK = "#0d0d1a"
CARD = "#13131a"
INK  = "#1a1a2e"

# ════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ════════════════════════════════════════════════════════════════════════
def load_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = Credentials.from_service_account_info(SERVICE_INFO, scopes=scopes)
    gc     = gspread.authorize(creds)
    sh     = gc.open_by_key(GSHEET_ID)

    ws = None
    for w in sh.worksheets():
        if w.title.strip().lower() == GSHEET_TAB.strip().lower():
            ws = w; break
    if ws is None:
        for w in sh.worksheets():
            if "po tracker" in w.title.lower():
                ws = w; break
    if ws is None:
        raise RuntimeError(f"Tab '{GSHEET_TAB}' not found.")

    data = ws.get_all_values(value_render_option="FORMATTED_VALUE")

    hdr_idx = 0
    for i in range(min(5, len(data))):
        up = [str(x).strip().upper() for x in data[i]]
        if "BU" in up and ("SN" in up or "PROJECT NAME" in up):
            hdr_idx = i; break

    raw_h, seen, headers = data[hdr_idx], {}, []
    for h in raw_h:
        h = str(h).strip()
        if not h: h = f"_col_{len(headers)}"
        if h in seen: seen[h] += 1; h = f"{h}_{seen[h]}"
        else: seen[h] = 0
        headers.append(h)

    df = pd.DataFrame(data[hdr_idx + 1:], columns=headers)
    bu_col = next((c for c in df.columns if c.strip().upper() == "BU"), None)
    df = df[df[bu_col].astype(str).str.strip().replace(
        {"": None, "None": None, "nan": None}).notna()]
    return df


def col(df, *keys):
    for c in df.columns:
        cl = c.lower().replace("\n", " ")
        if all(k in cl for k in keys):
            return c
    return None


def to_num(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False)
                     .str.replace("₹", "", regex=False).str.strip(),
        errors="coerce")


def parse_date(s):
    out = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    m = out.isna()
    if m.any():
        out.loc[m] = pd.to_datetime(s[m], errors="coerce", dayfirst=True)
    return out


# ════════════════════════════════════════════════════════════════════════
#  MFC STATUS COMPUTATION
# ════════════════════════════════════════════════════════════════════════
def compute_alerts(df):
    C_BU    = next(c for c in df.columns if c.strip().upper() == "BU")
    C_PROJ  = col(df, "project")
    C_ITEM  = "Items" if "Items" in df.columns else col(df, "item")
    C_BUYER = col(df, "handled by")
    C_SUP   = col(df, "supplier", "name")
    C_REF   = col(df, "po/od") or col(df, "po", "ref")
    C_VAL   = col(df, "po", "basic", "value")
    C_MFC   = col(df, "mfc", "dt")
    C_DAYS  = col(df, "delivery time") or col(df, "mfc", "days")

    today = pd.Timestamp(dt.date.today())
    mfc   = parse_date(df[C_MFC]) if C_MFC else pd.Series(pd.NaT, index=df.index)
    days  = to_num(df[C_DAYS]) if C_DAYS else pd.Series(float("nan"), index=df.index)

    rows = []
    for i in df.index:
        m, d = mfc.get(i), days.get(i)
        if pd.isna(m) or pd.isna(d):
            continue
        expected  = m + pd.Timedelta(days=int(d))
        days_left = (expected - today).days
        threshold = max(1, math.ceil(int(d) / 3))

        if days_left <= 0:    status = "OVERDUE"
        elif days_left <= threshold: status = "RED"
        elif days_left <= 30: status = "AMBER"
        else:                 status = "GREEN"

        rows.append({
            "BU":       str(df.at[i, C_BU]).strip() if C_BU else "",
            "Project":  str(df.at[i, C_PROJ]).strip() if C_PROJ else "",
            "Item":     str(df.at[i, C_ITEM]).strip() if C_ITEM else "",
            "Buyer":    str(df.at[i, C_BUYER]).strip() if C_BUYER else "",
            "Supplier": str(df.at[i, C_SUP]).strip() if C_SUP else "",
            "PORef":    str(df.at[i, C_REF]).strip() if C_REF else "",
            "POValue":  to_num(pd.Series([df.at[i, C_VAL]])).iloc[0] if C_VAL else 0,
            "MFCDate":  m.strftime("%d %b %Y"),
            "Expected": expected.strftime("%d %b %Y"),
            "DaysLeft": days_left,
            "Status":   status,
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════════
#  HTML BUILDERS
# ════════════════════════════════════════════════════════════════════════
def fmt_value(v):
    if v is None or pd.isna(v) or v == 0:
        return "—"
    if v >= 1e7:  return f"Rs {v/1e7:.2f} Cr"
    if v >= 1e5:  return f"Rs {v/1e5:.2f} L"
    return f"Rs {v:,.0f}"


def days_badge(days_left, status):
    c = STATUS_META[status]["color"]
    if status == "OVERDUE":
        txt = f"{abs(days_left)}d overdue"
    elif days_left == 0:
        txt = "due today"
    else:
        txt = f"{days_left}d left"
    return (f'<span style="color:#fff;background:{c};padding:3px 9px;border-radius:5px;'
            f'font-size:12px;font-weight:700;white-space:nowrap;">{txt}</span>')


def po_row_html(r):
    accent = STATUS_META[r["Status"]]["color"]
    return f"""
    <tr>
      <td style="padding:12px 16px;border-bottom:1px solid #eee;border-left:4px solid {accent};">
        <div style="font-size:14px;font-weight:700;color:{INK};">{r['Item'] or '—'}</div>
        <div style="font-size:12px;color:#888;margin-top:2px;">{r['BU']} &middot; {r['Project'] or '—'}</div>
        <div style="font-size:11px;color:#aaa;margin-top:3px;">OD/PO: {r['PORef'] or '—'} &middot; {r['Supplier'] or '—'}</div>
      </td>
      <td style="padding:12px 12px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;">
        <div style="font-size:13px;font-weight:700;color:{INK};">{fmt_value(r['POValue'])}</div>
        <div style="font-size:11px;color:#aaa;margin-top:2px;">{r['Buyer'] or '—'}</div>
      </td>
      <td style="padding:12px 12px;border-bottom:1px solid #eee;text-align:center;white-space:nowrap;">
        <div style="font-size:11px;color:#888;">MFC: {r['MFCDate']}</div>
        <div style="font-size:11px;color:#888;margin-top:2px;">Due: {r['Expected']}</div>
      </td>
      <td style="padding:12px 16px;border-bottom:1px solid #eee;text-align:right;">
        {days_badge(r['DaysLeft'], r['Status'])}
      </td>
    </tr>"""


def status_section(df_status, status):
    """One status block (e.g. all OVERDUE rows), sorted most-urgent first."""
    if len(df_status) == 0:
        return ""
    meta = STATUS_META[status]
    body = df_status.sort_values("DaysLeft")
    rows = "".join(po_row_html(r) for _, r in body.iterrows())
    return f"""
    <div style="padding:14px 24px 6px;">
      <div style="font-size:13px;font-weight:800;color:{meta['color']};text-transform:uppercase;letter-spacing:.05em;">
        {meta['icon']} {meta['label']} ({len(df_status)})
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">{rows}</table>"""


def summary_strip(df_alerts):
    counts = {s: int((df_alerts["Status"] == s).sum()) for s in STATUS_ORDER}
    cells = ""
    for s in STATUS_ORDER:
        cells += f"""
        <div style="flex:1;text-align:center;border-right:1px solid rgba(255,255,255,.08);">
          <div style="font-size:26px;font-weight:800;color:{STATUS_META[s]['color']};font-family:monospace;">{counts[s]}</div>
          <div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.07em;margin-top:2px;">{s.title()}</div>
        </div>"""
    val = df_alerts[df_alerts["Status"].isin(["OVERDUE", "RED"])]["POValue"].sum()
    cells += f"""
        <div style="flex:1.3;text-align:center;">
          <div style="font-size:22px;font-weight:800;color:#fff;font-family:monospace;">{fmt_value(val)}</div>
          <div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.07em;margin-top:2px;">At Risk</div>
        </div>"""
    return f'<div style="display:flex;background:{CARD};padding:16px 24px;gap:10px;">{cells}</div>'


def shell(audience, today_str, greeting, body_html, df_alerts):
    return f"""
<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:700px;margin:0 auto;background:#fff;">
  <div style="background:{DARK};padding:24px;">
    <div style="display:flex;align-items:center;justify-content:space-between;">
      <div>
        <div style="font-size:11px;font-weight:700;color:#fc4f4f;letter-spacing:.12em;text-transform:uppercase;">Zetwerk CPT &middot; CAT-2</div>
        <div style="font-size:22px;font-weight:800;color:#fff;margin-top:4px;">MFC Delivery Report</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:11px;color:#888;">{today_str}</div>
        <div style="font-size:11px;color:#888;margin-top:2px;">{audience}</div>
      </div>
    </div>
  </div>
  {summary_strip(df_alerts)}
  <div style="padding:20px 24px 4px;">
    <div style="font-size:14px;color:{INK};line-height:1.6;">{greeting}</div>
  </div>
  {body_html}
  <div style="padding:8px 24px 26px;">
    <a href="https://cat-2-dashboard.streamlit.app" style="display:inline-block;background:#e53e3e;color:#fff;text-decoration:none;padding:11px 22px;border-radius:8px;font-size:13px;font-weight:700;">Open Live Dashboard →</a>
  </div>
  <div style="background:{DARK};padding:18px 24px;">
    <div style="font-size:11px;color:#666;line-height:1.6;">
      Automated from the CAT-2 Procurement Dashboard. Priority order: Overdue → Red → Amber → Green.<br>
      Expected Delivery = MFC Date + Delivery Days. Generated {today_str}.
    </div>
  </div>
</div></body></html>"""


def build_buyer_email(buyer, df_own):
    """Buyer sees their own POs: OVERDUE → RED → AMBER → GREEN."""
    today_str = dt.date.today().strftime("%d %B %Y")
    body = "".join(status_section(df_own[df_own["Status"] == s], s) for s in STATUS_ORDER)
    if not body:
        body = """<div style="padding:36px 24px;text-align:center;">
          <div style="font-size:42px;">✅</div>
          <div style="font-size:15px;font-weight:700;color:#38a169;margin-top:8px;">No deliveries to track right now.</div></div>"""
    n_o = int((df_own["Status"] == "OVERDUE").sum())
    n_r = int((df_own["Status"] == "RED").sum())
    if (n_o + n_r) > 0:
        urgent = '<b style="color:#e53e3e;">' + str(n_o + n_r) + ' need urgent follow-up.</b>'
    else:
        urgent = 'Nothing urgent today.'
    greeting = f"Hi {buyer}, here is your delivery status. {urgent}"
    html = shell(buyer, today_str, greeting, body, df_own)
    subj = (f"🔴 Your MFC Report: {n_o} overdue, {n_r} critical — {today_str}"
            if (n_o or n_r) else f"MFC Report: all on track — {today_str}")
    return subj, html


def build_manager_email(df_all):
    """Manager sees ALL POs grouped by buyer, each buyer's OVERDUE→RED→AMBER→GREEN."""
    today_str = dt.date.today().strftime("%d %B %Y")

    # Order buyers by urgency (most overdue+red first)
    def urgency(b):
        sub = df_all[df_all["Buyer"] == b]
        return -int(sub["Status"].isin(["OVERDUE", "RED"]).sum())
    buyers = sorted([b for b in df_all["Buyer"].unique() if str(b).strip()], key=urgency)

    blocks = ""
    for b in buyers:
        sub = df_all[df_all["Buyer"] == b]
        n_o = int((sub["Status"] == "OVERDUE").sum())
        n_r = int((sub["Status"] == "RED").sum())
        n_a = int((sub["Status"] == "AMBER").sum())
        n_g = int((sub["Status"] == "GREEN").sum())
        inner = "".join(status_section(sub[sub["Status"] == s], s) for s in STATUS_ORDER)
        blocks += f"""
        <div style="margin:18px 0 4px;padding:12px 24px;background:#f7f8fa;border-top:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
          <div style="font-size:16px;font-weight:800;color:{INK};">{b or 'Unassigned'}</div>
          <div style="font-size:11px;color:#888;margin-top:3px;">
            <b style="color:#e53e3e;">{n_o} overdue</b> &middot;
            <b style="color:#dd6b20;">{n_r} critical</b> &middot;
            <b style="color:#d69e2e;">{n_a} watch</b> &middot;
            <b style="color:#38a169;">{n_g} on track</b>
          </div>
        </div>
        {inner}"""

    if not blocks:
        blocks = """<div style="padding:36px 24px;text-align:center;">
          <div style="font-size:42px;">✅</div>
          <div style="font-size:15px;font-weight:700;color:#38a169;margin-top:8px;">No deliveries to track.</div></div>"""

    n_o = int((df_all["Status"] == "OVERDUE").sum())
    n_r = int((df_all["Status"] == "RED").sum())
    greeting = ("Team-wide delivery status across all buyers. "
                "<b style='color:#e53e3e;'>" + str(n_o + n_r) + " POs need urgent attention.</b>")
    html = shell("All Buyers", today_str, greeting, blocks, df_all)
    subj = f"🔴 CAT-2 MFC Report: {n_o} overdue, {n_r} critical — {today_str}"
    return subj, html


# ════════════════════════════════════════════════════════════════════════
#  SEND
# ════════════════════════════════════════════════════════════════════════
def send_email(to_emails, subject, html, dry_run=False):
    if isinstance(to_emails, str):
        to_emails = [to_emails]
    if dry_run:
        print(f"  [DRY-RUN] To: {', '.join(to_emails)}  |  {subject}")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_NAME} <{GMAIL_USER}>"
    msg["To"]      = ", ".join(to_emails)
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASS)
        s.sendmail(GMAIL_USER, to_emails, msg.as_string())
    print(f"  ✓ Sent to {', '.join(to_emails)}  |  {subject}")


# ════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════
def main():
    dry_run = "--dry-run" in sys.argv
    test_to = None
    if "--test" in sys.argv:
        i = sys.argv.index("--test")
        if i + 1 < len(sys.argv):
            test_to = sys.argv[i + 1]

    print("Loading sheet …")
    df = load_sheet()
    alerts = compute_alerts(df)
    print(f"Computed {len(alerts)} POs with MFC data "
          f"({(alerts['Status']=='OVERDUE').sum()} overdue, "
          f"{(alerts['Status']=='RED').sum()} red, "
          f"{(alerts['Status']=='AMBER').sum()} amber, "
          f"{(alerts['Status']=='GREEN').sum()} green).")

    if test_to:
        subj, html = build_manager_email(alerts)
        send_email(test_to, subj, html, dry_run=dry_run)
        return

    print("Managers:")
    if MANAGER_EMAILS:
        subj, html = build_manager_email(alerts)
        send_email(MANAGER_EMAILS, subj, html, dry_run=dry_run)

    if SEND_BUYER_MAILS:
        print("Buyers:")
        for buyer, email in BUYER_EMAILS.items():
            own = alerts[alerts["Buyer"].str.strip().str.lower() == buyer.strip().lower()]
            if len(own) == 0:
                print(f"  - {buyer}: no POs, skipped")
                continue
            subj, html = build_buyer_email(buyer, own)
            send_email(email, subj, html, dry_run=dry_run)

    print("Done.")


if __name__ == "__main__":
    main()
