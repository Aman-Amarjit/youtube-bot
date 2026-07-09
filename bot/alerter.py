import os
import requests
from datetime import datetime, timezone
from bot.config_loader import GameConfig

def send(config: GameConfig, exception_or_message: Exception, stage: str = "") -> None:
    """
    Send an alert to the configured webhook URL (Discord/Slack compatible or generic JSON).
    Only called when the outcome is designated to send an alert.
    """
    url = os.environ.get("ALERT_WEBHOOK_URL")
    if not url:
        print("WARNING: ALERT_WEBHOOK_URL environment variable is not set. Skipping alert.")
        return
        
    outcome = getattr(exception_or_message, "outcome", "error")
    message = str(exception_or_message)
    
    # Generic structured payload
    payload = {
        "game_name": config.game_name,
        "game_slug": config.game_slug,
        "outcome": outcome,
        "stage": stage,
        "message": message,
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Attempt simple Discord/Slack embedding if we detect Discord/Slack webhook patterns
    if "discord.com" in url or "hooks.slack.com" in url:
        discord_payload = {
            "embeds": [
                {
                    "title": f"🚨 Bot Alert: {config.game_name} ({config.game_slug})",
                    "color": 15158332,  # Red
                    "fields": [
                        {"name": "Outcome", "value": f"`{outcome}`", "inline": True},
                        {"name": "Stage", "value": f"`{stage or 'unknown'}`", "inline": True},
                        {"name": "Details", "value": message, "inline": False}
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
        # Override payload
        payload = discord_payload
        
    print(f"Sending webhook alert for outcome '{outcome}' in stage '{stage}'...")
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code not in (200, 201, 204):
            print(f"WARNING: Webhook returned status code {res.status_code}: {res.text}")
        else:
            print("Webhook alert successfully delivered.")
    except Exception as e:
        print(f"WARNING: Webhook delivery failed: {e}")
