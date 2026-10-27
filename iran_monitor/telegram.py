import json
import secrets

from .sources import SourceError, fetch_json


class TelegramError(RuntimeError):
    def __init__(self, code, retry_after=10):
        super().__init__(f"Telegram API error {code}")
        self.code = code
        self.retry_after = min(max(int(retry_after), 1), 3600)


def authorized_command(update: dict, owner_id: int) -> str | None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("id") != owner_id or chat.get("type") != "private":
        return None
    text = message.get("text") or ""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return None
    return parts[0].split("@", 1)[0][1:].lower()


class TelegramClient:
    def __init__(self, token: str, chat_id: int, request=fetch_json):
        self._base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = chat_id
        self.request = request

    def call(self, method, params=None, *, body=None, content_type="application/json", timeout=30):
        if body is None:
            body = json.dumps(params or {}, ensure_ascii=False).encode()
        try:
            response = self.request(self._base + method, data=body,
                                    headers={"Content-Type": content_type}, timeout=timeout)
        except SourceError as exc:
            if exc.status is not None:
                raise TelegramError(exc.status, exc.retry_after) from None
            raise
        if response.get("ok") is not True:
            raise TelegramError(response.get("error_code", "unknown"),
                                (response.get("parameters") or {}).get("retry_after", 10))
        return response["result"]

    def message(self, text):
        return self.call("sendMessage", {"chat_id": self.chat_id, "text": text[:4096],
                                         "link_preview_options": {"is_disabled": True}})

    def photo(self, png: bytes, caption: str):
        boundary = "iranmonitor" + secrets.token_hex(12)
        chunks = []
        for name, value in (("chat_id", str(self.chat_id)), ("caption", caption[:1024])):
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="traffic.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
        body = b"".join(chunks) + png + f"\r\n--{boundary}--\r\n".encode()
        return self.call("sendPhoto", body=body, content_type=f"multipart/form-data; boundary={boundary}")

    def updates(self, offset):
        return self.call("getUpdates", {"offset": offset, "timeout": 20,
                                        "allowed_updates": ["message"]}, timeout=30)
