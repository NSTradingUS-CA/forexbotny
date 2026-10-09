"""
Guardian : lit status.json distant et envoie les rappels Telegram critiques
avant/après la fin de session NY, même si le workflow principal a été tué.

Fenêtre utile réelle : 16:44 → 17:14 ET
  → complète les reminders du bot principal (16:50-16:54, 16:55-16:57, 16:58)
  → couvre la clôture OANDA à 16:59 ET et l'arrêt bot à 17:05 ET

CORRECTIONS 2026-10-09 :
- Alignement sur les reminders du bot principal :
    * Cron 1 = 16:50 ET → fenêtre pré-clôture 16:44-16:53
    * Cron 2 = 16:56 ET → fenêtre dernier appel 16:53-17:03
    * Cron 3 = 17:06 ET → fenêtre post-mortem 17:03-17:14
- Fenêtres élargies à ±6-7 min pour tolérer les retards GitHub cron
- Une seule alerte par fenêtre (3 alertes max par jour)
- Le YAML ne doit contenir que 3 crons (20:50, 20:56, 21:06 UTC en EDT)
  pour éviter les doublons d'alerte
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
    minutes_now = now.hour * 60 + now.minute

    # Fenêtres en minutes depuis minuit (heure ET).
    # Alignées sur les reminders du bot principal :
    #   bot : 16:50-16:54 (reminders) / 16:55-16:57 (close) / 16:58 (critique) / 17:05 (stop)
    #
    # Chaque fenêtre tolère un retard GitHub cron de ±6-7 min.
    # Bornes supérieures exclusives pour éviter les chevauchements.
    WIN_PRE_CLOSE_START   = 16 * 60 + 44    # 16:44
    WIN_PRE_CLOSE_END     = 16 * 60 + 53    # 16:53 (exclu)
    WIN_LAST_CALL_START   = 16 * 60 + 53    # 16:53
    WIN_LAST_CALL_END     = 17 * 60 + 3     # 17:03 (exclu)
    WIN_POST_MORTEM_START = 17 * 60 + 3     # 17:03
    WIN_POST_MORTEM_END   = 17 * 60 + 14    # 17:14 (exclu)

    in_any_window = (
        (WIN_PRE_CLOSE_START <= minutes_now < WIN_PRE_CLOSE_END) or
        (WIN_LAST_CALL_START <= minutes_now < WIN_LAST_CALL_END) or
        (WIN_POST_MORTEM_START <= minutes_now < WIN_POST_MORTEM_END)
    )
    if not in_any_window:
        print(f"{now.strftime('%H:%M')} – Hors fenêtre utile (16:44–17:14 ET), sortie sans action.")
        return

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

    # === Fenêtre 1 : pré-clôture (16:44 → 16:53) ===
    # Alignée sur les reminders bot de 16:50-16:54.
    if WIN_PRE_CLOSE_START <= minutes_now < WIN_PRE_CLOSE_END:
        send_telegram(
            f"⏰ <b>Guardian – fermeture imminente</b>\n"
            f"Pair : {pair}\n"
            f"Prix actuel : {current}\n"
            f"SL : {sl} | TP2 : {tp2}\n"
            f"P&L latent : {pnl_cad:.2f} CAD\n"
            f"Marché ferme à 16:59 NY. Fermez manuellement si nécessaire."
        )
        print(f"{now.strftime('%H:%M')} – Rappel pré-clôture envoyé.")

    # === Fenêtre 2 : dernier appel (16:53 → 17:03) ===
    # Alignée sur la clôture forcée bot (16:55-16:57) et l'alerte critique (16:58).
    elif WIN_LAST_CALL_START <= minutes_now < WIN_LAST_CALL_END:
        send_telegram(
            f"🚨 <b>Guardian – DERNIER APPEL</b>\n"
            f"Trade {pair} toujours ouvert.\n"
            f"P&L latent : {pnl_cad:.2f} CAD\n"
            f"Fermez MAINTENANT ou laissez le broker clôturer."
        )
        print(f"{now.strftime('%H:%M')} – Dernier appel envoyé.")

    # === Fenêtre 3 : post-mortem (17:03 → 17:14) ===
    # Alignée sur l'arrêt bot à 17:05.
    elif WIN_POST_MORTEM_START <= minutes_now < WIN_POST_MORTEM_END:
        send_telegram(
            f"🕒 <b>Guardian – post-mortem</b>\n"
            f"Session NY fermée.\n"
            f"Trade {pair} : P&L final inconnu. Vérifiez OANDA."
        )
        print(f"{now.strftime('%H:%M')} – Post-mortem envoyé.")


if __name__ == "__main__":
    main()
