from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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

    def send_document(
        self,
        chat_id: int,
        file_path: str,
        caption: str = "",
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Send a document file to a Telegram chat.

        Args:
            chat_id: Target chat ID
            file_path: Absolute path to the file to send
            caption: Optional caption (max 1024 chars)
            filename: Optional custom filename (defaults to original name)

        Returns:
            Response data from Telegram API
        """
        url = f"{self.base_url}/bot{self.token}/sendDocument"
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > 50:
            raise ValueError(f"File too large for Telegram: {file_size_mb:.1f} MB (max 50 MB)")

        with open(file_path, "rb") as f:
            files = {"document": (filename or path.name, f)}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
            resp = requests.post(url, data=data, files=files, timeout=(30, 120))

        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram sendDocument failed: {result}")
        return result
