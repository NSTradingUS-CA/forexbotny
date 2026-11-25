import streamlit as st
import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

st.set_page_config(
    page_title="Forex Sniper 7-12",
    layout="wide"
)

# ---------- CSS global ----------
st.markdown(
    """
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
    .half-size-banner {
        background-color: #6f42c1;
        color: white;
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
    .ct-diagnostic {
        color: #17a2b8;
        font-size: 0.9rem;
        font-style: italic;
    }
    .stale-banner {
        color: #AAAAAA;
        font-size: 0.85rem;
        font-style: italic;
        text-align: center;
        margin-top: -0.5rem;
        margin-bottom: 0.5rem;
    }
    .perf-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }
    .perf-table th, .perf-table td {
        padding: 0.4rem 0.6rem;
        border-bottom: 1px solid #333;
        text-align: left;
    }
    .perf-table th {
        color: #1E90FF;
        font-weight: bold;
    }
    .perf-table tr:hover {
        background-color: #1a1a1a;
    }
</style>
""",
    unsafe_allow_html=True
)

# ---------- Authentification ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown(
        "<h1 style='text-align: center; color: #00C853;'>\u0001F510 Forex Sniper 7-12 \u2022 Cockpit Access</h1>",
        unsafe_allow_html=True
    )
    pwd = st.text_input(
        "Password",
        type="password"
    )
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
        resp = requests.get(
            url,
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_status():
    data = fetch_json("status.json")
    if not data:
        return None
    time_str = data.get("time", "")
    try:
        status_date = datetime.strptime(
            time_str,
            "%Y-%m-%d %H:%M:%S"
        ).date()
        today = datetime.now(MONTREAL_TZ).date()
        if status_date != today:
            data["_stale"] = True
            data["_stale_date"] = status_date.strftime("%a %d %b")
            if "session" in data:
                data["session"]["trades_today"] = 0
            data["active_trade"] = None
            data["blocked_pairs"] = []
            data["active_pairs"] = ["EUR_USD", "GBP_USD"]
            data["next_news_event"] = None
            data["bot_status"] = "stopped"
    except (ValueError, TypeError):
        pass
    return data


def fetch_pair_indicators():
    data = fetch_json("pair_indicators.json")
    if data:
        return data
    return {}


def fetch_closed_trades():
    data = fetch_json("closed_trades.json")
    if data:
        today_str = datetime.now(MONTREAL_TZ).strftime("%Y-%m-%d")
        if data.get("last_cleanup") == today_str:
            return data.get("trades", [])
        if data.get("last_cleanup") is None:
            return data.get("trades", [])
    return []


def fetch_rejected_signals():
    data = fetch_json("rejected_signals.json")
    if data:
        today_str = datetime.now(MONTREAL_TZ).strftime("%Y-%m-%d")
        if data.get("last_cleanup") == today_str:
            return data.get("signals", [])
        if data.get("last_cleanup") is None:
            return data.get("signals", [])
    return []


def fetch_pause_state():
    data = fetch_json("pause_state.json")
    if data:
        return data.get("pause_until", 0)
    return 0


def check_bot_running():
    token = st.secrets.get("GH_PAT")
    repo = st.secrets["GITHUB_REPOSITORY"]
    headers = {}
    headers["Accept"] = "application/vnd.github.v3+json"
    if token:
        headers["Authorization"] = f"token {token}"
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    for status in ("in_progress", "queued"):
        params = {}
        params["status"] = status
        try:
            resp = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=10
            )
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
    if value is None:
        return "--"
    if value == "":
        return "--"
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except (ValueError, TypeError):
        return str(value)


def display_setup(item):
    setup = item.get("setup", item.get("setup_type", "--"))
    return str(setup).upper()


def display_score(item):
    score = item.get("score", item.get("setup_score"))
    if score is not None:
        return fmt_optional(score, 1)
    return "--"


def display_r(item):
    r_value = item.get("r_multiple")
    if r_value is None:
        r_value = item.get("r")
    if r_value is None:
        r_value = item.get("realized_r")
    if r_value is None:
        r_value = item.get("current_r")
    if r_value is None:
        return "--"
    if r_value == "":
        return "--"
    try:
        return f"{float(r_value):+.2f}R"
    except (ValueError, TypeError):
        return str(r_value)


def display_risk(item):
    risk = item.get("risk_pct")
    if risk is None:
        risk = item.get("risk_percent")
    if risk is None:
        risk = item.get("risk")
    if risk is None:
        return "--"
    if risk == "":
        return "--"
    try:
        value = float(risk)
        return f"{value:.2f}%"
    except (ValueError, TypeError):
        return str(risk)


def display_trade_status(item):
    status = item.get("trade_status")
    if status is None:
        status = item.get("status")
    if status is None:
        status = item.get("management_status")
    if status is None:
        return "--"
    if status == "":
        return "--"
    return str(status).upper()


def tp1_display(active):
    tp1_hit = bool(active.get("tp1_hit", False))
    news_partial_close = bool(active.get("news_partial_close", False))
    news_partial_done = bool(active.get("news_partial_done", False))
    news_partial = False
    if news_partial_close:
        news_partial = True
    if news_partial_done:
        if not tp1_hit:
            news_partial = True
    if tp1_hit:
        return "\u2705"
    if news_partial:
        return "\U0001F4F0 News partial (NOT TP1)"
    return "\u274C"


def status_badge(condition, true_text="\u2705", false_text="\u274C"):
    if condition:
        return true_text
    return false_text

# ---------- Logo + nom du bot ----------
LOGO_URL = "https://raw.githubusercontent.com/NSTradingUS-CA/forexbotny/main/assets/logo.png"
st.markdown(
    f"""
<div style="display: flex; align-items: center; justify-content: center;">
    <img src="{LOGO_URL}" class="logo-rounded" style="width: 80px; height: auto; margin-right: 20px;">
    <h2 style="color: #FF9100; margin: 0;">Forex Sniper 7-12</h2>
</div>
<p style="text-align: center; color: #AAAAAA; font-size: 1.1rem; font-style: italic; margin-top: 10px; margin-bottom: 10px;">
    A fully autonomous trading bot that analyzes EURUSD and GBPUSD across London & New York sessions using a multi-criteria scoring engine. It takes up to 3 high-conviction trades per day.
    Comes with built-in risk management, crash-resilient performance, real-time dashboard, and instant Telegram alerts.
</p>
""",
    unsafe_allow_html=True
)

# ---------- Bouton Sign out ----------
col_empty = None
col_signout = None
cols_signout = st.columns([8, 1])
col_empty = cols_signout[0]
col_signout = cols_signout[1]
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
        st.error("Status unavailable - retrying in 10s")
        return
    if data.get("_stale"):
        stale_date = data.get("_stale_date", "?")
        stale_html = f'<div class="stale-banner">\u26a0 Last bot activity: {stale_date} - no session today, counters reset to zero.</div>'
        st.markdown(
            stale_html,
            unsafe_allow_html=True
        )
    bot_status = data.get("bot_status")
    if bot_status == "stopped":
        bot_is_running = False
    else:
        bot_is_running = check_bot_running()
    if data.get("news_day_half_size"):
        half_info = data.get("news_day_half_size_info", "news detected 07:00-16:55")
        half_html = f'<div class="half-size-banner">\U0001F4C9 HALF-SIZE DAY (50%) - {half_info} - all trades today at 50% size</div>'
        st.markdown(
            half_html,
            unsafe_allow_html=True
        )
    if pause_until > now_mtl.timestamp():
        resume_time = datetime.fromtimestamp(
            pause_until,
            MONTREAL_TZ
        ).strftime('%H:%M')
        news_event = data.get("next_news_event", {})
        event_title = news_event.get("title", "")
        event_time = news_event.get("time", "")
        blocked_pairs = data.get("blocked_pairs", [])
        active_pairs = data.get("active_pairs", [])
        if blocked_pairs:
            if active_pairs:
                blocked_str = ", ".join(blocked_pairs)
                active_str = ", ".join(active_pairs)
                banner_text = f"\U0001F4C5 {event_title} at {event_time} - Trading paused on {blocked_str} until {resume_time} (Active pairs: {active_str})"
            else:
                blocked_str = ", ".join(blocked_pairs)
                banner_text = f"\U0001F4C5 {event_title} at {event_time} - Trading paused on {blocked_str} until {resume_time}"
        else:
            banner_text = f"\U0001F4C5 High-impact news detected - Trading paused until {resume_time}"
        banner_html = f'<div class="news-pause-banner">{banner_text}</div>'
        st.markdown(
            banner_html,
            unsafe_allow_html=True
        )
    st.markdown(
        '<div class="session-metrics">',
        unsafe_allow_html=True
    )
    sess = data.get("session", {})
    cols_session = st.columns([1, 1, 1, 1])
    col1 = cols_session[0]
    col2 = cols_session[1]
    col3 = cols_session[2]
    col4 = cols_session[3]
    trades = sess.get('trades_today', 0)
    max_tr = sess.get('max_trades', 3)
    col1.markdown("#### Trades")
    col1.metric(
        "Trades",
        f"{trades}/{max_tr}",
        label_visibility="collapsed"
    )
    col2.markdown("#### Session")
    col2.metric(
        "Session",
        "07:00-12:00",
        label_visibility="collapsed"
    )
    col3.markdown("#### Status")
    if bot_is_running:
        status_icon = "\U0001F7E2"
    else:
        status_icon = "\U0001F534"
    col3.metric(
        "Status",
        status_icon,
        label_visibility="collapsed"
    )
    col4.markdown("#### Time")
    col4.metric(
        "Time",
        now_str,
        label_visibility="collapsed"
    )
    st.markdown(
        '</div>',
        unsafe_allow_html=True
    )
    st.markdown("---")
    cols = st.columns(2)
    for i, pair in enumerate(["EUR_USD", "GBP_USD"]):
        with cols[i]:
            pp = pair_data.get(pair, {})
            st.markdown(f"**{pair}**")
            price = pp.get('price')
            if price is not None:
                price_str = f"{price:.5f}"
            else:
                price_str = "--"
            st.metric(
                "Price",
                price_str
            )
            spread_val = pp.get('spread', '--')
            if spread_val != '--':
                spread_str = f"{safe_float(spread_val):.5f}"
            else:
                spread_str = '--'
            adx_str = fmt_num(pp.get('adx'))
            plus_di_str = fmt_num(pp.get('plus_di'))
            minus_di_str = fmt_num(pp.get('minus_di'))
            ema50 = pp.get('ema50')
            ema200 = pp.get('ema200')
            rsi_val = pp.get('rsi')
            atr_val = pp.get('atr')
            if ema50 is not None:
                ema50_str = f"{ema50:.5f}"
            else:
                ema50_str = "--"
            if ema200 is not None:
                ema200_str = f"{ema200:.5f}"
            else:
                ema200_str = "--"
            if rsi_val is not None:
                rsi_str = f"{rsi_val:.1f}"
            else:
                rsi_str = "--"
            if atr_val is not None:
                atr_str = f"{atr_val:.5f}"
            else:
                atr_str = "--"
            line1 = f"<span class='orange-label'>Spread:</span> {spread_str} | "
            line1 = line1 + f"<span class='orange-label'>ADX:</span> {adx_str} | "
            line1 = line1 + f"<span class='orange-label'>+DI:</span> {plus_di_str} | "
            line1 = line1 + f"<span class='orange-label'>-DI:</span> {minus_di_str}"
            line2 = f"<span class='orange-label'>EMA50:</span> {ema50_str} | "
            line2 = line2 + f"<span class='orange-label'>EMA200:</span> {ema200_str} | "
            line2 = line2 + f"<span class='orange-label'>RSI:</span> {rsi_str} | "
            line2 = line2 + f"<span class='orange-label'>ATR:</span> {atr_str}"
            st.markdown(
                f"<div class='indicators-line'>{line1}</div>",
                unsafe_allow_html=True
            )
            st.markdown(
                f"<div class='indicators-line'>{line2}</div>",
                unsafe_allow_html=True
            )
            sig = pp.get('last_signal')
            if sig:
                sig_upper = sig.upper()
                st.markdown(
                    f"Signal: <span class='green'>{sig_upper}</span>",
                    unsafe_allow_html=True
                )

    # ---------- Active Trade ----------
    active = data.get("active_trade")
    if active:
        st.markdown("---")
        st.markdown("#### \U0001F525 Active Trade")
        st.markdown(
            '<div class="active-trade-metrics">',
            unsafe_allow_html=True
        )
        cols_active = st.columns(4)
        c1 = cols_active[0]
        c2 = cols_active[1]
        c3 = cols_active[2]
        c4 = cols_active[3]
        c1.metric(
            "Pair",
            active.get("pair", "")
        )
        c2.metric(
            "Type",
            active.get("type", "")
        )
        entry_val = active.get('entry', 0)
        c3.metric(
            "Entry",
            f"{entry_val:.5f}"
        )
        current_val = active.get('current_price', 0)
        c4.metric(
            "Current",
            f"{current_val:.5f}"
        )
        pnl_cad = active.get('unrealized_pnl_cad')
        if pnl_cad is not None:
            pnl = pnl_cad
            currency = "CAD"
        else:
            pnl = active.get('unrealized_pnl', 0)
            currency = "USD"
        if pnl >= 0:
            delta_color = "normal"
        else:
            delta_color = "inverse"
        c1.metric(
            "P&L",
            f"{pnl:.2f} {currency}",
            delta_color=delta_color
        )
        tp1_val = active.get('tp1')
        tp2_val = active.get('tp2')
        if tp1_val is not None:
            c2.metric(
                "TP1 (partial)",
                f"{tp1_val:.5f}"
            )
        if tp2_val is not None:
            c3.metric(
                "TP2 (final)",
                f"{tp2_val:.5f}"
            )
        sl_val = active.get('sl', 0)
        dist_sl = active.get('distance_to_sl_pips', 0)
        c4.metric(
            "SL",
            f"{sl_val:.5f} ({dist_sl} pips)"
        )
        trail_info = active.get('trailing_stop', '')
        atr_active = active.get('atr', None)
        if atr_active is not None:
            trail_info = f"{trail_info} (ATR: {atr_active:.5f})"
        if trail_info:
            st.caption(f"Trailing Stop: {trail_info}")
        units_val = active.get('units', 0)
        st.caption(f"Volume: {abs(units_val)} units")
        if active.get('half_size'):
            st.caption("\U0001F4C9 Half-size trade (50%) - news day 07:00-16:55")
        if active.get('news_partial_close'):
            st.caption("\U0001F4F0 News partial close already taken on this trade - TP1 NOT hit by that partial")
        setup = display_setup(active)
        score = display_score(active)
        risk = display_risk(active)
        current_r = display_r(active)
        management = display_trade_status(active)
        be_triggered = active.get('be_triggered', False)
        tp1_str = tp1_display(active)
        if be_triggered:
            be_str = "\u2705"
        else:
            be_str = "\u274C"
        info_line = f"<div class='indicators-line'>"
        info_line = info_line + f"<span class='orange-label'>Setup:</span> {setup} | "
        info_line = info_line + f"<span class='orange-label'>Score:</span> {score} | "
        info_line = info_line + f"<span class='orange-label'>Risk:</span> {risk} | "
        info_line = info_line + f"<span class='orange-label'>R:</span> {current_r} | "
        info_line = info_line + f"<span class='orange-label'>Status:</span> {management} | "
        info_line = info_line + f"<span class='orange-label'>BE:</span> {be_str} | "
        info_line = info_line + f"<span class='orange-label'>TP1:</span> {tp1_str}"
        info_line = info_line + f"</div>"
        st.markdown(
            info_line,
            unsafe_allow_html=True
        )
        st.markdown(
            '</div>',
            unsafe_allow_html=True
        )
    # ---------- Historique + Rejets + Performance ----------
    st.markdown("---")
    tabs = st.tabs(
        [
            "\U0001F4DC Closed",
            "\U0001F6AB Rejected",
            "\U0001F4CA Setups Performance"
        ]
    )
    tab1 = tabs[0]
    tab2 = tabs[1]
    tab3 = tabs[2]
    # === ONGLET CLOSED ===
    with tab1:
        if closed_trades:
            for t in closed_trades[::-1]:
                pnl = t.get('pnl', 0)
                if pnl >= 0:
                    color = "green"
                else:
                    color = "red"
                pair_t = t.get('pair', '')
                type_t = t.get('type', '')
                setup_t = display_setup(t)
                r_t = display_r(t)
                score_t = display_score(t)
                units_t = abs(t.get('units', 0))
                time_t = t.get('time', '')
                news_tag = ""
                if t.get('news_partial_close'):
                    news_tag = " | \U0001F4F0 News partial"
                closed_line = f"<span class='{color}'>{pair_t} - Dir: {type_t} | Type: {setup_t} | R: {r_t} | Score: {score_t} | Vol: {units_t} units | PnL: {pnl:.2f} CAD ({time_t}){news_tag}</span>"
                st.markdown(
                    closed_line,
                    unsafe_allow_html=True
                )
        else:
            st.write("No closed trades.")
    # === ONGLET REJECTED ===
    with tab2:
        if rejected:
            for r in rejected[::-1]:
                time_pair = f"{r.get('time','')} {r.get('pair','')}"
                buy_reason = r.get('buy_reason', '')
                sell_reason = r.get('sell_reason', '')
                ct_diag = r.get('ct_diagnostic', '')
                rejected_line = f"**{time_pair}** - \U0001F535 **BUY:** {buy_reason}    |    \U0001F534 **SELL:** {sell_reason}"
                st.markdown(
                    rejected_line,
                    unsafe_allow_html=True
                )
                if ct_diag:
                    ct_html = f"<div class='ct-diagnostic'>\U0001F504 CT scan: {ct_diag}</div>"
                    st.markdown(
                        ct_html,
                        unsafe_allow_html=True
                    )
                st.markdown("---")
        else:
            st.write("No rejected setups.")
    # === ONGLET SETUPS PERFORMANCE ===
    with tab3:
        if not closed_trades:
            st.write("No setups performance stats available yet.")
        else:
            df_trades = pd.DataFrame(closed_trades)
            df_trades['setup'] = df_trades['setup'].str.upper()
            df_trades['r_multiple'] = pd.to_numeric(
                df_trades['r_multiple'],
                errors='coerce'
            )
            if 'score' in df_trades.columns:
                df_trades['score'] = pd.to_numeric(
                    df_trades['score'],
                    errors='coerce'
                )
            else:
                df_trades['score'] = pd.NA
            df_trades['pnl'] = pd.to_numeric(
                df_trades['pnl'],
                errors='coerce'
            )
            all_setups = df_trades['setup'].unique()
            setup_groups = list(all_setups)
            setup_groups.append("Global")

            def compute_metrics(df):
                if df.empty:
                    result = {}
                    result['count'] = 0
                    result['win_rate'] = 0.0
                    result['avg_r'] = 0.0
                    result['expectancy'] = 0.0
                    result['profit_factor'] = 0.0
                    result['max_drawdown'] = 0.0
                    result['avg_gain'] = 0.0
                    result['avg_loss'] = 0.0
                    return result
                count = len(df)
                wins = df[df['pnl'] > 0]
                losses = df[df['pnl'] <= 0]
                if count > 0:
                    win_rate = len(wins) / count * 100
                else:
                    win_rate = 0.0
                if not df['r_multiple'].isna().all():
                    avg_r = df['r_multiple'].mean()
                else:
                    avg_r = 0.0
                if not wins.empty:
                    if not wins['r_multiple'].isna().all():
                        avg_win_r = wins['r_multiple'].mean()
                    else:
                        avg_win_r = 0.0
                else:
                    avg_win_r = 0.0
                if not losses.empty:
                    if not losses['r_multiple'].isna().all():
                        avg_loss_r = losses['r_multiple'].abs().mean()
                    else:
                        avg_loss_r = 0.0
                else:
                    avg_loss_r = 0.0
                if count > 0:
                    expectancy = (win_rate / 100 * avg_win_r) - ((100 - win_rate) / 100 * avg_loss_r)
                else:
                    expectancy = 0.0
                if not wins.empty:
                    sum_gain_r = wins['r_multiple'].sum()
                else:
                    sum_gain_r = 0.0
                if not losses.empty:
                    sum_loss_r = losses['r_multiple'].abs().sum()
                else:
                    sum_loss_r = 0.0
                if sum_loss_r != 0:
                    profit_factor = sum_gain_r / sum_loss_r
                else:
                    profit_factor = 0.0
                cum_r = df['r_multiple'].cumsum()
                peak = cum_r.expanding().max()
                drawdown = peak - cum_r
                if not drawdown.empty:
                    max_drawdown = drawdown.max()
                else:
                    max_drawdown = 0.0
                if not wins.empty:
                    avg_gain = wins['pnl'].mean()
                else:
                    avg_gain = 0.0
                if not losses.empty:
                    avg_loss = losses['pnl'].abs().mean()
                else:
                    avg_loss = 0.0
                result = {}
                result['count'] = count
                result['win_rate'] = win_rate
                result['avg_r'] = avg_r
                result['expectancy'] = expectancy
                result['profit_factor'] = profit_factor
                result['max_drawdown'] = max_drawdown
                result['avg_gain'] = avg_gain
                result['avg_loss'] = avg_loss
                return result

            metrics_data = {}
            metrics_data['Métrique'] = []
            metrics_data['Métrique'].append('Nombre de trades')
            metrics_data['Métrique'].append('Win rate')
            metrics_data['Métrique'].append('Avg R')
            metrics_data['Métrique'].append('Expectancy')
            metrics_data['Métrique'].append('Profit factor')
            metrics_data['Métrique'].append('Max drawdown (R)')
            metrics_data['Métrique'].append('Gain moyen (CAD)')
            metrics_data['Métrique'].append('Perte moyenne (CAD)')
            for setup_name in setup_groups:
                if setup_name == "Global":
                    df_filtered = df_trades
                else:
                    df_filtered = df_trades[df_trades['setup'] == setup_name]
                metrics = compute_metrics(df_filtered)
                column = []
                column.append(f"{metrics['count']}")
                column.append(f"{metrics['win_rate']:.1f}%")
                column.append(f"{metrics['avg_r']:.2f}R")
                column.append(f"{metrics['expectancy']:.2f}R")
                column.append(f"{metrics['profit_factor']:.2f}")
                column.append(f"-{metrics['max_drawdown']:.2f}R")
                column.append(f"{metrics['avg_gain']:.2f} CAD")
                column.append(f"{metrics['avg_loss']:.2f} CAD")
                metrics_data[setup_name] = column
            df_table = pd.DataFrame(metrics_data)
            html_table = df_table.to_html(
                index=False,
                escape=False,
                classes="perf-table",
                border=0
            )
            st.markdown(
                html_table,
                unsafe_allow_html=True
            )

render_dashboard()

# ---------- Footer ----------
st.markdown(
    '<div class="footer">NorthSentinel Trading \u2022 Forex Sniper 7-12 \u2022 August, 2026 \u00a9</div>',
    unsafe_allow_html=True
)
