import v20
import pandas as pd
import pytz
from datetime import datetime, timedelta
import time
import csv
import os
import json
import base64
import requests
import re
import traceback
from dotenv import load_dotenv

load_dotenv()

# ========== CONFIGURATION ==========
API_KEY = os.getenv("OANDA_API_KEY")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_URL = "api-fxpractice.oanda.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
GH_PAT = os.getenv("GH_PAT")
PAIRS = ["EUR_USD", "GBP_USD"]
RISK_PERCENT = 0.65
RISK_PERCENT_BREAKOUT = 0.35
DAILY_LOSS_LIMIT_PERCENT = 2.0
TRADING_HOURS_START = 7
TRADING_HOURS_END = 11
BOT_SHUTDOWN_HOUR = 17
TIMEZONE = 'America/Toronto'
MAX_TRADES_PER_DAY = 3
MIN_MINUTES_BETWEEN_TRADES = 15
ATR_PERIOD = 14
ADX_PERIOD = 10
EXECUTION_GRANULARITY = "M15"
REGIME_GRANULARITY = "H1"
EXECUTION_CANDLES = 300
REGIME_CANDLES = 300
MIN_SETUP_SCORE = 6               # MODIFIÉ : 7 → 6
BREAKOUT_LOOKBACK = 12
BREAKOUT_BUFFER_ATR = 0.10
MAX_ENTRY_EXTENSION_ATR = 3.5      # MODIFIÉ : 2.5 → 3.5
MIN_SL_PIPS = 8
MAX_SL_PIPS = 35
NEWS_BLOCK_MINUTES = 15
HIGH_IMPACT_EVENTS = ["NFP", "CPI", "FOMC", "Interest Rate", "GDP", "Retail Sales"]
USE_MACD_FILTER = True
MACD_FAST = 5
MACD_SLOW = 13
MACD_SIGNAL = 9
USE_VOLUME_FILTER = False

BE_R_MULT = 1.0
TP_PARTIAL_RATIO = 0.33
TRAILING_ATR_MULT = 1.8
FIXED_TRAILING_PIPS = 20

LIMIT_ORDER_EXPIRY_MINUTES = 5
MAX_SLIPPAGE_ATR_FACTOR = 0.5

# Nouveaux paramètres pour la gestion des news
NEWS_CLOSE_BEFORE_MINUTES = 5
NEWS_WARNING_MINUTES = 15
NEWS_CHECK_FUTURE_HOURS = 24

PAIR_CONFIG = {
    "EUR_USD": {"MAX_SPREAD_PIPS": 2.5, "ADX_THRESHOLD": 18, "ATR_MULTIPLIER": 2.0},  # MODIFIÉ : 20 → 18
    "GBP_USD": {"MAX_SPREAD_PIPS": 3.0, "ADX_THRESHOLD": 15, "ATR_MULTIPLIER": 2.0}
}
# ============================

ctx = v20.Context(OANDA_URL, token=API_KEY)
trades_today = 0
last_trade_date = None
last_close_time = None
news_cache = {"time": None, "events": []}
tz = pytz.timezone(TIMEZONE)
active_trade = None
news_sentiment_filter = {}

spread_history = {pair: [] for pair in PAIRS}
SPREAD_WINDOW = 5

closed_trades_today = []
rejected_signals = []

late_shutdown_required = False
trade_opened_during_window_today = False
daily_start_balance = None

CLOSED_TRADES_FILE = "closed_trades.json"
REJECTED_FILE = "rejected_signals.json"
PAUSE_FILE = "pause_state.json"
STATUS_FILE = "status.json"

BOT_STATUS = "running"
_last_status_data = None
_last_status_push_time = None

# Caches pour rejected_signals.json
_last_rejected_data = None
_last_rejected_push_time = None


# ---------- Fichiers JSON ----------
def get_pause_until():
    if os.path.exists(PAUSE_FILE):
        with open(PAUSE_FILE, 'r') as f:
            return json.load(f).get("pause_until", 0)
    return 0


def set_pause_until(timestamp):
    with open(PAUSE_FILE, 'w') as f:
        json.dump({"pause_until": timestamp}, f)
    push_file_to_github(PAUSE_FILE, PAUSE_FILE)


def get_next_high_impact_news(now):
    events = get_high_impact_news()
    future_events = [e for e in events if e["time"] > now]
    if future_events:
        return min(future_events, key=lambda x: x["time"])
    return None


def check_and_block_news(now):
    events = get_high_impact_news()
    for event in events:
        block_start = event["time"] - timedelta(minutes=NEWS_BLOCK_MINUTES)
        block_end = event["time"] + timedelta(minutes=NEWS_BLOCK_MINUTES)
        if block_start <= now <= block_end:
            pause_until = block_end.timestamp()
            if get_pause_until() < pause_until:
                set_pause_until(pause_until)
                msg = (f"📅 High-impact news detected: {event['title']} at "
                       f"{event['time'].strftime('%H:%M')} – Trading paused from "
                       f"{block_start.strftime('%H:%M')} to {block_end.strftime('%H:%M')}")
                send_telegram_message(msg)
                print(msg)
            return True, event, event["time"] - now
    if get_pause_until() > 0 and now.timestamp() >= get_pause_until():
        set_pause_until(0)
        send_telegram_message("🟢 News pause lifted – trading resumed")
        print("News pause lifted.")
    return False, None, None


def push_file_to_github(local_path, remote_path):
    if not GH_PAT:
        return
    try:
        with open(local_path, 'r') as f:
            content = base64.b64encode(f.read().encode()).decode()
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/{remote_path}"
        headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json",
                   "Cache-Control": "no-cache"}
        resp = requests.get(url, headers=headers, timeout=10)
        sha = resp.json().get("sha") if resp.status_code == 200 else None
        payload = {"message": f"Update {remote_path}", "content": content, "branch": "main"}
        if sha:
            payload["sha"] = sha
        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_resp.status_code not in (200, 201):
            print(f"Push {remote_path} failed: {put_resp.status_code}")
    except Exception as e:
        print(f"Error pushing {remote_path}: {e}")


def cleanup_if_new_day(data, today_str, label):
    if data.get("last_cleanup") != today_str:
        print(f"New day detected – resetting {label}.")
        data = {"trades": [] if "trades" in data else [], "signals": [] if "signals" in data else [], "last_cleanup": today_str}
        return True, data
    return False, data


def load_closed_trades_from_file():
    global closed_trades_today
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    if os.path.exists(CLOSED_TRADES_FILE):
        try:
            with open(CLOSED_TRADES_FILE, 'r') as f:
                data = json.load(f)
            reset, data = cleanup_if_new_day(data, today_str, "closed_trades.json")
            if reset:
                closed_trades_today = []
                with open(CLOSED_TRADES_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
                push_file_to_github(CLOSED_TRADES_FILE, CLOSED_TRADES_FILE)
                return
            closed_trades_today = data.get("trades", [])
            print(f"Loaded {len(closed_trades_today)} closed trades from local file.")
        except Exception as e:
            print(f"Error loading closed trades file: {e}")
            closed_trades_today = []
    else:
        closed_trades_today = []


def save_closed_trades_to_file():
    try:
        data = {
            "trades": closed_trades_today,
            "last_cleanup": datetime.now(tz).strftime("%Y-%m-%d")
        }
        with open(CLOSED_TRADES_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        push_file_to_github(CLOSED_TRADES_FILE, CLOSED_TRADES_FILE)
    except Exception as e:
        print(f"Error saving closed trades file: {e}")


def load_rejected_from_file():
    global rejected_signals
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    if os.path.exists(REJECTED_FILE):
        try:
            with open(REJECTED_FILE, 'r') as f:
                data = json.load(f)
            reset, data = cleanup_if_new_day(data, today_str, "rejected_signals.json")
            if reset:
                rejected_signals = []
                with open(REJECTED_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
                push_file_to_github(REJECTED_FILE, REJECTED_FILE)
                return
            rejected_signals = data.get("signals", [])
            print(f"Loaded {len(rejected_signals)} rejected signals from local file.")
        except Exception as e:
            print(f"Error loading rejected signals file: {e}")
            rejected_signals = []
    else:
        rejected_signals = []


def save_rejected_to_file():
    global _last_rejected_data, _last_rejected_push_time

    now = datetime.now(tz)

    data = {
        "signals": rejected_signals[-50:],
        "last_cleanup": datetime.now(tz).strftime("%Y-%m-%d")
    }

    if data == _last_rejected_data:
        return

    if _last_rejected_push_time is not None:
        if (now - _last_rejected_push_time).total_seconds() < 60:
            return

    if not GH_PAT:
        return

    try:
        with open(REJECTED_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        push_file_to_github(REJECTED_FILE, REJECTED_FILE)
        _last_rejected_data = data.copy()
        _last_rejected_push_time = now
    except Exception as e:
        print(f"Error saving rejected signals file: {e}")


def push_status_json(data_dict):
    global _last_status_data, _last_status_push_time

    now = datetime.now(tz)

    if data_dict == _last_status_data:
        return

    if _last_status_push_time is not None:
        if (now - _last_status_push_time).total_seconds() < 60:
            return

    if not GH_PAT:
        return

    try:
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/status.json"
        headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json",
                   "Cache-Control": "no-cache"}
        resp = requests.get(url, headers=headers, timeout=10)
        sha = resp.json().get("sha") if resp.status_code == 200 else None
        content = json.dumps(data_dict, indent=2, default=str).encode()
        payload = {"message": "Update status", "content": base64.b64encode(content).decode(), "branch": "main"}
        if sha:
            payload["sha"] = sha
        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_resp.status_code in (200, 201):
            _last_status_data = data_dict.copy()
            _last_status_push_time = now
            print(f"✅ Status pushed successfully")
        else:
            print(f"Status push failed: {put_resp.status_code} {put_resp.text}")
    except Exception as e:
        print(f"Error pushing status.json: {e}")


def save_status_json():
    global BOT_STATUS
    now = datetime.now(tz)
    status = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "bot_status": BOT_STATUS,
        "session": {
            "trades_today": trades_today,
            "max_trades": MAX_TRADES_PER_DAY,
            "start": f"{TRADING_HOURS_START:02d}:00",
            "end": f"{TRADING_HOURS_END:02d}:00"
        },
        "active_trade": None,
        "next_news_event": None,
        "strategy": "H1 regime + M15 pullback/breakout",
        "max_risk_per_trade_percent": RISK_PERCENT,
        "daily_loss_limit_percent": DAILY_LOSS_LIMIT_PERCENT
    }

    if active_trade:
        pair = active_trade['pair']
        try:
            resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
            price_info = resp.body['prices'][0]
            bid = float(price_info.bids[0].price)
            ask = float(price_info.asks[0].price)
            current_price = bid if active_trade['direction'] == 'sell' else ask
        except:
            current_price = active_trade['entry_price']

        sl_distance = abs(current_price - active_trade['sl'])
        tp_distance = abs(active_trade['tp2'] - current_price) if active_trade.get('tp2') else 0
        unrealized_pnl = (current_price - active_trade['entry_price']) * abs(active_trade['units'])
        if active_trade['direction'] == 'sell':
            unrealized_pnl = -unrealized_pnl

        status["active_trade"] = {
            "pair": active_trade['pair'],
            "type": "Buy" if active_trade['direction'] == 'buy' else "Sell",
            "entry": active_trade['entry_price'],
            "sl": active_trade['sl'],
            "tp1": active_trade.get('tp1'),
            "tp2": active_trade.get('tp2'),
            "trailing_stop": active_trade.get('trailing_distance', '20 pips'),
            "current_price": current_price,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "distance_to_sl_pips": round(sl_distance / 0.0001, 1),
            "distance_to_tp2_pips": round(tp_distance / 0.0001, 1) if tp_distance else 0,
            "atr": active_trade.get('atr'),
            "be_triggered": active_trade.get('be_triggered', False),
            "tp1_hit": active_trade.get('tp1_hit', False),
            "score": active_trade.get('score'),
            "initial_risk": active_trade.get('initial_risk'),
            "setup_type": active_trade.get('setup_type'),
            "risk_percent": active_trade.get('risk_percent'),
            "opened_at": active_trade.get('opened_at'),
            "units": active_trade.get('units')
        }

    events = news_cache["events"]
    if events:
        for e in events:
            time_since_event = now - e["time"]
            if time_since_event < timedelta(minutes=30):
                status["next_news_event"] = {
                    "title": e["title"],
                    "time": e["time"].strftime("%H:%M"),
                    "impact": "High"
                }
                break

    push_status_json(status)


# ---------- Fonctions de trading ----------
def count_all_trades_today():
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    count = 0
    try:
        resp_open = retry_api_call(ctx.trade.list, ACCOUNT_ID, state='OPEN', count=100)
        for t in resp_open.body.get('trades', []):
            open_time = t.openTime if isinstance(t.openTime, str) else str(t.openTime)
            if open_time.startswith(today_str):
                count += 1
        resp_closed = retry_api_call(ctx.trade.list, ACCOUNT_ID, state='CLOSED', count=100)
        for t in resp_closed.body.get('trades', []):
            open_time = t.openTime if isinstance(t.openTime, str) else str(t.openTime)
            if open_time.startswith(today_str):
                count += 1
    except Exception as e:
        print(f"Erreur comptage global trades: {e}")
    return count


def load_existing_open_position():
    global active_trade

    saved_flags = {}
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                status_data = json.load(f)
                saved_trade = status_data.get("active_trade")
                if saved_trade:
                    saved_flags = {
                        "be_triggered": saved_trade.get("be_triggered", False),
                        "tp1_hit": saved_trade.get("tp1_hit", False),
                        "score": saved_trade.get("score"),
                        "setup_type": saved_trade.get("setup_type"),
                        "risk_percent": saved_trade.get("risk_percent"),
                        "initial_risk": saved_trade.get("initial_risk"),
                        "opened_at": saved_trade.get("opened_at"),
                        "trailing_distance": saved_trade.get("trailing_stop", "20 pips"),
                        "atr": saved_trade.get("atr"),
                        "units": saved_trade.get("units")
                    }
        except Exception as e:
            print(f"Could not read status.json for restore: {e}")

    try:
        resp_pos = retry_api_call(ctx.position.list, ACCOUNT_ID)
        for pos in resp_pos.body['positions']:
            instrument = pos.instrument
            if instrument not in PAIRS:
                continue
            long_units = int(pos.long.units)
            short_units = int(pos.short.units)
            if long_units != 0 or short_units != 0:
                resp_trades = retry_api_call(ctx.trade.list, ACCOUNT_ID, instrument=instrument, state='OPEN', count=1)
                open_trades = resp_trades.body.get('trades', [])
                if open_trades:
                    trade = open_trades[0]
                    entry_price = float(trade.price)
                    sl_price = float(trade.stopLossOrder.price) if trade.stopLossOrder else None
                    tp_price = float(trade.takeProfitOrder.price) if trade.takeProfitOrder else None
                    direction = 'buy' if int(trade.currentUnits) > 0 else 'sell'
                    initial_risk = abs(entry_price - sl_price) if sl_price is not None else saved_flags.get("initial_risk", 0.0)
                    active_trade = {
                        'trade_id': trade.id,
                        'pair': instrument,
                        'units': saved_flags.get("units", int(trade.currentUnits)),
                        'entry_price': entry_price,
                        'sl': sl_price,
                        'tp1': (entry_price + initial_risk) if direction == 'buy' else (entry_price - initial_risk),
                        'tp2': tp_price,
                        'tp': tp_price,
                        'direction': direction,
                        'setup_type': saved_flags.get("setup_type", 'recovered'),
                        'risk_percent': saved_flags.get("risk_percent", RISK_PERCENT),
                        'initial_risk': initial_risk,
                        'be_triggered': saved_flags.get("be_triggered", False),
                        'tp1_hit': saved_flags.get("tp1_hit", False),
                        'opened_at': saved_flags.get("opened_at", str(trade.openTime) if getattr(trade, 'openTime', None) else None),
                        'score': saved_flags.get("score"),
                        'trailing_distance': saved_flags.get("trailing_distance", "20 pips"),
                        'atr': saved_flags.get("atr")
                    }
                    print(f"Existing open position loaded: {instrument} {active_trade['direction']} with flags restored")
                    return
    except Exception as e:
        print(f"Could not load existing position: {e}")


def is_spread_ok(pair, current_spread):
    max_spread = PAIR_CONFIG[pair]["MAX_SPREAD_PIPS"] * 0.0001
    history = spread_history[pair]
    history.append(current_spread)
    if len(history) > SPREAD_WINDOW:
        history.pop(0)
    avg_spread = sum(history) / len(history)
    return avg_spread <= max_spread


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured. Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"Telegram send failed: {resp.text}")
    except Exception as e:
        print(f"Telegram error: {e}")


def get_finnhub_sentiment(pair):
    if not FINNHUB_API_KEY:
        return 'neutral'
    try:
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={pair.replace('_', '')}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if 'sentiment' in data and data['sentiment'] is not None:
            bullish = data['sentiment'].get('bullishPercent', 0)
            bearish = data['sentiment'].get('bearishPercent', 0)
            if bullish > 60:
                return 'bullish'
            elif bearish > 60:
                return 'bearish'
        articles = data.get('news', [])
        if articles:
            for article in articles[:3]:
                published = article.get('datetime', 0)
                now_ts = int(datetime.now(tz).timestamp())
                if (now_ts - published) < 1800:
                    sentiment = article.get('sentiment', 'neutral')
                    if sentiment == 'positive':
                        return 'bullish'
                    elif sentiment == 'negative':
                        return 'bearish'
        return 'neutral'
    except Exception as e:
        print(f"Finnhub API error: {e}")
        return 'neutral'


def get_high_impact_news():
    global news_cache
    if news_cache["time"] and (datetime.now(tz) - news_cache["time"]).seconds < 3600:
        return news_cache["events"]
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        events = []
        for item in data:
            if item.get('impact') == 'High' and any(ev in item['title'] for ev in HIGH_IMPACT_EVENTS):
                dt_utc = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
                event_time = dt_utc.astimezone(tz)
                events.append({"time": event_time, "title": item['title']})
        news_cache = {"time": datetime.now(tz), "events": events}
        print(f"News calendar updated: {len(events)} high-impact events found.")
        return events
    except Exception as e:
        print(f"News fetch error: {e}. Trading allowed as fallback.")
        return []


def log_trade(data):
    file_exists = os.path.isfile('trades_log.csv')
    with open('trades_log.csv', 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


def retry_api_call(func, *args, **kwargs):
    for i in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"API attempt {i+1}/3 failed: {e}")
            if i == 2:
                error_str = str(e).lower()
                if "timed out" not in error_str:
                    send_telegram_message(f"⚠️ API error after 3 attempts: {str(e)[:100]}")
                else:
                    print("Network timeout detected - skipping Telegram alert.")
            time.sleep(5)
    raise Exception("API call failed after 3 attempts")


def compute_adx(df, period=14):
    high, low, close = df['h'], df['l'], df['c']
    df['tr'] = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    df['atr_adx'] = df['tr'].ewm(alpha=1/period, adjust=False).mean()
    df['up_move'] = high - high.shift()
    df['down_move'] = low.shift() - low
    df['plus_dm'] = ((df['up_move'] > df['down_move']) & (df['up_move'] > 0)) * df['up_move']
    df['minus_dm'] = ((df['down_move'] > df['up_move']) & (df['down_move'] > 0)) * df['down_move']
    df['plus_di'] = 100 * (df['plus_dm'].ewm(alpha=1/period, adjust=False).mean() / df['atr_adx'])
    df['minus_di'] = 100 * (df['minus_dm'].ewm(alpha=1/period, adjust=False).mean() / df['atr_adx'])
    df['dx'] = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']))
    df['adx'] = df['dx'].ewm(alpha=1/period, adjust=False).mean()
    return df


def compute_macd(df, fast=12, slow=26, signal=9):
    df['ema_fast'] = df['c'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['c'].ewm(span=slow, adjust=False).mean()
    df['macd_line'] = df['ema_fast'] - df['ema_slow']
    df['macd_signal'] = df['macd_line'].ewm(span=signal, adjust=False).mean()
    df['macd_hist'] = df['macd_line'] - df['macd_signal']
    return df


def get_candles(instrument, count=300, granularity=EXECUTION_GRANULARITY):
    params = {"count": count, "granularity": granularity, "price": "M"}
    response = retry_api_call(ctx.instrument.candles, instrument, **params)
    candles = response.body['candles']
    rows = []
    for c in candles:
        if c.complete:
            rows.append({
                'time': pd.to_datetime(c.time),
                'o': float(c.mid.o),
                'h': float(c.mid.h),
                'l': float(c.mid.l),
                'c': float(c.mid.c),
                'volume': int(c.volume)
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    df['atr'] = (df['h'] - df['l']).rolling(ATR_PERIOD).mean()
    delta = df['c'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df = compute_adx(df, ADX_PERIOD)
    df = compute_macd(df, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    df['range'] = df['h'] - df['l']
    df['body'] = (df['c'] - df['o']).abs()
    df['body_ratio'] = df['body'] / df['range'].replace(0, pd.NA)
    if USE_VOLUME_FILTER:
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
    return df


def get_daily_loss_status(balance):
    try:
        realized = sum(float(t.get('pnl', 0)) for t in closed_trades_today)
    except Exception:
        realized = 0.0
    unrealized = 0.0
    if active_trade:
        try:
            pair = active_trade['pair']
            resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
            pi = resp.body['prices'][0]
            bid = float(pi.bids[0].price)
            ask = float(pi.asks[0].price)
            current = bid if active_trade['direction'] == 'sell' else ask
            move = (current - active_trade['entry_price']) * abs(float(active_trade['units']))
            unrealized = -move if active_trade['direction'] == 'sell' else move
        except Exception:
            unrealized = 0.0
    total_loss = realized + unrealized
    loss_pct = max(0.0, -total_loss / balance * 100) if balance > 0 else 0.0
    return loss_pct, loss_pct >= DAILY_LOSS_LIMIT_PERCENT


def setup_stop_and_target(df, direction, entry, pair_config, setup_type):
    atr = float(df['atr'].iloc[-2])
    swing = df.iloc[-4:-1]
    if direction == 'buy':
        structure_sl = float(swing['l'].min())
        raw_sl = min(structure_sl, entry - pair_config['ATR_MULTIPLIER'] * atr)
        if setup_type == 'breakout':
            raw_sl = min(structure_sl, entry - 1.15 * atr)
        risk = entry - raw_sl
        tp = entry + 2.0 * risk
    else:
        structure_sl = float(swing['h'].max())
        raw_sl = max(structure_sl, entry + pair_config['ATR_MULTIPLIER'] * atr)
        if setup_type == 'breakout':
            raw_sl = max(structure_sl, entry + 1.15 * atr)
        risk = raw_sl - entry
        tp = entry - 2.0 * risk
    sl_pips = risk / 0.0001
    if sl_pips < MIN_SL_PIPS or sl_pips > MAX_SL_PIPS:
        return None
    return raw_sl, tp, sl_pips, atr


def get_spread(instrument):
    response = retry_api_call(ctx.pricing.get, ACCOUNT_ID, instruments=instrument)
    price = response.body['prices'][0]
    spread = float(price.asks[0].price) - float(price.bids[0].price)
    return spread


def has_open_position(instrument):
    try:
        response = retry_api_call(ctx.position.list, ACCOUNT_ID)
        for pos in response.body['positions']:
            if pos.instrument == instrument:
                long_units = int(pos.long.units)
                short_units = int(pos.short.units)
                if long_units != 0 or short_units != 0:
                    return True
        return False
    except Exception as e:
        print(f"Position check failed: {e}")
        return False


def calculate_units(balance, sl_price_distance, instrument, risk_percent=RISK_PERCENT):
    risk_amount = balance * (risk_percent / 100.0)
    if sl_price_distance <= 0:
        return 0
    units = int((risk_amount / sl_price_distance) * 0.98)
    return max(1000, units)


def get_account_balance(response):
    try:
        return float(response.body.account.balance)
    except AttributeError:
        return float(response.body['account'].balance)


def close_partial_position(units_to_close):
    pair = active_trade['pair']
    direction = active_trade['direction']
    close_units = -units_to_close if direction == 'buy' else units_to_close
    body = {"units": str(close_units)}
    try:
        r = retry_api_call(ctx.position.close, ACCOUNT_ID, instrument=pair, data=body)
        if r.status_code == 200:
            print(f"Partial close: {abs(units_to_close)} units closed on {pair}")
            return True
    except Exception as e:
        print(f"Partial close failed: {e}")
    return False


def close_full_position_market():
    global active_trade
    if active_trade is None:
        return False
    pair = active_trade['pair']
    units = -active_trade['units']
    body = {"units": str(units)}
    try:
        r = retry_api_call(ctx.position.close, ACCOUNT_ID, instrument=pair, data=body)
        if r.status_code == 200:
            print(f"Full position closed on {pair}")
            return True
    except Exception as e:
        print(f"Full close failed: {e}")
        return False
    return False


def move_sl_to_entry():
    global active_trade
    if active_trade is None:
        return False
    pair = active_trade['pair']
    entry = active_trade['entry_price']
    current_sl = active_trade['sl']
    direction = active_trade['direction']
    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
        price_info = resp.body['prices'][0]
        bid = float(price_info.bids[0].price)
        ask = float(price_info.asks[0].price)
        current_price = bid if direction == 'sell' else ask
    except:
        current_price = None
    if current_price is None:
        return False
    offset = 0.2 * 0.0001
    if direction == 'buy' and current_price > entry and current_sl < entry:
        new_sl = entry - offset
    elif direction == 'sell' and current_price < entry and current_sl > entry:
        new_sl = entry + offset
    else:
        return False
    if direction == 'buy' and new_sl > current_sl:
        body = {"stopLoss": {"price": f"{new_sl:.5f}"}}
    elif direction == 'sell' and new_sl < current_sl:
        body = {"stopLoss": {"price": f"{new_sl:.5f}"}}
    else:
        return False
    try:
        retry_api_call(ctx.position.close, ACCOUNT_ID, instrument=pair, data=body)
        active_trade['sl'] = new_sl
        print(f"SL moved to entry ({new_sl:.5f}) on {pair}")
        return True
    except Exception as e:
        print(f"Failed to move SL to entry: {e}")
        return False


def manage_active_trade():
    global active_trade
    if active_trade is None:
        return
    pair = active_trade['pair']
    direction = active_trade['direction']
    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
        price_info = resp.body['prices'][0]
        bid = float(price_info.bids[0].price)
        ask = float(price_info.asks[0].price)
        current_price = bid if direction == 'sell' else ask
    except Exception:
        return

    entry = active_trade['entry_price']
    initial_risk = active_trade.get('initial_risk', abs(entry - active_trade['sl']))
    move = (current_price - entry) if direction == 'buy' else (entry - current_price)
    r_multiple = move / initial_risk if initial_risk > 0 else 0

    if not active_trade.get('be_triggered') and r_multiple >= BE_R_MULT:
        offset = 0.5 * 0.0001
        new_sl = entry + offset if direction == 'buy' else entry - offset
        old_sl = active_trade['sl']
        if (direction == 'buy' and new_sl > old_sl) or (direction == 'sell' and new_sl < old_sl):
            try:
                body = {"stopLoss": {"price": f"{new_sl:.5f}"}}
                retry_api_call(ctx.position.close, ACCOUNT_ID, instrument=pair, data=body)
                active_trade['sl'] = new_sl
                active_trade['be_triggered'] = True
                print(f"Break-even triggered on {pair} at +{r_multiple:.2f}R")
                send_telegram_message(f"🛡️ BE triggered on {pair} at +{r_multiple:.2f}R.")
            except Exception as e:
                print(f"Break-even update failed: {e}")

    tp1 = active_trade.get('tp1')
    units = abs(int(active_trade['units']))
    if tp1 is not None and not active_trade.get('tp1_hit'):
        if (direction == 'buy' and current_price >= tp1) or (direction == 'sell' and current_price <= tp1):
            partial_units = max(1000, int(units * TP_PARTIAL_RATIO))
            if partial_units < units and close_partial_position(partial_units):
                active_trade['units'] = units - partial_units
                active_trade['tp1_hit'] = True
                active_trade['tp1'] = None
                print(f"TP1 hit on {pair}, {partial_units} units closed")
                send_telegram_message(f"🎯 TP1 reached on {pair}: {partial_units} units closed, runner kept.")

    if active_trade.get('be_triggered') or active_trade.get('tp1_hit'):
        try:
            df = get_candles(pair, count=ATR_PERIOD + 30, granularity=EXECUTION_GRANULARITY)
            atr_val = float(df['atr'].iloc[-2])
            active_trade['atr'] = atr_val
            trail_distance = atr_val * TRAILING_ATR_MULT
            if direction == 'buy':
                new_sl = current_price - trail_distance
                if new_sl > active_trade['sl']:
                    body = {"stopLoss": {"price": f"{new_sl:.5f}"}}
                    retry_api_call(ctx.position.close, ACCOUNT_ID, instrument=pair, data=body)
                    active_trade['sl'] = new_sl
                    active_trade['trailing_distance'] = f"{TRAILING_ATR_MULT}x M15 ATR"
                    print(f"Trailing SL updated on {pair} to {new_sl:.5f}")
                    send_telegram_message(f"📈 Trailing SL updated on {pair} to {new_sl:.5f}")
            else:
                new_sl = current_price + trail_distance
                if new_sl < active_trade['sl']:
                    body = {"stopLoss": {"price": f"{new_sl:.5f}"}}
                    retry_api_call(ctx.position.close, ACCOUNT_ID, instrument=pair, data=body)
                    active_trade['sl'] = new_sl
                    active_trade['trailing_distance'] = f"{TRAILING_ATR_MULT}x M15 ATR"
                    print(f"Trailing SL updated on {pair} to {new_sl:.5f}")
                    send_telegram_message(f"📈 Trailing SL updated on {pair} to {new_sl:.5f}")
        except Exception as e:
            print(f"Trailing update failed: {e}")


def place_trade(instrument, entry, sl, tp, units, direction, setup_type, risk_percent, reason):
    global active_trade, trades_today
    if active_trade is not None:
        print("A trade is already active, cannot open another.")
        return False

    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments=instrument)
        price_info = resp.body['prices'][0]
        bid = float(price_info.bids[0].price)
        ask = float(price_info.asks[0].price)
        current_price = bid if direction == 'sell' else ask
    except:
        current_price = None

    if current_price is not None:
        atr = active_trade.get('atr', 0.0001) if active_trade else 0.0001
        max_slippage = MAX_SLIPPAGE_ATR_FACTOR * atr
        if abs(current_price - entry) > max_slippage:
            send_telegram_message(f"⚠️ Slippage too high for {instrument}: entry {entry:.5f} vs current {current_price:.5f} (diff > {max_slippage:.5f})")
            print(f"Trade aborted: slippage too high")
            return False

    expiry_time = datetime.now(tz) + timedelta(minutes=LIMIT_ORDER_EXPIRY_MINUTES)
    expiry_str = expiry_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    signed_units = -abs(units) if direction == 'sell' else abs(units)
    sl_distance = abs(entry - sl)
    tp_distance = sl_distance * 2.0
    tp1 = entry + sl_distance if direction == 'buy' else entry - sl_distance
    tp2 = tp
    trailing_distance = str(round(FIXED_TRAILING_PIPS * 0.0001, 5))

    order_body = {
        "type": "LIMIT",
        "instrument": instrument,
        "units": str(signed_units),
        "price": f"{entry:.5f}",
        "stopLossOnFill": {"price": f"{sl:.5f}"},
        "takeProfitOnFill": {"price": f"{tp2:.5f}"},
        "trailingStopLossOnFill": {"distance": trailing_distance},
        "timeInForce": "GTD",
        "gtdTime": expiry_str
    }

    r = retry_api_call(ctx.order.create, ACCOUNT_ID, order=order_body)
    if hasattr(r.body, 'errorMessage') and r.body.errorMessage:
        error_msg = r.body.errorMessage
        print(f"OANDA error: {error_msg}")
        send_telegram_message(f"⚠️ Order rejected: {error_msg}")
        return False

    try:
        fill_trans = r.body.get('orderFillTransaction', r.body.get('orderCreateTransaction'))
        if not fill_trans:
            print("Order created but not filled immediately. Waiting for fill...")
            send_telegram_message(f"⚠️ LIMIT order created for {instrument} at {entry:.5f}, but not executed immediately.")
            return False

        trade_opened = fill_trans.tradeOpened
        trade_id = trade_opened.tradeID
        entry_price = float(trade_opened.price)
        units_filled = int(trade_opened.units)

        score = None
        if reason and "score" in reason:
            match = re.search(r'score\s+(\d+)/\d+', reason, re.IGNORECASE)
            if match:
                score = int(match.group(1))

        active_trade = {
            'trade_id': trade_id,
            'pair': instrument,
            'units': units_filled,
            'entry_price': entry_price,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'direction': direction,
            'setup_type': setup_type,
            'risk_percent': risk_percent,
            'initial_risk': sl_distance,
            'be_triggered': False,
            'tp1_hit': False,
            'trailing_distance': f"{FIXED_TRAILING_PIPS} pips initial",
            'atr': 0.0,
            'opened_at': datetime.now(tz).isoformat(),
            'score': score
        }
    except Exception as e:
        print(f"Failed to extract trade details: {e}")
        send_telegram_message(f"⚠️ Error extracting trade details: {str(e)[:100]}")
        return False

    trades_today += 1
    rr = 2.0
    msg = (f"<b>✅ Trade opened ({trades_today}/{MAX_TRADES_PER_DAY})</b>\n"
           f"Pair: {instrument}\n"
           f"Setup: {setup_type.upper()}\n"
           f"Type: {'Buy' if direction == 'buy' else 'Sell'}\n"
           f"Risk: {risk_percent:.2f}%\n"
           f"Volume: {abs(units_filled)} units\n"
           f"Entry: {entry_price:.5f}\n"
           f"SL: {sl:.5f}\n"
           f"TP1: {tp1:.5f} (1R, {TP_PARTIAL_RATIO:.0%})\n"
           f"TP2: {tp2:.5f} (2R)\n"
           f"R/R: 1:2\n"
           f"Score: {score if score is not None else 'N/A'}\n"
           f"Time: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
    send_telegram_message(msg)
    print(f"✅ Trade placed on {instrument} ({direction}) [{setup_type}] - {abs(units_filled)} units")
    log_trade({
        "time": datetime.now(tz).isoformat(),
        "pair": instrument,
        "setup": setup_type,
        "entry": entry_price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "units": abs(units_filled),
        "direction": direction,
        "risk_percent": risk_percent,
        "rr": rr,
        "status": "OPEN",
        "score": score
    })
    return True


def check_closed_trade():
    global active_trade, last_close_time
    if active_trade is None:
        return
    pair = active_trade['pair']
    if has_open_position(pair):
        return
    try:
        resp = retry_api_call(ctx.trade.list, ACCOUNT_ID, instrument=pair, count=20, state='CLOSED')
        closed_trades = resp.body.get('trades', [])
        if not closed_trades:
            raise RuntimeError("No closed trade returned by OANDA")

        def close_key(t):
            value = getattr(t, 'closeTime', '')
            return str(value)
        closed_trades = sorted(closed_trades, key=close_key, reverse=True)
        latest = closed_trades[0]
        total_pnl = float(latest.realizedPL)
        close_price = float(latest.price)
        entry_price = active_trade['entry_price']
        units = active_trade['units']
        direction = active_trade.get('direction', 'buy')
        setup_type = active_trade.get('setup_type', 'unknown')
        initial_risk = active_trade.get('initial_risk', 0.0)

        if initial_risk > 0:
            if direction == 'buy':
                realized_r = (close_price - entry_price) / initial_risk
            else:
                realized_r = (entry_price - close_price) / initial_risk
        else:
            realized_r = 0.0

        score = active_trade.get('score')

        msg = (f"<b>🔴 Trade closed ({trades_today}/{MAX_TRADES_PER_DAY})</b>\n"
               f"Pair: {pair}\n"
               f"Setup: {setup_type.upper()}\n"
               f"Type: {'Buy' if direction == 'buy' else 'Sell'}\n"
               f"Entry: {entry_price:.5f}\n"
               f"Exit: {close_price:.5f}\n"
               f"Volume: {abs(units)}\n"
               f"P&L: {total_pnl:.2f} USD\n"
               f"R: {realized_r:+.2f}R\n"
               f"Time: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
        send_telegram_message(msg)

        closed_trades_today.append({
            "pair": pair,
            "type": "Buy" if direction == 'buy' else "Sell",
            "setup": setup_type,
            "pnl": total_pnl,
            "time": datetime.now(tz).strftime("%H:%M:%S"),
            "r_multiple": realized_r,
            "score": score,
            "units": abs(units)
        })
        save_closed_trades_to_file()
        log_trade({
            "time": datetime.now(tz).isoformat(),
            "pair": pair,
            "setup": setup_type,
            "entry": entry_price,
            "exit": close_price,
            "units": abs(units),
            "pnl": total_pnl,
            "direction": direction,
            "status": "CLOSED",
            "r_multiple": realized_r,
            "score": score
        })
        last_close_time = datetime.now(tz)
    except Exception as e:
        print(f"Error retrieving closed trade: {e}")
        send_telegram_message(f"⚠️ Trade on {pair} closed (details unavailable).")
        last_close_time = datetime.now(tz)
    active_trade = None


def check_signal(df, instrument):
    if len(df) < 220:
        return False, 0, 0, 0, 0, None, "Not enough M15 candles", "Not enough M15 candles", None, 0

    h1 = get_candles(instrument, count=REGIME_CANDLES, granularity=REGIME_GRANULARITY)
    if len(h1) < 220:
        return False, 0, 0, 0, 0, None, "Not enough H1 candles", "Not enough H1 candles", None, 0

    c = df.iloc[-2]
    prev = df.iloc[-3]
    h = h1.iloc[-2]
    config = PAIR_CONFIG[instrument]
    atr = float(c['atr'])
    if any(pd.isna(c[x]) for x in ['atr','ema20','ema50','rsi','adx','plus_di','minus_di']):
        return False, 0, 0, 0, 0, None, "Missing M15 indicators", "Missing M15 indicators", None, 0
    if any(pd.isna(h[x]) for x in ['ema50','ema200','adx']):
        return False, 0, 0, 0, 0, None, "Missing H1 regime", "Missing H1 regime", None, 0

    h1_up = h['ema50'] > h['ema200'] and h['c'] > h['ema50']
    h1_down = h['ema50'] < h['ema200'] and h['c'] < h['ema50']
    h1_trending = h['adx'] >= max(18, config['ADX_THRESHOLD'] - 2)

    buy_reasons = []
    sell_reasons = []

    if not h1_trending:
        reason = f"H1 regime too weak (ADX {h['adx']:.1f})"
        buy_reasons.append(reason)
        sell_reasons.append(reason)
        return False, 0, 0, 0, 0, None, "\n".join(buy_reasons), "\n".join(sell_reasons), None, 0

    extension = abs(c['c'] - c['ema50']) / atr if atr > 0 else 99
    if extension > MAX_ENTRY_EXTENSION_ATR:
        reason = f"Entry too extended ({extension:.2f} ATR)"
        buy_reasons.append(reason)
        sell_reasons.append(reason)
        return False, 0, 0, 0, 0, None, "\n".join(buy_reasons), "\n".join(sell_reasons), None, 0

    sentiment = news_sentiment_filter.get(instrument, 'neutral')

    # Conditions de rejet assouplies
    bull_rejection = (c['c'] > c['o'] and c['l'] <= c['ema20'] * 1.0015 and c['c'] > c['ema20'] and c['body_ratio'] >= 0.40)
    bear_rejection = (c['c'] < c['o'] and c['h'] >= c['ema20'] * 0.9985 and c['c'] < c['ema20'] and c['body_ratio'] >= 0.40)
    momentum_buy = c['plus_di'] > c['minus_di'] and c['rsi'] >= 50 and c['rsi'] <= 70   # MODIFIÉ : 68 → 70
    momentum_sell = c['minus_di'] > c['plus_di'] and c['rsi'] <= 50 and c['rsi'] >= 30  # MODIFIÉ : 48 → 50, 32 → 30
    adx_ok = c['adx'] >= config['ADX_THRESHOLD']
    macd_buy = c['macd_line'] > c['macd_signal']
    macd_sell = c['macd_line'] < c['macd_signal']

    # Setup A: Pullback - BUY
    if h1_up and sentiment != 'bearish' and bull_rejection and momentum_buy and adx_ok:
        score = 0
        score += 2
        score += 2
        score += 1 if c['adx'] >= config['ADX_THRESHOLD'] + 5 else 0
        score += 1 if c['plus_di'] > c['minus_di'] else 0
        score += 1 if 52 <= c['rsi'] <= 68 else 0   # on garde cette plage pour un bonus
        score += 1 if macd_buy else 0
        score += 1 if c['c'] > prev['h'] else 0
        if score >= MIN_SETUP_SCORE:
            levels = setup_stop_and_target(df, 'buy', float(c['c']), config, 'pullback')
            if levels:
                sl, tp, sl_pips, atr_val = levels
                return True, float(c['c']), sl, tp, sl_pips, 'buy', "", "", 'pullback', RISK_PERCENT
        else:
            buy_reasons.append(f"Pullback BUY score {score}/{MIN_SETUP_SCORE} too low")
    else:
        if not h1_up:
            buy_reasons.append("H1 trend not up for BUY")
        if sentiment == 'bearish':
            buy_reasons.append("Sentiment bearish blocks BUY")
        if not bull_rejection:
            buy_reasons.append("No bullish rejection at EMA20")
        if not momentum_buy:
            buy_reasons.append("Momentum not favorable for BUY")
        if not adx_ok:
            buy_reasons.append(f"ADX too low ({c['adx']:.1f} < {config['ADX_THRESHOLD']})")

    # Setup A: Pullback - SELL
    if h1_down and sentiment != 'bullish' and bear_rejection and momentum_sell and adx_ok:
        score = 0
        score += 2
        score += 2
        score += 1 if c['adx'] >= config['ADX_THRESHOLD'] + 5 else 0
        score += 1 if c['minus_di'] > c['plus_di'] else 0
        score += 1 if 32 <= c['rsi'] <= 48 else 0   # plage bonus
        score += 1 if macd_sell else 0
        score += 1 if c['c'] < prev['l'] else 0
        if score >= MIN_SETUP_SCORE:
            levels = setup_stop_and_target(df, 'sell', float(c['c']), config, 'pullback')
            if levels:
                sl, tp, sl_pips, atr_val = levels
                return True, float(c['c']), sl, tp, sl_pips, 'sell', "", "", 'pullback', RISK_PERCENT
        else:
            sell_reasons.append(f"Pullback SELL score {score}/{MIN_SETUP_SCORE} too low")
    else:
        if not h1_down:
            sell_reasons.append("H1 trend not down for SELL")
        if sentiment == 'bullish':
            sell_reasons.append("Sentiment bullish blocks SELL")
        if not bear_rejection:
            sell_reasons.append("No bearish rejection at EMA20")
        if not momentum_sell:
            sell_reasons.append("Momentum not favorable for SELL")
        if not adx_ok:
            sell_reasons.append(f"ADX too low ({c['adx']:.1f} < {config['ADX_THRESHOLD']})")

    # Setup B: Breakout
    if len(df) >= BREAKOUT_LOOKBACK + 5:
        box = df.iloc[-(BREAKOUT_LOOKBACK + 2):-2]
        resistance = float(box['h'].max())
        support = float(box['l'].min())
        buffer = BREAKOUT_BUFFER_ATR * atr
        buy_break = prev['c'] > resistance + buffer and c['l'] <= resistance + buffer and c['c'] > resistance
        sell_break = prev['c'] < support - buffer and c['h'] >= support - buffer and c['c'] < support
        breakout_quality_buy = c['body_ratio'] >= 0.55 and c['c'] > c['o'] and c['adx'] >= config['ADX_THRESHOLD']
        breakout_quality_sell = c['body_ratio'] >= 0.55 and c['c'] < c['o'] and c['adx'] >= config['ADX_THRESHOLD']

        if h1_up and sentiment != 'bearish' and buy_break and breakout_quality_buy and c['plus_di'] > c['minus_di']:
            score = 2 + 2 + 1
            score += 1 if c['adx'] >= config['ADX_THRESHOLD'] + 5 else 0
            score += 1 if c['rsi'] < 72 else 0
            score += 1 if macd_buy else 0
            score += 1 if c['c'] > c['ema20'] else 0
            if score >= MIN_SETUP_SCORE:
                levels = setup_stop_and_target(df, 'buy', float(c['c']), config, 'breakout')
                if levels:
                    sl, tp, sl_pips, atr_val = levels
                    return True, float(c['c']), sl, tp, sl_pips, 'buy', "", "", 'breakout', RISK_PERCENT_BREAKOUT
            else:
                buy_reasons.append(f"Breakout BUY score {score}/{MIN_SETUP_SCORE} too low")
        else:
            if not h1_up:
                buy_reasons.append("H1 not up for breakout BUY")
            if not buy_break:
                buy_reasons.append("No breakout BUY setup")
            if not breakout_quality_buy:
                buy_reasons.append("Breakout quality (body/ADX) insufficient for BUY")
            if not (c['plus_di'] > c['minus_di']):
                buy_reasons.append("+DI not > -DI for BUY")

        if h1_down and sentiment != 'bullish' and sell_break and breakout_quality_sell and c['minus_di'] > c['plus_di']:
            score = 2 + 2 + 1
            score += 1 if c['adx'] >= config['ADX_THRESHOLD'] + 5 else 0
            score += 1 if c['rsi'] > 28 else 0
            score += 1 if macd_sell else 0
            score += 1 if c['c'] < c['ema20'] else 0
            if score >= MIN_SETUP_SCORE:
                levels = setup_stop_and_target(df, 'sell', float(c['c']), config, 'breakout')
                if levels:
                    sl, tp, sl_pips, atr_val = levels
                    return True, float(c['c']), sl, tp, sl_pips, 'sell', "", "", 'breakout', RISK_PERCENT_BREAKOUT
            else:
                sell_reasons.append(f"Breakout SELL score {score}/{MIN_SETUP_SCORE} too low")
        else:
            if not h1_down:
                sell_reasons.append("H1 not down for breakout SELL")
            if not sell_break:
                sell_reasons.append("No breakout SELL setup")
            if not breakout_quality_sell:
                sell_reasons.append("Breakout quality (body/ADX) insufficient for SELL")
            if not (c['minus_di'] > c['plus_di']):
                sell_reasons.append("-DI not > +DI for SELL")

    if not buy_reasons:
        buy_reasons.append("No BUY setup triggered")
    if not sell_reasons:
        sell_reasons.append("No SELL setup triggered")
    return False, 0, 0, 0, 0, None, "\n".join(buy_reasons), "\n".join(sell_reasons), None, 0


def check_future_news_and_alert():
    now = datetime.now(tz)
    events = get_high_impact_news()
    future_events = [e for e in events if e["time"] > now and e["time"] - now < timedelta(hours=NEWS_CHECK_FUTURE_HOURS)]
    if future_events:
        msg = "⚠️ <b>Upcoming high-impact news before next session:</b>\n"
        for e in future_events:
            msg += f"• {e['title']} at {e['time'].strftime('%H:%M')} ({e['time'].strftime('%a %d %b')})\n"
        msg += "\nPlease close any open positions manually before market close."
        send_telegram_message(msg)
        print("Future news alert sent.")


def main():
    global trades_today, last_trade_date, last_close_time, active_trade
    global closed_trades_today, rejected_signals
    global late_shutdown_required, trade_opened_during_window_today, daily_start_balance
    global BOT_STATUS

    load_closed_trades_from_file()
    load_rejected_from_file()

    trades_today = count_all_trades_today()
    try:
        daily_start_balance = get_account_balance(retry_api_call(ctx.account.summary, ACCOUNT_ID))
    except Exception:
        daily_start_balance = None
    if active_trade is None:
        load_existing_open_position()

    trade_opened_during_window_today = False
    if active_trade is not None:
        opened_at = active_trade.get("opened_at")
        if opened_at:
            try:
                opened_dt = datetime.fromisoformat(
                    opened_at.replace("Z", "+00:00")
                ).astimezone(tz)
                trade_opened_during_window_today = (
                    opened_dt.date() == datetime.now(tz).date()
                    and TRADING_HOURS_START <= opened_dt.hour < TRADING_HOURS_END
                )
            except (ValueError, TypeError):
                trade_opened_during_window_today = False

    late_shutdown_required = (
        active_trade is not None
        and trade_opened_during_window_today
        and datetime.now(tz).hour >= TRADING_HOURS_END
    )

    start_msg = (
        f"🟢 Forex Sniper 7-12 started – max {MAX_TRADES_PER_DAY} trades/day, "
        f"buffer {MIN_MINUTES_BETWEEN_TRADES}min, Buy & Sell. "
        f"({trades_today} already taken)"
    )
    print(start_msg)
    send_telegram_message(start_msg)

    check_future_news_and_alert()

    try:
        while True:
            now = datetime.now(tz)

            today = now.date()
            if last_trade_date != today:
                trades_today = count_all_trades_today()
                last_trade_date = today
                last_close_time = None
                closed_trades_today.clear()
                rejected_signals.clear()
                late_shutdown_required = False
                trade_opened_during_window_today = False
                load_closed_trades_from_file()
                load_rejected_from_file()
                if active_trade is None:
                    load_existing_open_position()
                try:
                    daily_start_balance = get_account_balance(retry_api_call(ctx.account.summary, ACCOUNT_ID))
                except Exception:
                    daily_start_balance = None

                if active_trade is not None:
                    opened_at = active_trade.get("opened_at")
                    if opened_at:
                        try:
                            opened_dt = datetime.fromisoformat(
                                opened_at.replace("Z", "+00:00")
                            ).astimezone(tz)
                            trade_opened_during_window_today = (
                                opened_dt.date() == today
                                and TRADING_HOURS_START <= opened_dt.hour < TRADING_HOURS_END
                            )
                        except (ValueError, TypeError):
                            trade_opened_during_window_today = False

            manage_active_trade()
            check_closed_trade()

            if (
                now.hour >= TRADING_HOURS_END
                and trade_opened_during_window_today
                and active_trade is not None
            ):
                late_shutdown_required = True

            # Gestion des news avec trade ouvert
            if active_trade is not None:
                blocked, event, time_until = check_and_block_news(now)
                if event is not None and time_until is not None:
                    minutes_until = time_until.total_seconds() / 60.0
                    if minutes_until <= NEWS_WARNING_MINUTES and minutes_until > NEWS_CLOSE_BEFORE_MINUTES:
                        send_telegram_message(
                            f"📰 <b>High-impact news in {int(minutes_until)} minutes:</b> {event['title']} at {event['time'].strftime('%H:%M')}\n"
                            f"Trade on {active_trade['pair']} is open. Action will be taken at {NEWS_CLOSE_BEFORE_MINUTES} min before."
                        )
                    if minutes_until <= NEWS_CLOSE_BEFORE_MINUTES:
                        try:
                            resp = ctx.pricing.get(ACCOUNT_ID, instruments=active_trade['pair'])
                            price_info = resp.body['prices'][0]
                            bid = float(price_info.bids[0].price)
                            ask = float(price_info.asks[0].price)
                            current_price = bid if active_trade['direction'] == 'sell' else ask
                            unrealized_pnl = (current_price - active_trade['entry_price']) * active_trade['units']
                            if active_trade['direction'] == 'sell':
                                unrealized_pnl = -unrealized_pnl
                        except:
                            unrealized_pnl = 0

                        if unrealized_pnl > 0:
                            if close_full_position_market():
                                send_telegram_message(
                                    f"🔒 <b>Trade closed automatically before news</b>\n"
                                    f"Pair: {active_trade['pair']}\n"
                                    f"P&L: {unrealized_pnl:.2f} USD\n"
                                    f"Reason: High-impact news '{event['title']}' in <5 min."
                                )
                                time.sleep(2)
                            else:
                                send_telegram_message("⚠️ Failed to close trade automatically. Please monitor.")
                        else:
                            if move_sl_to_entry():
                                send_telegram_message(
                                    f"🛡️ <b>Stop-loss moved to entry before news</b>\n"
                                    f"Pair: {active_trade['pair']}\n"
                                    f"New SL: {active_trade['sl']:.5f}\n"
                                    f"Reason: High-impact news '{event['title']}' in <5 min."
                                )
                            else:
                                send_telegram_message("⚠️ Could not move SL to entry. Please monitor manually.")

            shutdown_1205 = (
                now.hour == 12
                and now.minute >= 5
                and not late_shutdown_required
            )

            shutdown_1705 = (
                now.hour > BOT_SHUTDOWN_HOUR
                or (
                    now.hour == BOT_SHUTDOWN_HOUR
                    and now.minute >= 5
                )
            )

            if shutdown_1205 or shutdown_1705:
                check_future_news_and_alert()
                BOT_STATUS = "stopped"
                save_status_json()

                stop_msg = (
                    f"🔴 Forex Sniper 7-12 stopped – End of session "
                    f"({now.strftime('%H:%M')}), {trades_today} trade(s) taken today."
                )
                print(stop_msg)
                send_telegram_message(stop_msg)
                break

            if not hasattr(main, "next_news_check"):
                main.next_news_check = now

            if now >= main.next_news_check:
                for pair in PAIRS:
                    sentiment = get_finnhub_sentiment(pair)
                    if sentiment != 'neutral':
                        news_sentiment_filter[pair] = sentiment
                main.next_news_check = now + timedelta(seconds=60)

            blocked, _, _ = check_and_block_news(now)
            news_blocked = blocked

            in_trading_hours = (
                now.hour >= TRADING_HOURS_START
                and now.hour < TRADING_HOURS_END
            )

            can_trade_time = True
            if last_close_time is not None:
                elapsed = now - last_close_time
                if elapsed < timedelta(minutes=MIN_MINUTES_BETWEEN_TRADES):
                    can_trade_time = False

            balance = None
            daily_loss_blocked = False
            try:
                balance = get_account_balance(retry_api_call(ctx.account.summary, ACCOUNT_ID))
                _, daily_loss_blocked = get_daily_loss_status(balance)
            except Exception as e:
                print(f"Risk check failed: {e}")
                daily_loss_blocked = True

            can_trade = (
                active_trade is None
                and trades_today < MAX_TRADES_PER_DAY
                and in_trading_hours
                and not news_blocked
                and can_trade_time
                and not daily_loss_blocked
            )

            if can_trade:
                candidates = []
                for pair in PAIRS:
                    if has_open_position(pair):
                        continue
                    try:
                        spread = get_spread(pair)
                    except Exception as e:
                        print(f"Spread check failed for {pair}: {e}")
                        continue
                    if not is_spread_ok(pair, spread):
                        print(f" -> REJECTED {pair}: spread too wide")
                        rejected_entry = {
                            "time": now.strftime("%H:%M:%S"),
                            "pair": pair,
                            "direction": None,
                            "buy_reason": "Spread too wide",
                            "sell_reason": "Spread too wide",
                            "spread": spread,
                            "adx": None,
                            "plus_di": None,
                            "minus_di": None,
                            "ema50": None,
                            "ema200": None,
                            "rsi": None,
                            "atr": None
                        }
                        rejected_signals.append(rejected_entry)
                        save_rejected_to_file()
                        continue
                    try:
                        df = get_candles(pair, count=EXECUTION_CANDLES, granularity=EXECUTION_GRANULARITY)
                        result = check_signal(df, pair)
                    except Exception as e:
                        print(f"Signal analysis failed for {pair}: {e}")
                        continue

                    signal, price, sl, tp, sl_pips, direction, buy_reason, sell_reason, setup_type, risk_percent = result

                    if signal:
                        candidates.append((pair, price, sl, tp, sl_pips, direction, buy_reason, setup_type, risk_percent))
                    else:
                        c = df.iloc[-2]
                        rejected_entry = {
                            "time": now.strftime("%H:%M:%S"),
                            "pair": pair,
                            "direction": None,
                            "buy_reason": buy_reason,
                            "sell_reason": sell_reason,
                            "spread": spread,
                            "adx": c['adx'] if not pd.isna(c['adx']) else None,
                            "plus_di": c['plus_di'] if not pd.isna(c['plus_di']) else None,
                            "minus_di": c['minus_di'] if not pd.isna(c['minus_di']) else None,
                            "ema50": c['ema50'] if not pd.isna(c['ema50']) else None,
                            "ema200": c['ema200'] if not pd.isna(c['ema200']) else None,
                            "rsi": c['rsi'] if not pd.isna(c['rsi']) else None,
                            "atr": c['atr'] if not pd.isna(c['atr']) else None
                        }
                        rejected_signals.append(rejected_entry)
                        save_rejected_to_file()

                        buy_short = buy_reason[:60] + "..." if len(buy_reason) > 60 else buy_reason
                        sell_short = sell_reason[:60] + "..." if len(sell_reason) > 60 else sell_reason
                        print(f" -> REJECTED {pair}: BUY: {buy_short} | SELL: {sell_short}")

                if candidates:
                    candidates.sort(key=lambda x: (0 if x[6] == 'pullback' else -1, -x[4]))
                    pair, price, sl, tp, sl_pips, direction, buy_reason, setup_type, risk_percent = candidates[0]
                    print(f" -> SIGNAL {direction} {pair} [{setup_type}] {buy_reason}")
                    sl_distance = abs(price - sl)
                    units = calculate_units(balance, sl_distance, pair, risk_percent)
                    if units >= 1000:
                        success = place_trade(pair, price, sl, tp, units, direction, setup_type, risk_percent, buy_reason)
                        if success:
                            trade_opened_during_window_today = True

            save_status_json()

            if not hasattr(main, "next_trade_save"):
                main.next_trade_save = now

            if now >= main.next_trade_save:
                save_closed_trades_to_file()
                save_rejected_to_file()
                main.next_trade_save = now + timedelta(minutes=5)

            time.sleep(30)

    except Exception as e:
        error_trace = traceback.format_exc()
        send_telegram_message(f"🚨 CRITICAL ERROR in main loop:\n{str(e)[:300]}\n\n{error_trace[:300]}")
        print(f"Critical error: {e}\n{error_trace}")
        BOT_STATUS = "stopped"
        save_status_json()
        raise
    except KeyboardInterrupt:
        BOT_STATUS = "stopped"
        save_status_json()
        stop_msg = "🔴 Bot stopped manually (Ctrl+C)"
        print(stop_msg)
        send_telegram_message(stop_msg)


if __name__ == "__main__":
    main()
