"""Interactive, atomic credential setup; secrets are read from the terminal."""

import getpass
import os
import re
import tempfile
from pathlib import Path

from .config import Config, load_env
from .telegram import TelegramClient


def configure(path: Path, *, secret=getpass.getpass, ask=input, tell=print):
    previous = load_env(path, {})
    values = dict(previous)
    tell("Configure your private bot. Tokens are hidden; Enter keeps an existing value.")
    for key, label in (("TELEGRAM_BOT_TOKEN", "Telegram bot token: "),
                       ("CLOUDFLARE_API_TOKEN", "Cloudflare Radar read token: ")):
        values[key] = secret(label).strip() or previous.get(key, "")
        if not re.fullmatch(r"[A-Za-z0-9_:-]+", values[key]):
            raise ValueError(f"Invalid characters in {key}")
    chat = ask("Your private chat ID (or 'find' after sending /start to the bot): ").strip()
    if chat.lower() == "find":
        client = TelegramClient(values["TELEGRAM_BOT_TOKEN"], 0)
        if client.call("getWebhookInfo").get("url"):
            raise ValueError("This bot has a webhook; use a dedicated bot")
        updates = client.call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
        ids = {u["message"]["chat"]["id"] for u in updates
               if u.get("message", {}).get("chat", {}).get("type") == "private"}
        tell("Private chat IDs: " + (", ".join(map(str, sorted(ids))) or "none; send /start first"))
        chat = ask("Choose YOUR private chat ID: ").strip()
    values["TELEGRAM_CHAT_ID"] = chat or previous.get("TELEGRAM_CHAT_ID", "")
    Config.from_values(values)  # Fail before replacing working credentials.
    keys = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CLOUDFLARE_API_TOKEN", "POLL_SECONDS", "DATA_DIR")
    defaults = {"POLL_SECONDS": "300", "DATA_DIR": "data"}
    text = "".join(f"{key}={values.get(key, defaults.get(key, ''))}\n" for key in keys)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".monitor-env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    tell("Configuration saved privately. Run check before starting monitoring.")
