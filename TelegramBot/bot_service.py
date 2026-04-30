from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from TelegramBot.telegram_client import TelegramClient
from TelegramBot.text import split_telegram_text


@dataclass
class TelegramBotService:
    """Long-polling Telegram bot that forwards messages to OrbitronKernel."""

    telegram: TelegramClient
    poll_timeout_s: int = 30
    sleep_on_error_s: float = 2.0
    allowed_chat_ids: set[int] | None = None

    _offset: int = 0

    def _start_typing(self, chat_id: int) -> threading.Event:
        stop_event = threading.Event()

        def worker() -> None:
            # Telegram clients typically show typing for a few seconds.
            while not stop_event.wait(4.0):
                try:
                    self.telegram.send_chat_action(chat_id, action="typing")
                except Exception:
                    pass

        try:
            self.telegram.send_chat_action(chat_id, action="typing")
        except Exception:
            pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return stop_event

    def run_forever(self) -> None:
        self._offset = self._load_offset()

        # Initialize Orchestrator (the living agent) instead of direct kernel access
        import sys
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from OrbitronAgents.Orchestrator.KernelBridge import KernelBridge

        bridge = KernelBridge()

        while True:
            try:
                updates = self.telegram.get_updates(offset=self._offset, timeout_s=self.poll_timeout_s)
                for update in updates:
                    self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
                    self._save_offset(self._offset)

                    message = update.get("message") or update.get("edited_message")
                    if not isinstance(message, dict):
                        continue

                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    if not isinstance(chat_id, int):
                        continue
                    if self.allowed_chat_ids is not None and chat_id not in self.allowed_chat_ids:
                        continue

                    text = message.get("text")
                    if not isinstance(text, str) or not text.strip():
                        continue

                    user = message.get("from") or {}
                    username = user.get("username") or user.get("first_name") or "user"

                    stop_typing = self._start_typing(chat_id)
                    try:
                        # Use Orchestrator with session memory (includes personality & context)
                        answer = bridge.chat_with_session(f"[{username}] {text}", chat_id=chat_id)
                    finally:
                        stop_typing.set()

                    for chunk in split_telegram_text(answer):
                        self.telegram.send_message(chat_id, chunk)

            except KeyboardInterrupt:
                raise
            except Exception:
                time.sleep(self.sleep_on_error_s)

    def _offset_path(self) -> Path:
        root = Path.home() / ".orbitron"
        root.mkdir(parents=True, exist_ok=True)
        return root / "telegram_offset.json"

    def _load_offset(self) -> int:
        try:
            p = self._offset_path()
            if not p.exists():
                return 0
            obj = json.loads(p.read_text(encoding="utf-8"))
            v = obj.get("offset")
            return int(v) if v is not None else 0
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            p = self._offset_path()
            p.write_text(json.dumps({"offset": int(offset)}), encoding="utf-8")
        except Exception:
            pass


def parse_allowed_chat_ids(env_value: str) -> set[int] | None:
    allowed = (env_value or "").strip()
    if not allowed:
        return None

    ids: set[int] = set()
    for part in allowed.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids


def service_from_env() -> TelegramBotService:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing (set it in .env)")

    # Only allow specific user (ID: 8420261626)
    # Can be overridden via TELEGRAM_ALLOWED_CHAT_IDS env var
    env_allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if env_allowed:
        allowed = parse_allowed_chat_ids(env_allowed)
    else:
        allowed = {8420261626}  # Default: only Sven

    client = TelegramClient(token=token)
    return TelegramBotService(telegram=client, allowed_chat_ids=allowed)
