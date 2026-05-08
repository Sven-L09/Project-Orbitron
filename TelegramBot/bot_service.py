from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

import requests

from TelegramBot.telegram_client import TelegramClient
from TelegramBot.text import split_telegram_text


@dataclass
class TelegramBotService:
    """Long-polling Telegram bot that forwards messages to ServiceSystem."""

    telegram: TelegramClient
    poll_timeout_s: int = 30
    sleep_on_error_s: float = 2.0
    allowed_chat_ids: set[int] | None = None
    message_handler: Optional[Callable[[str, int, str, Callable[[str], None]], Union[str, list[str]]]] = None
    service_system: Any = None  # Reference to ServiceSystem for status/restart/reset

    _offset: int = 0

    def _handle_command(self, text: str, chat_id: int, username: str, send: Callable[[str], None]) -> bool:
        """Handle bot commands. Returns True if the text was a command (and handled)."""
        text_stripped = text.strip()
        if not text_stripped.startswith("/"):
            return False

        # Split command and args: "/status" or "/reset 123"
        parts = text_stripped.split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "/status":
            self._cmd_status(chat_id, username, send)
            return True

        if command == "/restart":
            self._cmd_restart(chat_id, username, send)
            return True

        if command == "/reset":
            self._cmd_reset(chat_id, username, send)
            return True

        return False

    def _cmd_status(self, chat_id: int, username: str, send: Callable[[str], None]) -> None:
        """Handle /status command — show system status."""
        logger = logging.getLogger("TelegramBot")
        logger.info(f"[Telegram] /status command from {username}")

        lines = ["Orbitron System Status", "=" * 30]

        # Gather status from ServiceSystem if available
        service = self._get_service_system()
        if service:
            status = service.get_status()
            lines.append(f"Running: {'Yes' if status.get('running') else 'No'}")
            lines.append(f"Uptime: {status.get('uptime', 'N/A')}")

            # Model info
            if service.kernel and hasattr(service.kernel, 'ollama'):
                ollama = service.kernel.ollama
                lines.append(f"Model: {ollama.model}")
                lines.append(f"API: {ollama.base_url}")

            # Context / session info
            if service.kernel and hasattr(service.kernel, '_sessions'):
                sessions = service.kernel._sessions
                cache_size = len(sessions._cache)
                total_messages = sum(
                    len(s) for s in sessions._cache.values() if isinstance(s, list)
                )
                lines.append(f"Active Sessions: {cache_size}")
                lines.append(f"Total Messages in Context: {total_messages}")

                # Per-session detail for the requesting user
                user_session = sessions._cache.get(chat_id)
                if user_session and isinstance(user_session, list):
                    msg_count = len(user_session)
                    # Rough token estimate: ~4 chars per token
                    total_chars = sum(
                        len(m.get("content", "")) for m in user_session if isinstance(m, dict)
                    )
                    est_tokens = total_chars // 4
                    lines.append(f"Your Context: {msg_count} msgs, ~{est_tokens} tokens")

            # Component status
            components = status.get("components", {})
            comp_status = {}
            if service.message_bus:
                bus_stats = service.message_bus.get_stats()
                comp_status["MessageBus"] = f"OK (msgs: {bus_stats.get('messages_published', 0)})"
            if service.orchestrator:
                comp_status["Orchestrator"] = "OK"
                orch = components.get("orchestrator", {})
                if isinstance(orch, dict):
                    tasks = orch.get("tasks", {})
                    if isinstance(tasks, dict):
                        comp_status["Orchestrator"] = f"OK (tasks: {tasks.get('total', 0)})"
            if service.planner:
                comp_status["Planner"] = "OK"
            if service.executor:
                comp_status["Executor"] = "OK"

            for name, state in comp_status.items():
                lines.append(f"{name}: {state}")

            # Lifetime events
            lines.append(f"Events: {status.get('lifetime_events', 0)}")
        else:
            lines.append("ServiceSystem not available")

        send("\n".join(lines))

    def _cmd_restart(self, chat_id: int, username: str, send: Callable[[str], None]) -> None:
        """Handle /restart command — restart the application."""
        logger = logging.getLogger("TelegramBot")
        logger.info(f"[Telegram] /restart command from {username}")

        send("Restarting Orbitron...")

        # Graceful shutdown of ServiceSystem
        service = self._get_service_system()
        if service:
            try:
                service.stop()
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")

        logger.info("[Telegram] Initiating restart via os.execv")
        # Re-exec the current process
        time.sleep(1)  # Give time for the message to be sent
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _cmd_reset(self, chat_id: int, username: str, send: Callable[[str], None]) -> None:
        """Handle /reset command — clear message history context."""
        logger = logging.getLogger("TelegramBot")
        logger.info(f"[Telegram] /reset command from {username}")

        service = self._get_service_system()
        if not service or not service.kernel:
            send("Kernel nicht verfügbar — Reset fehlgeschlagen.")
            return

        # Clear the session for this chat_id
        service.kernel.clear_session(chat_id)

        # Also clear orchestrator memory if available
        if service.orchestrator and hasattr(service.orchestrator, 'memory'):
            try:
                service.orchestrator.memory.short_term.clear()
                logger.info("[Telegram] Orchestrator short-term memory cleared")
            except Exception as e:
                logger.warning(f"Could not clear orchestrator memory: {e}")

        logger.info(f"[Telegram] Session cleared for chat_id={chat_id}")
        send("Context zurückgesetzt. Neues Gespräch gestartet.")

    def _get_service_system(self):
        """Get the ServiceSystem instance."""
        return self.service_system

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

        logger = logging.getLogger("TelegramBot")
        logger.info("Telegram bot started")

        # Fallback to KernelBridge only if no handler is provided
        bridge = None
        if self.message_handler is None:
            import sys
            from pathlib import Path
            project_root = Path(__file__).resolve().parents[1]
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from OrbitronAgents.Orchestrator.KernelBridge import KernelBridge
            bridge = KernelBridge()
            logger.warning("No message_handler provided, using KernelBridge fallback")

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

                    logger.info(f"[Telegram] Message from {username} (chat_id={chat_id}): {text[:60]}...")

                    def _send(msg: str) -> None:
                        for chunk in split_telegram_text(msg):
                            self.telegram.send_message(chat_id, chunk)

                    # Check for bot commands first
                    if self._handle_command(text, chat_id, username, _send):
                        continue

                    stop_typing = self._start_typing(chat_id)
                    try:
                        # Route via ServiceSystem handler if available
                        if self.message_handler:
                            logger.info(f"[Telegram] Routing to ServiceSystem handler for task processing")
                            try:
                                answer = self.message_handler(text, chat_id, username, _send)
                            except TypeError:
                                # Backwards compatibility for 3-arg handlers
                                answer = self.message_handler(text, chat_id, username)
                        else:
                            # Use Orchestrator with session memory (includes personality & context)
                            answer = bridge.chat_with_session(f"[{username}] {text}", chat_id=chat_id)
                    finally:
                        stop_typing.set()

                    if isinstance(answer, list):
                        for msg in answer:
                            _send(msg)
                        total_len = sum(len(m) for m in answer)
                    else:
                        _send(answer)
                        total_len = len(answer)

                    logger.info(f"[Telegram] Response sent to {username} ({total_len} chars)")

            except KeyboardInterrupt:
                raise
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 409:
                    logger.warning("[Telegram] 409 Conflict - another bot instance may be running. Waiting 10s...")
                    time.sleep(10.0)
                else:
                    logger.exception("[Telegram] HTTP error: %s", e)
                    time.sleep(self.sleep_on_error_s)
            except Exception as e:
                logger.exception("[Telegram] Bot loop error: %s", e)
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


def service_from_env(message_handler: Optional[Callable[[str, int, str], str]] = None) -> TelegramBotService:
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
    return TelegramBotService(
        telegram=client,
        allowed_chat_ids=allowed,
        message_handler=message_handler,
    )