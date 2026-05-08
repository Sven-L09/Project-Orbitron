"""Orbitron Service System - Haupt-Controller für alle Services.

Dieses Modul ist der zentrale Einstiegspunkt für das Orbitron System.
Es initialisiert und verwaltet:
- MessageBus für Agent-Kommunikation
- Orchestrator für Task-Management
- Planner für Planung
- Kernel für Code-Ausführung
- TelegramBot für User-Interface

Mit umfassendem Lifetime Logging.
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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


class ServiceSystem:
    """Haupt-Controller für das Orbitron System.
    
    Verwaltet den kompletten Lebenszyklus aller Komponenten
    mit umfassendem Logging und Monitoring.
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
        self.kernel = None
        self.telegram_bot = None
        self.planner_message_handler = None
        self.executor_message_handler = None
        self._telegram_thread: Optional[threading.Thread] = None
        
        self._running = False
        self._start_time: Optional[datetime] = None
        
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
            
            # 5. Start Orchestrator
            logger.info("[5/5] Starting Orchestrator...")
            lifetime.log("Orchestrator", "startup_initiated")
            from OrbitronAgents.Orchestrator import create_orchestrator
            
            self.orchestrator = create_orchestrator(
                kernel=self.kernel,
                workspace_root=str(self.workspace_root),
                max_planning_iterations=self.max_planning_iterations,
                planning_timeout_seconds=3600,  # 1 hour for complex code generation
                execution_timeout_seconds=3600,  # 1 hour for execution (multiple LLM calls)
            )
            self.orchestrator.connect_to_message_bus()
            
            lifetime.log("Orchestrator", "startup_complete", {
                "max_iterations": self.max_planning_iterations,
            })
            logger.info("[OK] Orchestrator ready")
            
            # 6. Start Telegram Bot (if enabled)
            if self.enable_telegram:
                logger.info("[5/5] Starting Telegram Bot...")
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
            
            # Print summary
            logger.info("=" * 70)
            logger.info("ORBITRON SERVICE SYSTEM READY")
            logger.info("=" * 70)
            lifetime.log("ServiceSystem", "startup_complete", {
                "components": {
                    "message_bus": self.message_bus is not None,
                    "kernel": self.kernel is not None,
                    "planner": self.planner is not None,
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
        
        # Send progress update
        if progress_callback:
            progress_callback("Task erstellt. Starte Planung...")
        
        logger.info("[ServiceSystem] [TaskFlow] Step 2: Orchestrator.run_task(%s)", task.task_id)
        logger.info("[ServiceSystem] [TaskFlow]   -> Entering planning loop...")
        
        # Run task with progress updates
        result = self.orchestrator.run_task(task.task_id)
        
        # Send progress update after planning
        if progress_callback and result.get("success"):
            iterations = result.get("iterations", 1)
            if iterations and iterations > 1:
                progress_callback(f"Plan nach {iterations} Iterationen finalisiert. Starte Ausführung...")
            else:
                progress_callback("Plan in erster Iteration finalisiert. Starte Ausführung...")
        
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

        Routes the message through the orchestrator/planner flow and
        returns a human-readable response.
        """
        logger.info("[ServiceSystem] [Telegram] Message from %s (chat_id=%s): %s...", 
                     username, chat_id, text[:60])
        lifetime.log("ServiceSystem", "telegram_message_received", {
            "chat_id": chat_id,
            "username": username,
            "text_preview": text[:100],
        })

        context = {
            "source": "telegram",
            "chat_id": chat_id,
            "username": username,
        }

        # Progress callback for live updates
        def _progress_update(msg: str) -> None:
            if callable(send):
                # Generate a personal response for each progress update
                orchestrator_reply = self._generate_orchestrator_reply(
                    f"User '{username}' asked: '{text[:100]}...' — "
                    f"Progress update: {msg}. Respond briefly and personally."
                )
                send(orchestrator_reply)

        # Initial acknowledgment
        if callable(send):
            orchestrator_reply = self._generate_orchestrator_reply(
                f"User '{username}' asked: '{text[:100]}...' — Acknowledge briefly and say you're working on it."
            )
            send(orchestrator_reply)

        result = self.process_task(text, context, progress_callback=_progress_update)

        if result.get("success"):
            return self._format_plan_for_telegram(result)

        return f"Fehler beim Planen: {result.get('error', 'Unbekannter Fehler')}"

    def _generate_orchestrator_reply(self, prompt: str) -> str:
        """Generate a living, personal response from the Orchestrator.
        
        The Orchestrator has IDENTITY, SOUL, and USER context — 
        it should respond like a real person, not a robot.
        """
        if not self.orchestrator or not self.orchestrator.kernel:
            return "Ich arbeite daran..."
        
        try:
            system_prompt = self.orchestrator.get_system_prompt()
            response = self.orchestrator.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=30,
            )
            content = str((response.get("message") or {}).get("content") or "")
            return content.strip() or "Ich arbeite daran..."
        except Exception:
            return "Ich arbeite daran..."

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
        """Run in interactive mode."""
        print("\n" + "=" * 70)
        print("INTERACTIVE MODE")
        print("=" * 70)
        print("Commands:")
        print("  <task description>  - Process a task")
        print("  status             - Show system status")
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
                    continue
                
                if user_input.lower() == "lifetime":
                    self.print_lifetime_log()
                    continue
                
                # Process as task
                result = self.process_task(user_input)
                
                # Print summary
                if result.get("success"):
                    print(f"\n[OK] Task completed in {result.get('iterations')} iteration(s)")
                    if result.get("plan"):
                        plan = result["plan"]
                        print(f"  Plan: {plan.get('title', 'Untitled')}")
                        print(f"  Steps: {len(plan.get('steps', []))}")
                else:
                    print(f"\n[FAIL] Task failed: {result.get('error', 'Unknown error')}")
                
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
