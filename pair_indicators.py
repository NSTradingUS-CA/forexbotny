import v20
import pandas as pd
import pytz
from datetime import datetime, timedelta
import time
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
GH_PAT = os.getenv("GH_PAT")
PAIRS = ["EUR_USD", "GBP_USD"]
TIMEZONE = 'America/Toronto'
SHUTDOWN_HOUR = 17
ATR_PERIOD = 14
ADX_PERIOD = 10
MACD_FAST = 5
MACD_SLOW = 13
MACD_SIGNAL = 9
REFRESH_SECONDS = 10
# ============================

ctx = v20.Context(OANDA_URL, token=API_KEY)
tz = pytz.timezone(TIMEZONE)


def retry_api_call(func, *args, **kwargs):
    for i in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"API attempt {i+1}/3 failed: {e}")
            time.sleep(3)
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
    return df


def get_spread(instrument):
    response = retry_api_call(ctx.pricing.get, ACCOUNT_ID, instruments=instrument)
    price = response.body['prices'][0]
    spread = float(price.asks[0].price) - float(price.bids[0].price)
    return spread


def collect_indicators(pair):
    try:
        spread = get_spread(pair)
    except:
        return None
    try:
        df = get_candles(pair)
        last_candle = df.iloc[-2]
        return {
            "price": last_candle['c'],
            "spread": spread,
            "adx": last_candle['adx'],
            "plus_di": last_candle['plus_di'],
            "minus_di": last_candle['minus_di'],
            "ema50": last_candle['ema50'],
            "ema200": last_candle['ema200'],
            "rsi": last_candle['rsi'],
            "atr": last_candle['atr'],
            "ema_orientation": "bullish" if last_candle['ema50'] > last_candle['ema200'] else "bearish",
            "macd_signal": "bullish" if last_candle['macd_line'] > last_candle['macd_signal'] else "bearish",
            "last_signal": None
        }
    except Exception as e:
        print(f"Erreur get_candles {pair} : {e}")
        return None


def push_indicators(pair_indicators):
    if not GH_PAT:
        return
    try:
        url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}/contents/pair_indicators.json"
        headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json",
                   "Cache-Control": "no-cache"}
        resp = requests.get(url, headers=headers, timeout=10)
        sha = resp.json().get("sha") if resp.status_code == 200 else None
        content = json.dumps(pair_indicators, indent=2, default=str).encode()
        payload = {"message": "Update pair indicators", "content": base64.b64encode(content).decode(), "branch": "main"}
        if sha:
            payload["sha"] = sha
        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_resp.status_code not in (200, 201):
            print(f"Push pair_indicators.json failed: {put_resp.status_code}")
    except Exception as e:
        print(f"Error pushing pair_indicators.json: {e}")


def main():
    print(f"🟢 Pair Indicators started – refresh every {REFRESH_SECONDS}s until {SHUTDOWN_HOUR}:05")
    try:
        while True:
            now = datetime.now(tz)
            if now.hour > SHUTDOWN_HOUR or (now.hour == SHUTDOWN_HOUR and now.minute >= 5):
                print("🔴 Pair Indicators stopped – shutdown time reached")
                break

            pair_indicators = {}
            for pair in PAIRS:
                indicators = collect_indicators(pair)
                if indicators:
                    pair_indicators[pair] = indicators
                    print(f"{now.strftime('%H:%M:%S')} {pair} price={indicators['price']:.5f} spread={indicators['spread']:.5f}")

            if pair_indicators:
                push_indicators(pair_indicators)

            time.sleep(REFRESH_SECONDS)

    except KeyboardInterrupt:
        print("\nPair Indicators stopped manually.")


if __name__ == "__main__":
    main()
