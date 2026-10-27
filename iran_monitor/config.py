import os
from dataclasses import dataclass, field
from pathlib import Path


def load_env(path: Path, environment=None) -> dict[str, str]:
    values = {}
    if path.exists():
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not key.strip().replace("_", "").isalnum():
                raise ValueError(f"Invalid .env entry on line {index}")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    values.update(os.environ if environment is None else environment)
    return values


@dataclass(frozen=True)
class Config:
    bot_token: str = field(repr=False)
    chat_id: int
    radar_token: str = field(repr=False)
    poll_seconds: int = 300
    data_dir: Path = Path("data")

    @classmethod
    def from_values(cls, values):
        required = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CLOUDFLARE_API_TOKEN")
        missing = [key for key in required if not values.get(key, "").strip()]
        if missing:
            raise ValueError("Set these values in .env: " + ", ".join(missing))
        try:
            chat_id = int(values["TELEGRAM_CHAT_ID"])
            interval = int(values.get("POLL_SECONDS", "300"))
        except ValueError:
            raise ValueError("TELEGRAM_CHAT_ID and POLL_SECONDS must be integers") from None
        if chat_id <= 0:
            raise ValueError("TELEGRAM_CHAT_ID must be a positive private chat ID")
        if interval < 60:
            raise ValueError("POLL_SECONDS must be at least 60")
        token = values["TELEGRAM_BOT_TOKEN"].strip()
        if ":" not in token or not token.partition(":")[0].isdigit():
            raise ValueError("TELEGRAM_BOT_TOKEN must be a BotFather token")
        return cls(token, chat_id, values["CLOUDFLARE_API_TOKEN"].strip(), interval,
                   Path(values.get("DATA_DIR", "data")))
