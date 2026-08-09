import streamlit as st
import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="FX Sniper 8-12", layout="wide")

# ---------- CSS global ----------
st.markdown("""
<style>
    div.stButton > button {
        background-color: #FF9100 !important;
        color: white !important;
        font-weight: bold;
        border: none;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
        line-height: 1.1 !important;
    }
    .session-metrics [data-testid="stMetricValue"] {
        font-size: 0.7rem !important;
    }
    .session-metrics h4 {
        margin-bottom: 0.1rem !important;
        color: #1E90FF !important;
    }
    .session-metrics .stMetric {
        margin-top: 0 !important;
    }
    .active-trade-metrics [data-testid="stMetricValue"] {
        font-size: 0.55rem !important;
    }
    .stMetric {
        margin-bottom: 0.2rem !important;
    }
    .indicators-line {
        font-size: 1.1rem !important;
        line-height: 1.3 !important;
        color: #EAEAEA;
    }
    [data-testid="stMetricLabel"] {
        color: #1E90FF !important;
    }
    .stMarkdown h4, .stMarkdown label {
        color: #1E90FF !important;
    }
    .orange-label {
        color: #FF9100;
        font-weight: normal;
    }
    /* Coins arrondis pour le logo */
    .logo-rounded {
        border-radius: 20px;
    }
    /* Footer */
    .footer {
        text-align: center;
        color: #666;
        font-size: 0.8rem;
        margin-top: 2rem;
        padding-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Authentification ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; color: #00C853;'>🔐 FX Sniper 8‑12 Cockpit - Restricted Access</h1>",
                unsafe_allow_html=True)
    pwd = st.text_input("Password", type="password")
    if st.button("Sign in"):
        if pwd == st.secrets["DASHBOARD_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

# ---------- Utilitaires ----------
MONTREAL_TZ = ZoneInfo("America/Toronto")

@st.cache_data(ttl=30)
def fetch_status():
    repo = st.secrets["GITHUB_REPOSITORY"]
    url = f"https://raw.githubusercontent.com/{repo}/main/status.json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def check_bot_running():
    token = st.secrets.get("GH_PAT")
    repo = st.secrets["GITHUB_REPOSITORY"]
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    params = {"status": "in_progress"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            runs = resp.json()
            if runs["workflow_runs"]:
                return True
        params["status"] = "queued"
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            runs = resp.json()
            if runs["workflow_runs"]:
                return True
    except Exception:
        pass
    return False

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def fmt_num(value, decimals=5):
    try:
        return f"{float(value):.{decimals}f}"
    except (ValueError, TypeError):
        return "--"

# ---------- Logo + nom du bot (même ligne, logo arrondi) ----------
LOGO_URL = "https://raw.githubusercontent.com/NSTradingUS-CA/forexbotny/main/assets/logo.png"
st.markdown(f"""
<div style="display: flex; align-items: center; justify-content: center;">
    <img src="{LOGO_URL}" class="logo-rounded" style="width: 100px; height: auto; margin-right: 20px;">
    <h2 style="color: #FF9100; margin: 0;">FX Sniper 8‑12</h2>
</div>
""", unsafe_allow_html=True)

# ---------- Bouton Sign out ----------
col_empty, col_signout = st.columns([6, 1])
with col_signout:
    if st.button("Sign out"):
        st.session_state.authenticated = False
        st.rerun()

placeholder = st.empty()

while True:
    data = fetch_status()
    now_mtl = datetime.now(MONTREAL_TZ).strftime('%H:%M:%S')
    bot_is_running = check_bot_running()

    if not data:
        with placeholder.container():
            st.error("Status unavailable – retrying in 30s")
        time.sleep(30)
        continue

    with placeholder.container():
        # ---------- Session ----------
        st.markdown('<div class="session-metrics">', unsafe_allow_html=True)
        sess = data.get("session", {})
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        trades = sess.get('trades_today', 0)
        max_tr = sess.get('max_trades', 2)

        col1.markdown("#### Trades")
        col1.metric("", f"{trades}/{max_tr}")

        col2.markdown("#### Session")
        col2.metric("", f"{sess.get('start','08')}–{sess.get('end','12')}")

        col3.markdown("#### Status")
        col3.metric("", "🟢" if bot_is_running else "🔴")

        col4.markdown("#### Time")
        col4.metric("", now_mtl)
        st.markdown('</div>', unsafe_allow_html=True)

        # ---------- News ----------
        news = data.get("next_news_event")
        if news:
            st.markdown(
                f"⏰ **{news['title']}** at {news['time']} – :orange[{news.get('impact','')}]"
            )

        # ---------- Paires ----------
        st.markdown("---")
        cols = st.columns(2)
        for i, pair in enumerate(["EUR_USD", "GBP_USD"]):
            with cols[i]:
                p = data.get("pairs", {}).get(pair, {})
                st.markdown(f"**{pair}**")

                price = p.get('price')
                st.metric("Price", f"{price:.5f}" if price is not None else "--")

                spread_val = p.get('spread', '--')
                spread_str = f"{safe_float(spread_val):.5f}" if spread_val != '--' else '--'
                adx_str = fmt_num(p.get('adx'))
                plus_di_str = fmt_num(p.get('plus_di'))
                minus_di_str = fmt_num(p.get('minus_di'))
                ema50 = p.get('ema50')
                ema200 = p.get('ema200')
                rsi_val = p.get('rsi')

                ema50_str = f"{ema50:.5f}" if ema50 is not None else "--"
                ema200_str = f"{ema200:.5f}" if ema200 is not None else "--"
                rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "--"

                line1 = (
                    f"<span class='orange-label'>Spread:</span> {spread_str} | "
                    f"<span class='orange-label'>ADX:</span> {adx_str} | "
                    f"<span class='orange-label'>+DI:</span> {plus_di_str} | "
                    f"<span class='orange-label'>-DI:</span> {minus_di_str}"
                )
                line2 = (
                    f"<span class='orange-label'>EMA50:</span> {ema50_str} | "
                    f"<span class='orange-label'>EMA200:</span> {ema200_str} | "
                    f"<span class='orange-label'>RSI:</span> {rsi_str}"
                )

                st.markdown(f"<div class='indicators-line'>{line1}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='indicators-line'>{line2}</div>", unsafe_allow_html=True)

                sig = p.get('last_signal')
                if sig:
                    st.markdown(f"Signal: <span class='green'>{sig.upper()}</span>", unsafe_allow_html=True)

        # ---------- Active Trade ----------
        active = data.get("active_trade")
        if active:
            st.markdown("---")
            st.markdown("#### 🔥 Active Trade")
            st.markdown('<div class="active-trade-metrics">', unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Pair", active.get("pair",""))
            c2.metric("Type", active.get("type",""))
            c3.metric("Entry", f"{active.get('entry',0):.5f}")
            c4.metric("Current", f"{active.get('current_price',0):.5f}")
            pnl = active.get('unrealized_pnl',0)
            c1.metric("P&L", f"{pnl:.2f} USD", delta_color="normal" if pnl>=0 else "inverse")
            c2.metric("SL", f"{active.get('sl',0):.5f} ({active.get('distance_to_sl_pips',0)}p)")
            c3.metric("TP", f"{active.get('tp',0):.5f} ({active.get('distance_to_tp_pips',0)}p)")
            c4.metric("Trail", f"{active.get('trailing_stop',0)}p")
            st.markdown('</div>', unsafe_allow_html=True)

        # ---------- Historique & Rejets ----------
        tab1, tab2 = st.tabs(["📜 Closed", "🚫 Rejected"])
        with tab1:
            closed = data.get("closed_trades_today", [])
            if closed:
                for t in closed[::-1]:
                    pnl = t.get('pnl',0)
                    color = "green" if pnl >= 0 else "red"
                    st.markdown(
                        f"<span class='{color}'>{t.get('pair','')} {t.get('type','')} – {pnl:.2f} USD ({t.get('time','')})</span>",
                        unsafe_allow_html=True)
            else:
                st.write("No closed trades.")
        with tab2:
            rejected = data.get("rejected_signals", [])
            if rejected:
                for r in rejected[::-1]:
                    st.markdown(
                        f"<span class='orange'>{r.get('time','')} {r.get('pair','')} – {r.get('reason','')}</span>",
                        unsafe_allow_html=True)
                    if "indicators" in r:
                        with st.expander("Details"):
                            st.json(r["indicators"])
            else:
                st.write("No rejected setups.")

    # ---------- Footer ----------
    st.markdown('<div class="footer">NorthSentinel Trading – FX Sniper 8‑12 – August, 2026 ©</div>', unsafe_allow_html=True)

    time.sleep(30)
