import v20
import pandas as pd
import pytz
from datetime import datetime, timedelta
import time, csv, os, json, base64, requests, re, traceback, signal
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv('OANDA_API_KEY')
ACCOUNT_ID = os.getenv('OANDA_ACCOUNT_ID')
OANDA_URL = 'api-fxpractice.oanda.com'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
GH_PAT = os.getenv('GH_PAT')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
PAIRS = ['EUR_USD', 'GBP_USD']
RISK_PULLBACK = 0.65
RISK_BREAKOUT = 0.35
RISK_PINBAR = 0.55
RISK_INSIDE_BAR = 0.45
RISK_SUPPORT_RESISTANCE = 0.5
RISK_MOMENTUM_CONTINU = 0.4
RISK_ENGULFING = 0.6
RISK_ORB = 0.5
RISK_TREND_BREAKOUT = 0.3
RISK_COUNTER_TREND_BREAKOUT = 0.25
DAILY_LOSS_LIMIT_PERCENT = 2.0
TRADING_HOURS_START = 7
TRADING_HOURS_END = 11
BOT_SHUTDOWN_HOUR = 17
TIMEZONE = 'America/Toronto'
MAX_TRADES_PER_DAY = 3
MIN_MINUTES_BETWEEN_TRADES = 15
ATR_PERIOD = 14
ADX_PERIOD = 10
EXECUTION_GRANULARITY = 'H1'
REGIME_GRANULARITY = 'H1'
EXECUTION_CANDLES = 300
REGIME_CANDLES = 300
BREAKOUT_LOOKBACK = 12
BREAKOUT_BUFFER_ATR = 0.1
MIN_SL_PIPS = 8
MAX_SL_PIPS = 35
NEWS_BLOCK_PRE_MINUTES = 7
NEWS_BLOCK_POST_MINUTES = 10
HIGH_IMPACT_EVENTS = ['NFP', 'CPI', 'FOMC', 'Interest Rate', 'GDP', 'Retail Sales', 'Nonfarm Payrolls', 'Employment', 'Rate Decision']
USE_MACD_FILTER = True
MACD_FAST = 5
MACD_SLOW = 13
MACD_SIGNAL = 9
MACD_TOLERANCE = 0.0001
USE_VOLUME_FILTER = False
TP1_R_MULT = 0.75
TP_PARTIAL_RATIO = 0.33
TRAILING_SL_MULT = 1.0
EARLY_SECURE_R = 0.5
EARLY_SECURE_BE_OFFSET_PIPS = 2.0
EARLY_WIDEN_R = 1.0
EARLY_WIDEN_ATR_MULT = 2.0
TRAILING_ATR_MULT = 1.5
TRAILING_MIN_PIPS = 20.0
STAGNATION_MINUTES = 60
TP2_WIDEN_TRIGGER = 0.9
TP2_WIDEN_FACTOR = 1.5
TP2_WIDEN_SETUPS = {'Momentum', 'Breakout', 'ORB', 'Trend Breakout'}
TP2_INITIAL_LOCK_OFFSET_PIPS = 5.0
NEWS_CLOSE_PCT_EXTENSION = 0.33
NEWS_CLOSE_PCT_OTHER = 0.5
TIME_LOCK_WINDOW_START_H = 11
TIME_LOCK_WINDOW_START_M = 5
TIME_LOCK_WINDOW_END_H = 12
TIME_LOCK_WINDOW_END_M = 30
TIME_LOCK_MIN_TRADE_AGE_MIN = 75
TIME_LOCK_PEAK_MIN_FRACTION = 0.6
TIME_LOCK_PEAK_MAX_FRACTION = 0.85
TIME_LOCK_RETRACE_MIN = 0.3
TIME_LOCK_CLOSE_PCT = 0.67
TIME_LOCK_SL_OFFSET_PIPS = 2.0
REGIME_ADVERSE_MIN_SIGNALS = 3
REGIME_ADVERSE_MIN_PEAK_FRACTION = 0.4
REGIME_ADVERSE_CLOSE_PCT = 0.67
REGIME_ADVERSE_SL_OFFSET_PIPS = 2.0
REGIME_CONFIRM_BARS = 2
CHECKPOINT_HOUR = 11
CHECKPOINT_MINUTE = 0
SLIPPAGE_ATR_FACTOR = 0.4
SLIPPAGE_MIN_PIPS = 2.0
NEWS_CLOSE_BEFORE_MINUTES = 5
NEWS_CHECK_FUTURE_HOURS = 24
BE_TOLERANCE_PIPS = 0.5
PAIR_CONFIG = {'EUR_USD': {'MAX_SPREAD_PIPS': 2.5, 'ADX_THRESHOLD': 16, 'ATR_MULTIPLIER': 2.0}, 'GBP_USD': {'MAX_SPREAD_PIPS': 3.0, 'ADX_THRESHOLD': 13, 'ATR_MULTIPLIER': 2.0}}
SETUP_RR = {'pullback': 1.5, 'engulfing': 1.8, 'pinbar': 2.0, 'insidebar': 2.0, 'sr': 2.0, 'momentum': 2.2, 'orb': 2.5, 'breakout': 2.5, 'trendbreakout': 3.0, 'countertrendbreakout': 2.0}
GITHUB_PUSH_MIN_INTERVAL = 300
CANDLE_CACHE_TTL_SECONDS = 120
GITHUB_MAX_PUSH_ATTEMPTS = 3
LIVE_LOG_FILE = 'live_log.md'
LIVE_LOG_MAX_LINES = 400
_live_log_buffer = []
_last_live_push = None
LIVE_LOG_PUSH_INTERVAL = 60
ctx = v20.Context(OANDA_URL, token=API_KEY)
trades_today = 0
last_trade_date = None
last_close_time = None
news_cache = {'time': None, 'events': []}
tz = pytz.timezone(TIMEZONE)
active_trade = None
news_sentiment_filter = {}
orb_range = {'high': None, 'low': None, 'recorded': False, 'date': None}
spread_history = {pair: [] for pair in PAIRS}
SPREAD_WINDOW = 5
closed_trades_today = []
rejected_signals = []
late_shutdown_required = False
trade_opened_during_window_today = False
daily_start_balance = None
_current_blocked_pairs = []
_current_active_pairs = []
_current_news_event = None
CLOSED_TRADES_FILE = 'closed_trades.json'
REJECTED_FILE = 'rejected_signals.json'
PAUSE_FILE = 'pause_state.json'
STATUS_FILE = 'status.json'
BOT_STATUS = 'running'
_last_status_data = None
_last_status_push_time = None
_last_rejected_data = None
_last_rejected_push_time = None
_last_closed_trades_data = None
_candle_cache = {}
_last_news_block_message_sent = False
_last_reminder_minute = None
_critical_alert_sent = False
_regime_adverse_streak = 0

def _oanda_headers():
    return {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}

def _oanda_http_retry(method, url, json_body=None, max_attempts=3):
    for i in range(max_attempts):
        try:
            r = requests.request(method, url, headers=_oanda_headers(), json=json_body, timeout=15)
            if r.status_code in (200, 201, 400, 404):
                return r
            print(f'⚠ HTTP {r.status_code}: {r.text[:200]}')
        except Exception as e:
            print(f'HTTP attempt {i + 1}/{max_attempts} failed: {e}')
        if i < max_attempts - 1:
            time.sleep(3 * (i + 1))
    return None

def _extract_attr(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _github_put_with_retry(url, headers, content_b64, message, max_attempts=GITHUB_MAX_PUSH_ATTEMPTS):
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            sha = resp.json().get('sha') if resp.status_code == 200 else None
            payload = {'message': message, 'content': content_b64, 'branch': 'main'}
            if sha:
                payload['sha'] = sha
            put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
            if put_resp.status_code in (200, 201):
                return put_resp.status_code
            if put_resp.status_code == 409 and attempt < max_attempts - 1:
                time.sleep(2)
                continue
            return put_resp.status_code
        except Exception as e:
            print(f'Error GitHub PUT {attempt + 1}: {e}')
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            return None
    return None

def push_file_to_github(local_path, remote_path):
    if not GH_PAT:
        return
    try:
        with open(local_path, 'r') as f:
            content = base64.b64encode(f.read().encode()).decode()
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/{remote_path}"
        headers = {'Authorization': f'token {GH_PAT}', 'Accept': 'application/vnd.github.v3+json', 'Cache-Control': 'no-cache'}
        status = _github_put_with_retry(url, headers, content, f'Update {remote_path}')
        print(f'✅ Push {remote_path} succeeded' if status in (200, 201) else f'Push {remote_path} failed: {status}')
    except Exception as e:
        print(f'Error pushing {remote_path}: {e}')

def live_log(msg, force=False):
    """Console log + buffer + live GitHub push (60s throttle unless forced). Shown in live_log.md."""
    global _last_live_push
    ts = datetime.now(tz).strftime('%H:%M:%S')
    line = f'- `{ts}` {msg}'
    print(line)
    _live_log_buffer.append(line)
    if len(_live_log_buffer) > LIVE_LOG_MAX_LINES:
        _live_log_buffer.pop(0)
    now = datetime.now(tz)
    if not force and _last_live_push is not None and ((now - _last_live_push).total_seconds() < LIVE_LOG_PUSH_INTERVAL):
        return
    if not GH_PAT:
        return
    try:
        header = f"# Live Log — Forex Sniper\n\nSession du {now.strftime('%Y-%m-%d')} — MAJ {now.strftime('%H:%M:%S')} ET — Bot: {BOT_STATUS}\n\n"
        if active_trade:
            header += f"**Trade actif :** {active_trade.get('pair')} {active_trade.get('direction')} @ {active_trade.get('entry_price')} — Phase {active_trade.get('phase', 0)} — Peak {active_trade.get('peak_profit_pips', 0):.1f}p\n\n"
        body = header + '\n'.join(_live_log_buffer) + '\n'
        with open(LIVE_LOG_FILE, 'w') as f:
            f.write(body)
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/{LIVE_LOG_FILE}"
        headers = {'Authorization': f'token {GH_PAT}', 'Accept': 'application/vnd.github.v3+json', 'Cache-Control': 'no-cache'}
        status = _github_put_with_retry(url, headers, base64.b64encode(body.encode()).decode(), 'Live log update')
        if status in (200, 201):
            _last_live_push = now
    except Exception as e:
        print(f'⚠ live_log push failed: {e}')

def fetch_position_pnl_from_oanda(instrument):
    try:
        resp = retry_api_call(ctx.position.get, ACCOUNT_ID, instrument)
        body = getattr(resp, 'body', None)
        if body is None:
            return None
        pos = _extract_attr(body, 'position', None)
        if pos is None:
            return None
        pl_raw = _extract_attr(pos, 'unrealizedPL', None)
        if pl_raw is not None:
            try:
                return float(pl_raw)
            except:
                pass
        total = 0.0
        for side_name in ('long', 'short'):
            side = _extract_attr(pos, side_name, None)
            if side is None:
                continue
            side_pl = _extract_attr(side, 'unrealizedPL', None)
            if side_pl is not None:
                try:
                    total += float(side_pl)
                except:
                    pass
        return total if total != 0.0 else None
    except Exception as e:
        print(f'⚠ fetch_position_pnl failed: {e}')
        return None

def fetch_trade_raw(trade_id):
    url = f'https://{OANDA_URL}/v3/accounts/{ACCOUNT_ID}/trades/{trade_id}'
    r = _oanda_http_retry('GET', url)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json().get('trade')
    except Exception as e:
        print(f'⚠ Could not parse trade JSON: {e}')
        return None

def extract_sl_from_trade_json(trade_json):
    if not trade_json:
        return (None, None)
    trailing = trade_json.get('trailingStopLossOrder')
    if trailing:
        tsv = trailing.get('trailingStopValue')
        if tsv is not None:
            try:
                return (float(tsv), 'trailing_stop_value')
            except:
                pass
        p = trailing.get('price')
        if p is not None:
            try:
                return (float(p), 'trailing_price')
            except:
                pass
    sl = trade_json.get('stopLossOrder')
    if sl:
        p = sl.get('price')
        if p is not None:
            try:
                return (float(p), 'fixed_sl')
            except:
                pass
    return (None, None)

def fetch_closing_fills(trade_id):
    fills = []
    try:
        tr_resp = retry_api_call(ctx.transaction.list, ACCOUNT_ID, count=500)
    except Exception as e:
        print(f'⚠ fetch_closing_fills: {e}')
        return fills
    for tx in tr_resp.body.get('transactions', []):
        if getattr(tx, 'type', None) != 'ORDER_FILL':
            continue
        trades_closed = getattr(tx, 'tradesClosed', None)
        if not trades_closed:
            continue
        if not isinstance(trades_closed, (list, tuple)):
            trades_closed = [trades_closed]
        for tc in trades_closed:
            if str(getattr(tc, 'tradeID', '')) != str(trade_id):
                continue
            try:
                cu = abs(int(getattr(tc, 'units', 0)))
                fp = float(getattr(tx, 'price', 0))
                ft = str(getattr(tx, 'time', ''))
                if cu > 0 and fp > 0:
                    fills.append({'units': cu, 'price': fp, 'time': ft})
            except:
                continue
    fills.sort(key=lambda x: x.get('time', ''))
    return fills

def get_pause_until():
    if os.path.exists(PAUSE_FILE):
        with open(PAUSE_FILE, 'r') as f:
            return json.load(f).get('pause_until', 0)
    return 0

def set_pause_until(timestamp):
    with open(PAUSE_FILE, 'w') as f:
        json.dump({'pause_until': timestamp}, f)
    push_file_to_github(PAUSE_FILE, PAUSE_FILE)

def get_next_high_impact_news(now):
    events = get_high_impact_news()
    fut = [e for e in events if e['time'] > now]
    return min(fut, key=lambda x: x['time']) if fut else None

def get_affected_pairs(event_title):
    tl = event_title.lower()
    if any((ev.lower() in tl for ev in ['nfp', 'cpi', 'fomc', 'interest rate', 'nonfarm payrolls', 'employment'])):
        return PAIRS
    elif 'gdp' in tl and 'uk' not in tl:
        return ['GBP_USD']
    elif 'retail sales' in tl and 'uk' in tl:
        return ['GBP_USD']
    elif 'retail sales' in tl:
        return PAIRS
    else:
        return PAIRS

def check_and_block_news(now):
    global _current_blocked_pairs, _current_active_pairs, _current_news_event
    events = get_high_impact_news()
    for event in events:
        bs = event['time'] - timedelta(minutes=NEWS_BLOCK_PRE_MINUTES)
        be = event['time'] + timedelta(minutes=NEWS_BLOCK_POST_MINUTES)
        if bs <= now <= be:
            pu = be.timestamp()
            first = get_pause_until() < pu
            if first:
                set_pause_until(pu)
            aff = get_affected_pairs(event['title'])
            _current_blocked_pairs = aff
            _current_active_pairs = [p for p in PAIRS if p not in aff]
            _current_news_event = event
            if first and active_trade is not None:
                msg = f"📅 High-impact news: {event['title']} at {event['time'].strftime('%H:%M')}"
                send_telegram_message(msg)
                live_log(msg, force=True)
            return (True, event, event['time'] - now, aff)
    if get_pause_until() > 0 and now.timestamp() >= get_pause_until():
        set_pause_until(0)
        _current_blocked_pairs = []
        _current_active_pairs = PAIRS
        _current_news_event = None
        print('News pause lifted.')
    return (False, None, None, [])

def cleanup_if_new_day(data, today_str, label):
    if data.get('last_cleanup') != today_str:
        print(f'New day — resetting {label}.')
        data = {'trades': [] if 'trades' in data else [], 'signals': [] if 'signals' in data else [], 'last_cleanup': today_str}
        return (True, data)
    return (False, data)

def load_closed_trades_from_file():
    global closed_trades_today
    today_str = datetime.now(tz).strftime('%Y-%m-%d')
    if os.path.exists(CLOSED_TRADES_FILE):
        try:
            with open(CLOSED_TRADES_FILE, 'r') as f:
                data = json.load(f)
            (reset, data) = cleanup_if_new_day(data, today_str, 'closed_trades.json')
            if reset:
                closed_trades_today = []
            else:
                closed_trades_today = data.get('trades', [])
            with open(CLOSED_TRADES_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            if reset:
                push_file_to_github(CLOSED_TRADES_FILE, CLOSED_TRADES_FILE)
        except Exception as e:
            print(f'Error loading closed trades: {e}')
            closed_trades_today = []
    else:
        closed_trades_today = []

def save_closed_trades_to_file():
    global _last_closed_trades_data
    try:
        data = {'trades': closed_trades_today, 'last_cleanup': datetime.now(tz).strftime('%Y-%m-%d')}
        with open(CLOSED_TRADES_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        snap = json.dumps(closed_trades_today, sort_keys=True, default=str)
        if _last_closed_trades_data == snap:
            return
        push_file_to_github(CLOSED_TRADES_FILE, CLOSED_TRADES_FILE)
        _last_closed_trades_data = snap
    except Exception as e:
        print(f'Error saving closed trades: {e}')

def load_rejected_from_file():
    global rejected_signals
    today_str = datetime.now(tz).strftime('%Y-%m-%d')
    if os.path.exists(REJECTED_FILE):
        try:
            with open(REJECTED_FILE, 'r') as f:
                data = json.load(f)
            (reset, data) = cleanup_if_new_day(data, today_str, 'rejected_signals.json')
            if reset:
                rejected_signals = []
            else:
                rejected_signals = data.get('signals', [])
            with open(REJECTED_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            if reset:
                push_file_to_github(REJECTED_FILE, REJECTED_FILE)
        except Exception as e:
            print(f'Error loading rejected: {e}')
            rejected_signals = []
    else:
        rejected_signals = []

def save_rejected_to_file():
    global _last_rejected_data, _last_rejected_push_time
    now = datetime.now(tz)
    data = {'signals': rejected_signals[-100:], 'last_cleanup': datetime.now(tz).strftime('%Y-%m-%d')}
    if data == _last_rejected_data:
        return
    if _last_rejected_push_time is not None and (now - _last_rejected_push_time).total_seconds() < GITHUB_PUSH_MIN_INTERVAL:
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
        print(f'Error saving rejected: {e}')

def push_status_json(data_dict, force=False):
    global _last_status_data, _last_status_push_time
    now = datetime.now(tz)
    if not force and data_dict == _last_status_data:
        return
    if not force and _last_status_push_time is not None and ((now - _last_status_push_time).total_seconds() < GITHUB_PUSH_MIN_INTERVAL):
        return
    if not GH_PAT:
        return
    try:
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/status.json"
        headers = {'Authorization': f'token {GH_PAT}', 'Accept': 'application/vnd.github.v3+json', 'Cache-Control': 'no-cache'}
        content = json.dumps(data_dict, indent=2, default=str).encode()
        b64 = base64.b64encode(content).decode()
        status = _github_put_with_retry(url, headers, b64, 'Update status')
        if status in (200, 201):
            _last_status_data = data_dict.copy()
            _last_status_push_time = now
            print('✅ Status pushed')
        else:
            print(f'Status push failed: {status}')
    except Exception as e:
        print(f'Error pushing status.json: {e}')

def get_usd_cad_rate():
    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments='USD_CAD')
        return float(resp.body['prices'][0].bids[0].price)
    except Exception as e:
        print(f'⚠ Could not fetch USD/CAD: {e}')
        return 1.0

def save_status_json(force=False):
    global BOT_STATUS
    now = datetime.now(tz)
    status = {'time': now.strftime('%Y-%m-%d %H:%M:%S'), 'bot_status': BOT_STATUS, 'session': {'trades_today': trades_today, 'max_trades': MAX_TRADES_PER_DAY, 'start': f'{TRADING_HOURS_START:02d}:00', 'end': f'{TRADING_HOURS_END:02d}:00'}, 'active_trade': None, 'next_news_event': None, 'strategy': 'H1 Multi-Setup — State machine v2 (stop fixe -> BE+2 -> TP1 -> trailing ATR)', 'max_risk_per_trade_percent': max(RISK_PULLBACK, RISK_BREAKOUT, RISK_PINBAR, RISK_INSIDE_BAR, RISK_SUPPORT_RESISTANCE, RISK_MOMENTUM_CONTINU, RISK_ENGULFING, RISK_ORB, RISK_TREND_BREAKOUT, RISK_COUNTER_TREND_BREAKOUT), 'daily_loss_limit_percent': DAILY_LOSS_LIMIT_PERCENT, 'blocked_pairs': _current_blocked_pairs, 'active_pairs': _current_active_pairs}
    if _current_news_event:
        status['next_news_event'] = {'title': _current_news_event['title'], 'time': _current_news_event['time'].strftime('%H:%M'), 'impact': 'High'}
    elif news_cache['events']:
        for e in news_cache['events']:
            if now - e['time'] < timedelta(minutes=30):
                status['next_news_event'] = {'title': e['title'], 'time': e['time'].strftime('%H:%M'), 'impact': 'High'}
                break
    if active_trade:
        pair = active_trade['pair']
        try:
            resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
            pi = resp.body['prices'][0]
            bid = float(pi.bids[0].price)
            ask = float(pi.asks[0].price)
            current_price = bid if active_trade['direction'] == 'sell' else ask
        except:
            current_price = active_trade['entry_price']
        sl_distance = abs(current_price - active_trade['sl'])
        tp_distance = abs(active_trade['tp2'] - current_price) if active_trade.get('tp2') else 0
        units_abs = abs(int(active_trade['units']))
        unreal = (active_trade['entry_price'] - current_price) * units_abs if active_trade['direction'] == 'sell' else (current_price - active_trade['entry_price']) * units_abs
        usd_cad = get_usd_cad_rate()
        status['active_trade'] = {'pair': pair, 'type': 'Buy' if active_trade['direction'] == 'buy' else 'Sell', 'entry': active_trade['entry_price'], 'sl': active_trade['sl'], 'tp1': active_trade.get('tp1'), 'tp2': active_trade.get('tp2'), 'tp2_initial': active_trade.get('tp2_initial'), 'tp2_initial_locked': active_trade.get('tp2_initial_locked', False), 'trailing_stop': 'ATR after TP1 only', 'phase': active_trade.get('phase', 0), 'current_price': current_price, 'unrealized_pnl_usd': round(unreal, 2), 'unrealized_pnl_cad': round(unreal * usd_cad, 2), 'usd_cad_rate': round(usd_cad, 4), 'distance_to_sl_pips': round(sl_distance / 0.0001, 1), 'distance_to_tp2_pips': round(tp_distance / 0.0001, 1) if tp_distance else 0, 'atr': active_trade.get('atr'), 'be_triggered': active_trade.get('be_triggered', False), 'tp1_hit': active_trade.get('tp1_hit', False), 'tp2_widened': active_trade.get('tp2_widened', False), 'peak_profit_pips': active_trade.get('peak_profit_pips', 0.0), 'time_lock_done': active_trade.get('time_lock_done', False), 'regime_adverse_handled': active_trade.get('regime_adverse_handled', False), 'setup_type': active_trade.get('setup_type'), 'risk_percent': active_trade.get('risk_percent'), 'initial_risk': active_trade.get('initial_risk'), 'opened_at': active_trade.get('opened_at'), 'units': active_trade.get('units'), 'score': active_trade.get('quality_score'), 'news_partial_done': active_trade.get('news_partial_done', False), 'early_secure_done': active_trade.get('early_secure_done', False), 'early_widen_done': active_trade.get('early_widen_done', False)}
    push_status_json(status, force=force)

def count_all_trades_today():
    today_str = datetime.now(tz).strftime('%Y-%m-%d')
    count = 0
    try:
        resp_open = retry_api_call(ctx.trade.list, ACCOUNT_ID, state='OPEN', count=100)
        for t in resp_open.body.get('trades', []):
            if str(t.openTime if isinstance(t.openTime, str) else str(t.openTime)).startswith(today_str):
                count += 1
        resp_closed = retry_api_call(ctx.trade.list, ACCOUNT_ID, state='CLOSED', count=100)
        for t in resp_closed.body.get('trades', []):
            if str(t.openTime if isinstance(t.openTime, str) else str(t.openTime)).startswith(today_str):
                count += 1
    except Exception as e:
        print(f'Count error: {e}')
    return count

def load_existing_open_position():
    global active_trade
    saved_flags = {}
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                status_data = json.load(f)
            saved_trade = status_data.get('active_trade')
            if saved_trade:
                saved_flags = {'be_triggered': saved_trade.get('be_triggered', False), 'tp1_hit': saved_trade.get('tp1_hit', False), 'tp2_widened': saved_trade.get('tp2_widened', False), 'tp2_initial': saved_trade.get('tp2_initial'), 'tp2_initial_locked': saved_trade.get('tp2_initial_locked', False), 'peak_profit_pips': saved_trade.get('peak_profit_pips', 0.0), 'time_lock_done': saved_trade.get('time_lock_done', False), 'regime_adverse_handled': saved_trade.get('regime_adverse_handled', False), 'setup_type': saved_trade.get('setup_type'), 'risk_percent': saved_trade.get('risk_percent'), 'initial_risk': saved_trade.get('initial_risk'), 'opened_at': saved_trade.get('opened_at'), 'atr': saved_trade.get('atr'), 'units': saved_trade.get('units'), 'quality_score': saved_trade.get('score'), 'last_peak_time': saved_trade.get('last_peak_time'), 'news_partial_done': saved_trade.get('news_partial_done', False), 'early_secure_done': saved_trade.get('early_secure_done', False), 'early_widen_done': saved_trade.get('early_widen_done', False), 'phase': saved_trade.get('phase', 0)}
        except Exception as e:
            print(f'Could not read status.json: {e}')
    try:
        resp_pos = retry_api_call(ctx.position.list, ACCOUNT_ID)
        for pos in resp_pos.body['positions']:
            instrument = pos.instrument
            if instrument not in PAIRS:
                continue
            if int(pos.long.units) == 0 and int(pos.short.units) == 0:
                continue
            resp_trades = retry_api_call(ctx.trade.list, ACCOUNT_ID, instrument=instrument, state='OPEN', count=10)
            open_trades = resp_trades.body.get('trades', [])
            if not open_trades:
                continue
            trade = open_trades[0]
            entry_price = float(trade.price)
            trade_id = trade.id
            trade_json = fetch_trade_raw(trade_id)
            (sl_price, sl_source) = extract_sl_from_trade_json(trade_json)
            if sl_price is not None:
                print(f'🔍 SL loaded ({sl_source}): {sl_price:.5f}')
            tp_price = float(trade.takeProfitOrder.price) if trade.takeProfitOrder else None
            direction = 'buy' if int(trade.currentUnits) > 0 else 'sell'
            saved_risk = saved_flags.get('initial_risk')
            initial_risk = saved_risk if saved_risk is not None and saved_risk > 0 else abs(entry_price - sl_price) if sl_price is not None else 0.0
            _tp1_dist = initial_risk * TP1_R_MULT
            tp1_price = entry_price + _tp1_dist if direction == 'buy' else entry_price - _tp1_dist
            tp1_order_id = None
            try:
                pending_orders = retry_api_call(ctx.order.list_pending, ACCOUNT_ID)
                for o in pending_orders.body.get('orders', []):
                    if o.instrument == instrument and o.type == 'LIMIT' and (int(o.units) != 0):
                        if direction == 'buy' and int(o.units) < 0 or (direction == 'sell' and int(o.units) > 0):
                            tp1_order_id = o.id
                            break
            except Exception as e:
                print(f'⚠ pending orders restore: {e}')
            phase = saved_flags.get('phase', 0)
            if saved_flags.get('tp1_hit'):
                phase = 3
            elif saved_flags.get('be_triggered'):
                phase = 1
            active_trade = {'trade_id': trade_id, 'tp1_order_id': tp1_order_id, 'pair': instrument, 'units': int(trade.currentUnits), 'initial_units': abs(int(trade.currentUnits)), 'entry_price': entry_price, 'sl': sl_price, 'tp1': tp1_price, 'tp2': tp_price, 'tp2_initial': saved_flags.get('tp2_initial', tp_price), 'tp2_initial_locked': saved_flags.get('tp2_initial_locked', False), 'tp': tp_price, 'direction': direction, 'setup_type': saved_flags.get('setup_type', 'recovered'), 'risk_percent': saved_flags.get('risk_percent', RISK_PULLBACK), 'initial_risk': initial_risk, 'be_triggered': saved_flags.get('be_triggered', False), 'tp1_hit': saved_flags.get('tp1_hit', tp1_order_id is None), 'tp2_widened': saved_flags.get('tp2_widened', False), 'peak_profit_pips': saved_flags.get('peak_profit_pips', 0.0), 'last_peak_time': saved_flags.get('last_peak_time', datetime.now(tz).isoformat()), 'time_lock_done': saved_flags.get('time_lock_done', False), 'regime_adverse_handled': saved_flags.get('regime_adverse_handled', False), 'checkpoint_sent': False, 'opened_at': saved_flags.get('opened_at', str(trade.openTime) if getattr(trade, 'openTime', None) else None), 'atr': saved_flags.get('atr'), 'quality_score': saved_flags.get('quality_score'), 'news_partial_done': saved_flags.get('news_partial_done', False), 'early_secure_done': saved_flags.get('early_secure_done', False), 'early_widen_done': saved_flags.get('early_widen_done', False), 'phase': phase, 'trailing_active': phase >= 3}
            print(f"Existing open position loaded: {instrument} {direction} phase={phase} early_secure={active_trade['early_secure_done']}")
            return
    except Exception as e:
        print(f'Could not load existing position: {e}')

def is_spread_ok(pair, current_spread):
    max_spread = PAIR_CONFIG[pair]['MAX_SPREAD_PIPS'] * 0.0001
    h = spread_history[pair]
    h.append(current_spread)
    if len(h) > SPREAD_WINDOW:
        h.pop(0)
    return sum(h) / len(h) <= max_spread

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('Telegram not configured.')
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return
            elif resp.status_code == 429:
                try:
                    retry_after = resp.json().get('parameters', {}).get('retry_after', 5)
                except:
                    retry_after = 5
                time.sleep(retry_after)
            else:
                print(f'Telegram failed {resp.status_code}: {resp.text}')
                break
        except Exception as e:
            print(f'Telegram error {attempt + 1}/3: {e}')
            if attempt < 2:
                time.sleep(2)
    print('❌ Telegram send failed after 3 attempts.')

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
        for article in data.get('news', [])[:3]:
            if int(datetime.now(tz).timestamp()) - article.get('datetime', 0) < 1800:
                if article.get('sentiment') == 'positive':
                    return 'bullish'
                elif article.get('sentiment') == 'negative':
                    return 'bearish'
        return 'neutral'
    except Exception as e:
        print(f'Finnhub error: {e}')
        return 'neutral'

def _normalize_news_title(title):
    if not title:
        return title
    t = title.strip().lower()
    t = re.sub('^(core|prelim|preliminary|final|advance|revised|flash)\\s+', '', t)
    t = re.sub('\\s*\\((m/m|y/y|q/q|mom|yoy|qoq)\\)\\s*$', '', t)
    t = re.sub('\\s+(m/m|y/y|q/q|mom|yoy|qoq)\\s*$', '', t)
    t = re.sub('\\s+', ' ', t).strip()
    for (pattern, canon) in [('\\bcpi\\b', 'CPI'), ('\\bnon-?farm payroll', 'NFP'), ('\\bnfp\\b', 'NFP'), ('\\binterest rate\\b', 'Interest Rate Decision'), ('\\brate decision\\b', 'Interest Rate Decision'), ('\\bfomc\\b', 'FOMC'), ('\\bgdp\\b', 'GDP'), ('\\bretail sales\\b', 'Retail Sales'), ('\\bemployment\\b', 'Employment')]:
        if re.search(pattern, t):
            return canon
    return t.title()

def get_high_impact_news():
    global news_cache
    now = datetime.now(tz)
    if news_cache['time'] and (now - news_cache['time']).seconds < 3600:
        return news_cache['events']
    events = []
    try:
        resp = requests.get('https://nfs.faireconomy.media/ff_calendar_thisweek.json', headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if resp.status_code == 200:
            for item in resp.json():
                if item.get('impact') == 'High' and any((kw in item['title'] for kw in HIGH_IMPACT_EVENTS)):
                    dt_utc = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
                    events.append({'time': dt_utc.astimezone(tz), 'title': item['title']})
    except Exception as e:
        print(f'⚠ faireconomy error: {e}')
    if ALPHA_VANTAGE_API_KEY:
        try:
            resp = requests.get(f'https://www.alphavantage.co/query?function=CALENDAR_EVENT&apikey={ALPHA_VANTAGE_API_KEY}', timeout=10)
            if resp.status_code == 200:
                for item in resp.json().get('data', []):
                    if any((c in item.get('currency', '') for c in ['EUR', 'USD', 'GBP'])) and item.get('impact', '').lower() == 'high':
                        events.append({'time': datetime.fromisoformat(item['date']).astimezone(tz), 'title': item['event_type']})
        except Exception as e:
            print(f'⚠ Alpha Vantage error: {e}')
    try:
        resp = requests.get('https://api-fxpractice.oanda.com/labs/v1/calendar', headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}, params={'instrument': 'EUR_USD,GBP_USD', 'period': 86400}, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get('events', []):
                if item.get('impact') == 'High':
                    events.append({'time': datetime.fromtimestamp(int(item['timestamp']) / 1000, tz), 'title': item['title']})
    except Exception as e:
        print(f'⚠ OANDA ForexLabs error: {e}')
    unique = {}
    for e in events:
        key = (e['time'].strftime('%Y-%m-%d %H:%M'), _normalize_news_title(e['title']))
        if key not in unique:
            unique[key] = {'time': e['time'], 'title': _normalize_news_title(e['title'])}
    final_events = sorted(list(unique.values()), key=lambda x: x['time'])
    news_cache = {'time': now, 'events': final_events}
    print(f'📰 News calendar: {len(final_events)} high-impact events.')
    return final_events

def log_trade(data):
    file_exists = os.path.isfile('trades_log.csv')
    with open('trades_log.csv', 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)
    live_log(f"📝 trades_log.csv : {data.get('pair')} {data.get('setup')} {data.get('direction')} @ {data.get('entry')}")

def retry_api_call(func, *args, **kwargs):
    for i in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f'API attempt {i + 1}/3 failed: {e}')
            if i == 2 and 'timed out' not in str(e).lower():
                send_telegram_message(f'⚠ API error after 3 attempts: {str(e)[:100]}')
            time.sleep(5 * 2 ** i)
    raise Exception('API call failed after 3 attempts')

def compute_adx(df, period=14):
    (high, low, close) = (df['h'], df['l'], df['c'])
    df['tr'] = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    df['atr_adx'] = df['tr'].ewm(alpha=1 / period, adjust=False).mean()
    df['up_move'] = high - high.shift()
    df['down_move'] = low.shift() - low
    df['plus_dm'] = ((df['up_move'] > df['down_move']) & (df['up_move'] > 0)) * df['up_move']
    df['minus_dm'] = ((df['down_move'] > df['up_move']) & (df['down_move'] > 0)) * df['down_move']
    df['plus_di'] = 100 * (df['plus_dm'].ewm(alpha=1 / period, adjust=False).mean() / df['atr_adx'])
    df['minus_di'] = 100 * (df['minus_dm'].ewm(alpha=1 / period, adjust=False).mean() / df['atr_adx'])
    df['dx'] = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']))
    df['adx'] = df['dx'].ewm(alpha=1 / period, adjust=False).mean()
    return df

def compute_macd(df, fast=12, slow=26, signal=9):
    df['ema_fast'] = df['c'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['c'].ewm(span=slow, adjust=False).mean()
    df['macd_line'] = df['ema_fast'] - df['ema_slow']
    df['macd_signal'] = df['macd_line'].ewm(span=signal, adjust=False).mean()
    df['macd_hist'] = df['macd_line'] - df['macd_signal']
    return df

def _build_candles_df(instrument, count, granularity):
    params = {'count': count, 'granularity': granularity, 'price': 'M'}
    response = retry_api_call(ctx.instrument.candles, instrument, **params)
    candles = response.body['candles']
    rows = []
    for c in candles:
        if c.complete:
            rows.append({'time': pd.to_datetime(c.time), 'o': float(c.mid.o), 'h': float(c.mid.h), 'l': float(c.mid.l), 'c': float(c.mid.c), 'volume': int(c.volume)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    df['atr'] = (df['h'] - df['l']).rolling(ATR_PERIOD).mean()
    delta = df['c'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss
    df['rsi'] = 100 - 100 / (1 + rs)
    df = compute_adx(df, ADX_PERIOD)
    df = compute_macd(df, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    df['range'] = df['h'] - df['l']
    df['body'] = (df['c'] - df['o']).abs()
    df['body_ratio'] = df['body'] / df['range'].replace(0, pd.NA)
    if USE_VOLUME_FILTER:
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
    return df

def get_candles(instrument, count=300, granularity=EXECUTION_GRANULARITY):
    now = datetime.now(tz)
    cache_key = (instrument, granularity, count)
    if cache_key in _candle_cache and (now - _candle_cache[cache_key]['time']).total_seconds() < CANDLE_CACHE_TTL_SECONDS:
        return _candle_cache[cache_key]['df']
    df = _build_candles_df(instrument, count, granularity)
    _candle_cache[cache_key] = {'time': now, 'df': df}
    return df

def get_daily_loss_status(balance):
    try:
        realized = sum((float(t.get('pnl', 0)) for t in closed_trades_today))
    except:
        realized = 0.0
    unrealized = 0.0
    if active_trade:
        try:
            resp = ctx.pricing.get(ACCOUNT_ID, instruments=active_trade['pair'])
            pi = resp.body['prices'][0]
            bid = float(pi.bids[0].price)
            ask = float(pi.asks[0].price)
            current = bid if active_trade['direction'] == 'sell' else ask
            move = (current - active_trade['entry_price']) * abs(float(active_trade['units']))
            unrealized = -move if active_trade['direction'] == 'sell' else move
        except:
            unrealized = 0.0
    total_loss = realized + unrealized
    loss_pct = max(0.0, -total_loss / balance * 100) if balance > 0 else 0.0
    return (loss_pct, loss_pct >= DAILY_LOSS_LIMIT_PERCENT)

def setup_stop_and_target(df, direction, entry, pair_config, setup_type):
    atr = float(df['atr'].iloc[-1])
    swing = df.iloc[-4:-1]
    rr = SETUP_RR.get(setup_type.lower().replace(' ', '').replace('/', ''), 2.0)
    if direction == 'buy':
        structure_sl = float(swing['l'].min())
        raw_sl = min(structure_sl, entry - pair_config['ATR_MULTIPLIER'] * atr)
        if setup_type == 'breakout':
            raw_sl = min(structure_sl, entry - 1.15 * atr)
        risk = entry - raw_sl
        tp = entry + rr * risk
    else:
        structure_sl = float(swing['h'].max())
        raw_sl = max(structure_sl, entry + pair_config['ATR_MULTIPLIER'] * atr)
        if setup_type == 'breakout':
            raw_sl = max(structure_sl, entry + 1.15 * atr)
        risk = raw_sl - entry
        tp = entry - rr * risk
    sl_pips = risk / 0.0001
    if sl_pips < MIN_SL_PIPS or sl_pips > MAX_SL_PIPS:
        return None
    return (raw_sl, tp, sl_pips, atr)

def get_spread(instrument):
    response = retry_api_call(ctx.pricing.get, ACCOUNT_ID, instruments=instrument)
    price = response.body['prices'][0]
    return float(price.asks[0].price) - float(price.bids[0].price)

def has_open_position(instrument):
    try:
        response = retry_api_call(ctx.position.list, ACCOUNT_ID)
        for pos in response.body['positions']:
            if pos.instrument == instrument and (int(pos.long.units) != 0 or int(pos.short.units) != 0):
                return True
        return False
    except Exception as e:
        print(f'Position check failed: {e}')
        return False

def calculate_units(balance, sl_price_distance, instrument, risk_percent):
    risk_amount = balance * (risk_percent / 100.0)
    if sl_price_distance <= 0:
        return 0
    units = int(risk_amount / sl_price_distance * 0.98)
    return max(1000, units)

def get_account_balance(response):
    try:
        return float(response.body.account.balance)
    except AttributeError:
        return float(response.body['account'].balance)

def cancel_tp1_order():
    global active_trade
    if active_trade is None:
        return
    tp1_order_id = active_trade.get('tp1_order_id')
    if tp1_order_id:
        try:
            retry_api_call(ctx.order.cancel, ACCOUNT_ID, tp1_order_id)
            print(f'🧹 TP1 Limit {tp1_order_id} canceled.')
        except:
            pass
        active_trade['tp1_order_id'] = None
        active_trade['tp1_hit'] = True

def close_partial_position(units_to_close, expected_remaining=None):
    cancel_tp1_order()
    pair = active_trade['pair']
    direction = active_trade['direction']
    url = f'https://{OANDA_URL}/v3/accounts/{ACCOUNT_ID}/positions/{pair}/close'
    units_abs = str(abs(int(units_to_close)))
    field = 'longUnits' if direction == 'buy' else 'shortUnits'
    r = _oanda_http_retry('PUT', url, json_body={field: units_abs})
    if r is None or r.status_code != 200:
        if r is not None:
            print(f'⚠ {field} rejected {r.status_code}: {r.text[:150]}')
        print(f'↻ Fallback units pour partial {pair}')
        r = _oanda_http_retry('PUT', url, json_body={'units': units_abs})
    if r is None or r.status_code != 200:
        print(f'❌ Partial close failed {pair}')
        return False
    if expected_remaining is not None:
        try:
            check = retry_api_call(ctx.trade.get, ACCOUNT_ID, active_trade['trade_id'])
            server_units = int(check.body['trade'].currentUnits)
            if abs(server_units) != expected_remaining:
                print(f'❌ PARTIAL CHECK FAILED server={server_units} expected=±{expected_remaining}')
                send_telegram_message(f'🚨 Partial close NOT applied {pair}: server={server_units} expected=±{expected_remaining}')
                return False
            print(f'🔍 Verified server after partial: {server_units}')
        except Exception as e:
            print(f'⚠ Partial verification impossible: {e}')
    print(f'Partial close OK: {units_to_close} on {pair}')
    return True

def close_full_position_market():
    global active_trade
    if active_trade is None:
        return False
    cancel_tp1_order()
    pair = active_trade['pair']
    direction = active_trade['direction']
    url = f'https://{OANDA_URL}/v3/accounts/{ACCOUNT_ID}/positions/{pair}/close'
    field = 'longUnits' if direction == 'buy' else 'shortUnits'
    r = _oanda_http_retry('PUT', url, json_body={field: 'ALL'})
    if r is None or r.status_code != 200:
        if r is not None:
            print(f'⚠ {field}=ALL rejected {r.status_code}')
            print(f'↻ Fallback units=ALL {pair}')
            r = _oanda_http_retry('PUT', url, json_body={'units': 'ALL'})
    if r is not None and r.status_code == 200:
        print(f'Full close OK {pair}')
        return True
    print(f'❌ Full close failed {pair}')
    return False

def update_trade_sl_tp(trade_id, sl_price=None, tp_price=None):
    body = {}
    if sl_price is not None:
        body['stopLoss'] = {'price': f'{sl_price:.5f}'}
    if tp_price is not None:
        body['takeProfit'] = {'price': f'{tp_price:.5f}'}
    if not body:
        return False
    try:
        r = retry_api_call(ctx.trade.set_dependent_orders, ACCOUNT_ID, trade_id, **body)
        if getattr(r, 'status', None) != 200:
            print(f"⚠ set_dependent_orders status={getattr(r, 'status', None)} body={getattr(r, 'body', None)}")
            return False
    except Exception as e:
        print(f'❌ set_dependent_orders failed: {e}')
        return False
    if sl_price is not None:
        try:
            check = retry_api_call(ctx.trade.get, ACCOUNT_ID, trade_id)
            trade = check.body['trade']
            server_sl = None
            if getattr(trade, 'stopLossOrder', None) and trade.stopLossOrder:
                server_sl = float(trade.stopLossOrder.price)
            if server_sl is None or abs(server_sl - sl_price) > 5e-05:
                print(f'❌ SL CHECK FAILED server={server_sl} expected={sl_price:.5f}')
                send_telegram_message(f'🚨 SL NOT transmitted {trade_id}: server={server_sl} expected={sl_price:.5f}')
                return False
            print(f'🔍 Verified SL={server_sl:.5f}')
        except Exception as e:
            print(f'⚠ SL verification impossible: {e}')
    return True

def move_sl_to_be():
    """v2 Early Secure: fixed SL -> BE + 2 pips. Never tight trailing."""
    global active_trade
    if active_trade is None:
        return False
    entry = active_trade['entry_price']
    direction = active_trade['direction']
    offset = EARLY_SECURE_BE_OFFSET_PIPS * 0.0001
    new_sl = entry + offset if direction == 'buy' else entry - offset
    current_sl = active_trade.get('sl')
    if direction == 'buy' and current_sl is not None and (new_sl <= current_sl):
        return False
    if direction == 'sell' and current_sl is not None and (new_sl >= current_sl):
        return False
    if update_trade_sl_tp(active_trade['trade_id'], sl_price=new_sl):
        active_trade['sl'] = new_sl
        active_trade['be_triggered'] = True
        live_log(f'🛡 Early Secure (Phase 1) : SL -> BE+{EARLY_SECURE_BE_OFFSET_PIPS:.0f}p = {new_sl:.5f}', force=True)
        return True
    return False

def set_trailing_atr(atr_mult, allow_widen=False):
    """ATR trailing, only after TP1. Returns True if applied."""
    global active_trade
    if active_trade is None or active_trade.get('phase', 0) < 3:
        return False
    atr = active_trade.get('atr') or 0
    if not atr or atr <= 0:
        return False
    ts_pips = max(atr_mult * atr / 0.0001, TRAILING_MIN_PIPS)
    try:
        trade_json = fetch_trade_raw(active_trade['trade_id'])
        current_ts = None
        if trade_json:
            ts_order = trade_json.get('trailingStopLossOrder')
            if ts_order and ts_order.get('trailingStopValue'):
                try:
                    current_ts = abs(float(ts_order.get('trailingStopValue'))) / 0.0001
                except:
                    pass
        if not allow_widen and current_ts is not None and (ts_pips >= current_ts):
            return False
        r = retry_api_call(ctx.trade.set_dependent_orders, ACCOUNT_ID, active_trade['trade_id'], **{'trailingStopLoss': {'distance': f'{ts_pips * 0.0001:.5f}'}})
        if getattr(r, 'status', None) != 200:
            print(f"⚠ TS ATR status={getattr(r, 'status', None)}")
            return False
        active_trade['trailing_active'] = True
        live_log(f"🔄 Trailing ATR -> {ts_pips:.1f}p (x{atr_mult}) sur {active_trade['pair']}")
        return True
    except Exception as e:
        print(f'❌ TS ATR failed: {e}')
        return False

def lock_ts_to_breakeven():
    global active_trade
    if active_trade is None:
        return False
    pair = active_trade['pair']
    direction = active_trade['direction']
    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
        pi = resp.body['prices'][0]
        bid = float(pi.bids[0].price)
        ask = float(pi.asks[0].price)
        current_price = bid if direction == 'sell' else ask
    except Exception as e:
        print(f'⚠ price for TS lock: {e}')
        return False
    entry = active_trade['entry_price']
    distance = abs(current_price - entry)
    if distance <= 0:
        return False
    buffer = 0.5 * 0.0001
    ts_distance = distance - buffer if distance > buffer else distance
    try:
        r = retry_api_call(ctx.trade.set_dependent_orders, ACCOUNT_ID, active_trade['trade_id'], **{'trailingStopLoss': {'distance': f'{ts_distance:.5f}'}})
        if getattr(r, 'status', None) != 200:
            print(f"⚠ TS lock status={getattr(r, 'status', None)}")
            return False
    except Exception as e:
        print(f'❌ TS lock failed: {e}')
        return False
    print(f'🔒 TS locked to BE {pair} Distance={ts_distance:.5f}')
    send_telegram_message(f'🔒 <b>Stagnation Lock</b> · {pair} {direction.upper()}\nPrice stagnant {STAGNATION_MINUTES}m. Trailing Stop -> <b>Breakeven</b>.')
    live_log(f'🔒 Stagnation Lock (Phase 3) : TS -> BE sur {pair}', force=True)
    active_trade['be_triggered'] = True
    save_status_json(force=True)
    return True

def check_adverse_regime_closed(direction, current_price, df):
    """v2: reads ONLY the last CLOSED H1 candle (iloc[-2] if -1 is in progress, else -1 closed via cache). REGIME_CONFIRM_BARS required via streak handled in manage."""
    if df is None or df.empty:
        return (False, [], 0)
    try:
        c = df.iloc[-1]
    except:
        return (False, [], 0)
    for k in ['ema50', 'plus_di', 'minus_di', 'macd_line', 'macd_signal']:
        if k not in c or pd.isna(c[k]):
            return (False, [], 0)
    signals = []
    if direction == 'buy':
        if current_price < float(c['ema50']):
            signals.append('Price<EMA50')
        if float(c['minus_di']) > float(c['plus_di']):
            signals.append('-DI>+DI')
        if float(c['macd_line']) < float(c['macd_signal']):
            signals.append('MACD flip')
    else:
        if current_price > float(c['ema50']):
            signals.append('Price>EMA50')
        if float(c['plus_di']) > float(c['minus_di']):
            signals.append('+DI>-DI')
        if float(c['macd_line']) > float(c['macd_signal']):
            signals.append('MACD flip')
    return (len(signals) >= REGIME_ADVERSE_MIN_SIGNALS, signals, len(signals))

def manage_active_trade():
    global active_trade, _regime_adverse_streak
    if active_trade is None:
        return
    phase = active_trade.get('phase', 0)
    tp1_order_id = active_trade.get('tp1_order_id')
    if tp1_order_id and (not active_trade.get('tp1_hit', False)):
        try:
            o_check = retry_api_call(ctx.order.get, ACCOUNT_ID, tp1_order_id)
            state = getattr(o_check.body['order'], 'state', 'PENDING')
            if state in ('FILLED', 'CANCELLED', 'TRIGGERED'):
                active_trade['tp1_hit'] = True
                active_trade['phase'] = 3
                live_log(f"🎯 TP1 reached {active_trade['pair']} — Entering Phase 3 (Runner)", force=True)
                send_telegram_message(f"🎯 TP1 reached on {active_trade['pair']} (server-side). Runner continues.")
                save_status_json(force=True)
        except Exception as e:
            if '404' in str(e) or 'not found' in str(e).lower():
                if not active_trade.get('tp1_hit', False):
                    active_trade['tp1_hit'] = True
                    active_trade['phase'] = 3
                    live_log(f"🎯 TP1 reached {active_trade['pair']} — Phase 3", force=True)
                    send_telegram_message(f"🎯 TP1 reached on {active_trade['pair']}. Runner continues.")
                    save_status_json(force=True)
    try:
        trade_json = fetch_trade_raw(active_trade['trade_id'])
        if trade_json:
            (new_sl, sl_source) = extract_sl_from_trade_json(trade_json)
            if new_sl is not None:
                active_trade['sl'] = new_sl
            cu = trade_json.get('currentUnits')
            if cu is not None:
                try:
                    active_trade['units'] = int(cu)
                except:
                    pass
            entry = active_trade['entry_price']
            direction = active_trade['direction']
            tolerance = BE_TOLERANCE_PIPS * 0.0001
            if new_sl is not None:
                be_reached = new_sl >= entry - tolerance if direction == 'buy' else new_sl <= entry + tolerance
                if be_reached and (not active_trade.get('be_triggered', False)):
                    send_telegram_message(f"🛡 <b>Break-even reached</b>\nPair: {active_trade['pair']}\nEntry: {entry:.5f}\nSL: {new_sl:.5f}")
                    active_trade['be_triggered'] = True
                    save_status_json(force=True)
        else:
            print('⚠ fetch_trade_raw None – keeping previous SL')
    except Exception as e:
        print(f'⚠ refresh state failed: {e}')
    pair = active_trade['pair']
    direction = active_trade['direction']
    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
        pi = resp.body['prices'][0]
        bid = float(pi.bids[0].price)
        ask = float(pi.asks[0].price)
        current_price = bid if direction == 'sell' else ask
    except:
        return
    entry = active_trade['entry_price']
    setup_type = active_trade.get('setup_type', '')
    profit_pips_now = (current_price - entry) / 0.0001 if direction == 'buy' else (entry - current_price) / 0.0001
    if profit_pips_now > active_trade.get('peak_profit_pips', 0.0):
        active_trade['peak_profit_pips'] = profit_pips_now
        active_trade['last_peak_time'] = datetime.now(tz).isoformat()
    init_risk = active_trade.get('initial_risk', 0)
    init_risk_pips = init_risk / 0.0001 if init_risk > 0 else 0
    if phase in (0, 1) and (not active_trade.get('early_secure_done', False)):
        if init_risk > 0 and profit_pips_now >= EARLY_SECURE_R * init_risk / 0.0001:
            if move_sl_to_be():
                active_trade['early_secure_done'] = True
                active_trade['phase'] = 1
                send_telegram_message(f'🛡 <b>Early Secure</b> · {pair} {direction.upper()}\nProfit {profit_pips_now:+.1f} pips · SL -> BE+{EARLY_SECURE_BE_OFFSET_PIPS:.0f}p (Phase 1). Trailing still OFF before TP1.')
                save_status_json(force=True)
    if active_trade.get('tp1_hit', False):
        active_trade['phase'] = 3
        if not active_trade.get('trailing_active', False):
            set_trailing_atr(TRAILING_ATR_MULT, allow_widen=False)
        if not active_trade.get('early_widen_done', False) and init_risk > 0 and (profit_pips_now >= EARLY_WIDEN_R * init_risk / 0.0001):
            if set_trailing_atr(EARLY_WIDEN_ATR_MULT, allow_widen=True):
                active_trade['early_widen_done'] = True
                send_telegram_message(f'📈 <b>Early Widen</b> · {pair} {direction.upper()}\nProfit {profit_pips_now:+.1f} pips (1,0R) — Trailing widened to {EARLY_WIDEN_ATR_MULT}x ATR (Phase 3)')
                save_status_json(force=True)
        if not active_trade.get('be_triggered', False) or True:
            last_peak_str = active_trade.get('last_peak_time')
            if last_peak_str and (not active_trade.get('stagnation_done', False)):
                try:
                    last_peak_dt = datetime.fromisoformat(last_peak_str.replace('Z', '+00:00')).astimezone(tz)
                    time_since_peak = (datetime.now(tz) - last_peak_dt).total_seconds() / 60.0
                    if time_since_peak >= STAGNATION_MINUTES:
                        print(f'⏳ Stagnation {time_since_peak:.0f}m. Lock TS to BE...')
                        if lock_ts_to_breakeven():
                            active_trade['stagnation_done'] = True
                except Exception as e:
                    print(f'⚠ last_peak parse: {e}')
        tp2 = active_trade.get('tp2')
        if tp2 is not None and setup_type in TP2_WIDEN_SETUPS and (not active_trade.get('tp2_widened', False)):
            tp2_distance = abs(tp2 - entry)
            trigger_distance = TP2_WIDEN_TRIGGER * tp2_distance
            reached = current_price >= entry + trigger_distance if direction == 'buy' else current_price <= entry - trigger_distance
            if reached:
                widen_amount = (TP2_WIDEN_FACTOR - 1.0) * tp2_distance
                new_tp2 = tp2 + widen_amount if direction == 'buy' else tp2 - widen_amount
                if update_trade_sl_tp(active_trade['trade_id'], tp_price=new_tp2):
                    old_tp2 = tp2
                    active_trade['tp2'] = new_tp2
                    active_trade['tp2_widened'] = True
                    new_rr = abs(new_tp2 - entry) / init_risk if init_risk > 0 else 0
                    old_rr = abs(old_tp2 - entry) / init_risk if init_risk > 0 else 0
                    msg = f'🎯 <b>TP2 widened</b>\nPair: {pair}\nSetup: {setup_type.upper()}\nOld TP2: {old_tp2:.5f} ({old_rr:.1f}R)\nNew TP2: {new_tp2:.5f} ({new_rr:.1f}R)'
                    send_telegram_message(msg)
                    live_log(msg, force=True)
                    save_status_json(force=True)
        tp2_initial = active_trade.get('tp2_initial')
        if tp2_initial is not None and active_trade.get('tp2_widened', False) and (not active_trade.get('tp2_initial_locked', False)):
            offset = TP2_INITIAL_LOCK_OFFSET_PIPS * 0.0001
            reached = current_price >= tp2_initial + offset if direction == 'buy' else current_price <= tp2_initial - offset
            if reached:
                current_sl = active_trade.get('sl', 0) or 0
                better = tp2_initial > current_sl if direction == 'buy' else tp2_initial < current_sl
                if better:
                    if update_trade_sl_tp(active_trade['trade_id'], sl_price=tp2_initial):
                        old_sl = current_sl
                        active_trade['sl'] = tp2_initial
                        active_trade['tp2_initial_locked'] = True
                        rr_floor = abs(tp2_initial - entry) / init_risk if init_risk > 0 else 0
                        msg = f'🔐 <b>TP2 initial locked</b> · {pair} {direction.upper()} · {setup_type.upper()}\nSL: {old_sl:.5f} → {tp2_initial:.5f}\nRR floor: {rr_floor:.1f}R'
                        send_telegram_message(msg)
                        live_log(msg, force=True)
                        save_status_json(force=True)
                else:
                    active_trade['tp2_initial_locked'] = True
    now_check = datetime.now(tz)
    pre_tp1_protection_done = active_trade.get('regime_adverse_handled', False) or active_trade.get('time_lock_done', False)
    if not pre_tp1_protection_done and (not active_trade.get('tp1_hit', False)):
        tp1_distance_pips = TP1_R_MULT * init_risk / 0.0001 if init_risk > 0 else 0
        peak = active_trade.get('peak_profit_pips', 0.0)
        if tp1_distance_pips > 0 and peak / tp1_distance_pips >= REGIME_ADVERSE_MIN_PEAK_FRACTION:
            try:
                df_regime = get_candles(pair, count=EXECUTION_CANDLES, granularity=EXECUTION_GRANULARITY)
            except Exception as e:
                print(f'⚠ Regime candles: {e}')
                df_regime = None
            (is_adverse, signals_list, signal_count) = check_adverse_regime_closed(direction, current_price, df_regime)
            if is_adverse:
                _regime_adverse_streak += 1
            else:
                _regime_adverse_streak = 0
            if _regime_adverse_streak >= REGIME_CONFIRM_BARS:
                _regime_adverse_streak = 0
                units_abs = abs(int(active_trade['units']))
                partial_units = max(1000, int(units_abs * REGIME_ADVERSE_CLOSE_PCT))
                remaining = units_abs - partial_units
                peak_frac = peak / tp1_distance_pips
                if partial_units >= units_abs or remaining < 1000:
                    if close_full_position_market():
                        send_telegram_message(f'⚠ <b>Adverse regime (full close, confirmed {REGIME_CONFIRM_BARS} candles)</b> · {pair}\nSetup {setup_type.upper()} · {signal_count}/3 · peak {peak:.1f}p ({peak_frac:.0%} TP1)')
                        live_log(f'⚠ Adverse Regime confirmed - Full close {pair}', force=True)
                        active_trade['regime_adverse_handled'] = True
                        time.sleep(2)
                        check_closed_trade()
                        return
                elif close_partial_position(partial_units, expected_remaining=remaining):
                    active_trade['units'] = remaining if direction == 'buy' else -remaining
                    offset = REGIME_ADVERSE_SL_OFFSET_PIPS * 0.0001
                    new_sl = entry + offset if direction == 'buy' else entry - offset
                    if update_trade_sl_tp(active_trade['trade_id'], sl_price=new_sl):
                        active_trade['sl'] = new_sl
                        active_trade['regime_adverse_handled'] = True
                        active_trade['be_triggered'] = True
                        partial_pnl_usd = (current_price - entry) * partial_units if direction == 'buy' else (entry - current_price) * partial_units
                        usd_cad = get_usd_cad_rate()
                        partial_pnl_cad = partial_pnl_usd * usd_cad
                        msg = f"⚠ <b>Adverse regime (confirmed)</b> · {pair} {direction.upper()} · {setup_type.upper()}\n{signal_count}/3: {' · '.join(signals_list)}\nPeak {peak:+.1f}p ({peak_frac:.0%} TP1) · Now {profit_pips_now:+.1f}\nClosed 67% @ {profit_pips_now:+.1f}p → {partial_pnl_cad:+.2f} CAD\nRunner 33% @ SL BE+{REGIME_ADVERSE_SL_OFFSET_PIPS:.0f}p"
                        send_telegram_message(msg)
                        live_log(msg, force=True)
                        save_status_json(force=True)
                    else:
                        active_trade['regime_adverse_handled'] = True
    window_start = now_check.replace(hour=TIME_LOCK_WINDOW_START_H, minute=TIME_LOCK_WINDOW_START_M, second=0, microsecond=0)
    window_end = now_check.replace(hour=TIME_LOCK_WINDOW_END_H, minute=TIME_LOCK_WINDOW_END_M, second=0, microsecond=0)
    if window_start <= now_check < window_end and (not active_trade.get('time_lock_done', False)) and (not active_trade.get('regime_adverse_handled', False)) and (not active_trade.get('tp1_hit', False)):
        opened_at_str = active_trade.get('opened_at')
        trade_age_min = None
        age_at_11am_min = None
        if opened_at_str:
            try:
                opened_dt = datetime.fromisoformat(opened_at_str.replace('Z', '+00:00')).astimezone(tz)
                trade_age_min = (now_check - opened_dt).total_seconds() / 60.0
                eleven_am = now_check.replace(hour=11, minute=0, second=0, microsecond=0)
                age_at_11am_min = (eleven_am - opened_dt).total_seconds() / 60.0
            except:
                pass
        if age_at_11am_min is not None and age_at_11am_min >= TIME_LOCK_MIN_TRADE_AGE_MIN:
            if init_risk > 0:
                tp1_distance_pips = TP1_R_MULT * init_risk / 0.0001
                peak = active_trade.get('peak_profit_pips', 0.0)
                peak_fraction = peak / tp1_distance_pips if tp1_distance_pips > 0 else 0.0
                retrace_fraction = (peak - profit_pips_now) / peak if peak > 0 else 0.0
                if TIME_LOCK_PEAK_MIN_FRACTION <= peak_fraction <= TIME_LOCK_PEAK_MAX_FRACTION and retrace_fraction >= TIME_LOCK_RETRACE_MIN:
                    units_abs = abs(int(active_trade['units']))
                    partial_units = max(1000, int(units_abs * TIME_LOCK_CLOSE_PCT))
                    remaining = units_abs - partial_units
                    if partial_units >= units_abs or remaining < 1000:
                        if close_full_position_market():
                            send_telegram_message(f'🔒 <b>Time-lock (full)</b> · {pair}\nSetup {setup_type.upper()} · peak {peak:.1f}p ({peak_fraction:.0%} TP1) · retrace {retrace_fraction:.0%}')
                            live_log(f'🔒 Time-lock full {pair}', force=True)
                            active_trade['time_lock_done'] = True
                            time.sleep(2)
                            check_closed_trade()
                            return
                    elif close_partial_position(partial_units, expected_remaining=remaining):
                        active_trade['units'] = remaining if direction == 'buy' else -remaining
                        offset = TIME_LOCK_SL_OFFSET_PIPS * 0.0001
                        new_sl = entry + offset if direction == 'buy' else entry - offset
                        if update_trade_sl_tp(active_trade['trade_id'], sl_price=new_sl):
                            active_trade['sl'] = new_sl
                            active_trade['time_lock_done'] = True
                            active_trade['be_triggered'] = True
                            partial_pnl_usd = (current_price - entry) * partial_units if direction == 'buy' else (entry - current_price) * partial_units
                            usd_cad = get_usd_cad_rate()
                            partial_pnl_cad = partial_pnl_usd * usd_cad
                            msg = f'🔒 <b>Time-lock</b> · {pair} {direction.upper()} · {setup_type.upper()}\nPeak {peak:.1f}p ({peak_fraction:.0%} TP1) · Retrace {retrace_fraction:.0%} · {int(trade_age_min or 0)}m\nClosed 67% @ {profit_pips_now:+.1f}p → {partial_pnl_cad:+.2f} CAD\nRunner 33% @ SL BE+{TIME_LOCK_SL_OFFSET_PIPS:.0f}p'
                            send_telegram_message(msg)
                            live_log(msg, force=True)
                            save_status_json(force=True)
                        else:
                            active_trade['time_lock_done'] = True
    if now_check.hour == CHECKPOINT_HOUR and now_check.minute == CHECKPOINT_MINUTE and (not active_trade.get('checkpoint_sent', False)) and (not active_trade.get('tp1_hit', False)):
        tp1_distance_pips = TP1_R_MULT * init_risk / 0.0001 if init_risk > 0 else 0
        peak = active_trade.get('peak_profit_pips', 0.0)
        peak_frac = peak / tp1_distance_pips if tp1_distance_pips > 0 else 0.0
        line2 = f'Peak {peak:+.1f}p ({peak_frac:.0%} TP1) · Now {profit_pips_now:+.1f} · Retrace {max(0.0, (peak - profit_pips_now) / peak):.0%}' if peak > 0 else f'Peak {peak:+.1f}p ({peak_frac:.0%} TP1) · Now {profit_pips_now:+.1f}'
        msg = f"⏰ <b>11:00 checkpoint</b> · {pair} {direction.upper()} · {setup_type.upper()}\n{line2}\nPhase {active_trade.get('phase', 0)}"
        send_telegram_message(msg)
        live_log(msg)
        active_trade['checkpoint_sent'] = True
        save_status_json(force=True)

def compute_quality_score(signal, c, df, instrument, config, atr):
    (price, sl, tp, sl_pips, direction, setup_type, risk_pct) = signal
    adx_score = min(c['adx'] / 50.0, 1.0) * 20
    di_spread = abs(c['plus_di'] - c['minus_di'])
    di_score = min(di_spread / 30.0, 1.0) * 15
    if direction == 'buy':
        (ideal_low, ideal_high) = (55, 65)
    else:
        (ideal_low, ideal_high) = (35, 45)
    rsi = c['rsi']
    rsi_score = 15 if ideal_low <= rsi <= ideal_high else max(0, rsi / ideal_low * 15) if rsi < ideal_low else max(0, (100 - rsi) / (100 - ideal_high) * 15)
    body_ratio = c['body_ratio'] if not pd.isna(c['body_ratio']) else 0.0
    body_score = min(body_ratio, 1.0) * 20
    rejection_score = 5
    if setup_type in ['Pullback', 'Pin Bar', 'Support', 'Resistance']:
        rejection = (c['o'] - c['l']) / c['range'] if direction == 'buy' and c['range'] > 0 else (c['h'] - c['o']) / c['range'] if c['range'] > 0 else 0
        rejection_score = min(rejection * 2, 1.0) * 10
    elif setup_type == 'Engulfing':
        rejection_score = 8
    elif setup_type == 'Breakout':
        rejection_score = 6
    ema_proximity_score = 5
    if setup_type == 'Pullback':
        dist_ema = abs(c['c'] - c['ema50']) / atr if atr > 0 else 99
        ema_proximity_score = 10 if dist_ema < 0.2 else min(max(0, 10 * (1 - (dist_ema - 0.2) / 5)), 10)
    sl_score = (1 - min(max((sl_pips - MIN_SL_PIPS) / (MAX_SL_PIPS - MIN_SL_PIPS), 0), 1)) * 10 if MIN_SL_PIPS < MAX_SL_PIPS else 5
    return min(max(adx_score + di_score + rsi_score + body_score + rejection_score + ema_proximity_score + sl_score, 0), 100)

def _best_hypothetical_setup(c, df, instrument, config, atr, h1_up, h1_down, sentiment):
    best = None
    catalog = [('Pullback', RISK_PULLBACK, 'pullback'), ('Breakout', RISK_BREAKOUT, 'breakout'), ('Pin Bar', RISK_PINBAR, 'pinbar'), ('Inside Bar', RISK_INSIDE_BAR, 'insidebar'), ('Engulfing', RISK_ENGULFING, 'engulfing'), ('Momentum', RISK_MOMENTUM_CONTINU, 'momentum'), ('Trend Breakout', RISK_TREND_BREAKOUT, 'trendbreakout'), ('ORB', RISK_ORB, 'orb'), ('Counter Trend Breakout', RISK_COUNTER_TREND_BREAKOUT, 'countertrendbreakout'), ('Support', RISK_SUPPORT_RESISTANCE, 'sr'), ('Resistance', RISK_SUPPORT_RESISTANCE, 'sr')]
    for direction in ('buy', 'sell'):
        if direction == 'buy' and (not (h1_up and sentiment != 'bearish')):
            continue
        if direction == 'sell' and (not (h1_down and sentiment != 'bullish')):
            continue
        for (name, risk, key) in catalog:
            try:
                levels = setup_stop_and_target(df, direction, c['c'], config, key)
                if not levels:
                    continue
                (sl, tp, sl_pips, _) = levels
                sig = (c['c'], sl, tp, sl_pips, direction, name, risk)
                score = compute_quality_score(sig, c, df, instrument, config, atr)
                if best is None or score > best[0]:
                    best = (score, name, direction)
            except:
                continue
    return best

def get_orb_range_exact(instrument):
    """ORB EXACT 7:00-8:00 Toronto time, on M15 candles. Returns (high, low) or (None, None)."""
    try:
        params = {'count': 200, 'granularity': 'M15', 'price': 'M'}
        response = retry_api_call(ctx.instrument.candles, instrument, **params)
        highs = []
        lows = []
        for c in response.body['candles']:
            if not c.complete:
                continue
            try:
                dt_utc = pd.to_datetime(c.time)
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.tz_localize('UTC')
                dt_local = dt_utc.tz_convert(TIMEZONE)
            except Exception:
                continue
            today = datetime.now(tz).date()
            if dt_local.date() == today and dt_local.hour == 7 and (dt_local.minute in (0, 15, 30, 45)):
                highs.append(float(c.mid.h))
                lows.append(float(c.mid.l))
        if len(highs) == 4 and len(lows) == 4:
            return (max(highs), min(lows))
        return (None, None)
    except Exception as e:
        print(f'⚠ ORB exact failed {instrument}: {e}')
        return (None, None)

def check_signal(df, instrument):
    if len(df) < 220:
        return (False, 0, 0, 0, 0, None, None, 0, 0.0, 'Not enough candles')
    c = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3] if len(df) >= 3 else prev
    config = PAIR_CONFIG[instrument]
    atr = float(c['atr'])
    if any((pd.isna(c[x]) for x in ['atr', 'ema50', 'ema200', 'rsi', 'adx', 'plus_di', 'minus_di', 'macd_line', 'macd_signal'])):
        return (False, 0, 0, 0, 0, None, None, 0, 0.0, 'Missing indicators')
    h1_up = c['ema50'] > c['ema200'] and c['c'] > c['ema50']
    h1_down = c['ema50'] < c['ema200'] and c['c'] < c['ema50']
    macd_bullish = c['macd_line'] > c['macd_signal'] - MACD_TOLERANCE
    macd_bearish = c['macd_line'] < c['macd_signal'] + MACD_TOLERANCE
    adx_ok = c['adx'] >= config['ADX_THRESHOLD']
    rsi_ok = 30 < c['rsi'] < 70
    sentiment = news_sentiment_filter.get(instrument, 'neutral')
    support = df['l'].tail(20).min()
    resistance = df['h'].tail(20).max()
    global orb_range
    now = datetime.now(tz)
    today_str = now.strftime('%Y-%m-%d')
    if orb_range.get('date') != today_str:
        orb_range = {'high': None, 'low': None, 'recorded': False, 'date': today_str}
    if not orb_range['recorded'] and now.hour >= 8:
        (_orb_high, _orb_low) = get_orb_range_exact(instrument)
        if _orb_high is not None and _orb_low is not None and (_orb_high > _orb_low):
            orb_range['high'] = _orb_high
            orb_range['low'] = _orb_low
            orb_range['recorded'] = True
            live_log(f"📦 ORB EXACT {instrument} : 7h-8h Toronto high={_orb_high:.5f} low={_orb_low:.5f} (M15 x4, kept until midnight)")
    signals = []

    def add(direction, cond, key, name, risk):
        if cond:
            levels = setup_stop_and_target(df, direction, c['c'], config, key)
            if levels:
                (sl, tp, sl_pips, _) = levels
                signals.append((c['c'], sl, tp, sl_pips, direction, name, risk))
    inside_prev = prev['h'] < prev2['h'] and prev['l'] > prev2['l']
    if h1_up and sentiment != 'bearish':
        add('buy', c['o'] < prev['l'] and c['c'] > prev['h'] and (c['c'] > c['o']), 'engulfing', 'Engulfing', RISK_ENGULFING)
        add('buy', c['o'] - c['l'] > (c['h'] - c['c']) * 2 and c['c'] > c['o'], 'pinbar', 'Pin Bar', RISK_PINBAR)
        add('buy', c['o'] - c['l'] > (c['h'] - c['c']) * 2 and c['c'] > c['o'] and (c['l'] <= c['ema50'] <= c['h'] or (c['c'] > c['ema50'] and c['o'] < c['ema50'])), 'pullback', 'Pullback', RISK_PULLBACK)
        add('buy', c['l'] <= support * 1.001 and c['c'] > support, 'sr', 'Support', RISK_SUPPORT_RESISTANCE)
        if len(df) >= BREAKOUT_LOOKBACK + 5:
            box = df.iloc[-(BREAKOUT_LOOKBACK + 2):-2]
            res = float(box['h'].max())
            buffer = BREAKOUT_BUFFER_ATR * atr
            add('buy', prev['c'] > res + buffer and c['l'] <= res + buffer and (c['c'] > res), 'breakout', 'Breakout', RISK_BREAKOUT)
        if inside_prev:
            add('buy', c['c'] > prev2['h'], 'insidebar', 'Inside Bar', RISK_INSIDE_BAR)
        add('buy', c['c'] > c['ema50'] and c['adx'] > 25, 'momentum', 'Momentum', RISK_MOMENTUM_CONTINU)
        if orb_range['recorded'] and now.hour >= TRADING_HOURS_START + 1:
            add('buy', c['c'] > orb_range['high'], 'orb', 'ORB', RISK_ORB)
        add('buy', c['c'] > df['h'].tail(6).iloc[:-1].max() and c['adx'] > 30 and (c['body_ratio'] >= 0.3), 'trendbreakout', 'Trend Breakout', RISK_TREND_BREAKOUT)
    if h1_down and sentiment != 'bearish':
        add('buy', c['c'] > df['h'].tail(6).iloc[:-1].max() and c['adx'] > 20 and (c['body_ratio'] >= 0.3), 'countertrendbreakout', 'Counter Trend Breakout', RISK_COUNTER_TREND_BREAKOUT)
    if h1_down and sentiment != 'bullish':
        add('sell', c['o'] > prev['h'] and c['c'] < prev['l'] and (c['c'] < c['o']), 'engulfing', 'Engulfing', RISK_ENGULFING)
        add('sell', c['h'] - c['o'] > (c['c'] - c['l']) * 2 and c['c'] < c['o'], 'pinbar', 'Pin Bar', RISK_PINBAR)
        add('sell', c['h'] - c['o'] > (c['c'] - c['l']) * 2 and c['c'] < c['o'] and (c['l'] <= c['ema50'] <= c['h'] or (c['c'] < c['ema50'] and c['o'] > c['ema50'])), 'pullback', 'Pullback', RISK_PULLBACK)
        add('sell', c['h'] >= resistance * 0.999 and c['c'] < resistance, 'sr', 'Resistance', RISK_SUPPORT_RESISTANCE)
        if len(df) >= BREAKOUT_LOOKBACK + 5:
            box = df.iloc[-(BREAKOUT_LOOKBACK + 2):-2]
            sup = float(box['l'].min())
            buffer = BREAKOUT_BUFFER_ATR * atr
            add('sell', prev['c'] < sup - buffer and c['h'] >= sup - buffer and (c['c'] < sup), 'breakout', 'Breakout', RISK_BREAKOUT)
        if inside_prev:
            add('sell', c['c'] < prev2['l'], 'insidebar', 'Inside Bar', RISK_INSIDE_BAR)
        add('sell', c['c'] < c['ema50'] and c['adx'] > 25, 'momentum', 'Momentum', RISK_MOMENTUM_CONTINU)
        if orb_range['recorded'] and now.hour >= TRADING_HOURS_START + 1:
            add('sell', c['c'] < orb_range['low'], 'orb', 'ORB', RISK_ORB)
        add('sell', c['c'] < df['l'].tail(6).iloc[:-1].min() and c['adx'] > 30 and (c['body_ratio'] >= 0.3), 'trendbreakout', 'Trend Breakout', RISK_TREND_BREAKOUT)
    if h1_up and sentiment != 'bullish':
        add('sell', c['c'] < df['l'].tail(6).iloc[:-1].min() and c['adx'] > 20 and (c['body_ratio'] >= 0.3), 'countertrendbreakout', 'Counter Trend Breakout', RISK_COUNTER_TREND_BREAKOUT)
    filtered = []
    for sig in signals:
        (_, _, _, _, direction, _, _) = sig
        if not adx_ok:
            continue
        if direction == 'buy' and (not (macd_bullish and rsi_ok)):
            continue
        if direction == 'sell' and (not (macd_bearish and rsi_ok)):
            continue
        filtered.append(sig)
    signals = filtered
    if signals:
        scored = [(compute_quality_score(sig, c, df, instrument, config, atr), sig) for sig in signals]
        scored.sort(key=lambda x: x[0], reverse=True)
        (best_score, best_signal) = scored[0]
        (price, sl, tp, sl_pips, direction, setup_type, risk_pct) = best_signal
        return (True, price, sl, tp, sl_pips, direction, setup_type, risk_pct, best_score, f'{setup_type} selected (score {best_score:.1f})')
    buy_reasons = []
    sell_reasons = []
    if not h1_up:
        buy_reasons.append('H1 not up')
    if h1_up and sentiment == 'bearish':
        buy_reasons.append('Sentiment bearish')
    if not h1_down:
        sell_reasons.append('H1 not down')
    if h1_down and sentiment == 'bullish':
        sell_reasons.append('Sentiment bullish')
    if not adx_ok:
        buy_reasons.append(f"ADX < {config['ADX_THRESHOLD']}")
        sell_reasons.append(f"ADX < {config['ADX_THRESHOLD']}")
    if not rsi_ok:
        buy_reasons.append(f"RSI {c['rsi']:.1f} outside 30-70")
        sell_reasons.append(f"RSI {c['rsi']:.1f} outside 30-70")
    if not macd_bullish:
        buy_reasons.append('MACD not bullish')
    if not macd_bearish:
        sell_reasons.append('MACD not bearish')
    if not buy_reasons:
        buy_reasons.append('No BUY setup')
    if not sell_reasons:
        sell_reasons.append('No SELL setup')
    diag_str = ''
    try:
        diag = _best_hypothetical_setup(c, df, instrument, config, atr, h1_up, h1_down, sentiment)
        if diag is not None:
            diag_str = f' [Best hypothetical: {diag[1]} {diag[2].upper()} score={diag[0]:.1f}]'
    except Exception as e:
        diag_str = f' [Diagnostic error: {e}]'
    return (False, 0, 0, 0, 0, None, None, 0, 0.0, f"{', '.join(buy_reasons)} | {', '.join(sell_reasons)}{diag_str}")

def check_future_news_and_alert():
    now = datetime.now(tz)
    events = get_high_impact_news()
    future = [e for e in events if e['time'] > now and e['time'] - now < timedelta(hours=NEWS_CHECK_FUTURE_HOURS)]
    if future:
        msg = '⚠ <b>Upcoming high-impact news:</b>\n'
        for e in future:
            msg += f"• {e['title']} at {e['time'].strftime('%H:%M')} ({e['time'].strftime('%a %d %b')})\n"
        msg += '\nPlease close any open positions manually before market close.'
        send_telegram_message(msg)
        print('Future news alert sent.')

def recover_recent_closed_trades(hours=24):
    global closed_trades_today
    try:
        resp = retry_api_call(ctx.trade.list, ACCOUNT_ID, state='CLOSED', count=100)
        closed = resp.body.get('trades', [])
    except Exception as e:
        print(f'⚠ Recovery closed: {e}')
        return
    now_mtl = datetime.now(tz)
    cutoff = now_mtl.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)
    existing = {(t.get('pair'), t.get('time'), t.get('entry')) for t in closed_trades_today}
    added = 0
    for t in closed:
        try:
            close_time_str = str(getattr(t, 'closeTime', ''))
            if not close_time_str:
                continue
            close_time = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
            if close_time < cutoff:
                continue
            pair = t.instrument
            entry = float(t.price)
            units = int(getattr(t, 'initialUnits', getattr(t, 'currentUnits', 0)))
            realized = float(getattr(t, 'realizedPL', 0))
            direction = 'buy' if units > 0 else 'sell'
            units_abs = abs(units)
            close_price = float(t.averageClosePrice) if getattr(t, 'averageClosePrice', None) else float(t.closePrice) if getattr(t, 'closePrice', None) else (entry + realized / units_abs if direction == 'buy' else entry - realized / units_abs) if units_abs > 0 else entry
            sl_price = float(t.stopLossOrder.price) if getattr(t, 'stopLossOrder', None) else None
            init_risk = abs(entry - sl_price) if sl_price else 0
            r_mult = ((close_price - entry) / init_risk if direction == 'buy' else (entry - close_price) / init_risk) if init_risk > 0 else 0
            usd_cad = get_usd_cad_rate()
            time_str = close_time.astimezone(tz).strftime('%H:%M:%S')
            key = (pair, time_str, entry)
            if key in existing:
                continue
            closed_trades_today.append({'pair': pair, 'type': 'Buy' if direction == 'buy' else 'Sell', 'setup': 'recovered', 'pnl': round(realized, 2), 'pnl_usd': round(realized / usd_cad, 2) if usd_cad > 0 else round(realized, 2), 'time': time_str, 'r_multiple': round(r_mult, 2), 'units': units_abs, 'entry': entry, 'exit': close_price, 'score': None})
            existing.add(key)
            added += 1
        except Exception as e:
            print(f'⚠ Recovery parse: {e}')
            continue
    if added:
        print(f'♻ Recovered {added} closed trade(s).')
        save_closed_trades_to_file()
    else:
        print('♻ Recovery: no missing closed trade.')

def place_trade(instrument, entry_price_signal, sl_signal, tp_signal, direction, setup_type, risk_percent, reason, df, balance):
    global active_trade, trades_today, rejected_signals
    if active_trade is not None:
        return False
    try:
        resp = ctx.pricing.get(ACCOUNT_ID, instruments=instrument)
        pi = resp.body['prices'][0]
        bid = float(pi.bids[0].price)
        ask = float(pi.asks[0].price)
        current_price = bid if direction == 'sell' else ask
    except Exception as e:
        send_telegram_message(f'⚠ Could not get price {instrument}: {e}')
        return False
    current_spread = ask - bid
    slippage_pips = abs(current_price - entry_price_signal) / 0.0001
    try:
        atr = float(df['atr'].iloc[-1])
        atr_pips = atr / 0.0001
        max_slippage_pips = min(max(SLIPPAGE_MIN_PIPS, SLIPPAGE_ATR_FACTOR * atr_pips), 8.0)
    except:
        max_slippage_pips = 3.0
    if slippage_pips > max_slippage_pips:
        msg = f'Slippage too high ({slippage_pips:.1f}p) on {instrument} – rejected. Max: {max_slippage_pips:.1f}p.'
        print(msg)
        rejected_signals.append({'time': datetime.now(tz).strftime('%H:%M:%S'), 'pair': instrument, 'buy_reason': msg, 'sell_reason': msg})
        save_rejected_to_file()
        return False
    config = PAIR_CONFIG[instrument]
    levels = setup_stop_and_target(df, direction, current_price, config, setup_type)
    if not levels:
        msg = f'SL/TP recalc failed {instrument} at {current_price:.5f}'
        rejected_signals.append({'time': datetime.now(tz).strftime('%H:%M:%S'), 'pair': instrument, 'buy_reason': msg, 'sell_reason': msg})
        save_rejected_to_file()
        return False
    (new_sl, new_tp, sl_pips, atr_val) = levels
    sl_distance = abs(current_price - new_sl)
    if sl_distance <= 0:
        return False
    new_units = calculate_units(balance, sl_distance, instrument, risk_percent)
    if new_units < 1000:
        print(f'Volume too low ({new_units}) {instrument}')
        return False
    signed_units = -abs(new_units) if direction == 'sell' else abs(new_units)
    order = {'type': 'MARKET', 'instrument': instrument, 'units': str(signed_units), 'stopLossOnFill': {'price': f'{new_sl:.5f}'}, 'takeProfitOnFill': {'price': f'{new_tp:.5f}'}}
    r = retry_api_call(ctx.order.create, ACCOUNT_ID, order=order)
    if hasattr(r.body, 'errorMessage') and r.body.errorMessage:
        msg = r.body.errorMessage
        send_telegram_message(f'⚠ Market order rejected: {msg}')
        rejected_signals.append({'time': datetime.now(tz).strftime('%H:%M:%S'), 'pair': instrument, 'buy_reason': f'Market rejected: {msg}', 'sell_reason': f'Market rejected: {msg}'})
        save_rejected_to_file()
        return False
    try:
        fill = r.body.get('orderFillTransaction', r.body.get('orderCreateTransaction'))
        if not fill:
            print(f'Market order not filled immediately {instrument}')
            return False
        trade = fill.tradeOpened
        actual_entry_price = float(trade.price)
    except Exception as e:
        send_telegram_message(f'⚠ Error extracting trade: {str(e)[:100]}')
        return False
    tp1_order_id = None
    tp1_units = int(new_units * TP_PARTIAL_RATIO)
    if tp1_units >= 1000:
        real_sl_distance = abs(actual_entry_price - new_sl)
        _tp1_dist = real_sl_distance * TP1_R_MULT
        tp1_price = actual_entry_price + _tp1_dist if direction == 'buy' else actual_entry_price - _tp1_dist
        signed_tp1_units = -tp1_units if direction == 'buy' else tp1_units
        order_tp1 = {'type': 'LIMIT', 'instrument': instrument, 'units': str(signed_tp1_units), 'price': f'{tp1_price:.5f}', 'positionFill': 'REDUCE_ONLY', 'timeInForce': 'GTC'}
        r_tp1 = retry_api_call(ctx.order.create, ACCOUNT_ID, order=order_tp1)
        if not hasattr(r_tp1.body, 'errorMessage') or not r_tp1.body.errorMessage:
            create_tx = r_tp1.body.get('orderCreateTransaction')
            if create_tx:
                tp1_order_id = create_tx.id
    score_match = re.search('score\\s+([\\d.]+)', reason, re.IGNORECASE)
    quality_score = float(score_match.group(1)) if score_match else None
    real_sl_distance = abs(actual_entry_price - new_sl)
    real_tp1_dist = real_sl_distance * TP1_R_MULT
    real_tp1_price = actual_entry_price + real_tp1_dist if direction == 'buy' else actual_entry_price - real_tp1_dist
    active_trade = {'trade_id': trade.tradeID, 'tp1_order_id': tp1_order_id, 'pair': instrument, 'units': int(trade.units), 'initial_units': new_units, 'entry_price': actual_entry_price, 'sl': new_sl, 'tp1': real_tp1_price, 'tp2': new_tp, 'tp2_initial': new_tp, 'tp2_initial_locked': False, 'direction': direction, 'setup_type': setup_type, 'risk_percent': risk_percent, 'initial_risk': real_sl_distance, 'be_triggered': False, 'tp1_hit': False if tp1_order_id else True, 'tp2_widened': False, 'peak_profit_pips': 0.0, 'last_peak_time': datetime.now(tz).isoformat(), 'time_lock_done': False, 'regime_adverse_handled': False, 'checkpoint_sent': False, 'trailing_active': False, 'atr': atr_val, 'opened_at': datetime.now(tz).isoformat(), 'quality_score': quality_score, 'news_partial_done': False, 'early_secure_done': False, 'early_widen_done': False, 'phase': 0, 'stagnation_done': False}
    trades_today += 1
    rr_ratio = SETUP_RR.get(setup_type.lower().replace(' ', '').replace('/', ''), 2.0)
    msg = f"<b>✅ Trade opened ({trades_today}/{MAX_TRADES_PER_DAY})</b>\nPair: {instrument}\nSetup: {setup_type.upper()}\nType: {('Buy' if direction == 'buy' else 'Sell')}\nRisk: {risk_percent:.2f}%\nVolume: {new_units} units\nEntry: {actual_entry_price:.5f} (slippage {slippage_pips:.1f}p)\nSL initial (FIXE): {new_sl:.5f} — Phase 0, trailing OFF\nTP1: {real_tp1_price:.5f} ({TP1_R_MULT:.2f}R, {TP_PARTIAL_RATIO:.0%}) - Server-side Limit\nTP2: {new_tp:.5f} ({rr_ratio:.1f}R)\nR/R: 1:{rr_ratio:.1f}\nQuality: {quality_score:.1f}\nTime: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}\n🛡 : Early Secure -> SL (BE+2p at 0.5R) · ATR Trailing only after TP1"
    send_telegram_message(msg)
    live_log(f'✅ Trade opened {instrument} {direction} {setup_type} @ {actual_entry_price:.5f} SL {new_sl:.5f} TP1 {real_tp1_price:.5f} TP2 {new_tp:.5f} — Phase 0', force=True)
    log_trade({'time': datetime.now(tz).isoformat(), 'pair': instrument, 'setup': setup_type, 'entry': actual_entry_price, 'sl': new_sl, 'tp1': real_tp1_price, 'tp2': new_tp, 'units': new_units, 'direction': direction, 'risk_percent': risk_percent, 'status': 'OPEN'})
    return True

def check_closed_trade():
    global active_trade, last_close_time
    if active_trade is None:
        return
    pair = active_trade['pair']
    if has_open_position(pair):
        return
    time.sleep(1)
    try:
        cancel_tp1_order()
        resp = retry_api_call(ctx.trade.list, ACCOUNT_ID, instrument=pair, count=50, state='CLOSED')
        closed_trades = resp.body.get('trades', [])
        if not closed_trades:
            print(f'No closed trade {pair} yet, retry later.')
            return
        our_trade_id = str(active_trade['trade_id'])
        our_trade = None
        for t in closed_trades:
            if str(getattr(t, 'id', '')) == our_trade_id:
                our_trade = t
                break
        if our_trade is None:
            print(f'⚠ Trade {our_trade_id} pas encore CLOSED {pair} – retry.')
            return
        latest = our_trade
        total_pnl_cad = float(latest.realizedPL)
        entry = active_trade['entry_price']
        units = int(getattr(latest, 'initialUnits', 0))
        if units == 0:
            units = abs(active_trade.get('initial_units', active_trade.get('units', 0)))
        direction = active_trade.get('direction', 'buy')
        setup = active_trade.get('setup_type', 'unknown')
        init_risk = active_trade.get('initial_risk', 0.0)
        close_price = None
        source = None
        if hasattr(latest, 'averageClosePrice') and latest.averageClosePrice is not None:
            try:
                cp = float(latest.averageClosePrice)
                if cp > 0:
                    close_price = cp
                    source = 'averageClosePrice'
            except:
                pass
        if close_price is None and hasattr(latest, 'closePrice') and (latest.closePrice is not None):
            try:
                cp = float(latest.closePrice)
                if cp > 0:
                    close_price = cp
                    source = 'closePrice'
            except:
                pass
        if close_price is None:
            try:
                tr_resp = retry_api_call(ctx.transaction.list, ACCOUNT_ID, count=500)
                for tx in tr_resp.body.get('transactions', []):
                    if getattr(tx, 'type', '') == 'ORDER_FILL' and hasattr(tx, 'tradeID') and (str(tx.tradeID) == our_trade_id) and (getattr(tx, 'price', None) is not None):
                        cp = float(tx.price)
                        if cp > 0:
                            close_price = cp
                            source = 'transaction'
                            break
            except Exception as e:
                print(f'⚠ Transaction API: {e}')
        if close_price is None and abs(units) > 0:
            close_price = entry + total_pnl_cad / abs(units) if direction == 'buy' else entry - total_pnl_cad / abs(units)
            source = 'calculated_from_pnl'
        if close_price is None:
            close_price = entry
            source = 'fallback_entry'
            print(f'⚠ Fallback entry: {close_price:.5f}')
        if abs(close_price - entry) < 1e-06 and abs(total_pnl_cad) > 0.1 and (abs(units) > 0):
            close_price = entry + total_pnl_cad / abs(units) if direction == 'buy' else entry - total_pnl_cad / abs(units)
            source = 'forced_from_pnl'
        print(f'✅ Trade {our_trade_id} closed – Exit from {source}: {close_price:.5f}')
        realized_r = ((close_price - entry) / init_risk if direction == 'buy' else (entry - close_price) / init_risk) if init_risk > 0 else 0.0
        usd_cad = get_usd_cad_rate()
        total_pnl_usd = total_pnl_cad / usd_cad if usd_cad > 0 else total_pnl_cad
        closing_fills = fetch_closing_fills(our_trade_id)
        if len(closing_fills) > 1:
            exit_lines = f'Exit: {close_price:.5f} (avg of {len(closing_fills)} fills)'
            for (i, cf) in enumerate(closing_fills, start=1):
                exit_lines += f"\n  • Fill {i}: {cf['units']} units @ {cf['price']:.5f}"
        else:
            exit_lines = f'Exit: {close_price:.5f}'
        msg = f"<b>🔴 Trade closed ({trades_today}/{MAX_TRADES_PER_DAY})</b>\nPair: {pair}\nSetup: {setup.upper()}\nType: {('Buy' if direction == 'buy' else 'Sell')}\nEntry: {entry:.5f}\n{exit_lines}\nVolume: {abs(units)}\nP&L: {total_pnl_cad:.2f} CAD\nR: {realized_r:+.2f}R\nFinal phase: {active_trade.get('phase', 0)}\nTime: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}"
        send_telegram_message(msg)
        live_log(f"🔴 Trade closed {pair} {direction} {setup} Exit {close_price:.5f} PnL {total_pnl_cad:+.2f} CAD R {realized_r:+.2f} Phase {active_trade.get('phase', 0)}", force=True)
        closed_trades_today.append({'pair': pair, 'type': 'Buy' if direction == 'buy' else 'Sell', 'setup': setup, 'pnl': round(total_pnl_cad, 2), 'pnl_usd': round(total_pnl_usd, 2), 'time': datetime.now(tz).strftime('%H:%M:%S'), 'r_multiple': round(realized_r, 2), 'units': abs(units), 'entry': entry, 'exit': close_price, 'score': active_trade.get('quality_score')})
        save_closed_trades_to_file()
        last_close_time = datetime.now(tz)
    except Exception as e:
        print(f'Error retrieving closed trade: {e}')
        send_telegram_message(f'⚠ Trade on {pair} closed (details unavailable).')
        last_close_time = datetime.now(tz)
    active_trade = None

def _handle_sigterm(signum, frame):
    print('⚠ SIGTERM - final push before stop.')
    try:
        save_status_json(force=True)
        save_closed_trades_to_file()
        save_rejected_to_file()
        live_log('🔴 Bot stopped (SIGTERM) - final push', force=True)
    except Exception as e:
        print(f'Final push error: {e}')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, _handle_sigterm)

def main():
    global trades_today, last_trade_date, last_close_time, active_trade, closed_trades_today, rejected_signals, late_shutdown_required, trade_opened_during_window_today, daily_start_balance, BOT_STATUS, orb_range, _last_news_block_message_sent, _last_reminder_minute, _critical_alert_sent
    load_closed_trades_from_file()
    load_rejected_from_file()
    recover_recent_closed_trades(hours=24)
    trades_today = count_all_trades_today()
    try:
        daily_start_balance = get_account_balance(retry_api_call(ctx.account.summary, ACCOUNT_ID))
    except:
        daily_start_balance = None
    if active_trade is None:
        load_existing_open_position()
    if active_trade is not None and (not has_open_position(active_trade['pair'])):
        print(f"Trade {active_trade['pair']} closed manually before start.")
        check_closed_trade()
    _now_check = datetime.now(tz)
    _after_1205 = _now_check.hour > 12 or (_now_check.hour == 12 and _now_check.minute >= 5)
    if _after_1205 and active_trade is None:
        print(f"🕒 Started at {_now_check.strftime('%H:%M')} with no trade - exit.")
        BOT_STATUS = 'stopped'
        save_status_json()
        return
    trade_opened_during_window_today = False
    if active_trade is not None:
        opened_at = active_trade.get('opened_at')
        if opened_at:
            try:
                opened_dt = datetime.fromisoformat(opened_at.replace('Z', '+00:00')).astimezone(tz)
                trade_opened_during_window_today = opened_dt.date() == datetime.now(tz).date() and TRADING_HOURS_START <= opened_dt.hour < TRADING_HOURS_END
            except:
                pass
    late_shutdown_required = active_trade is not None and trade_opened_during_window_today and (datetime.now(tz).hour >= TRADING_HOURS_END)
    events = get_high_impact_news()
    now = datetime.now(tz)
    future_events = [e for e in events if e['time'] > now and e['time'] - now < timedelta(hours=NEWS_CHECK_FUTURE_HOURS)]
    if _after_1205 and active_trade is not None:
        at = active_trade
        direction_label = 'BUY' if at['direction'] == 'buy' else 'SELL'
        lines = [f"🔄 <b>Relay takeover</b> • {_now_check.strftime('%H:%M')} ET", f'Session: {trades_today}/{MAX_TRADES_PER_DAY} trades', '', f"🔥 <b>Active Trade on {at['pair']} ({direction_label})</b>", f"Entry: {at['entry_price']:.5f} • SL: {at['sl']:.5f} • Phase {at.get('phase', 0)}"]
        if at.get('tp2') is not None:
            lines.append(f"TP2 {at.get('tp2'):.5f} • Runner {abs(int(at['units']))} units")
        if at.get('be_triggered'):
            lines.append('🛡 BE secured ✅')
        if at.get('tp1_hit'):
            lines.append('🎯 TP1 hit ✅')
        if at.get('tp2_widened'):
            lines.append('🎯 TP2 widened ✅')
        if at.get('tp2_initial_locked'):
            lines.append('🔐 TP2 initial locked ✅')
        if at.get('time_lock_done'):
            lines.append('🔒 Time-lock done ✅')
        if at.get('regime_adverse_handled'):
            lines.append('⚠ Adverse regime handled ✅')
        if at.get('early_secure_done'):
            lines.append('🛡 Early Secure done ✅')
        if at.get('early_widen_done'):
            lines.append('📈 Early Widen done ✅')
        try:
            pnl_oanda = fetch_position_pnl_from_oanda(at['pair'])
            if pnl_oanda is not None:
                lines.append(f'P&L: {pnl_oanda:+.2f} CAD')
        except:
            pass
        lines.append('')
        lines.append('Relay runs until 17:05 ET (forced close at 16:55).')
        start_msg = '\n'.join(lines)
    else:
        start_msg = f'🟢 Forex Sniper 7-12 Multi-Setup started – max {MAX_TRADES_PER_DAY} trades/day, buffer {MIN_MINUTES_BETWEEN_TRADES}min. State machine: Phase 0 (Fixed SL) -> Phase 1 (BE+2 at 0.5R) -> Phase 2 TP1 (Partial Closure) -> Phase 3 (ATR Trailing). ({trades_today} already taken)\n📅 News pause: {NEWS_BLOCK_PRE_MINUTES} min pre + {NEWS_BLOCK_POST_MINUTES} min post.'
        if future_events:
            start_msg += '\n\n📰 <b>Upcoming high-impact news:</b>\n'
            for e in future_events:
                start_msg += f"• {e['title']} at {e['time'].strftime('%H:%M')} ({e['time'].strftime('%a %d %b')})\n"
    print(start_msg)
    send_telegram_message(start_msg)
    live_log(f'🟢 Session start v2 — {start_msg}', force=True)
    try:
        while True:
            now = datetime.now(tz)
            if (now.hour > 12 or (now.hour == 12 and now.minute >= 5)) and active_trade is None:
                print('🕒 After 12:05 with no trade - stop.')
                BOT_STATUS = 'stopped'
                save_status_json()
                send_telegram_message('🔴 Bot stopped – End of session (past 12:05), no active trade.')
                live_log('🔴 End of session 12:05 - no active trade', force=True)
                break
            if now.hour == 16 and 50 <= now.minute <= 54 and (active_trade is not None) and (_last_reminder_minute != now.minute):
                pnl_oanda = fetch_position_pnl_from_oanda(active_trade['pair'])
                pnl_str = f'{pnl_oanda:.2f} CAD' if pnl_oanda is not None else 'unavailable (OANDA API)'
                send_telegram_message(f"⏰ <b>Reminder {now.strftime('%H:%M')}</b>\nPair: {active_trade['pair']}\nP&L (OANDA): {pnl_str}\nMarket closes at 16:59 NY.\nAutomatic forced closure at 16:55-16:57.")
                print(f"Reminder {now.strftime('%H:%M')} sent.")
                _last_reminder_minute = now.minute
                live_log(f"⏰ Reminder {now.strftime('%H:%M')} - PnL {pnl_str}")
            if now.hour == 16 and 55 <= now.minute <= 57 and (active_trade is not None):
                pair = active_trade['pair']
                if not has_open_position(pair):
                    print(f'Position {pair} already closed.')
                    check_closed_trade()
                else:
                    pnl_oanda = fetch_position_pnl_from_oanda(pair)
                    pnl_str = f'{pnl_oanda:.2f} CAD' if pnl_oanda is not None else 'indisponible'
                    print(f'16:{now.minute:02d} – Forced close. P&L: {pnl_str}')
                    if close_full_position_market():
                        send_telegram_message(f'🔒 <b>Trade closed (forced, end of session)</b>\nPair: {pair}\nP&L: {pnl_str}\nReason: End of session')
                        live_log(f'🔒 Forced close {pair} PnL {pnl_str}', force=True)
                        time.sleep(2)
                        check_closed_trade()
                    else:
                        send_telegram_message(f'⚠ <b>Forced closure failed on {pair}.</b>\nPlease close manually before 16:59 NY.')
            if now.hour == 16 and now.minute == 58 and (active_trade is not None) and (not _critical_alert_sent):
                send_telegram_message(f"🚨 <b>CRITICAL: trade still open at 16:58</b>\nPair: {active_trade['pair']}\nForced closure failed. ~60s to close manually before 16:59 NY.")
                print('🚨 16:58 alert sent.')
                _critical_alert_sent = True
            if now.hour > BOT_SHUTDOWN_HOUR or (now.hour == BOT_SHUTDOWN_HOUR and now.minute >= 5):
                if active_trade is not None:
                    send_telegram_message(f"🚨 <b>Trade still open after market close</b>\nPair: {active_trade['pair']}\nPosition carries over the weekend. Verify on OANDA.")
                print('🕒 17:05 reached – stopping.')
                BOT_STATUS = 'stopped'
                save_status_json()
                send_telegram_message('🔴 Bot stopped – End of session (17:05).')
                live_log('🔴 End of session 17:05', force=True)
                break
            (blocked, news_event, time_until, blocked_pairs) = check_and_block_news(now)
            if blocked:
                if active_trade is None and (not _last_news_block_message_sent):
                    if set(blocked_pairs) == set(PAIRS):
                        msg = f"📅 <b>High-impact news:</b> {news_event['title']} at {news_event['time'].strftime('%H:%M')} – Trading paused on <b>ALL pairs</b> until {datetime.fromtimestamp(get_pause_until(), tz).strftime('%H:%M')}."
                    else:
                        active = [p for p in PAIRS if p not in blocked_pairs]
                        msg = f"📅 <b>High-impact news:</b> {news_event['title']} at {news_event['time'].strftime('%H:%M')} – Paused on {', '.join(blocked_pairs)} until {datetime.fromtimestamp(get_pause_until(), tz).strftime('%H:%M')}.\n(Active: {', '.join(active)})"
                    send_telegram_message(msg)
                    _last_news_block_message_sent = True
                    live_log(msg)
                can_trade = False
            elif _last_news_block_message_sent:
                send_telegram_message('🟢 News pause lifted – trading resumed')
                _last_news_block_message_sent = False
            try:
                today = now.date()
                if last_trade_date != today:
                    trades_today = count_all_trades_today()
                    last_trade_date = today
                    last_close_time = None
                    closed_trades_today.clear()
                    rejected_signals.clear()
                    late_shutdown_required = False
                    trade_opened_during_window_today = False
                    orb_range = {'high': None, 'low': None, 'recorded': False, 'date': today.strftime('%Y-%m-%d')}
                    _candle_cache.clear()
                    _last_reminder_minute = None
                    _critical_alert_sent = False
                    load_closed_trades_from_file()
                    load_rejected_from_file()
                    recover_recent_closed_trades(hours=24)
                    if active_trade is None:
                        load_existing_open_position()
                    try:
                        daily_start_balance = get_account_balance(retry_api_call(ctx.account.summary, ACCOUNT_ID))
                    except:
                        daily_start_balance = None
                    if active_trade is not None:
                        opened_at = active_trade.get('opened_at')
                        if opened_at:
                            try:
                                opened_dt = datetime.fromisoformat(opened_at.replace('Z', '+00:00')).astimezone(tz)
                                trade_opened_during_window_today = opened_dt.date() == today and TRADING_HOURS_START <= opened_dt.hour < TRADING_HOURS_END
                            except:
                                pass
                manage_active_trade()
                check_closed_trade()
                if now.hour >= TRADING_HOURS_END and trade_opened_during_window_today and (active_trade is not None):
                    late_shutdown_required = True
                if active_trade is not None and blocked and (news_event is not None) and (time_until is not None):
                    minutes_until = time_until.total_seconds() / 60.0
                    if minutes_until <= NEWS_CLOSE_BEFORE_MINUTES and active_trade['pair'] in blocked_pairs:
                        if not active_trade.get('news_partial_done', False):
                            active_trade['news_partial_done'] = True
                            pair = active_trade['pair']
                            setup_type = active_trade.get('setup_type', '')
                            news_title = news_event['title']
                            news_time = news_event['time'].strftime('%H:%M')
                            try:
                                resp = ctx.pricing.get(ACCOUNT_ID, instruments=pair)
                                pi = resp.body['prices'][0]
                                bid = float(pi.bids[0].price)
                                ask = float(pi.asks[0].price)
                                current = bid if active_trade['direction'] == 'sell' else ask
                                units_abs = abs(int(active_trade['units']))
                                pnl_usd = (active_trade['entry_price'] - current) * units_abs if active_trade['direction'] == 'sell' else (current - active_trade['entry_price']) * units_abs
                            except:
                                pnl_usd = 0
                            usd_cad = get_usd_cad_rate()
                            pnl_cad = pnl_usd * usd_cad
                            close_pct = NEWS_CLOSE_PCT_EXTENSION if setup_type in TP2_WIDEN_SETUPS else NEWS_CLOSE_PCT_OTHER
                            setup_label = 'extension' if setup_type in TP2_WIDEN_SETUPS else 'standard'
                            units_abs = abs(int(active_trade['units']))
                            partial_units = max(1000, int(units_abs * close_pct))
                            remaining = units_abs - partial_units
                            if partial_units >= units_abs or remaining < 1000:
                                if close_full_position_market():
                                    send_telegram_message(f'📰 <b>Imminent News – Full closure</b>\nPair: {pair}\nSetup: {setup_type.upper()}\nNews: {news_title} at {news_time}\nP&L: {pnl_cad:+.2f} CAD')
                                    live_log(f'📰 Imminent news - Full close {pair} {pnl_cad:+.2f} CAD', force=True)
                                    time.sleep(2)
                                    check_closed_trade()
                                else:
                                    send_telegram_message(f'⚠ Closing failed {pair} before news. Please monitor.')
                            elif close_partial_position(partial_units, expected_remaining=remaining):
                                active_trade['units'] = remaining if active_trade['direction'] == 'buy' else -remaining
                                sl_state = 'trailing (BE)' if active_trade.get('be_triggered') else 'initial SL'
                                send_telegram_message(f'📰 <b>Imminent News – Partial close</b>\nPair: {pair}\nSetup: {setup_type.upper()} ({setup_label})\nNews: {news_title} at {news_time}\nClosed: {int(close_pct * 100)}% ({partial_units} units)\nRunner: {remaining} units ({sl_state} intact)\nP&L: {pnl_cad:+.2f} CAD')
                                live_log(f'📰 Imminent news - Partial {int(close_pct * 100)}% {pair}')
                                print(f'Imminent news - {pair}: {int(close_pct * 100)}% closed.')
                            else:
                                send_telegram_message(f'⚠ Partial close failed before news on {pair}. Please monitor.')
                if not hasattr(main, 'next_news_check'):
                    main.next_news_check = now
                if now >= main.next_news_check:
                    for pair in PAIRS:
                        s = get_finnhub_sentiment(pair)
                        if s != 'neutral':
                            news_sentiment_filter[pair] = s
                    main.next_news_check = now + timedelta(seconds=60)
                all_pairs_blocked = set(blocked_pairs) == set(PAIRS)
                if blocked and all_pairs_blocked:
                    can_trade = False
                else:
                    in_trading_hours = TRADING_HOURS_START <= now.hour < TRADING_HOURS_END
                    can_trade_time = True
                    if last_close_time is not None and now - last_close_time < timedelta(minutes=MIN_MINUTES_BETWEEN_TRADES):
                        can_trade_time = False
                    balance = None
                    daily_loss_blocked = False
                    try:
                        balance = get_account_balance(retry_api_call(ctx.account.summary, ACCOUNT_ID))
                        (_, daily_loss_blocked) = get_daily_loss_status(balance)
                    except Exception as e:
                        print(f'Risk check failed: {e}')
                        daily_loss_blocked = True
                    can_trade = active_trade is None and trades_today < MAX_TRADES_PER_DAY and in_trading_hours and can_trade_time and (not daily_loss_blocked)
                if can_trade:
                    candidates = []
                    for pair in PAIRS:
                        if pair in blocked_pairs:
                            print(f' -> SKIPPED {pair}: news block')
                            continue
                        if has_open_position(pair):
                            continue
                        try:
                            spread = get_spread(pair)
                        except Exception as e:
                            print(f'Spread failed {pair}: {e}')
                            continue
                        if not is_spread_ok(pair, spread):
                            print(f' -> REJECTED {pair}: spread too wide')
                            rejected_signals.append({'time': now.strftime('%H:%M:%S'), 'pair': pair, 'buy_reason': 'Spread too wide', 'sell_reason': 'Spread too wide', 'spread': spread})
                            save_rejected_to_file()
                            continue
                        try:
                            df = get_candles(pair, count=EXECUTION_CANDLES, granularity=EXECUTION_GRANULARITY)
                        except Exception as e:
                            print(f'Candles failed {pair}: {e}')
                            continue
                        (signal, price, sl, tp, sl_pips, direction, setup_type, risk_pct, score, reason) = check_signal(df, pair)
                        if signal:
                            last_trade = None
                            for t in reversed(closed_trades_today):
                                if t.get('pair') == pair:
                                    last_trade = t
                                    break
                            if last_trade and last_trade.get('setup', '').lower() == setup_type.lower():
                                msg = f'Single Setup Rule: Already took a {setup_type} trade on {pair} today. Setup rejected.'
                                print(f' -> REJECTED {pair}: {msg}')
                                rejected_signals.append({'time': now.strftime('%H:%M:%S'), 'pair': pair, 'buy_reason': msg if direction == 'buy' else '', 'sell_reason': msg if direction == 'sell' else '', 'spread': spread})
                                save_rejected_to_file()
                                continue
                            candidates.append((score, pair, price, sl, tp, sl_pips, direction, setup_type, risk_pct, reason, df))
                        else:
                            c = df.iloc[-1]
                            parts = reason.split('|')
                            buy_reason = parts[0].strip() if len(parts) > 0 else reason
                            sell_reason = ''
                            diagnostic = ''
                            if len(parts) > 1:
                                sell_reason = parts[1].strip()
                                diag_idx = sell_reason.rfind(' [Best hypothetical')
                                if diag_idx == -1:
                                    diag_idx = sell_reason.rfind(' [Diagnostic error')
                                if diag_idx > 0:
                                    diagnostic = sell_reason[diag_idx:].strip()
                                    sell_reason = sell_reason[:diag_idx].strip()
                            rejected_signals.append({'time': now.strftime('%H:%M:%S'), 'pair': pair, 'buy_reason': buy_reason, 'sell_reason': sell_reason, 'spread': spread, 'adx': c['adx'] if not pd.isna(c['adx']) else None, 'plus_di': c['plus_di'] if not pd.isna(c['plus_di']) else None, 'minus_di': c['minus_di'] if not pd.isna(c['minus_di']) else None, 'ema50': c['ema50'] if not pd.isna(c['ema50']) else None, 'ema200': c['ema200'] if not pd.isna(c['ema200']) else None, 'rsi': c['rsi'] if not pd.isna(c['rsi']) else None, 'atr': c['atr'] if not pd.isna(c['atr']) else None, 'diagnostic': diagnostic if diagnostic else None})
                            save_rejected_to_file()
                            print(f' -> REJECTED {pair}: {reason[:160]}...')
                    if candidates:
                        best = max(candidates, key=lambda c: c[0])
                        (score, pair, price, sl, tp, sl_pips, direction, setup_type, risk_pct, reason, df) = best
                        print(f' -> SIGNAL {direction} {pair} [{setup_type}] {reason}')
                        live_log(f'📶 SIGNAL {direction} {pair} [{setup_type}] {reason}')
                        success = place_trade(pair, price, sl, tp, direction, setup_type, risk_pct, reason, df, balance)
                        if success:
                            trade_opened_during_window_today = True
                if now.hour == 12 and now.minute >= 50:
                    save_status_json(force=True)
                    save_closed_trades_to_file()
                    save_rejected_to_file()
                    live_log('💾 Backup 12:50 - status + trades + rejected', force=True)
                    main.next_trade_save = now + timedelta(seconds=30)
                else:
                    save_status_json()
                if not hasattr(main, 'next_trade_save'):
                    main.next_trade_save = now
                if now >= main.next_trade_save:
                    save_closed_trades_to_file()
                    save_rejected_to_file()
                    live_log('💾 Periodic backup - trades + rejected')
                    main.next_trade_save = now + timedelta(minutes=5)
                live_log(f"💓 Heartbeat {now.strftime('%H:%M:%S')} - Phase {(active_trade.get('phase', '—') if active_trade else 'no trade')} — Trades {trades_today}/{MAX_TRADES_PER_DAY}")
                time.sleep(10)
            except Exception as inner_e:
                print(f'⚠ Error in main loop: {inner_e}')
                traceback.print_exc()
                live_log(f'⚠ Loop error: {inner_e}', force=True)
                time.sleep(60)
                continue
    except KeyboardInterrupt:
        BOT_STATUS = 'stopped'
        save_status_json()
        send_telegram_message('🔴 Bot stopped manually (Ctrl+C)')
        live_log('🔴 Bot stopped manually (Ctrl+C)', force=True)
if __name__ == '__main__':
    main()
