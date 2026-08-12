import streamlit as st
import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Forex Sniper 7‑12", layout="wide")

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
    .footer {
        width: 100%;
        box-sizing: border-box;
        text-align: center;
        color: #666;
        font-size: 0.8rem;
        padding: 0.75rem 0;
        margin-top: 1.5rem;
        background-color: #0D0D0D;
    }
    .setup-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-weight: bold;
        font-size: 0.85rem;
        margin-right: 6px;
    }
    .trade-detail-line {
        font-size: 0.95rem;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Authentification ----------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown(
        "<h1 style='text-align: center; color: #00C853;'>🔐 Forex Sniper 7‑12 • Cockpit Access</h1>",
        unsafe_allow_html=True
    )
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


def github_raw_url(filename):
    repo = st.secrets["GITHUB_REPOSITORY"]
    return f"https://raw.githubusercontent.com/{repo}/main/{filename}"


def fetch_json_file(filename):
    """Lit un JSON GitHub avec cache-buster pour éviter les données périmées."""
    url = github_raw_url(filename)
    try:
        resp = requests.get(url, params={"t": int(time.time())}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_status():
    return fetch_json_file("status.json")


def fetch_pair_indicators():
    data = fetch_json_file("pair_indicators.json")
    if data is None:
        return {}
    # Supporte à la fois un JSON direct {"EUR_USD": {...}}
    # et un JSON enveloppé {"pairs": {...}}.
    if isinstance(data, dict) and isinstance(data.get("pairs"), dict):
        return data["pairs"]
    return data if isinstance(data, dict) else {}


def fetch_closed_trades():
    data = fetch_json_file("closed_trades.json")
    if not data:
        return []
    if isinstance(data, dict):
        return data.get("trades", [])
    return data if isinstance(data, list) else []


def fetch_rejected_signals():
    data = fetch_json_file("rejected_signals.json")
    if not data:
        return []
    if isinstance(data, dict):
        return data.get("signals", [])
    return data if isinstance(data, list) else []


def check_bot_running():
    """Vérifie si un workflow GitHub Actions est en cours ou en attente."""
    token = st.secrets.get("GH_PAT")
    repo = st.secrets["GITHUB_REPOSITORY"]
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    url = f"https://api.github.com/repos/{repo}/actions/runs"

    for status in ("in_progress", "queued"):
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"status": status, "per_page": 10},
                timeout=10
            )
            if resp.status_code == 200 and resp.json().get("workflow_runs"):
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


def fmt_pips(value):
    try:
        return f"{float(value):.1f} pips"
    except (ValueError, TypeError):
        return "--"


def setup_name(item):
    return item.get("setup_type") or item.get("setup") or item.get("strategy") or "--"


def score_text(item):
    score = item.get("score")
    if score is None:
        return "--"
    return f"{score}/9"


def direction_text(item):
    direction = item.get("direction") or item.get("type") or ""
    direction = str(direction).upper()
    if direction in ("BUY", "SELL"):
        return direction
    return "--"


def current_r(active):
    """Calcule le R flottant si entry/sl/current sont disponibles."""
    explicit = active.get("current_r", active.get("r_multiple"))
    if explicit is not None:
        try:
            return float(explicit)
        except (ValueError, TypeError):
            pass

    entry = active.get("entry", active.get("entry_price"))
    sl = active.get("sl", active.get("stop_loss"))
    current = active.get("current_price", active.get("price"))
    direction = str(active.get("direction", active.get("type", ""))).lower()

    try:
        risk = abs(float(entry) - float(sl))
        if risk <= 0:
            return None
        move = float(current) - float(entry)
        if direction == "sell":
            move *= -1
        return move / risk
    except (ValueError, TypeError):
        return None


def trade_pnl(item):
    return safe_float(item.get("pnl", item.get("realized_pnl", 0)))


def trade_r(item):
    value = item.get("r_multiple", item.get("r"))
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------- Logo + nom du bot (même ligne, logo arrondi) ----------
LOGO_URL = "https://raw.githubusercontent.com/NSTradingUS-CA/forexbotny/main/assets/logo.png"
st.markdown(f"""
<div style="display: flex; align-items: center; justify-content: center;">
    <img src="{LOGO_URL}" class="logo-rounded" style="width: 80px; height: auto; margin-right: 20px;">
    <h2 style="color: #FF9100; margin: 0;">Forex Sniper 7‑12</h2>
</div>
""", unsafe_allow_html=True)

# ---------- Bouton Sign out ----------
col_empty, col_signout = st.columns([6, 1])
with col_signout:
    if st.button("Sign out"):
        st.session_state.authenticated = False
        st.rerun()

placeholder = st.empty()

# ---------- Boucle de rafraîchissement ----------
while True:
    data = fetch_status()
    pair_data = fetch_pair_indicators()
    closed_trades = fetch_closed_trades()
    rejected = fetch_rejected_signals()
    now_mtl = datetime.now(MONTREAL_TZ).strftime('%H:%M:%S')
    bot_is_running = check_bot_running()

    with placeholder.container():
        if not data:
            st.error("Status unavailable – retrying in 30s")
        else:
            # ---------- Session ----------
            st.markdown('<div class="session-metrics">', unsafe_allow_html=True)
            sess = data.get("session", {})
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

            trades = sess.get("trades_today", 0)
            max_tr = sess.get("max_trades", 3)

            col1.markdown("#### Trades")
            col1.metric("", f"{trades}/{max_tr}")

            col2.markdown("#### Session")
            col2.metric("", f"{sess.get('start','07')}–{sess.get('end','11')}")

            col3.markdown("#### Status")
            col3.metric("", "🟢" if bot_is_running else "🔴")

            col4.markdown("#### Time")
            col4.metric("", now_mtl)
            st.markdown('</div>', unsafe_allow_html=True)

            # ---------- News ----------
            news = data.get("next_news_event")
            if news:
                st.markdown(
                    f"⏰ **{news.get('title','News')}** at {news.get('time','--')} – "
                    f":orange[{news.get('impact','')} ]"
                )

            # ---------- Paires ----------
            st.markdown("---")
            cols = st.columns(2)
            for i, pair in enumerate(["EUR_USD", "GBP_USD"]):
                with cols[i]:
                    p = pair_data.get(pair, {})
                    st.markdown(f"**{pair}**")

                    price = p.get("price")
                    st.metric("Price", f"{price:.5f}" if price is not None else "--")

                    spread_val = p.get("spread", "--")
                    spread_str = f"{safe_float(spread_val):.5f}" if spread_val != "--" else "--"
                    adx_str = fmt_num(p.get("adx"), 1)
                    plus_di_str = fmt_num(p.get("plus_di"), 1)
                    minus_di_str = fmt_num(p.get("minus_di"), 1)
                    ema50_str = fmt_num(p.get("ema50"))
                    ema200_str = fmt_num(p.get("ema200"))
                    rsi_val = p.get("rsi")
                    rsi_str = f"{float(rsi_val):.1f}" if rsi_val is not None else "--"

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

                    sig = p.get("last_signal")
                    if sig:
                        st.markdown(
                            f"Signal: <span class='green'>{str(sig).upper()}</span>",
                            unsafe_allow_html=True
                        )

            # ---------- Active Trade ----------
            active = data.get("active_trade")
            st.markdown("---")
            st.markdown("#### 🔥 Active Trade")

            if active:
                st.markdown('<div class="active-trade-metrics">', unsafe_allow_html=True)

                c1, c2, c3, c4 = st.columns(4)
                pair = active.get("pair", "")
                direction = direction_text(active)
                setup = setup_name(active)
                score = score_text(active)

                c1.metric("Pair", pair)
                c2.metric("Direction", direction)
                c3.metric("Setup", setup)
                c4.metric("Score", score)

                c1, c2, c3, c4 = st.columns(4)
                entry = active.get("entry", active.get("entry_price"))
                current = active.get("current_price", active.get("price"))
                sl = active.get("sl", active.get("stop_loss"))
                tp1 = active.get("tp1")
                tp2 = active.get("tp2", active.get("tp"))

                c1.metric("Entry", fmt_num(entry))
                c2.metric("Current", fmt_num(current))

                pnl = safe_float(active.get("unrealized_pnl", active.get("pnl", 0)))
                c3.metric("P&L", f"{pnl:.2f} USD", delta_color="normal" if pnl >= 0 else "inverse")

                r_now = current_r(active)
                c4.metric("Current R", f"{r_now:+.2f}R" if r_now is not None else "--")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("SL", f"{fmt_num(sl)} ({fmt_pips(active.get('distance_to_sl_pips'))})")
                c2.metric("TP1 (partial)", fmt_num(tp1) if tp1 is not None else "--")
                c3.metric("TP2 (final)", fmt_num(tp2) if tp2 is not None else "--")
                c4.metric("Risk", f"{active.get('risk_percent', active.get('risk', '--'))}%" if active.get('risk_percent', active.get('risk')) is not None else "--")

                status = active.get("trade_status") or active.get("status")
                be = active.get("be_triggered")
                trailing = active.get("trailing_stop", active.get("trailing_distance"))
                atr_active = active.get("atr")

                details = []
                if status:
                    details.append(f"Status: <b>{status}</b>")
                if be is not None:
                    details.append(f"BE: <b>{'ON' if be else 'OFF'}</b>")
                if trailing not in (None, ""):
                    details.append(f"Trailing: <b>{trailing}</b>")
                if atr_active not in (None, ""):
                    details.append(f"ATR: <b>{fmt_num(atr_active)}</b>")
                if details:
                    st.markdown(
                        "<div class='trade-detail-line'>" + " | ".join(details) + "</div>",
                        unsafe_allow_html=True
                    )

                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("No active trade.")

            # ---------- Closed + Rejected ----------
            tab1, tab2 = st.tabs(["📜 Closed", "🚫 Rejected"])

            with tab1:
                if closed_trades:
                    # Résumé du jour
                    total_pnl = sum(trade_pnl(t) for t in closed_trades)
                    r_values = [trade_r(t) for t in closed_trades if trade_r(t) is not None]
                    wins = sum(1 for t in closed_trades if trade_pnl(t) > 0)

                    s1, s2, s3, s4 = st.columns(4)
                    s1.metric("Trades", len(closed_trades))
                    s2.metric("Win rate", f"{(wins / len(closed_trades) * 100):.0f}%")
                    s3.metric("P&L", f"{total_pnl:+.2f} USD")
                    s4.metric("R total", f"{sum(r_values):+.2f}R" if r_values else "--")
                    st.markdown("---")

                    for t in closed_trades[::-1]:
                        pnl = trade_pnl(t)
                        color = "green" if pnl >= 0 else "red"
                        r_value = trade_r(t)
                        r_display = f" | {r_value:+.2f}R" if r_value is not None else ""
                        setup = setup_name(t)
                        score = score_text(t)
                        direction = direction_text(t)

                        st.markdown(
                            f"<span class='{color}'>"
                            f"<b>{t.get('time','')}</b> {t.get('pair','')} {direction} – "
                            f"{setup} – Score {score} – {pnl:+.2f} USD{r_display}"
                            f"</span>",
                            unsafe_allow_html=True
                        )

                        details = {
                            "Entry": t.get("entry", t.get("entry_price")),
                            "Exit": t.get("exit", t.get("exit_price")),
                            "SL": t.get("sl", t.get("stop_loss")),
                            "TP1": t.get("tp1"),
                            "TP2": t.get("tp2", t.get("tp")),
                            "Risk %": t.get("risk_percent", t.get("risk")),
                            "Setup": setup,
                            "Score": t.get("score"),
                            "Reason": t.get("close_reason", t.get("reason")),
                        }
                        details = {k: v for k, v in details.items() if v is not None}
                        if details:
                            with st.expander("Details"):
                                st.json(details)
                else:
                    st.write("No closed trades.")

            with tab2:
                if rejected:
                    # Les rejets sont conservés dans rejected_signals.json,
                    # indépendamment du status.json.
                    for r in rejected[::-1][:50]:
                        setup = setup_name(r)
                        score = score_text(r)
                        direction = direction_text(r)
                        reason = r.get("reason", "Unknown reason")

                        st.markdown(
                            f"<span class='orange'>"
                            f"<b>{r.get('time','')}</b> {r.get('pair','')} {direction} – "
                            f"{setup} – Score {score} – {reason}"
                            f"</span>",
                            unsafe_allow_html=True
                        )

                        details = {}
                        for key in (
                            "setup_type", "setup", "score", "direction", "reason",
                            "risk_percent", "adx", "rsi", "ema50", "ema200",
                            "plus_di", "minus_di", "atr", "spread", "market_regime"
                        ):
                            if key in r and r[key] is not None:
                                details[key] = r[key]

                        if "indicators" in r and isinstance(r["indicators"], dict):
                            details["indicators"] = r["indicators"]

                        if details:
                            with st.expander("Details"):
                                st.json(details)
                else:
                    st.write("No rejected setups.")

    # ---------- Footer ----------
    st.markdown(
        '<div class="footer">NorthSentinel Trading • Forex Sniper 7‑12 • August, 2026 ©</div>',
        unsafe_allow_html=True
    )

    time.sleep(30)
    st.rerun()
