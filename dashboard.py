import streamlit as st
import requests
import time
import os

st.set_page_config(page_title="MyForexBotNY Cockpit", layout="wide")

# ---------- Authentification ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown(
        "<h1 style='text-align: center; color: #00C853;'>🔐 MyForexBotNY</h1>",
        unsafe_allow_html=True,
    )
    pwd = st.text_input("Password", type="password")
    if st.button("Sign in"):
        if pwd == os.getenv("DASHBOARD_PASSWORD", "forex2026"):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

# ---------- Fonctions utilitaires ----------
@st.cache_data(ttl=30)
def fetch_status():
    url = "https://raw.githubusercontent.com/{}/{}/main/status.json".format(
        os.getenv("GITHUB_REPOSITORY", "votre-utilisateur/forexbotny")
    )
    headers = {}
    token = os.getenv("GH_PAT")
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

# ---------- Interface ----------
st.markdown(
    """
    <style>
    body { background-color: #0D0D0D; color: #EAEAEA; }
    .card { background: #1A1A1A; border: 1px solid #333; border-radius: 10px; padding: 20px; margin: 10px; }
    .green { color: #00C853; }
    .red { color: #FF1744; }
    .orange { color: #FF9100; }
    .white { color: #EAEAEA; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    "<h1 style='text-align: center; color: #00C853;'>🖥️ MyForexBotNY Cockpit</h1>",
    unsafe_allow_html=True,
)

# Barre de statut et logout
col1, col2 = st.columns([4, 1])
with col1:
    st.write("🟢 Bot running" if True else "🔴 Stopped")  # sera dynamique
with col2:
    if st.button("Sign out"):
        st.session_state.authenticated = False
        st.rerun()

placeholder = st.empty()

while True:
    data = fetch_status()
    if not data:
        placeholder.error("Status unavailable – retrying in 30s")
        time.sleep(30)
        continue

    with placeholder.container():
        # Résumé de la séance
        st.markdown("### 📊 Session")
        sess = data["session"]
        col1, col2, col3 = st.columns(3)
        col1.metric("Trades today", f"{sess['trades_today']}/{sess['max_trades']}")
        col2.metric("Session", f"{sess['start']} – {sess['end']} (NY)")
        col3.metric("Status", "🟢 Running" if data["bot_status"] == "running" else "🔴 Stopped")

        # Prochaine news
        news = data.get("next_news_event")
        if news:
            st.markdown(f"⏰ Next high‑impact event : **{news['title']}** at {news['time']} (NY) – :orange[{news['impact']}]")

        # Paires
        st.markdown("### 💱 Pairs")
        cols = st.columns(2)
        pairs_data = data.get("pairs", {})
        for i, pair in enumerate(["EUR_USD", "GBP_USD"]):
            with cols[i]:
                p = pairs_data.get(pair, {})
                st.markdown(f"**{pair}**  "
                            f"<span class='green'>{p.get('ema_orientation','')}</span> / "
                            f"<span class='orange'>{p.get('macd_signal','')}</span>",
                            unsafe_allow_html=True)
                st.metric("Price", f"{p.get('price','--'):.5f}")
                st.caption(f"Spread: {p.get('spread','--'):.5f} | ADX: {p.get('adx','--')}  "
                           f"+DI: {p.get('plus_di','--')} / -DI: {p.get('minus_di','--')}")
                last_sig = p.get("last_signal")
                if last_sig:
                    st.markdown(f"Last signal: <span class='green'>{last_sig.upper()}</span>", unsafe_allow_html=True)

        # Trade actif
        active = data.get("active_trade")
        if active:
            st.markdown("### 🔥 Active Trade")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Pair", active["pair"])
            col2.metric("Type", active["type"], delta_color="off")
            col3.metric("Entry", f"{active['entry']:.5f}")
            col4.metric("Current", f"{active['current_price']:.5f}")
            col1.metric("Unrealized P&L", f"{active['unrealized_pnl']:.2f} USD",
                        delta_color="normal" if active["unrealized_pnl"] >= 0 else "inverse")
            col2.metric("SL", f"{active['sl']:.5f} ({active['distance_to_sl_pips']} pips)")
            col3.metric("TP", f"{active['tp']:.5f} ({active['distance_to_tp_pips']} pips)")
            col4.metric("Trailing Stop", f"{active['trailing_stop']} pips")

        # Historique + Rejets
        tab1, tab2 = st.tabs(["📜 Closed Trades", "🚫 Rejected Setups"])
        with tab1:
            closed = data.get("closed_trades_today", [])
            if closed:
                for t in closed[::-1]:
                    color = "green" if t["pnl"] >= 0 else "red"
                    st.markdown(
                        f"<span class='{color}'>{t['pair']} {t['type']} – {t['pnl']:.2f} USD at {t['time']}</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.write("No closed trades yet.")
        with tab2:
            rejected = data.get("rejected_signals", [])
            if rejected:
                for r in rejected[::-1]:
                    st.markdown(f"<span class='orange'>{r['time']} {r['pair']} – {r['reason']}</span>",
                                unsafe_allow_html=True)
                    if "indicators" in r:
                        with st.expander("Details"):
                            st.json(r["indicators"])
            else:
                st.write("No rejected setups.")

    time.sleep(30)
