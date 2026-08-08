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
GH_PAT = os.getenv("GH_PAT")
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
    "EUR_USD": {"MAX_SPREAD_PIPS": 2.5, "ADX_THRESHOLD": 20, "ATR_MULTIPLIER": 2.0},
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
last_news_block_time = None
news_sentiment_filter = {}

spread_history = {pair: [] for pair in PAIRS}
SPREAD_WINDOW = 5

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


# ----- Fonctions existantes inchangées (count_all_trades_today, load_existing_open_position,
#  is_spread_ok, send_telegram_message, get_finnhub_sentiment, update_news_filters,
#  get_high_impact_news, is_news_time_blocked, log_trade, retry_api_call, compute_adx,
#  compute_macd, get_candles, get_spread, has_open_position, calculate_units,
#  get_account_balance, place_trade, check_closed_trade, check_signal)
# (je les ai omises ici pour rester concis, elles sont strictement identiques à la version précédente)


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

            # ★ Nouveauté : collecter les indicateurs pour le cockpit MÊME hors séance
            pair_indicators = {}
            for pair in PAIRS:
                # Ne pas trader si position déjà ouverte, mais on peut quand même récupérer les prix
                if has_open_position(pair):
                    continue

                try:
                    spread = get_spread(pair)
                except:
                    continue

                # Vérification rapide du spread pour l'affichage (sans bloquer le cockpit)
                spread_ok = is_spread_ok(pair, spread)

                try:
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
                        "ema50": ema50_val,
                        "ema200": ema200_val,
                        "rsi": rsi_val,
                        "ema_orientation": "bullish" if ema50_val > ema200_val else "bearish",
                        "macd_signal": "bullish" if macd_line > macd_signal else "bearish",
                        "last_signal": None
                    }

                    # Log même hors trading
                    print(f"{now.strftime('%H:%M:%S')} {pair} spread: {spread:.5f} | "
                          f"ADX:{adx_val:.1f} +DI:{plus_di:.1f} -DI:{minus_di:.1f} "
                          f"EMA50:{ema50_val:.5f} EMA200:{ema200_val:.5f} "
                          f"RSI:{rsi_val:.1f} MACD:{macd_line:.5f} Sig:{macd_signal:.5f}")

                    # Détection de signal uniquement si can_trade est vrai
                    if can_trade and spread_ok:
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
                except Exception as e:
                    print(f"Error analyzing {pair}: {e}")

            # Mise à jour du status.json à chaque cycle (même vide)
            save_status_json(pair_indicators)

            time.sleep(30)

    except KeyboardInterrupt:
        stop_msg = "🔴 Bot stopped manually (Ctrl+C)"
        print(stop_msg)
        send_telegram_message(stop_msg)


if __name__ == "__main__":
    main()
