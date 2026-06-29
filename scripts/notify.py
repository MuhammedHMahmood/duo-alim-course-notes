"""Discord webhook notifications + run logging for the pipeline.

The webhook URL is read from Windows Credential Manager (keyring) under
service 'duo-class-notes', key 'discord_webhook_url'. If it isn't set, notify()
still writes to logs/runs.log and simply skips the Discord post (no crash).
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from common import get_api_key, PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "runs.log"

# Embed colors (match the mockup): green / red / blue.
COLORS = {"success": 0x639922, "error": 0xE24B4A, "info": 0x378ADD}


def _webhook_url():
    try:
        return get_api_key("discord_webhook_url")
    except Exception:
        return None


def _log(line):
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")


def notify(level, title, description=None, fields=None, footer=None):
    """Append to logs/runs.log and, if a webhook is configured, post a Discord embed.

    fields: list of (name, value) tuples, rendered as inline embed fields.
    Returns True if the Discord post succeeded, False otherwise (never raises).
    """
    log_line = f"{level.upper()}: {title}"
    if description:
        log_line += f" — {description}"
    if fields:
        log_line += " | " + ", ".join(f"{k}: {v}" for k, v in fields)
    _log(log_line)

    url = _webhook_url()
    if not url:
        return False

    embed = {
        "title": title[:256],
        "color": COLORS.get(level, COLORS["info"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if description:
        embed["description"] = description[:4000]
    if fields:
        embed["fields"] = [{"name": str(k), "value": str(v), "inline": True} for k, v in fields]
    if footer:
        embed["footer"] = {"text": footer}

    data = json.dumps({"embeds": [embed]}).encode("utf-8")
    # Discord's Cloudflare edge 403s the default "Python-urllib" UA — send a real one.
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "duo-class-notes/1.0"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        _log(f"WARN: Discord post failed: {e}")
        return False
