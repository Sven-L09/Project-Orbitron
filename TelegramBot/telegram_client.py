from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class TelegramClient:
    token: str
    base_url: str = "https://api.telegram.org"

    def get_updates(self, *, offset: int = 0, timeout_s: int = 30) -> list[dict[str, Any]]:
        url = f"{self.base_url}/bot{self.token}/getUpdates"
        params = {
            "timeout": timeout_s,
            "offset": offset,
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
        resp = requests.get(url, params=params, timeout=(10, timeout_s + 10))
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        result = data.get("result")
        if not isinstance(result, list):
            return []
        return [u for u in result if isinstance(u, dict)]

    def send_message(self, chat_id: int, text: str) -> None:
        url = f"{self.base_url}/bot{self.token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        resp = requests.post(url, json=payload, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        url = f"{self.base_url}/bot{self.token}/sendChatAction"
        payload = {"chat_id": chat_id, "action": action}
        resp = requests.post(url, json=payload, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendChatAction failed: {data}")
