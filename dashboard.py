import requests
import time

st.set_page_config(page_title="MyForexBotNY Cockpit", layout="wide")

# ---------- CSS global (avec classes par section) ----------
st.markdown("""
<style>
    /* Boutons orange */
    div.stButton > button {
        background-color: #FF9100 !important;
        color: white !important;
        font-weight: bold;
        border: none;
    }

    /* ---------- FORCER LA RÉDUCTION GLOBALE DES MÉTRIQUES (base) ---------- */
    [data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
        line-height: 1.1 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 1.2rem !important;
        line-height: 1.1 !important;
    }

    /* ---------- SECTION SESSION (plus petite) ---------- */
    .session-metrics [data-testid="stMetricValue"] {
        font-size: 0.7rem !important;
    }
    .session-metrics [data-testid="stMetricLabel"] {
        font-size: 0.6rem !important;
    }

    /* ---------- SECTION ACTIVE TRADE (encore plus petite) ---------- */
    .active-trade-metrics [data-testid="stMetricValue"] {
        font-size: 0.55rem !important;
    }
    .active-trade-metrics [data-testid="stMetricLabel"] {
        font-size: 0.35rem !important;
    }

    /* Réduction de l'espacement global */
    .stMetric {
        margin-bottom: 0.2rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Authentification ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; color: #00C853;'>🔐 MyForexBotNY</h1>",
                unsafe_allow_html=True)
    pwd = st.text_input("Password", type="password")
    if st.button("Sign in"):
        if pwd == st.secrets["DASHBOARD_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

# ---------- Après authentification ----------
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

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

# Titre centré en haut
st.markdown("<h2 style='text-align: center; color: #00C853; margin-top: 0;'>🖥️ MyForexBotNY Cockpit</h2>",
            unsafe_allow_html=True)

# Bouton Sign out en haut à droite
col_empty, col_signout = st.columns([6, 1])
with col_signout:
    if st.button("Sign out"):
        st.session_state.authenticated = False
        st.rerun()

placeholder = st.empty()

while True:
    data = fetch_status()
    if not data:
        with placeholder.container():
            st.error("Status unavailable – retrying in 30s")
        time.sleep(30)
        continue

    with placeholder.container():
        # ================= Session (classe session-metrics) =================
        st.markdown('<div class="session-metrics">', unsafe_allow_html=True)
        sess = data.get("session", {})
        col1, col2, col3 = st.columns(3)
        trades = sess.get('trades_today', 0)
        max_tr = sess.get('max_trades', 2)
        col1.metric("Trades", f"{trades}/{max_tr}")
        col2.metric("Session", f"{sess.get('start','08')}–{sess.get('end','12')}")
        running = data.get("bot_status") == "running"
        col3.metric("Status", "🟢" if running else "🔴")
        st.markdown('</div>', unsafe_allow_html=True)

        st.caption(f"Updated: {data.get('time', '-')}")

        # News
        news = data.get("next_news_event")
        if news:
            st.markdown(
                f"⏰ **{news['title']}** at {news['time']} – :orange[{news.get('impact','')}]"
            )

        # ================= Paires =================
        st.markdown("---")
        cols = st.columns(2)
        for i, pair in enumerate(["EUR_USD", "GBP_USD"]):
            with cols[i]:
                p = data.get("pairs", {}).get(pair, {})
                ema = p.get('ema_orientation','')
                macd = p.get('macd_signal','')
                st.markdown(f"**{pair}** <span class='green'>{ema}</span> / <span class='orange'>{macd}</span>",
                            unsafe_allow_html=True)
                price = p.get('price')
                st.metric("Price", f"{price:.5f}" if price is not None else "--")
                spread = p.get('spread', '--')
                spread_str = f"{safe_float(spread):.5f}" if spread != '--' else '--'
                st.caption(f"Spread: {spread_str} | ADX: {p.get('adx','--')}  "
                           f"+DI: {p.get('plus_di','--')} / -DI: {p.get('minus_di','--')}")
                sig = p.get('last_signal')
                if sig:
                    st.markdown(f"Signal: <span class='green'>{sig.upper()}</span>", unsafe_allow_html=True)

        # ================= Active Trade (classe active-trade-metrics) =================
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

        # ================= Historique & Rejets =================
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

    time.sleep(30)
