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
from dotenv import load_dotenv

load_dotenv()

# ========== CONFIGURATION ==========
API_KEY = os.getenv("OANDA_API_KEY")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_URL = "api-fxpractice.oanda.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
GH_PAT = os.getenv("GH_PAT")                # token GitHub avec droits repo
PAIRS = ["EUR_USD", "GBP_USD"]
RISK_PERCENT = 1.0
TRADING_HOURS_START = 8
TRADING_HOURS_END = 12
TIMEZONE = 'America/Toronto'
MAX_TRADES_PER_DAY = 2
MIN_MINUTES_BETWEEN_TRADES = 20
TRAILING_DISTANCE_PIPS = 15
ATR_PERIOD = 14
ADX_PERIOD = 10
NEWS_BLOCK_MINUTES = 30
BREAKING_NEWS_BLOCK_MINUTES = 15
HIGH_IMPACT_EVENTS = ["NFP", "CPI", "FOMC", "Interest Rate", "GDP", "Retail Sales"]
USE_MACD_FILTER = True
MACD_FAST = 5
MACD_SLOW = 13
MACD_SIGNAL = 9
USE_VOLUME_FILTER = False

PAIR_CONFIG = {
    "EUR_USD": {
        "MAX_SPREAD_PIPS": 2.5,
        "ADX_THRESHOLD": 20,
        "ATR_MULTIPLIER": 2.0,
    },
    "GBP_USD": {
        "MAX_SPREAD_PIPS": 3.0,
        "ADX_THRESHOLD": 15,
        "ATR_MULTIPLIER": 2.0,
    }
}
# ============================

ctx = v20.Context(OANDA_URL, token=API_KEY)
trades_today = 0
last_trade_date = None
last_close_time = None
news_cache = {"time": None, "events": []}
tz = pytz.timezone(TIMEZONE)
active_trade = None
last_news_block_time = None
news_sentiment_filter = {}

spread_history = {pair: [] for pair in PAIRS}
SPREAD_WINDOW = 5

# Cockpit data
closed_trades_today = []
rejected_signals = []


def push_status_json(data_dict):
    if not GH_PAT:
        return
    try:
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/status.json"
        headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json"}
        resp = requests.get(url, headers=headers, timeout=10)
        sha = resp.json().get("sha") if resp.status_code == 200 else None

        content = json.dumps(data_dict, indent=2, default=str).encode()
        payload = {
            "message": "Update status",
            "content": base64.b64encode(content).decode(),
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha
        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_resp.status_code not in (200, 201):
            print(f"Status push failed: {put_resp.status_code} {put_resp.text}")
    except Exception as e:
        print(f"Error pushing status.json: {e}")


def save_status_json(pair_indicators):
    now = datetime.now(tz)
    status = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "bot_status": "running",
        "session": {
            "trades_today": trades_today,
            "max_trades": MAX_TRADES_PER_DAY,
            "start": f"{TRADING_HOURS_START:02d}:00",
            "end": f"{TRADING_HOURS_END:02d}:00"
        },
        "pairs": pair_indicators,
        "active_trade": None,
        "closed_trades_today": closed_trades_today,
        "rejected_signals": rejected_signals[-20:],
        "next_news_event": None
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
        tp_distance = abs(active_trade['tp'] - current_price)
        unrealized_pnl = (current_price - active_trade['entry_price']) * abs(active_trade['units'])
        if active_trade['direction'] == 'sell':
            unrealized_pnl = -unrealized_pnl

        status["active_trade"] = {
            "pair": active_trade['pair'],
            "type": "Buy" if active_trade['direction'] == 'buy' else "Sell",
            "entry": active_trade['entry_price'],
            "sl": active_trade['sl'],
            "tp": active_trade['tp'],
            "trailing_stop": TRAILING_DISTANCE_PIPS,
            "current_price": current_price,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "distance_to_sl_pips": round(sl_distance / 0.0001, 1),
            "distance_to_tp_pips": round(tp_distance / 0.0001, 1)
        }

    events = news_cache["events"]
    if events:
        future_events = [e for e in events if e["time"] > now]
        if future_events:
            next_ev = min(future_events, key=lambda e: e["time"])
            status["next_news_event"] = {
                "title": next_ev["title"],
                "time": next_ev["time"].strftime("%H:%M"),
                "impact": "High"
            }

    push_status_json(status)


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
    try:
        resp_pos = retry_api_call(ctx.position.list, ACCOUNT_ID)
        for pos in resp_pos.body['positions']:
            instrument = pos.instrument
            if instrument not in PAIRS:
                continue
            long_units = int(pos.long.units)
            short_units = int(pos.short.units)
            if long_units != 0 or short_units != 0:
                resp_trades = retry_api_call(ctx.trade.list, ACCOUNT_ID,
                                             instrument=instrument, state='OPEN', count=1)
                open_trades = resp_trades.body.get('trades', [])
                if open_trades:
                    trade = open_trades[0]
                    active_trade = {
                        'trade_id': trade.id,
                        'pair': instrument,
                        'units': int(trade.currentUnits),
                        'entry_price': float(trade.price),
                        'sl': float(trade.stopLossOrder.price) if trade.stopLossOrder else None,
                        'tp': float(trade.takeProfitOrder.price) if trade.takeProfitOrder else None,
                        'direction': 'buy' if int(trade.currentUnits) > 0 else 'sell'
                    }
                    print(f"Existing open position loaded: {instrument} {active_trade['direction']}")
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


def update_news_filters():
    global last_news_block_time, news_sentiment_filter
    now = datetime.now(tz)
    if last_news_block_time:
        if now - last_news_block_time > timedelta(minutes=BREAKING_NEWS_BLOCK_MINUTES):
            last_news_block_time = None
            news_sentiment_filter = {}
            send_telegram_message("🟢 News sentiment filter lifted – normal trading resumed")
            print("News sentiment filter lifted.")
    for pair in PAIRS:
        sentiment = get_finnhub_sentiment(pair)
        if sentiment != 'neutral':
            if last_news_block_time is None:
                last_news_block_time = now
            news_sentiment_filter[pair] = sentiment
            msg = (f"⚠️ Breaking news sentiment for {pair}: {sentiment} "
                   f"(directional filter active for {BREAKING_NEWS_BLOCK_MINUTES} min)")
            send_telegram_message(msg)
            print(msg)


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


def is_news_time_blocked():
    now_local = datetime.now(tz)
    events = get_high_impact_news()
    for event in events:
        block_start = event["time"] - timedelta(minutes=NEWS_BLOCK_MINUTES)
        block_end = event["time"] + timedelta(minutes=NEWS_BLOCK_MINUTES)
        if block_start <= now_local <= block_end:
            print(f"⛔ Calendar news block: {event['title']} at {event['time'].strftime('%H:%M')} local")
            return True
    return False


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
            time.sleep(5)
    raise Exception("API call failed after 3 attempts")


def compute_adx(df, period=14):
    high, low, close = df['h'], df['l'], df['c']
    df['tr'] = pd.concat([high - low,
                          (high - close.shift()).abs(),
                          (low - close.shift()).abs()], axis=1).max(axis=1)
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


def get_candles(instrument, count=300):
    params = {"count": count, "granularity": "H1", "price": "M"}
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
    if USE_VOLUME_FILTER:
        df['volume_ma'] = df['volume'].rolling(window=VOLUME_MA_PERIOD).mean()
    return df


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


def calculate_units(balance, sl_price_distance, instrument):
    risk_amount = balance * (RISK_PERCENT / 100)
    units = int(risk_amount / sl_price_distance)
    return max(1000, units)


def get_account_balance(response):
    try:
        return float(response.body.account.balance)
    except AttributeError:
        return float(response.body['account'].balance)


def place_trade(instrument, entry, sl, tp, units, direction):
    global active_trade, trades_today
    if active_trade is not None:
        print("A trade is already active, cannot open another.")
        return False
    if direction == 'sell':
        units = -units
    trailing_distance = str(round(TRAILING_DISTANCE_PIPS * 0.0001, 5))

    order_body = {
        "type": "MARKET",
        "instrument": instrument,
        "units": str(units),
        "stopLossOnFill": {"price": f"{sl:.5f}"},
        "takeProfitOnFill": {"price": f"{tp:.5f}"},
        "trailingStopLossOnFill": {"distance": trailing_distance}
    }

    r = retry_api_call(ctx.order.create, ACCOUNT_ID, order=order_body)

    if hasattr(r.body, 'errorMessage') and r.body.errorMessage:
        error_msg = r.body.errorMessage
        print(f"OANDA error: {error_msg}")
        send_telegram_message(f"⚠️ Trade rejected: {error_msg}")
        return False

    try:
        fill_trans = r.body['orderFillTransaction']
        trade_opened = fill_trans.tradeOpened
        trade_id = trade_opened.tradeID
        entry_price = float(trade_opened.price)
        units_filled = trade_opened.units
        active_trade = {
            'trade_id': trade_id,
            'pair': instrument,
            'units': units_filled,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp,
            'direction': direction
        }
    except Exception as e:
        print(f"Failed to extract trade details: {e}")
        print(f"Response body: {r.body}")
        return False

    trades_today += 1

    if direction == 'buy':
        risk = entry - sl
        reward = tp - entry
    else:
        risk = sl - entry
        reward = entry - tp
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    msg = (f"<b>✅ Trade opened ({trades_today}/{MAX_TRADES_PER_DAY})</b>\n"
           f"Pair: {instrument}\n"
           f"Type: {'Buy' if direction == 'buy' else 'Sell'}\n"
           f"Volume: {abs(units)} units\n"
           f"Entry: {entry:.5f}\n"
           f"Stop Loss: {sl:.5f}\n"
           f"Take Profit: {tp:.5f}\n"
           f"Trailing Stop: {TRAILING_DISTANCE_PIPS} pips\n"
           f"R/R: 1:{rr}\n"
           f"Time: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
    send_telegram_message(msg)

    print(f"✅ Trade placed on {instrument} ({direction}) - {abs(units)} units")
    log_trade({
        "time": datetime.now(tz).isoformat(),
        "pair": instrument,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "units": abs(units),
        "direction": direction,
        "rr": rr,
        "status": "OPEN"
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
        resp = retry_api_call(ctx.trade.list, ACCOUNT_ID,
                              instrument=pair, count=1, state='CLOSED')
        closed_trades = resp.body.get('trades', [])
        if closed_trades:
            last_trade = closed_trades[0]
            realized_pl = float(last_trade.realizedPL)
            close_price = float(last_trade.price)
            entry_price = active_trade['entry_price']
            units = active_trade['units']
            direction = active_trade.get('direction', 'buy')

            msg = (f"<b>🔴 Trade closed ({trades_today}/{MAX_TRADES_PER_DAY})</b>\n"
                   f"Pair: {pair}\n"
                   f"Type: {'Buy' if direction == 'buy' else 'Sell'}\n"
                   f"Entry: {entry_price:.5f}\n"
                   f"Exit: {close_price:.5f}\n"
                   f"Volume: {abs(units)}\n"
                   f"P&L: {realized_pl:.2f} USD\n"
                   f"Time: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
            send_telegram_message(msg)

            # Ajouter à l'historique du cockpit
            closed_trades_today.append({
                "pair": pair,
                "type": "Buy" if direction == 'buy' else "Sell",
                "pnl": realized_pl,
                "time": datetime.now(tz).strftime("%H:%M:%S")
            })

            log_trade({
                "time": datetime.now(tz).isoformat(),
                "pair": pair,
                "entry": entry_price,
                "exit": close_price,
                "units": abs(units),
                "pnl": realized_pl,
                "direction": direction,
                "status": "CLOSED"
            })
            last_close_time = datetime.now(tz)
    except Exception as e:
        print(f"Error retrieving closed trade: {e}")
        send_telegram_message(f"⚠️ Trade on {pair} closed (details unavailable).")
        last_close_time = datetime.now(tz)
    active_trade = None


def check_signal(df, instrument):
    if len(df) < 200:
        return False, 0, 0, 0, 0, None

    last_candle = df.iloc[-2]
    price = last_candle['c']
    ema50 = last_candle['ema50']
    ema200 = last_candle['ema200']
    atr = last_candle['atr']
    rsi = last_candle['rsi']
    adx = last_candle['adx']
    plus_di = last_candle['plus_di']
    minus_di = last_candle['minus_di']

    if pd.isna(atr) or pd.isna(ema50) or pd.isna(adx):
        return False, 0, 0, 0, 0, None

    config = PAIR_CONFIG[instrument]
    adx_threshold = config["ADX_THRESHOLD"]
    atr_multiplier = config["ATR_MULTIPLIER"]

    sentiment = news_sentiment_filter.get(instrument, None)

    # --- Signal ACHAT ---
    if sentiment is None or sentiment == 'bullish':
        if adx >= adx_threshold and plus_di > minus_di:
            macd_ok = True
            if USE_MACD_FILTER:
                macd_line = last_candle['macd_line']
                macd_signal = last_candle['macd_signal']
                if pd.isna(macd_line) or macd_line <= macd_signal or macd_line <= 0:
                    macd_ok = False
            if macd_ok:
                vol_ok = True
                if USE_VOLUME_FILTER:
                    volume = last_candle['volume']
                    vol_ma = last_candle['volume_ma']
                    if pd.isna(vol_ma) or volume < vol_ma:
                        vol_ok = False
                if vol_ok:
                    trend_up = ema50 > ema200
                    touched_ema = (last_candle['l'] <= ema50 <= last_candle['h'])
                    bullish_rejection = (last_candle['c'] > last_candle['o']) and \
                                        ((last_candle['o'] - last_candle['l']) > (last_candle['h'] - last_candle['c']))
                    rsi_ok = 30 < rsi < 70
                    if trend_up and touched_ema and bullish_rejection and rsi_ok:
                        sl = ema200 - (atr_multiplier * atr)
                        sl_distance = price - sl
                        sl_pips = sl_distance / 0.0001
                        tp = price + 2 * sl_distance
                        return True, price, sl, tp, sl_pips, 'buy'

    # --- Signal VENTE ---
    if sentiment is None or sentiment == 'bearish':
        if adx >= adx_threshold and minus_di > plus_di:
            macd_ok = True
            if USE_MACD_FILTER:
                macd_line = last_candle['macd_line']
                macd_signal = last_candle['macd_signal']
                if pd.isna(macd_line) or macd_line >= macd_signal or macd_line >= 0:
                    macd_ok = False
            if macd_ok:
                vol_ok = True
                if USE_VOLUME_FILTER:
                    volume = last_candle['volume']
                    vol_ma = last_candle['volume_ma']
                    if pd.isna(vol_ma) or volume < vol_ma:
                        vol_ok = False
                if vol_ok:
                    trend_down = ema50 < ema200
                    touched_ema = (last_candle['h'] >= ema50 >= last_candle['l'])
                    bearish_rejection = (last_candle['c'] < last_candle['o']) and \
                                        ((last_candle['h'] - last_candle['o']) < (last_candle['c'] - last_candle['l']))
                    rsi_ok = 30 < rsi < 70
                    if trend_down and touched_ema and bearish_rejection and rsi_ok:
                        sl = ema200 + (atr_multiplier * atr)
                        sl_distance = sl - price
                        sl_pips = sl_distance / 0.0001
                        tp = price - 2 * sl_distance
                        return True, price, sl, tp, sl_pips, 'sell'

    return False, 0, 0, 0, 0, None


def main():
    global trades_today, last_trade_date, last_close_time, active_trade

    trades_today = count_all_trades_today()
    if active_trade is None:
        load_existing_open_position()
    print(f"Trades already taken today: {trades_today}, active trade: {active_trade is not None}")

    start_msg = (f"🟢 MyForexBotNY started – max {MAX_TRADES_PER_DAY} trades/day, "
                 f"buffer {MIN_MINUTES_BETWEEN_TRADES}min, Buy & Sell. "
                 f"({trades_today} already taken)")
    print(start_msg)
    send_telegram_message(start_msg)

    try:
        while True:
            now = datetime.now(tz)

            if now.hour > TRADING_HOURS_END or (now.hour == TRADING_HOURS_END and now.minute >= 5):
                stop_msg = (f"🔴 MyForexBotNY stopped – End of session ({now.strftime('%H:%M')}), "
                            f"{trades_today} trade(s) taken today.")
                print(stop_msg)
                send_telegram_message(stop_msg)
                save_status_json({})
                break

            today = now.date()
            if last_trade_date != today:
                trades_today = count_all_trades_today()
                last_trade_date = today
                last_close_time = None
                closed_trades_today.clear()
                if active_trade is None:
                    load_existing_open_position()

            check_closed_trade()

            if not hasattr(main, "next_news_check"):
                main.next_news_check = now
            if now >= main.next_news_check:
                update_news_filters()
                main.next_news_check = now + timedelta(seconds=60)

            in_trading_hours = TRADING_HOURS_START <= now.hour < TRADING_HOURS_END
            calendar_blocked = is_news_time_blocked()

            can_trade_time = True
            if last_close_time is not None:
                elapsed = now - last_close_time
                if elapsed < timedelta(minutes=MIN_MINUTES_BETWEEN_TRADES):
                    can_trade_time = False
                    remaining = MIN_MINUTES_BETWEEN_TRADES - int(elapsed.total_seconds()/60)
                    print(f"⏳ Post-close cooldown – {remaining} min remaining")

            can_trade = (active_trade is None
                         and trades_today < MAX_TRADES_PER_DAY
                         and in_trading_hours
                         and not calendar_blocked
                         and can_trade_time)

            pair_indicators = {}

            if can_trade:
                for pair in PAIRS:
                    if has_open_position(pair):
                        print(f"{pair}: position already open. Skip.")
                        continue

                    spread = get_spread(pair)
                    print(f"{now.strftime('%H:%M:%S')} {pair} spread: {spread:.5f}", end='')

                    if not is_spread_ok(pair, spread):
                        reason = f"Spread too high (avg {sum(spread_history[pair])/len(spread_history[pair]):.5f})"
                        print(" -> " + reason)
                        rejected_signals.append({
                            "time": now.strftime("%H:%M:%S"),
                            "pair": pair,
                            "direction": None,
                            "reason": reason
                        })
                        continue

                    df = get_candles(pair)
                    last_candle = df.iloc[-2]
                    adx_val = last_candle['adx']
                    ema50_val = last_candle['ema50']
                    ema200_val = last_candle['ema200']
                    plus_di = last_candle['plus_di']
                    minus_di = last_candle['minus_di']
                    rsi_val = last_candle['rsi']
                    macd_line = last_candle['macd_line']
                    macd_signal = last_candle['macd_signal']

                    pair_indicators[pair] = {
                        "price": last_candle['c'],
                        "spread": spread,
                        "adx": adx_val,
                        "plus_di": plus_di,
                        "minus_di": minus_di,
                        "ema_orientation": "bullish" if ema50_val > ema200_val else "bearish",
                        "macd_signal": "bullish" if macd_line > macd_signal else "bearish",
                        "last_signal": None
                    }

                    print(f" | ADX:{adx_val:.1f} +DI:{plus_di:.1f} -DI:{minus_di:.1f} "
                          f"EMA50:{ema50_val:.5f} EMA200:{ema200_val:.5f} "
                          f"RSI:{rsi_val:.1f} MACD:{macd_line:.5f} Sig:{macd_signal:.5f}", end='')

                    signal, price, sl, tp, sl_pips, direction = check_signal(df, pair)
                    if signal:
                        print(f" -> SIGNAL {direction}")
                        pair_indicators[pair]["last_signal"] = direction
                        balance_response = retry_api_call(ctx.account.summary, ACCOUNT_ID)
                        balance = get_account_balance(balance_response)
                        sl_distance = price - sl if direction == 'buy' else sl - price
                        units = calculate_units(balance, sl_distance, pair)
                        success = place_trade(pair, price, sl, tp, units, direction)
                        if success:
                            break
                    else:
                        print(" -> no signal")
                        reason = "No pullback setup"
                        if adx_val < PAIR_CONFIG[pair]["ADX_THRESHOLD"]:
                            reason = f"ADX too low ({adx_val:.1f} < {PAIR_CONFIG[pair]['ADX_THRESHOLD']})"
                        elif plus_di > minus_di:
                            pass
                        rejected_signals.append({
                            "time": now.strftime("%H:%M:%S"),
                            "pair": pair,
                            "direction": None,
                            "reason": reason,
                            "indicators": {
                                "adx": adx_val, "plus_di": plus_di, "minus_di": minus_di,
                                "ema50": ema50_val, "ema200": ema200_val,
                                "rsi": rsi_val, "macd_line": macd_line, "macd_signal": macd_signal
                            }
                        })
            else:
                for pair in PAIRS:
                    spread = get_spread(pair)
                    pair_indicators[pair] = {"spread": spread}

            save_status_json(pair_indicators)

            time.sleep(30)

    except KeyboardInterrupt:
        stop_msg = "🔴 Bot stopped manually (Ctrl+C)"
        print(stop_msg)
        send_telegram_message(stop_msg)


if __name__ == "__main__":
    main()
