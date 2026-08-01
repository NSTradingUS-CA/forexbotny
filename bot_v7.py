import v20
import pandas as pd
import pytz
from datetime import datetime, timedelta
import time
import csv
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# ========== CONFIG ==========
API_KEY = os.getenv("OANDA_API_KEY")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_URL = "https://api-fxpractice.oanda.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PAIRS = ["EUR_USD", "GBP_USD"]
RISK_PERCENT = 1.0
TRADING_HOURS_START = 0
TRADING_HOURS_END = 23
TIMEZONE = 'America/Toronto'
MAX_TRADES_PER_DAY = 1
TRAILING_DISTANCE_PIPS = 20
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5
MAX_SPREAD_PIPS = 2.0
NEWS_BLOCK_MINUTES = 30
HIGH_IMPACT_EVENTS = ["NFP", "CPI", "FOMC", "Interest Rate", "GDP", "Retail Sales"]
ADX_PERIOD = 14
ADX_THRESHOLD = 25
USE_MACD_FILTER = True
USE_VOLUME_FILTER = True
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLUME_MA_PERIOD = 20
# ============================

ctx = v20.Context(OANDA_URL, token=API_KEY)
trades_today = 0
last_trade_date = None
news_cache = {"time": None, "events": []}
tz = pytz.timezone(TIMEZONE)
active_trade = None   # stocke les infos du trade en cours : { 'trade_id', 'pair', 'units', 'entry_price' }


def send_telegram_message(text):
    """Envoie un message via le bot Telegram configuré."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured (missing token or chat ID). Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"Telegram send failed: {resp.text}")
    except Exception as e:
        print(f"Telegram error: {e}")


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
            print(f"⛔ News block: {event['title']} at {event['time'].strftime('%H:%M')} local")
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
    params = {
        "count": count,
        "granularity": "H1",
        "price": "M"
    }
    response = retry_api_call(ctx.instrument.candles, instrument, **params)
    candles = response.body['candles']
    rows = []
    for c in candles:
        if c['complete']:
            rows.append({
                'time': pd.to_datetime(c['time']),
                'o': float(c['mid']['o']),
                'h': float(c['mid']['h']),
                'l': float(c['mid']['l']),
                'c': float(c['mid']['c']),
                'volume': int(c['volume'])
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
    response = retry_api_call(ctx.pricing.get, instrument)
    price = response.body['prices'][0]
    spread = float(price['asks'][0]['price']) - float(price['bids'][0]['price'])
    return spread


def has_open_position(instrument):
    try:
        response = retry_api_call(ctx.position.get, ACCOUNT_ID)
        for pos in response.body['positions']:
            if pos['instrument'] == instrument:
                long_units = float(pos['long']['units'])
                short_units = float(pos['short']['units'])
                if long_units != 0 or short_units != 0:
                    return True
        return False
    except Exception as e:
        print(f"Position check failed: {e}")
        return False


def calculate_units(balance, sl_price_distance, instrument):
    risk_amount = balance * (RISK_PERCENT / 100)
    pip_value = 0.0001
    units = int(risk_amount / (sl_price_distance * pip_value))
    return max(1000, units)


def place_trade(instrument, entry, sl, tp, units):
    global active_trade
    trailing_distance = str(round(TRAILING_DISTANCE_PIPS * 0.0001, 5))
    order_data = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "stopLossOnFill": {"price": f"{sl:.5f}"},
            "takeProfitOnFill": {"price": f"{tp:.5f}"},
            "trailingStopLossOnFill": {"distance": trailing_distance}
        }
    }
    r = retry_api_call(ctx.order.create, ACCOUNT_ID, order_data)

    # Extraire les infos du trade ouvert
    try:
        trade_opened = r.body['orderFillTransaction']['tradeOpened']
        trade_id = trade_opened['tradeID']
        entry_price = float(trade_opened['price'])
        units_filled = trade_opened['units']
        active_trade = {
            'trade_id': trade_id,
            'pair': instrument,
            'units': units_filled,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp
        }
    except (KeyError, TypeError) as e:
        print(f"Warning: Could not extract trade details: {e}")
        active_trade = None

    # Message Telegram
    msg = (f"<b>✅ Trade ouvert</b>\n"
           f"Paire : {instrument}\n"
           f"Type : {'Achat' if units > 0 else 'Vente'}\n"
           f"Volume : {units} unités\n"
           f"Entrée : {entry:.5f}\n"
           f"Stop Loss : {sl:.5f}\n"
           f"Take Profit : {tp:.5f}\n"
           f"Trailing Stop : {TRAILING_DISTANCE_PIPS} pips\n"
           f"Heure : {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
    send_telegram_message(msg)

    print(f"✅ Trade placed on {instrument} - {units} units")
    log_trade({
        "time": datetime.now(tz).isoformat(),
        "pair": instrument,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "units": units,
        "status": "OPEN"
    })


def check_closed_trade():
    """Si un trade était actif et que la position n'est plus ouverte, envoie la notification de clôture."""
    global active_trade
    if active_trade is None:
        return

    pair = active_trade['pair']
    if has_open_position(pair):
        return  # toujours ouvert

    # Récupérer le dernier trade fermé pour cette paire
    try:
        resp = retry_api_call(ctx.trade.list, ACCOUNT_ID,
                              instrument=pair,
                              count=1,
                              state='CLOSED')
        closed_trades = resp.body.get('trades', [])
        if closed_trades:
            last_trade = closed_trades[0]
            realized_pl = float(last_trade['realizedPL'])
            close_price = float(last_trade['price'])  # prix de clôture
            entry_price = active_trade['entry_price']
            units = active_trade['units']

            msg = (f"<b>🔴 Trade clôturé</b>\n"
                   f"Paire : {pair}\n"
                   f"Entrée : {entry_price:.5f}\n"
                   f"Sortie : {close_price:.5f}\n"
                   f"Volume : {units}\n"
                   f"P&L : {realized_pl:.2f} {('USD' if pair.endswith('USD') else '')}\n"
                   f"Heure : {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
            send_telegram_message(msg)

            # Mise à jour du log local
            log_trade({
                "time": datetime.now(tz).isoformat(),
                "pair": pair,
                "entry": entry_price,
                "exit": close_price,
                "units": units,
                "pnl": realized_pl,
                "status": "CLOSED"
            })
    except Exception as e:
        print(f"Erreur lors de la récupération du trade fermé : {e}")
        # On envoie quand même une notification sans détails
        send_telegram_message(f"⚠️ Trade sur {pair} clôturé (détails non disponibles).")

    active_trade = None


def check_signal(df, instrument):
    if len(df) < 200:
        return False, 0, 0, 0, 0

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
        return False, 0, 0, 0, 0

    if adx < ADX_THRESHOLD or plus_di <= minus_di:
        return False, 0, 0, 0, 0

    if USE_MACD_FILTER:
        macd_line = last_candle['macd_line']
        macd_signal = last_candle['macd_signal']
        if pd.isna(macd_line) or pd.isna(macd_signal):
            return False, 0, 0, 0, 0
        if macd_line <= macd_signal or macd_line <= 0:
            return False, 0, 0, 0, 0

    if USE_VOLUME_FILTER:
        volume = last_candle['volume']
        vol_ma = last_candle['volume_ma']
        if pd.isna(vol_ma) or volume < vol_ma:
            return False, 0, 0, 0, 0

    trend_up = ema50 > ema200
    touched_ema = (last_candle['l'] <= ema50 <= last_candle['h'])
    bullish_rejection = (last_candle['c'] > last_candle['o']) and \
                        ((last_candle['o'] - last_candle['l']) > (last_candle['h'] - last_candle['c']))
    rsi_ok = 30 < rsi < 70

    if trend_up and touched_ema and bullish_rejection and rsi_ok:
        sl = ema200 - (ATR_MULTIPLIER * atr)
        sl_price_distance = price - sl
        sl_pips = sl_price_distance / 0.0001
        tp = price + 2 * sl_price_distance
        return True, price, sl, tp, sl_pips

    return False, 0, 0, 0, 0


def main():
    global trades_today, last_trade_date
    print(f"OANDA Bot V7 (Telegram notifications) started. Timezone: {TIMEZONE}")
    print(f"Trading window: {TRADING_HOURS_START:02d}:00 - {TRADING_HOURS_END:02d}:00 local")
    try:
        while True:
            now = datetime.now(tz)

            # Arrêt automatique 5 minutes après la fin de la séance
            if now.hour > TRADING_HOURS_END or (now.hour == TRADING_HOURS_END and now.minute >= 5):
                print(f"🛑 Trading window closed ({now.strftime('%H:%M')}). Bot shutting down.")
                break

            today = now.date()
            if last_trade_date != today:
                trades_today = 0
                last_trade_date = today

            # Vérifier la clôture d'un trade existant (même hors heures de trading)
            check_closed_trade()

            in_trading_hours = TRADING_HOURS_START <= now.hour < TRADING_HOURS_END
            news_blocked = is_news_time_blocked()
            can_trade = (trades_today < MAX_TRADES_PER_DAY and in_trading_hours and not news_blocked)

            if can_trade:
                for pair in PAIRS:
                    if has_open_position(pair):
                        print(f"{pair}: position already open. Skip.")
                        continue
                    spread = get_spread(pair)
                    if spread > MAX_SPREAD_PIPS * 0.0001:
                        print(f"{pair}: spread too high ({spread:.5f}). Skip.")
                        continue
                    df = get_candles(pair)
                    signal, price, sl, tp, sl_pips = check_signal(df, pair)
                    if signal:
                        balance_response = retry_api_call(ctx.account.summary, ACCOUNT_ID)
                        balance = float(balance_response.body['account']['balance'])
                        sl_price_distance = price - sl
                        units = calculate_units(balance, sl_price_distance, pair)
                        place_trade(pair, price, sl, tp, units)
                        trades_today += 1
                        break
            elif news_blocked:
                print(f"{now.strftime('%H:%M:%S')} - News block active")
            else:
                print(f"{now.strftime('%H:%M:%S')} - Waiting... Trades today: {trades_today}")

            time.sleep(30)

    except KeyboardInterrupt:
        print("\nBot stopped manually.")


if __name__ == "__main__":
    main()
