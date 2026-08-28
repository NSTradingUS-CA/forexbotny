import streamlit as st
import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

st.set_page_config(page_title="Forex Sniper 7-12", layout="wide")

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
    .logo-rounded {
        border-radius: 20px;
    }
    .news-pause-banner {
        background-color: #FF9100;
        color: #0D0D0D;
        text-align: center;
        font-weight: bold;
        font-size: 1rem;
        padding: 0.6rem;
        margin: 0.5rem 0;
        border-radius: 5px;
    }
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        box-sizing: border-box;
        text-align: center;
        color: #666;
        font-size: 0.8rem;
        padding: 0.75rem 0;
        margin-top: 0;
        background-color: #0D0D0D;
        z-index: 9999;
    }
    .status-badge {
        display: inline-block;
        padding: 0.1rem 0.5rem;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.9rem;
    }
    .badge-green {
        background-color: #28a745;
        color: white;
    }
    .badge-red {
        background-color: #dc3545;
        color: white;
    }
    .badge-gray {
        background-color: #6c757d;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Authentification ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; color: #00C853;'>🔐 Forex Sniper 7‑12 • Cockpit Access</h1>",
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

@st.cache_data(ttl=5)
def fetch_json(filename):
    repo = st.secrets["GITHUB_REPOSITORY"]
    cache_buster = int(time.time())
    url = f"https://raw.githubusercontent.com/{repo}/main/{filename}?t={cache_buster}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def fetch_status():
    return fetch_json("status.json")

def fetch_pair_indicators():
    data = fetch_json("pair_indicators.json")
    if data:
        return data
    return {}

def fetch_closed_trades():
    data = fetch_json("closed_trades.json")
    if data:
        today_str = datetime.now(MONTREAL_TZ).strftime("%Y-%m-%d")
        if data.get("last_cleanup") == today_str or data.get("last_cleanup") is None:
            return data.get("trades", [])
    return []

def fetch_rejected_signals():
    data = fetch_json("rejected_signals.json")
    if data:
        today_str = datetime.now(MONTREAL_TZ).strftime("%Y-%m-%d")
        if data.get("last_cleanup") == today_str or data.get("last_cleanup") is None:
            return data.get("signals", [])
    return []

def fetch_pause_state():
    data = fetch_json("pause_state.json")
    if data:
        return data.get("pause_until", 0)
    return 0

def check_bot_running():
    """Fallback : vérifie via l'API GitHub si un workflow est en cours."""
    token = st.secrets.get("GH_PAT")
    repo = st.secrets["GITHUB_REPOSITORY"]
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    for status in ("in_progress", "queued"):
        params = {"status": status}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                runs = resp.json()
                if runs.get("workflow_runs"):
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

def fmt_optional(value, decimals=2, suffix=""):
    if value is None or value == "":
        return "--"
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except (ValueError, TypeError):
        return str(value)

def display_setup(item):
    return str(item.get("setup", item.get("setup_type", "--"))).upper()

def display_score(item):
    score = item.get("score", item.get("setup_score"))
    return fmt_optional(score, 1) if score is not None else "--"

def display_r(item):
    r_value = item.get("r_multiple", item.get("r", item.get("realized_r", item.get("current_r"))))
    if r_value is None or r_value == "":
        return "--"
    try:
        return f"{float(r_value):+.2f}R"
    except (ValueError, TypeError):
        return str(r_value)

def display_risk(item):
    risk = item.get("risk_pct", item.get("risk_percent", item.get("risk")))
    if risk is None or risk == "":
        return "--"
    try:
        value = float(risk)
        return f"{value:.2f}%"
    except (ValueError, TypeError):
        return str(risk)

def display_trade_status(item):
    status = item.get("trade_status", item.get("status", item.get("management_status")))
    return str(status).upper() if status not in (None, "") else "--"

def status_badge(condition, true_text="✅", false_text="❌"):
    return true_text if condition else false_text

# ---------- Logo + nom du bot ----------
LOGO_URL = "https://raw.githubusercontent.com/NSTradingUS-CA/forexbotny/main/assets/logo.png"
st.markdown(f"""
<div style="display: flex; align-items: center; justify-content: center;">
    <img src="{LOGO_URL}" class="logo-rounded" style="width: 80px; height: auto; margin-right: 20px;">
    <h2 style="color: #FF9100; margin: 0;">Forex Sniper 7‑12</h2>
</div>
<p style="text-align: center; color: #AAAAAA; font-size: 1.1rem; font-style: italic; margin-top: 10px; margin-bottom: 10px;">
    A fully autonomous trading bot that analyzes EURUSD and GBPUSD across London & New York sessions using a multi-criteria scoring engine. It takes up to 3 high-conviction trades per day.  
    Comes with built-in risk management, crash-resilient performance, real-time dashboard, and instant Telegram alerts.
</p>
""", unsafe_allow_html=True)

# ---------- Bouton Sign out ----------
col_empty, col_signout = st.columns([8, 1])
with col_signout:
    if st.button("Sign out"):
        st.session_state.authenticated = False
        st.rerun()

@st.fragment(run_every="10s")
def render_dashboard():
    data = fetch_status()
    pair_data = fetch_pair_indicators()
    closed_trades = fetch_closed_trades()
    rejected = fetch_rejected_signals()
    pause_until = fetch_pause_state()
    now_mtl = datetime.now(MONTREAL_TZ)
    now_str = now_mtl.strftime('%H:%M:%S')

    if not data:
        st.error("Status unavailable – retrying in 10s")
        return

    # ---------- Déterminer si le bot est en cours d'exécution ----------
    bot_status = data.get("bot_status")
    if bot_status == "stopped":
        bot_is_running = False
    else:
        bot_is_running = check_bot_running()

    # ---------- Bannière de pause news ----------
    if pause_until > now_mtl.timestamp():
        resume_time = datetime.fromtimestamp(pause_until, MONTREAL_TZ).strftime('%H:%M')
        news_event = data.get("next_news_event", {})
        event_title = news_event.get("title", "")
        event_time = news_event.get("time", "")
        blocked_pairs = data.get("blocked_pairs", [])
        active_pairs = data.get("active_pairs", [])
        
        if blocked_pairs and active_pairs:
            blocked_str = ", ".join(blocked_pairs)
            active_str = ", ".join(active_pairs)
            banner_text = (
                f"📅 {event_title} at {event_time} – "
                f"Trading paused on {blocked_str} until {resume_time} "
                f"(Active pairs: {active_str})"
            )
        elif blocked_pairs:
            blocked_str = ", ".join(blocked_pairs)
            banner_text = (
                f"📅 {event_title} at {event_time} – "
                f"Trading paused on {blocked_str} until {resume_time}"
            )
        else:
            banner_text = f"📅 High-impact news detected – Trading paused until {resume_time}"
        
        st.markdown(
            f'<div class="news-pause-banner">{banner_text}</div>',
            unsafe_allow_html=True
        )

    # ---------- Session ----------
    st.markdown('<div class="session-metrics">', unsafe_allow_html=True)
    sess = data.get("session", {})
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    trades = sess.get('trades_today', 0)
    max_tr = sess.get('max_trades', 3)

    col1.markdown("#### Trades")
    col1.metric("", f"{trades}/{max_tr}")

    col2.markdown("#### Session")
    col2.metric("", f"07:00–12:00")

    col3.markdown("#### Status")
    col3.metric("", "🟢" if bot_is_running else "🔴")

    col4.markdown("#### Time")
    col4.metric("", now_str)
    st.markdown('</div>', unsafe_allow_html=True)

    # ---------- Paires ----------
    st.markdown("---")
    cols = st.columns(2)
    for i, pair in enumerate(["EUR_USD", "GBP_USD"]):
        with cols[i]:
            p = pair_data.get(pair, {})
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
            atr_val = p.get('atr')

            ema50_str = f"{ema50:.5f}" if ema50 is not None else "--"
            ema200_str = f"{ema200:.5f}" if ema200 is not None else "--"
            rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "--"
            atr_str = f"{atr_val:.5f}" if atr_val is not None else "--"

            line1 = (
                f"<span class='orange-label'>Spread:</span> {spread_str} | "
                f"<span class='orange-label'>ADX:</span> {adx_str} | "
                f"<span class='orange-label'>+DI:</span> {plus_di_str} | "
                f"<span class='orange-label'>-DI:</span> {minus_di_str}"
            )
            line2 = (
                f"<span class='orange-label'>EMA50:</span> {ema50_str} | "
                f"<span class='orange-label'>EMA200:</span> {ema200_str} | "
                f"<span class='orange-label'>RSI:</span> {rsi_str} | "
                f"<span class='orange-label'>ATR:</span> {atr_str}"
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
        
        # Métriques principales
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pair", active.get("pair", ""))
        c2.metric("Type", active.get("type", ""))
        c3.metric("Entry", f"{active.get('entry',0):.5f}")
        c4.metric("Current", f"{active.get('current_price',0):.5f}")
        
        pnl = active.get('unrealized_pnl',0)
        c1.metric("P&L", f"{pnl:.2f} USD", delta_color="normal" if pnl>=0 else "inverse")
        
        tp1_val = active.get('tp1')
        tp2_val = active.get('tp2')
        if tp1_val is not None:
            c2.metric("TP1 (partial)", f"{tp1_val:.5f}")
        if tp2_val is not None:
            c3.metric("TP2 (final)", f"{tp2_val:.5f}")
        c4.metric("SL", f"{active.get('sl',0):.5f} ({active.get('distance_to_sl_pips',0)} pips)")
        
        # Informations de trailing
        trail_info = active.get('trailing_stop', '')
        atr_active = active.get('atr', None)
        if atr_active is not None:
            trail_info = f"{trail_info} (ATR: {atr_active:.5f})"
        if trail_info:
            st.caption(f"Trailing Stop: {trail_info}")

        st.caption(f"Volume: {abs(active.get('units', 0))} units")

        setup = display_setup(active)
        score = display_score(active)
        risk = display_risk(active)
        current_r = display_r(active)
        management = display_trade_status(active)
        
        be_triggered = active.get('be_triggered', False)
        tp1_hit = active.get('tp1_hit', False)
        be_str = "✅" if be_triggered else "❌"
        tp1_str = "✅" if tp1_hit else "❌"
        
        st.markdown(
            f"<div class='indicators-line'>"
            f"<span class='orange-label'>Setup:</span> {setup} | "
            f"<span class='orange-label'>Score:</span> {score} | "
            f"<span class='orange-label'>Risk:</span> {risk} | "
            f"<span class='orange-label'>R:</span> {current_r} | "
            f"<span class='orange-label'>Status:</span> {management} | "
            f"<span class='orange-label'>BE:</span> {be_str} | "
            f"<span class='orange-label'>TP1:</span> {tp1_str}"
            f"</div>",
            unsafe_allow_html=True
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # ---------- Historique + Rejets + Performance ----------
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📜 Closed", "🚫 Rejected", "📊 Setups Performance"])

    with tab1:
        if closed_trades:
            for t in closed_trades[::-1]:
                pnl = t.get('pnl',0)
                color = "green" if pnl >= 0 else "red"
                st.markdown(
                    f"<span class='{color}'>{t.get('pair','')} {t.get('type','')} – "
                    f"{display_setup(t)} | R: {display_r(t)} | Score: {display_score(t)} | "
                    f"Vol: {abs(t.get('units', 0))} units | "
                    f"{pnl:.2f} USD ({t.get('time','')})</span>",
                    unsafe_allow_html=True)
        else:
            st.write("No closed trades.")

    # *************** ONGLET REJECTED (MODIFIÉ) ***************
    with tab2:
        if rejected:
            for r in rejected[::-1]:   # tous les rejets, sans limite
                time_pair = f"{r.get('time','')} {r.get('pair','')}"
                buy_reason = r.get('buy_reason', '')
                sell_reason = r.get('sell_reason', '')
                st.markdown(
                    f"**{time_pair}** – 🔵 **BUY:** {buy_reason}    |    🔴 **SELL:** {sell_reason}",
                    unsafe_allow_html=True
                )
                st.markdown("---")
        else:
            st.write("No rejected setups.")

    # *************** ONGLET PERFORMANCE (GÉNÉRALISÉ) ***************
    with tab3:
        if not closed_trades:
            st.write("No setups performance stats available yet.")
        else:
            df_trades = pd.DataFrame(closed_trades)
            df_trades['setup'] = df_trades['setup'].str.upper()
            df_trades['r_multiple'] = pd.to_numeric(df_trades['r_multiple'], errors='coerce')
            df_trades['score'] = pd.to_numeric(df_trades['score'], errors='coerce')
            df_trades['pnl'] = pd.to_numeric(df_trades['pnl'], errors='coerce')

            all_setups = df_trades['setup'].unique()
            setup_groups = list(all_setups) + ["Global"]

            def compute_metrics(df):
                if df.empty:
                    return {
                        'count': 0,
                        'win_rate': 0.0,
                        'avg_r': 0.0,
                        'expectancy': 0.0,
                        'profit_factor': 0.0,
                        'max_drawdown': 0.0,
                        'avg_gain': 0.0,
                        'avg_loss': 0.0
                    }
                count = len(df)
                wins = df[df['pnl'] > 0]
                losses = df[df['pnl'] <= 0]
                win_rate = len(wins) / count * 100 if count > 0 else 0.0
                avg_r = df['r_multiple'].mean() if not df['r_multiple'].isna().all() else 0.0
                avg_win_r = wins['r_multiple'].mean() if not wins.empty and not wins['r_multiple'].isna().all() else 0.0
                avg_loss_r = losses['r_multiple'].abs().mean() if not losses.empty and not losses['r_multiple'].isna().all() else 0.0
                expectancy = (win_rate/100 * avg_win_r) - ((100-win_rate)/100 * avg_loss_r) if count > 0 else 0.0
                sum_gain_r = wins['r_multiple'].sum() if not wins.empty else 0.0
                sum_loss_r = losses['r_multiple'].abs().sum() if not losses.empty else 0.0
                profit_factor = sum_gain_r / sum_loss_r if sum_loss_r != 0 else 0.0
                cum_r = df['r_multiple'].cumsum()
                peak = cum_r.expanding().max()
                drawdown = peak - cum_r
                max_drawdown = drawdown.max() if not drawdown.empty else 0.0
                avg_gain = wins['pnl'].mean() if not wins.empty else 0.0
                avg_loss = losses['pnl'].abs().mean() if not losses.empty else 0.0
                return {
                    'count': count,
                    'win_rate': win_rate,
                    'avg_r': avg_r,
                    'expectancy': expectancy,
                    'profit_factor': profit_factor,
                    'max_drawdown': max_drawdown,
                    'avg_gain': avg_gain,
                    'avg_loss': avg_loss
                }

            metrics_data = {
                'Métrique': [
                    'Nombre de trades',
                    'Win rate',
                    'Avg R',
                    'Expectancy',
                    'Profit factor',
                    'Max drawdown (R)',
                    'Gain moyen (USD)',
                    'Perte moyenne (USD)'
                ]
            }

            for setup_name in setup_groups:
                if setup_name == "Global":
                    df_filtered = df_trades
                else:
                    df_filtered = df_trades[df_trades['setup'] == setup_name]
                metrics = compute_metrics(df_filtered)
                metrics_data[setup_name] = [
                    f"{metrics['count']}",
                    f"{metrics['win_rate']:.1f}%",
                    f"{metrics['avg_r']:.2f}R",
                    f"{metrics['expectancy']:.2f}R",
                    f"{metrics['profit_factor']:.2f}",
                    f"-{metrics['max_drawdown']:.2f}R",
                    f"{metrics['avg_gain']:.2f} USD",
                    f"{metrics['avg_loss']:.2f} USD"
                ]

            df_table = pd.DataFrame(metrics_data)
            st.table(df_table)

render_dashboard()

# ---------- Footer ----------
st.markdown(
    '<div class="footer">NorthSentinel Trading • Forex Sniper 7‑12 • August, 2026 ©</div>',
    unsafe_allow_html=True
)
