"""Orbitron Service System - Haupt-Controller für alle Services.

Dieses Modul ist der zentrale Einstiegspunkt für das Orbitron System.
Es initialisiert und verwaltet:
- MessageBus für Agent-Kommunikation
- Orchestrator für Task-Management
- Planner für Planung
- Kernel für Code-Ausführung
- TelegramBot für User-Interface

Mit umfassendem Lifetime Logging und asynchroner Task-Queue.
"""

import json
import logging
import os
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional

# Logging Setup
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
logging.basicConfig(
    level=logging.DEBUG,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

# File handler für persistente Logs
LOG_DIR = Path.home() / ".orbitron" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"orbitron_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logging.getLogger().addHandler(file_handler)

# Suppress noisy third-party logs
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger("ServiceSystem")


def _bootstrap_sys_path() -> None:
    """Add project root to sys.path for imports."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
        logger.debug(f"Added {root} to sys.path")


def _load_dotenv() -> None:
    """Load environment variables from .env file."""
    candidate_paths: list[Path] = []
    try:
        candidate_paths.append(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass
    candidate_paths.append(Path.cwd() / ".env")

    loaded = False
    for env_path in candidate_paths:
        if not env_path.exists() or not env_path.is_file():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key:
                    continue
                os.environ.setdefault(key, value)
            loaded = True
            logger.info(f"Loaded .env from {env_path}")
        except Exception as e:
            logger.warning(f"Failed to load {env_path}: {e}")
    
    if not loaded:
        logger.warning("No .env file loaded")


class LifetimeLogger:
    """Logger für System-Lebenszyklus-Events."""
    
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
    
    def log(self, component: str, event: str, details: Optional[dict] = None) -> None:
        """Log a lifecycle event."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "component": component,
            "event": event,
            "details": details or {},
        }
        with self._lock:
            self.events.append(entry)
        logger.info(f"[{component}] {event}" + (f" | {details}" if details else ""))
    
    def get_events(self, component: Optional[str] = None) -> list[dict[str, Any]]:
        """Get all events, optionally filtered by component."""
        with self._lock:
            if component:
                return [e for e in self.events if e["component"] == component]
            return self.events.copy()
    
    def save_to_file(self, path: Optional[Path] = None) -> None:
        """Save events to JSON file."""
        path = path or LOG_DIR / f"lifetime_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with self._lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2, default=str)
        logger.info(f"Lifetime log saved to {path}")


# Global lifetime logger
lifetime = LifetimeLogger()


# ========== Async Task Queue ==========

class QueueTaskStatus(Enum):
    """Status of a task in the async queue."""
    QUEUED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class QueuedTask:
    """A task waiting in the async queue."""
    task_id: str
    description: str
    chat_id: int
    username: str
    status: QueueTaskStatus = QueueTaskStatus.QUEUED
    result: Optional[dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # Callback to send messages back to the user (str callable or ResponseSender-like object)
    send_callback: Optional[Any] = field(default=None, repr=False)


class AsyncTaskQueue:
    """Manages a queue of tasks that are processed one at a time in the background.

    Features:
    - Thread-safe task queue
    - Sequential processing (one task at a time)
    - Immediate acknowledgment to the user
    - Completion notifications
    - Queue position tracking
    """

    def __init__(self):
        self._queue: list[QueuedTask] = []
        self._lock = threading.Lock()
        self._current_task: Optional[QueuedTask] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._task_processor: Optional[Callable] = None
        self._task_counter = 0
        self._service_system: Any = None  # Reference to ServiceSystem for LLM replies

    def start(self, task_processor: Callable[[str, dict], dict[str, Any]], service_system: Any = None) -> None:
        """Start the background worker thread.

        Args:
            task_processor: Callable(description, context) -> result dict
            service_system: Reference to ServiceSystem for LLM-generated replies
        """
        self._task_processor = task_processor
        self._service_system = service_system
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="TaskQueueWorker",
        )
        self._worker_thread.start()
        logger.info("[AsyncTaskQueue] Worker thread started")

    def stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        logger.info("[AsyncTaskQueue] Worker stopped")

    def enqueue(
        self,
        description: str,
        chat_id: int,
        username: str,
        send_callback: Optional[Callable[[str], None]] = None,
    ) -> QueuedTask:
        """Add a task to the queue.

        Returns:
            The queued task with its ID and position
        """
        with self._lock:
            self._task_counter += 1
            task_id = f"qtask-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{self._task_counter}"
            task = QueuedTask(
                task_id=task_id,
                description=description,
                chat_id=chat_id,
                username=username,
                send_callback=send_callback,
            )
            self._queue.append(task)
            position = len(self._queue)
            logger.info("[AsyncTaskQueue] Enqueued task %s (position=%d): %s",
                        task_id, position, description[:80])

        return task

    def get_queue_status(self) -> dict[str, Any]:
        """Get current queue status."""
        with self._lock:
            queued = [t for t in self._queue if t.status == QueueTaskStatus.QUEUED]
            return {
                "current_task": {
                    "task_id": self._current_task.task_id,
                    "description": self._current_task.description[:80],
                    "started_at": self._current_task.started_at.isoformat() if self._current_task.started_at else None,
                } if self._current_task else None,
                "queued_count": len(queued),
                "queue": [
                    {
                        "task_id": t.task_id,
                        "description": t.description[:80],
                        "username": t.username,
                    }
                    for t in queued
                ],
                "total_processed": self._task_counter,
            }

    def get_current_task_description(self) -> Optional[str]:
        """Get a short description of the currently running task, if any."""
        with self._lock:
            if self._current_task:
                return self._current_task.description[:80]
            return None

    def _worker_loop(self) -> None:
        """Background worker: processes tasks one at a time."""
        while self._running:
            task = self._pick_next_task()
            if task is None:
                time.sleep(0.5)
                continue

            self._process_task(task)

    def _pick_next_task(self) -> Optional[QueuedTask]:
        """Pick the next queued task (FIFO)."""
        with self._lock:
            for task in self._queue:
                if task.status == QueueTaskStatus.QUEUED:
                    task.status = QueueTaskStatus.RUNNING
                    task.started_at = datetime.now()
                    self._current_task = task
                    return task
            return None

    def _process_task(self, task: QueuedTask) -> None:
        """Process a single task and notify the user on completion."""
        logger.info("[AsyncTaskQueue] Processing task %s: %s",
                    task.task_id, task.description[:80])

        context = {
            "source": "telegram",
            "chat_id": task.chat_id,
            "username": task.username,
        }

        try:
            result = self._task_processor(task.description, context) \
                if self._task_processor else {"success": False, "error": "No processor"}

            task.result = result
            task.status = QueueTaskStatus.COMPLETED if result.get("success") else QueueTaskStatus.FAILED
            task.completed_at = datetime.now()

        except Exception as e:
            logger.exception("[AsyncTaskQueue] Task %s failed with exception", task.task_id)
            task.result = {"success": False, "error": str(e)}
            task.status = QueueTaskStatus.FAILED
            task.completed_at = datetime.now()

        finally:
            with self._lock:
                self._current_task = None

        # Send completion notification
        self._notify_completion(task)

    def _notify_completion(self, task: QueuedTask) -> None:
        """Send a completion notification to the user.

        Uses the ServiceSystem's LLM to generate a natural, personality-driven reply.
        Sends document files (Word, PDF, Markdown) AFTER the text message.
        Source code files (CSS, JS, HTML, py, etc.) are NOT sent as attachments.
        """
        if not task.send_callback:
            return

        try:
            # --- Send text notification FIRST ---
            if task.status == QueueTaskStatus.COMPLETED and self._service_system:
                result = task.result or {}
                try:
                    reply = self._service_system._generate_result_reply(result, user_text=task.description)
                except Exception:
                    reply = None

                if reply:
                    # Append queue status if more tasks are waiting
                    with self._lock:
                        remaining = sum(1 for t in self._queue if t.status == QueueTaskStatus.QUEUED)
                    if remaining > 0:
                        reply += f"\n\n🔄 Nächste Aufgabe wartet ({remaining} übrig)"
                    if hasattr(task.send_callback, 'send_text'):
                        task.send_callback.send_text(reply)
                    else:
                        task.send_callback(reply)
                else:
                    # LLM failed — use simple fallback
                    self._send_fallback_text(task)
            elif task.status == QueueTaskStatus.COMPLETED:
                self._send_fallback_text(task)
            else:
                # Task failed
                error = task.result.get("error", "Unbekannter Fehler") if task.result else "Unbekannter Fehler"
                if hasattr(task.send_callback, 'send_text'):
                    task.send_callback.send_text(f"❌ Fehlgeschlagen: {task.description[:60]}\n⚠️ {error[:200]}")
                else:
                    task.send_callback(f"❌ Fehlgeschlagen: {task.description[:60]}\n⚠️ {error[:200]}")

            # --- Send document files AFTER text ---
            if task.status == QueueTaskStatus.COMPLETED and task.result:
                artifacts = task.result.get("artifacts", [])
                if artifacts:
                    workspace = self._service_system.workspace_root if self._service_system else None
                    for artifact in artifacts:
                        # Only send document files, not source code
                        if not self._is_document_file(artifact):
                            continue

                        # Try to find the file in the workspace
                        file_path = self._resolve_artifact_path(artifact, workspace)
                        if file_path:
                            try:
                                if hasattr(task.send_callback, 'send_file'):
                                    task.send_callback.send_file(
                                        str(file_path),
                                        caption=f"📄 {Path(file_path).name}",
                                    )
                            except Exception as e:
                                logger.warning("[AsyncTaskQueue] Failed to send file %s: %s", file_path, e)

        except Exception as e:
            logger.error("[AsyncTaskQueue] Failed to send completion notification: %s", e)

    def _send_fallback_text(self, task: QueuedTask) -> None:
        """Send a natural fallback text notification when LLM generation fails.

        This produces a simple, flowing text — NOT a structured template.
        """
        summary = task.result.get("summary", "") if task.result else ""
        # Extract just the first meaningful sentence from the summary
        short_summary = ""
        if summary:
            # Take the first sentence or first 150 chars, whichever is shorter
            first_sentence = summary.split(".")[0].strip()
            if first_sentence and len(first_sentence) > 10:
                short_summary = first_sentence + "."
            else:
                short_summary = summary[:150].strip()

        if short_summary:
            msg = f"✅ Erledigt — {short_summary}"
        else:
            msg = f"✅ Fertig — {task.description[:80]}"

        with self._lock:
            remaining = sum(1 for t in self._queue if t.status == QueueTaskStatus.QUEUED)
        if remaining > 0:
            msg += f"\n\n🔄 Nächste Aufgabe wartet ({remaining} übrig)"

        if hasattr(task.send_callback, 'send_text'):
            task.send_callback.send_text(msg)
        else:
            task.send_callback(msg)

    @staticmethod
    def _is_document_file(path: str) -> bool:
        """Check if a file path is a document (not source code).

        Documents: .docx, .pdf, .md, .txt, .rtf, .odt, .epub, .xlsx, .pptx, .csv
        NOT documents: .css, .js, .html, .py, .ts, .json, .xml, .yaml, .sh, etc.
        """
        if not path:
            return False
        doc_extensions = {
            ".docx", ".pdf", ".md", ".txt", ".rtf", ".odt", ".epub",
            ".xlsx", ".pptx", ".csv", ".doc", ".xls", ".ppt",
        }
        p = Path(path)
        return p.suffix.lower() in doc_extensions

    @staticmethod
    def _resolve_artifact_path(artifact: str, workspace_root: Optional[Path] = None) -> Optional[Path]:
        """Try to find an artifact file on disk.

        Searches in the workspace root and common subdirectories.
        Returns the Path if found, None otherwise.
        """
        if not artifact:
            return None

        # Candidate paths to search
        candidates: list[Path] = []

        # Absolute path
        p = Path(artifact)
        if p.is_absolute():
            candidates.append(p)
        else:
            # Relative to workspace
            if workspace_root:
                ws = Path(str(workspace_root))
                candidates.extend([
                    ws / artifact,
                    ws / "Frontend" / artifact,
                    ws / ".orbitron" / "workspace" / artifact,
                ])
            # Also try CWD
            candidates.append(Path.cwd() / artifact)

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        return None


class ServiceSystem:
    """Haupt-Controller für das Orbitron System.

    Verwaltet den kompletten Lebenszyklus aller Komponenten
    mit umfassendem Logging, Monitoring und asynchroner Task-Queue.
    """

    def __init__(
        self,
        workspace_root: str | None = None,
        enable_telegram: bool = True,
        max_planning_iterations: int = 3,
    ):
        """Initialize the Service System.

        Args:
            workspace_root: Root directory for the workspace
            enable_telegram: Whether to start the Telegram bot
            max_planning_iterations: Maximum planning revision loops
        """
        self.workspace_root = Path(workspace_root) if workspace_root else Path(__file__).resolve().parents[1]
        self.enable_telegram = enable_telegram
        self.max_planning_iterations = max_planning_iterations

        # Components
        self.message_bus = None
        self.orchestrator = None
        self.planner = None
        self.executor = None
        self.tester = None
        self.kernel = None
        self.telegram_bot = None
        self.planner_message_handler = None
        self.executor_message_handler = None
        self.tester_message_handler = None
        self._telegram_thread: Optional[threading.Thread] = None

        self._running = False
        self._start_time: Optional[datetime] = None

        # Async task queue
        self._task_queue = AsyncTaskQueue()

        # Print header
        print("=" * 70)
        print("ORBITRON SERVICE SYSTEM")
        print("=" * 70)
        print(f"Workspace: {self.workspace_root}")
        print(f"Telegram Bot: {'enabled' if enable_telegram else 'disabled'}")
        print(f"Max Planning Iterations: {max_planning_iterations}")
        print(f"Log File: {LOG_FILE}")
        print("=" * 70)

        lifetime.log("ServiceSystem", "initialized", {
            "workspace": str(self.workspace_root),
            "telegram_enabled": enable_telegram,
            "max_planning_iterations": max_planning_iterations,
        })

    def start(self) -> bool:
        """Start all Orbitron components.

        Returns:
            True if startup successful
        """
        logger.info("=" * 70)
        logger.info("STARTING ORBITRON SERVICE SYSTEM")
        logger.info("=" * 70)

        self._start_time = datetime.now()
        lifetime.log("ServiceSystem", "startup_begin")

        try:
            # 1. Start MessageBus
            logger.info("[1/5] Starting MessageBus...")
            lifetime.log("MessageBus", "startup_initiated")
            from OrbitronMessageSystem import get_message_bus

            self.message_bus = get_message_bus(
                persistence_dir=str(self.workspace_root / ".orbitron" / "messages")
            )
            self.message_bus.start()

            stats = self.message_bus.get_stats()
            lifetime.log("MessageBus", "startup_complete", stats)
            logger.info(f"[OK] MessageBus ready (handlers: {stats['handlers_registered']})")

            # 2. Initialize Kernel
            logger.info("[2/5] Initializing Kernel...")
            lifetime.log("Kernel", "startup_initiated")
            try:
                from OrbitronKernel.kernel import OrbitronKernel
                self.kernel = OrbitronKernel()
                lifetime.log("Kernel", "startup_complete")
                logger.info("[OK] Kernel ready")
            except Exception as e:
                logger.warning(f"[WARN] Kernel failed: {e}")
                lifetime.log("Kernel", "startup_failed", {"error": str(e)})
                logger.info("  Continuing without kernel...")

            agent_workspace = self.workspace_root
            if self.kernel:
                configured_workspace = self.kernel.config.get("kernel.workspace")
                if configured_workspace:
                    try:
                        agent_workspace = Path(configured_workspace).expanduser().resolve()
                    except Exception:
                        agent_workspace = Path(configured_workspace)

            if str(agent_workspace) != str(self.workspace_root):
                logger.info(f"Using agent workspace: {agent_workspace}")
                self.workspace_root = Path(agent_workspace)

            self.workspace_root.mkdir(parents=True, exist_ok=True)

            # 3. Start Planner Agent
            logger.info("[3/5] Starting Planner Agent...")
            lifetime.log("Planner", "startup_initiated")
            from OrbitronAgents.Planner import create_planner_agent
            from OrbitronMessageSystem.orchestrator_planner_bridge import PlannerMessageHandler

            self.planner = create_planner_agent(
                kernel=self.kernel,
                workspace_root=str(self.workspace_root),
            )

            # Register planner skill with kernel if available
            if self.kernel:
                self.kernel.register_skill(self.planner.skill)
                logger.debug("Planner skill registered with kernel")

            lifetime.log("Planner", "startup_complete", {
                "skill_name": self.planner.skill.name,
                "tools_count": len(self.planner.skill.get_tools()),
            })
            logger.info(f"[OK] Planner Agent ready ({len(self.planner.skill.get_tools())} tools)")

            # Register planner handler on message bus
            self.planner_message_handler = PlannerMessageHandler(self.planner, agent_name="planner")
            lifetime.log("Planner", "message_handler_registered")
            logger.info("[OK] Planner message handler registered")

            # 4. Start Executor Agent
            logger.info("[4/5] Starting Executor Agent...")
            lifetime.log("Executor", "startup_initiated")
            from OrbitronAgents.Executor import create_executor_agent
            from OrbitronMessageSystem.orchestrator_executor_bridge import ExecutorMessageHandler

            self.executor = create_executor_agent(
                agent_name="executor",
                workspace_root=str(self.workspace_root),
                kernel=self.kernel,
            )

            # Register executor handler on message bus
            self.executor_message_handler = ExecutorMessageHandler(self.executor, agent_name="executor")
            lifetime.log("Executor", "message_handler_registered")
            logger.info("[OK] Executor Agent ready")

            # 4b. Start Tester Agent
            logger.info("[4b/6] Starting Tester Agent...")
            lifetime.log("Tester", "startup_initiated")
            from OrbitronAgents.Tester import create_tester_agent
            from OrbitronMessageSystem.orchestrator_tester_bridge import TesterMessageHandler

            self.tester = create_tester_agent(
                agent_name="tester",
                workspace_root=str(self.workspace_root),
                kernel=self.kernel,
            )

            # Register tester handler on message bus
            self.tester_message_handler = TesterMessageHandler(self.tester, agent_name="tester")
            lifetime.log("Tester", "message_handler_registered")
            logger.info("[OK] Tester Agent ready")

            # 5. Start Orchestrator
            logger.info("[5/6] Starting Orchestrator...")
            lifetime.log("Orchestrator", "startup_initiated")
            from OrbitronAgents.Orchestrator import create_orchestrator

            self.orchestrator = create_orchestrator(
                kernel=self.kernel,
                workspace_root=str(self.workspace_root),
                max_planning_iterations=self.max_planning_iterations,
                planning_timeout_seconds=900,  # 15 min timeout, then retry
                execution_timeout_seconds=900,  # 15 min timeout, then retry
            )
            self.orchestrator.connect_to_message_bus()

            lifetime.log("Orchestrator", "startup_complete", {
                "max_iterations": self.max_planning_iterations,
            })
            logger.info("[OK] Orchestrator ready")

            # 6. Start Telegram Bot (if enabled)
            if self.enable_telegram:
                logger.info("[6/6] Starting Telegram Bot...")
                lifetime.log("TelegramBot", "startup_initiated")
                try:
                    from TelegramBot.bot_service import TelegramBotService, service_from_env
                    self.telegram_bot = service_from_env(message_handler=self.handle_user_message)
                    self.telegram_bot.service_system = self

                    # Start in background thread
                    self._telegram_thread = threading.Thread(
                        target=self._run_telegram_bot,
                        daemon=True,
                        name="TelegramBot"
                    )
                    self._telegram_thread.start()

                    lifetime.log("TelegramBot", "startup_complete", {
                        "thread_name": self._telegram_thread.name,
                    })
                    logger.info("[OK] Telegram Bot ready (background thread)")
                except Exception as e:
                    logger.error(f"[FAIL] Telegram Bot failed: {e}")
                    lifetime.log("TelegramBot", "startup_failed", {"error": str(e)})
            else:
                logger.info("[5/5] Telegram Bot skipped (disabled)")

            self._running = True

            # Start async task queue
            self._task_queue.start(task_processor=self._process_task_sync, service_system=self)
            logger.info("[OK] Async Task Queue started")

            # Print summary
            logger.info("=" * 70)
            logger.info("ORBITRON SERVICE SYSTEM READY")
            logger.info("=" * 70)
            lifetime.log("ServiceSystem", "startup_complete", {
                "components": {
                    "message_bus": self.message_bus is not None,
                    "kernel": self.kernel is not None,
                    "planner": self.planner is not None,
                    "executor": self.executor is not None,
                    "tester": self.tester is not None,
                    "orchestrator": self.orchestrator is not None,
                    "telegram_bot": self.telegram_bot is not None,
                }
            })

            print("\n" + "=" * 70)
            print("SYSTEM READY")
            print("=" * 70)
            print(f"  MessageBus:    {'[OK]' if self.message_bus else '[FAIL]'}")
            print(f"  Kernel:        {'[OK]' if self.kernel else '[FAIL]'}")
            print(f"  Planner:       {'[OK]' if self.planner else '[FAIL]'}")
            print(f"  Executor:      {'[OK]' if self.executor else '[FAIL]'}")
            print(f"  Tester:        {'[OK]' if self.tester else '[FAIL]'}")
            print(f"  Orchestrator:  {'[OK]' if self.orchestrator else '[FAIL]'}")
            print(f"  TelegramBot:   {'[OK]' if self.telegram_bot else '[FAIL]'}")
            print("=" * 70)

            return True

        except Exception as e:
            logger.exception("Startup failed")
            lifetime.log("ServiceSystem", "startup_failed", {"error": str(e)})
            return False

    def _run_telegram_bot(self) -> None:
        """Run the Telegram bot in a separate thread."""
        try:
            logger.info("Telegram Bot thread started")
            lifetime.log("TelegramBot", "thread_started")
            if self.telegram_bot:
                self.telegram_bot.run_forever()
        except Exception as e:
            logger.error(f"Telegram Bot error: {e}")
            lifetime.log("TelegramBot", "thread_error", {"error": str(e)})

    def stop(self) -> None:
        """Stop all components gracefully."""
        logger.info("=" * 70)
        logger.info("SHUTTING DOWN ORBITRON SERVICE SYSTEM")
        logger.info("=" * 70)
        lifetime.log("ServiceSystem", "shutdown_begin")

        # Calculate uptime
        if self._start_time:
            uptime = datetime.now() - self._start_time
            logger.info(f"Uptime: {uptime}")

        # Stop Telegram Bot
        if self.telegram_bot:
            logger.info("Stopping Telegram Bot...")
            lifetime.log("TelegramBot", "shutdown_initiated")
            # Daemon thread will be killed automatically
            lifetime.log("TelegramBot", "shutdown_complete")
            logger.info("[OK] Telegram Bot stopped")

        # Stop Orchestrator
        if self.orchestrator:
            logger.info("Stopping Orchestrator...")
            lifetime.log("Orchestrator", "shutdown_initiated")
            try:
                self.orchestrator.disconnect()
                lifetime.log("Orchestrator", "shutdown_complete")
                logger.info("[OK] Orchestrator stopped")
            except Exception as e:
                logger.error(f"[FAIL] Error stopping orchestrator: {e}")
                lifetime.log("Orchestrator", "shutdown_error", {"error": str(e)})

        # Stop Executor message handler
        if self.executor_message_handler:
            logger.info("Stopping Executor message handler...")
            try:
                self.executor_message_handler.close()
                lifetime.log("Executor", "message_handler_stopped")
                logger.info("[OK] Executor message handler stopped")
            except Exception as e:
                logger.error(f"[FAIL] Error stopping executor handler: {e}")
                lifetime.log("Executor", "message_handler_error", {"error": str(e)})

        # Stop Tester message handler
        if self.tester_message_handler:
            logger.info("Stopping Tester message handler...")
            try:
                self.tester_message_handler.close()
                lifetime.log("Tester", "message_handler_stopped")
                logger.info("[OK] Tester message handler stopped")
            except Exception as e:
                logger.error(f"[FAIL] Error stopping tester handler: {e}")
                lifetime.log("Tester", "message_handler_error", {"error": str(e)})

        # Stop Planner message handler
        if self.planner_message_handler:
            logger.info("Stopping Planner message handler...")
            try:
                self.planner_message_handler.close()
                lifetime.log("Planner", "message_handler_stopped")
                logger.info("[OK] Planner message handler stopped")
            except Exception as e:
                logger.error(f"[FAIL] Error stopping planner handler: {e}")
                lifetime.log("Planner", "message_handler_error", {"error": str(e)})

        # Stop MessageBus
        if self.message_bus:
            logger.info("Stopping MessageBus...")
            lifetime.log("MessageBus", "shutdown_initiated")
            try:
                self.message_bus.stop()
                lifetime.log("MessageBus", "shutdown_complete")
                logger.info("[OK] MessageBus stopped")
            except Exception as e:
                logger.error(f"[FAIL] Error stopping message bus: {e}")
                lifetime.log("MessageBus", "shutdown_error", {"error": str(e)})

        # Stop async task queue
        self._task_queue.stop()
        logger.info("[OK] Async Task Queue stopped")

        self._running = False
        lifetime.log("ServiceSystem", "shutdown_complete")
        logger.info("=" * 70)
        logger.info("ORBITRON SERVICE SYSTEM STOPPED")
        logger.info("=" * 70)

        # Save lifetime logs
        lifetime.save_to_file()

        print("\n" + "=" * 70)
        print("SYSTEM STOPPED")
        print(f"Log saved to: {LOG_FILE}")
        print("=" * 70)

    def process_task(
        self,
        description: str,
        context: Optional[dict[str, Any]] = None,
        progress_callback: Optional[callable] = None,
    ) -> dict[str, Any]:
        """Process a task through the complete system.

        Args:
            description: Task description
            context: Optional context
            progress_callback: Optional callback for progress updates

        Returns:
            Task result dictionary
        """
        if not self._running:
            logger.error("[ServiceSystem] Cannot process task: System not running")
            return {"success": False, "error": "System not running"}

        if not self.orchestrator:
            logger.error("[ServiceSystem] Cannot process task: Orchestrator not available")
            return {"success": False, "error": "Orchestrator not available"}

        task_id = f"task-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        logger.info("=" * 70)
        logger.info("[ServiceSystem] PROCESSING TASK: %s", task_id)
        logger.info("[ServiceSystem] Description: %s...", description[:80])
        logger.info("=" * 70)

        lifetime.log("ServiceSystem", "task_submitted", {
            "task_id": task_id,
            "description": description[:100],
        })

        # Log Planner invocation
        logger.info("[ServiceSystem] [TaskFlow] Step 1: Orchestrator.create_task()")
        task = self.orchestrator.create_task(description, context)
        lifetime.log("Orchestrator", "task_created", {"task_id": task.task_id})

        # Send progress update (only to logs, no more robotic Telegram messages)
        if progress_callback:
            progress_callback("")

        logger.info("[ServiceSystem] [TaskFlow] Step 2: Orchestrator.run_task(%s)", task.task_id)
        logger.info("[ServiceSystem] [TaskFlow]   -> Entering planning loop...")

        # Run task with progress updates
        result = self.orchestrator.run_task(task.task_id)

        # No intermediate progress messages to Telegram — the initial
        # acknowledgment and the final result reply are enough.

        # Log result
        if result.get("success"):
            logger.info("=" * 70)
            logger.info("[ServiceSystem] TASK COMPLETED SUCCESSFULLY")
            logger.info("[ServiceSystem]   Task ID: %s", result.get('task_id'))
            logger.info("[ServiceSystem]   Status: %s", result.get('status'))
            logger.info("[ServiceSystem]   Planning Iterations: %s", result.get('iterations'))
            if result.get("plan"):
                plan = result["plan"]
                logger.info("[ServiceSystem]   Plan Title: %s", plan.get('title', 'N/A'))
                logger.info("[ServiceSystem]   Steps: %d", len(plan.get('steps', [])))
            logger.info("=" * 70)

            lifetime.log("ServiceSystem", "task_completed", {
                "task_id": task_id,
                "iterations": result.get("iterations"),
                "plan_title": result.get("plan", {}).get("title"),
            })
        else:
            logger.error("=" * 70)
            logger.error("[ServiceSystem] TASK FAILED")
            logger.error("[ServiceSystem]   Error: %s", result.get('error', 'Unknown error'))
            logger.error("=" * 70)

            lifetime.log("ServiceSystem", "task_failed", {
                "task_id": task_id,
                "error": result.get("error"),
            })

        return result

    def handle_user_message(
        self,
        text: str,
        chat_id: int,
        username: str,
        send: Optional[callable] = None,
    ) -> str:
        """Handle inbound user message from Telegram.

        Enqueues the task for async processing and returns an immediate
        acknowledgment. The user gets a completion notification when the
        task finishes.
        """
        logger.info("[ServiceSystem] [Telegram] Message from %s (chat_id=%s): %s...", 
                     username, chat_id, text[:60])
        lifetime.log("ServiceSystem", "telegram_message_received", {
            "chat_id": chat_id,
            "username": username,
            "text_preview": text[:100],
        })

        # Enqueue the task for background processing
        queued_task = self._task_queue.enqueue(
            description=text,
            chat_id=chat_id,
            username=username,
            send_callback=send,
        )

        # Generate immediate acknowledgment
        queue_status = self._task_queue.get_queue_status()
        current_task = queue_status.get("current_task")
        queued_count = queue_status.get("queued_count", 0)

        if current_task and queued_count > 0:
            # There's a task running + this one is queued
            ack = self._generate_queued_reply(
                text, username=username,
                current_task_desc=current_task.get("description", ""),
                queue_position=queued_count,
            )
        elif current_task:
            # A task is running, this one is next
            ack = self._generate_working_reply(text, username=username)
        else:
            # Queue is empty, this will start immediately
            ack = self._generate_orchestrator_reply(text, username=username)

        if callable(send):
            send(ack)

        return ack

    def _process_task_sync(self, description: str, context: dict[str, Any]) -> dict[str, Any]:
        """Synchronous task processor used by the async queue worker.

        Args:
            description: Task description
            context: Context dict (source, chat_id, username)

        Returns:
            Task result dictionary
        """
        return self.process_task(description, context)

    def _generate_working_reply(self, user_text: str, username: str = "Sven") -> str:
        """Generate acknowledgment when the system is currently working on a task."""
        if not self.orchestrator or not self.orchestrator.kernel:
            return "Ich schau mir das an, sobald ich mit der aktuellen Aufgabe fertig bin."

        try:
            current_desc = self._task_queue.get_current_task_description() or "aktueller Auftrag"
            prompt = (
                f"{username} schreibt: '{user_text[:300]}'\n"
                f"Du arbeitest gerade an: '{current_desc[:100]}'\n\n"
                f"Antworte als Orbitron — du nimmst den Auftrag an, aber du bist noch beschäftigt. "
                f"Kurz, natürlich, menschlich. Maximal 2 Sätze."
            )
            identity = self._load_identity_text()
            soul = self._load_soul_text()
            user = self._load_user_text()
            system_prompt = (
                f"Du bist Orbitron — Sven's digitaler Partner.\n\n"
                f"Identität: {identity}\n\n"
                f"Seele: {soul}\n\n"
                f"Nutzer: {user}\n\n"
                f"Sprich als Orbitron direkt mit Sven. Kurz, natürlich, auf Deutsch. Maximal 2 Sätze."
            )
            response = self.orchestrator.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=45,
                max_retries=1,
            )
            content = str((response.get("message") or {}).get("content") or "")
            return content.strip() or "Ich schau mir das an, sobald ich mit der aktuellen Aufgabe fertig bin."
        except Exception:
            return "Ich schau mir das an, sobald ich mit der aktuellen Aufgabe fertig bin."

    def _generate_queued_reply(
        self,
        user_text: str,
        username: str = "Sven",
        current_task_desc: str = "",
        queue_position: int = 1,
    ) -> str:
        """Generate acknowledgment when the task is queued behind others."""
        if not self.orchestrator or not self.orchestrator.kernel:
            return f"Ich schau mir das an. ({queue_position} Aufgabe{'n' if queue_position > 1 else ''} vor dir.)"

        try:
            prompt = (
                f"{username} schreibt: '{user_text[:300]}'\n"
                f"Du arbeitest gerade an: '{current_task_desc[:100]}'\n"
                f"Es gibt noch {queue_position} Aufgabe{'n' if queue_position > 1 else ''} vor dieser.\n\n"
                f"Antworte als Orbitron — du nimmst den Auftrag an, aber es dauert noch. "
                f"Kurz, natürlich, menschlich. Maximal 2 Sätze."
            )
            identity = self._load_identity_text()
            soul = self._load_soul_text()
            user = self._load_user_text()
            system_prompt = (
                f"Du bist Orbitron — Sven's digitaler Partner.\n\n"
                f"Identität: {identity}\n\n"
                f"Seele: {soul}\n\n"
                f"Nutzer: {user}\n\n"
                f"Sprich als Orbitron direkt mit Sven. Kurz, natürlich, auf Deutsch. Maximal 2 Sätze."
            )
            response = self.orchestrator.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=45,
                max_retries=1,
            )
            content = str((response.get("message") or {}).get("content") or "")
            return content.strip() or f"Ich schau mir das an. ({queue_position} Aufgabe{'n' if queue_position > 1 else ''} vor dir.)"
        except Exception:
            return f"Ich schau mir das an. ({queue_position} Aufgabe{'n' if queue_position > 1 else ''} vor dir.)"

    def _generate_error_reply(self, error: str, user_text: str) -> str:
        """Generate a natural error message from the Orchestrator."""
        if not self.orchestrator or not self.orchestrator.kernel:
            return f"Das hat leider nicht geklappt: {error}"

        try:
            prompt = (
                f"Beim Auftrag '{user_text[:200]}' ist ein Fehler aufgetreten:\n"
                f"{error[:300]}\n\n"
                f"Erkläre Sven kurz, was schiefgelaufen ist — natürlich und ehrlich. "
                f"Keine Floskeln, maximal 3 Sätze."
            )
            identity = self._load_identity_text()
            soul = self._load_soul_text()
            user = self._load_user_text()
            system_prompt = (
                f"Du bist Orbitron — Sven's digitaler Partner.\n\n"
                f"Identität: {identity}\n\n"
                f"Seele: {soul}\n\n"
                f"Nutzer: {user}\n\n"
                f"Sprich als Orbitron direkt mit Sven. Ehrlich, natürlich, auf Deutsch. Maximal 3 Sätze."
            )
            response = self.orchestrator.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=45,
                max_retries=1,
            )
            content = str((response.get("message") or {}).get("content") or "")
            return content.strip() or f"Das hat leider nicht geklappt: {error}"
        except Exception:
            return f"Das hat leider nicht geklappt: {error}"

    def _generate_orchestrator_reply(self, user_text: str, username: str = "Sven") -> str:
        """Generate a natural acknowledgment from the Orchestrator.

        Uses a minimal prompt — no full IDENTITY/SOUL/USER context needed
        for a 2-sentence acknowledgment. Short timeout, no retries.
        """
        if not self.orchestrator or not self.orchestrator.kernel:
            return "Ich schau mir das an."

        try:
            prompt = (
                f"{username} schreibt: '{user_text[:300]}'\n\n"
                f"Antworte als Orbitron — kurz, natürlich, menschlich. "
                f"Keine Floskeln, kein Echo. Zeig dass du verstanden hast "
                f"und dich dransetzt. Maximal 2 Sätze."
            )
            identity = self._load_identity_text()
            soul = self._load_soul_text()
            user = self._load_user_text()
            system_prompt = (
                f"Du bist Orbitron — Sven's digitaler Partner.\n\n"
                f"Identität: {identity}\n\n"
                f"Seele: {soul}\n\n"
                f"Nutzer: {user}\n\n"
                f"Sprich als Orbitron direkt mit Sven. Kurz, natürlich, auf Deutsch. Maximal 2 Sätze."
            )
            response = self.orchestrator.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=45,
                max_retries=1,
            )
            content = str((response.get("message") or {}).get("content") or "")
            return content.strip() or "Ich schau mir das an."
        except Exception:
            return "Ich schau mir das an."

    def _generate_result_reply(self, result: dict[str, Any], user_text: str) -> Optional[str]:
        """Generate a natural result summary from the Orchestrator.

        Uses Identity and Soul to generate a flowing, personal response.
        Returns None if the LLM is unavailable — the caller should use
        a simple natural fallback, NOT a structured template.
        """
        if not self.orchestrator or not self.orchestrator.kernel:
            return None

        try:
            result_summary = self._build_result_summary(result)

            # Load identity, soul, and user for personality
            identity = self._load_identity_text()
            soul = self._load_soul_text()
            user = self._load_user_text()

            system_prompt = (
                f"Du bist Orbitron — Sven's digitaler Partner.\n\n"
                f"Deine Identität: {identity}\n\n"
                f"Deine Seele: {soul}\n\n"
                f"Dein Nutzer: {user}\n\n"
                f"Sprich als Orbitron direkt mit Sven. Natürlich, menschlich, auf Deutsch. "
                f"Keine Aufzählungen, keine Struktur — Fließtext. "
                f"Erwähne keine internen Details wie Iterationen, Pipeline-Phasen oder Agent-Namen. "
                f"Maximal 4 Sätze."
            )

            prompt = (
                f"Sven hat dich gebeten: '{user_text[:300]}'\n\n"
                f"Ergebnis:\n{result_summary}\n\n"
                f"Sag Sven was du erledigt hast — als Orbitron, direkt und persönlich."
            )
            response = self.orchestrator.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=60,
                max_retries=1,
            )
            content = str((response.get("message") or {}).get("content") or "")
            return content.strip() or None
        except Exception:
            logger.warning("[ServiceSystem] LLM result reply failed, using natural fallback")
            return None

    def _load_identity_text(self) -> str:
        """Load IDENTITY.md content for personality-aware responses."""
        try:
            identity_path = self.workspace_root / "IDENTITY.md"
            if identity_path.exists():
                text = identity_path.read_text(encoding="utf-8")
                # Trim to essential parts (name, stil, stimme, selbstverständnis)
                lines = text.split("\n")
                keep = []
                skip_sections = {"Lernprinzipien", "Grenzen", "Aktive Anpassung"}
                skipping = False
                for line in lines:
                    if line.startswith("## "):
                        section = line.lstrip("# ").strip()
                        skipping = section in skip_sections
                    if not skipping:
                        keep.append(line)
                return "\n".join(keep)[:1500]
        except Exception:
            pass
        return "Orbitron — digitaler Partner. Gelassen, präzise, direkt."

    def _load_soul_text(self) -> str:
        """Load SOUL.md content for personality-aware responses."""
        try:
            soul_path = self.workspace_root / "SOUL.md"
            if soul_path.exists():
                text = soul_path.read_text(encoding="utf-8")
                # Trim to essential parts
                lines = text.split("\n")
                keep = []
                skip_sections = {"Lernprinzipien", "Selbst-Entwicklung", "Grenzen"}
                skipping = False
                for line in lines:
                    if line.startswith("## "):
                        section = line.lstrip("# ").strip()
                        skipping = section in skip_sections
                    if not skipping:
                        keep.append(line)
                return "\n".join(keep)[:1500]
        except Exception:
            pass
        return "Klarheit vor Cleverness. Partnerschaft auf Augenhöhe."

    def _load_user_text(self) -> str:
        """Load USER.md content for user-aware responses."""
        try:
            user_path = self.workspace_root / "USER.md"
            if user_path.exists():
                text = user_path.read_text(encoding="utf-8")
                # Trim to essential parts
                lines = text.split("\n")
                keep = []
                skip_sections = {"Projekte", "Aktuelle Projekte"}
                skipping = False
                for line in lines:
                    if line.startswith("## "):
                        section = line.lstrip("# ").strip()
                        skipping = section in skip_sections
                    if not skipping:
                        keep.append(line)
                return "\n".join(keep)[:1000]
        except Exception:
            pass
        return "Sven — Entwickler, Architekt, Visionär."

    def _build_result_summary(self, result: dict[str, Any]) -> str:
        """Build a compact text summary of the result dict for the LLM.

        This is used as context for the LLM to generate a natural reply.
        It should contain useful information but NOT raw internal data
        like iteration counts or agent names.
        """
        parts = []

        success = result.get("success", False)
        parts.append(f"Erfolgreich: {'ja' if success else 'nein'}")

        # Autonomous loop result
        if result.get("autonomous"):
            summary = result.get("summary") or result.get("answer", "")
            if summary:
                parts.append(f"Zusammenfassung: {summary[:500]}")
            artifacts = result.get("artifacts") or []
            if artifacts:
                parts.append(f"Erstellte Dateien: {', '.join(str(a) for a in artifacts[:10])}")
            return "\n".join(parts)

        # Plan-based result
        plan = result.get("plan") or {}
        if plan:
            summary = plan.get("summary") or plan.get("description") or ""
            if summary:
                parts.append(f"Beschreibung: {summary[:300]}")

        # Execution result — extract summary and artifacts
        exec_summary = result.get("summary", "")
        if exec_summary:
            parts.append(f"Ergebnis: {exec_summary[:500]}")

        artifacts = result.get("artifacts", [])
        if artifacts:
            parts.append(f"Erstellte Dateien: {', '.join(str(a) for a in artifacts[:10])}")

        # Test result — just pass/fail
        test_result = result.get("test_result")
        if test_result and isinstance(test_result, dict):
            passed = test_result.get("passed", False)
            quality = test_result.get("quality_rating", "")
            parts.append(f"Qualitätsprüfung: {'bestanden' if passed else 'nicht bestanden'}" + (f" ({quality})" if quality else ""))

        return "\n".join(parts)

    def _format_plan_for_telegram(self, result: dict[str, Any]) -> str:
        """Format a plan response for Telegram without raw planning steps."""
        plan = result.get("plan") or {}
        analysis = result.get("analysis") or {}

        plan_type = plan.get("plan_type") or result.get("plan_type")
        if plan_type == "execution":
            return self._format_execution_for_telegram(result)

        title = plan.get("title", "Unbenannter Plan")
        summary = plan.get("summary") or plan.get("description") or ""
        itinerary = plan.get("itinerary") or []
        risks = plan.get("risks") or []
        packing = plan.get("packing_list") or []
        logistics = plan.get("logistics") or {}
        iterations = result.get("iterations", "N/A")

        lines = [
            "Plan erstellt:",
            f"Titel: {title}",
            f"Iterationen: {iterations}",
        ]

        if summary:
            lines.append("")
            lines.append("Kurzfassung:")
            lines.append(summary)

        if itinerary:
            lines.append("")
            lines.append("Tagesablauf (Kurz):")
            for item in itinerary[:6]:
                time_str = item.get("time", "")
                activity = item.get("activity", "")
                if time_str and activity:
                    lines.append(f"- {time_str}: {activity}")
                elif activity:
                    lines.append(f"- {activity}")

        if logistics:
            lines.append("")
            lines.append("Logistik:")
            if logistics.get("transport"):
                lines.append(f"- Anreise: {logistics['transport']}")
            if logistics.get("permits"):
                lines.append(f"- Genehmigungen: {logistics['permits']}")
            if logistics.get("campsite"):
                lines.append(f"- Zeltplatz: {logistics['campsite']}")
            if logistics.get("weather"):
                lines.append(f"- Wetter: {logistics['weather']}")

        if packing:
            lines.append("")
            lines.append("Packliste (Auszug):")
            for item in packing[:6]:
                lines.append(f"- {item}")

        if risks:
            lines.append("")
            lines.append("Risiken:")
            for item in risks[:4]:
                lines.append(f"- {item}")

        return "\n".join(lines)

    def _format_execution_for_telegram(self, result: dict[str, Any]) -> str:
        """Format an execution response for Telegram."""
        plan = result.get("plan") or {}
        execution = result.get("execution") or {}
        exec_result = execution.get("execution_result") or {}

        title = plan.get("title", "Unbenannter Auftrag")
        summary = plan.get("summary") or plan.get("description") or ""
        iterations = result.get("iterations", "N/A")
        validation = result.get("validation") or {}
        validation_iterations = validation.get("iterations")

        artifacts = exec_result.get("artifacts") or []
        steps_failed = exec_result.get("steps_failed")

        lines = [
            "Umsetzung abgeschlossen:",
            f"Titel: {title}",
            f"Planungs-Iterationen: {iterations}",
        ]

        if validation_iterations is not None:
            lines.append(f"Validierungs-Iterationen: {validation_iterations}")

        if summary:
            lines.append("")
            lines.append("Kurzfassung:")
            lines.append(summary)

        if isinstance(artifacts, list) and artifacts:
            lines.append("")
            lines.append("Artefakte:")
            for item in artifacts[:12]:
                lines.append(f"- {item}")
        else:
            lines.append("")
            lines.append("Artefakte: Keine gemeldet")

        if isinstance(steps_failed, int) and steps_failed > 0:
            lines.append("")
            lines.append(f"Warnung: {steps_failed} Schritt(e) fehlgeschlagen")

        return "\n".join(lines)

    def get_status(self) -> dict[str, Any]:
        """Get system status."""
        status = {
            "running": self._running,
            "workspace": str(self.workspace_root),
            "uptime": None,
            "components": {},
            "lifetime_events": len(lifetime.get_events()),
        }

        if self._start_time:
            status["uptime"] = str(datetime.now() - self._start_time)

        if self.message_bus:
            status["components"]["message_bus"] = self.message_bus.get_stats()

        if self.orchestrator:
            status["components"]["orchestrator"] = self.orchestrator.get_status()

        if self.planner:
            status["components"]["planner"] = {
                "initialized": True,
                "plans_count": len(self.planner.skill._plans) if hasattr(self.planner.skill, '_plans') else 0,
            }

        if self.tester:
            status["components"]["tester"] = self.tester.get_status()

        return status

    def print_lifetime_log(self) -> None:
        """Print all lifetime events."""
        print("\n" + "=" * 70)
        print("LIFETIME LOG")
        print("=" * 70)
        for event in lifetime.get_events():
            ts = event["timestamp"].split("T")[1].split(".")[0] if "T" in event["timestamp"] else event["timestamp"]
            print(f"{ts} | {event['component']:20s} | {event['event']}")
            if event.get("details"):
                for key, value in event["details"].items():
                    print(f"  {key}: {value}")
        print("=" * 70)

    def run_forever(self) -> None:
        """Run the service system forever (main entry point)."""
        if not self.start():
            logger.error("Failed to start ServiceSystem")
            sys.exit(1)

        try:
            self.interactive_mode()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.stop()

    def interactive_mode(self) -> None:
        """Run in interactive mode with async task queue support."""
        print("\n" + "=" * 70)
        print("INTERACTIVE MODE")
        print("=" * 70)
        print("Commands:")
        print("  <task description>  - Enqueue a task (non-blocking)")
        print("  status             - Show system status")
        print("  queue              - Show task queue")
        print("  lifetime           - Show lifetime log")
        print("  quit               - Exit")
        print("=" * 70)

        while self._running:
            try:
                user_input = input("\nOrbitron> ").strip()

                if not user_input:
                    continue

                if user_input.lower() == "quit":
                    break

                if user_input.lower() == "status":
                    status = self.get_status()
                    print(f"\nSystem Status:")
                    print(f"  Running: {status['running']}")
                    print(f"  Uptime: {status.get('uptime', 'N/A')}")
                    print(f"  Lifetime Events: {status['lifetime_events']}")
                    if 'orchestrator' in status['components']:
                        orch = status['components']['orchestrator']
                        print(f"  Tasks: {orch['tasks']['total']}")
                    # Show queue status
                    queue_status = self._task_queue.get_queue_status()
                    current = queue_status.get("current_task")
                    queued = queue_status.get("queued_count", 0)
                    if current:
                        print(f"  Queue: Working on '{current.get('description', '?')[:50]}' ({queued} queued)")
                    else:
                        print(f"  Queue: Idle ({queued} queued)")
                    continue

                if user_input.lower() == "queue":
                    queue_status = self._task_queue.get_queue_status()
                    current = queue_status.get("current_task")
                    queued = queue_status.get("queued_count", 0)
                    queue_list = queue_status.get("queue", [])
                    print(f"\n📋 Task Queue:")
                    if current:
                        print(f"  🔄 Working: {current.get('description', '?')[:60]}")
                    else:
                        print(f"  ⏸️  Idle")
                    if queue_list:
                        print(f"  📝 Queued ({queued}):")
                        for i, task in enumerate(queue_list, 1):
                            print(f"    {i}. {task.get('description', '?')[:50]}")
                    else:
                        print(f"  📝 Queued: None")
                    continue

                if user_input.lower() == "lifetime":
                    self.print_lifetime_log()
                    continue

                # Enqueue task for async processing
                def _print_callback(msg: str) -> None:
                    print(f"\n{msg}")

                queued_task = self._task_queue.enqueue(
                    description=user_input,
                    chat_id=0,  # CLI mode
                    username="CLI",
                    send_callback=_print_callback,
                )

                queue_status = self._task_queue.get_queue_status()
                current = queue_status.get("current_task")
                queued = queue_status.get("queued_count", 0)

                if current and current.get("task_id") == queued_task.task_id:
                    print(f"🔄 Task queued — working on it now...")
                elif queued > 0:
                    print(f"📋 Task queued — {queued} task(s) ahead of you")
                else:
                    print(f"🔄 Task queued — starting soon...")

            except KeyboardInterrupt:
                print("\n\nInterrupted")
                break
            except EOFError:
                break
            except Exception as e:
                logger.exception("Error in interactive mode")
                print(f"Error: {e}")


def main() -> None:
    """Main entry point."""
    _bootstrap_sys_path()
    _load_dotenv()

    # Create and run service system
    system = ServiceSystem(
        enable_telegram=True,
        max_planning_iterations=3,
    )

    system.run_forever()


if __name__ == "__main__":
    main()
