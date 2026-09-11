"""
Guardian : lit status.json distant et envoie les rappels Telegram critiques
avant la fin de session NY, même si le workflow principal a été tué.
"""
import os
import json
import base64
import requests
import pytz
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GH_PAT = os.getenv("GH_PAT")
REPO = os.getenv("GITHUB_REPOSITORY")
tz = pytz.timezone('America/Toronto')


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram non configuré.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


def fetch_status():
    if not GH_PAT or not REPO:
        print("GH_PAT ou GITHUB_REPOSITORY manquant.")
        return None
    try:
        url = f"https://api.github.com/repos/{REPO}/contents/status.json"
        headers = {"Authorization": f"token {GH_PAT}",
                   "Accept": "application/vnd.github.v3+json",
                   "Cache-Control": "no-cache"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"]).decode()
            return json.loads(content)
    except Exception as e:
        print(f"fetch_status error: {e}")
    return None


def main():
    now = datetime.now(tz)
    status = fetch_status()
    if status is None:
        print("status.json introuvable – rien à faire.")
        return

    active = status.get("active_trade")
    if not active:
        print(f"{now.strftime('%H:%M')} – Aucun trade actif. Guardian silencieux.")
        return

    pair = active.get("pair", "?")
    pnl_cad = active.get("unrealized_pnl_cad", 0)
    current = active.get("current_price", 0)
    sl = active.get("sl", 0)
    tp2 = active.get("tp2", 0)

    # 16:45 → rappel de fermeture imminente
    if now.hour == 16 and 45 <= now.minute < 50:
        send_telegram(
            f"⏰ <b>Guardian 16:45</b> – Trade encore ouvert :\n"
            f"Pair : {pair}\n"
            f"Prix actuel : {current}\n"
            f"SL : {sl} | TP2 : {tp2}\n"
            f"P&L latent : {pnl_cad:.2f} CAD\n"
            f"Marché ferme à 16:59 NY. Fermez manuellement si nécessaire."
        )
        print("Rappel 16:45 envoyé.")

    # 16:55 → dernier appel
    elif now.hour == 16 and 55 <= now.minute < 60:
        send_telegram(
            f"🚨 <b>Guardian 16:55</b> – DERNIER APPEL :\n"
            f"Trade {pair} toujours ouvert.\n"
            f"P&L latent : {pnl_cad:.2f} CAD\n"
            f"Fermez MAINTENANT ou laissez le broker clôturer."
        )
        print("Rappel 16:55 envoyé.")

    # 17:10 → post-mortem
    elif now.hour == 17 and now.minute >= 10 and now.minute < 15:
        send_telegram(
            f"🕒 <b>Guardian 17:10</b> – Session NY fermée.\n"
            f"Trade {pair} : P&L final inconnu. Vérifiez OANDA."
        )
        print("Post-mortem 17:10 envoyé.")

    else:
        print(f"{now.strftime('%H:%M')} – Trade actif mais hors fenêtre d'alerte.")


if __name__ == "__main__":
    main()
