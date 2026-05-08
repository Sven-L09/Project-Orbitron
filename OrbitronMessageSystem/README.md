# Orbitron Message System

## Überblick

Das Orbitron Message System bietet eine klare API für die Kommunikation zwischen Agenten im Orbitron-System. Es basiert auf einem Message Bus mit Publish/Subscribe-Muster und unterstützt Request/Response-Kommunikation.

## Architektur

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Orchestrator   │◄───►│  MessageBus  │◄───►│     Planner     │
│     Agent       │     │              │     │     Agent       │
└─────────────────┘     └──────────────┘     └─────────────────┘
         │                       │                      │
         └───────────────────────┴──────────────────────┘
                    AgentCommunicator API
```

## Komponenten

### 1. Message Types (`message_types.py`)

Grundlegende Nachrichtentypen für die Kommunikation:

- **Message** - Basisklasse für alle Nachrichten
- **MessageHeader** - Routing-Informationen
- **MessageType** - Art der Nachricht (REQUEST, RESPONSE, EVENT, etc.)
- **MessagePriority** - Prioritätslevel
- **AgentRole** - Definierte Rollen (ORCHESTRATOR, PLANNER, CODER, etc.)

Spezialisierte Nachrichten:
- **PlanningRequest** - Anfrage an den Planner
- **PlanningResponse** - Antwort vom Planner
- **CommandMessage** - Befehl zur Ausführung
- **StatusMessage** - Status-Update
- **ErrorMessage** - Fehlermeldung

### 2. Message Bus (`message_bus.py`)

Zentrale Kommunikationsinfrastruktur:

```python
from OrbitronMessageSystem import get_message_bus

bus = get_message_bus()
bus.start()

# Agent registrieren
handler_id = bus.register(
    agent_name="my_agent",
    agent_role=AgentRole.CODER,
    callback=on_message_received,
)

# Nachricht senden
bus.publish(message)

# An spezifischen Agenten senden
response = bus.send(
    recipient="planner",
    message=message,
    wait_for_response=True,
    timeout_ms=30000,
)
```

### 3. Agent API (`agent_api.py`)

High-Level API für Agenten:

```python
from OrbitronMessageSystem import (
    create_orchestrator_communicator,
    create_planner_communicator,
)

# Orchestrator erstellen
orch = create_orchestrator_communicator("orchestrator-1")
orch.connect()

# Planning anfragen
response = orch.request_planning(
    request="Implementiere User Authentication",
    context={"priority": "high"},
    timeout_ms=60000,
)

# Planner erstellen
planner = create_planner_communicator("planner-1")
planner.connect()

# Planungsergebnis senden
planner.send_planning_result(
    request_id=request_id,
    plan={"steps": [...]},
    analysis={"complexity": "medium"},
)
```

### 4. Orchestrator-Planner Bridge (`orchestrator_planner_bridge.py`)

Spezialisierte Integration zwischen Orchestrator und Planner:

```python
from OrbitronMessageSystem.orchestrator_planner_bridge import (
    OrchestratorPlannerBridge,
    PlannerMessageHandler,
)

# Im Orchestrator
bridge = OrchestratorPlannerBridge("orchestrator-1")
result = bridge.request_plan(
    task_description="Implementiere Feature X",
    context={"files": ["main.py"]},
)

# Im Planner
handler = PlannerMessageHandler(planner_agent, "planner-1")
# Handler empfängt automatisch Nachrichten und routed sie an den Agenten
```

## Nachrichten-Fluss

### Synchrone Planungs-Anfrage

```
Orchestrator                    Planner
     │                              │
     ├─ PlanningRequest ───────────►│
     │                              │
     │                    [Processing]
     │                              │
     │◄─ PlanningResponse ─────────┤
     │                              │
```

### Asynchrone Planungs-Anfrage

```
Orchestrator                    Planner
     │                              │
     ├─ PlanningRequest ───────────►│
     │                              │
     │  [Weiterarbeit möglich]       │
     │                              │
     │                    [Processing]
     │                              │
     │◄─ PlanningResponse (Callback)─┤
     │                              │
```

## API-Referenz

### AgentCommunicator

Hauptklasse für Agent-Kommunikation:

| Methode | Zweck |
|---------|-------|
| `connect()` | Mit Message Bus verbinden |
| `disconnect()` | Verbindung trennen |
| `request_planning()` | Planung anfragen (sync) |
| `request_planning_async()` | Planung anfragen (async) |
| `send_command()` | Befehl senden |
| `send_status()` | Status broadcasten |
| `respond_to()` | Auf Nachricht antworten |
| `send_error()` | Fehler senden |

### MessageBus

Zentrale Nachrichten-Infrastruktur:

| Methode | Zweck |
|---------|-------|
| `register()` | Agent registrieren |
| `unregister()` | Agent abmelden |
| `publish()` | Nachricht veröffentlichen |
| `send()` | An spezifischen Agenten senden |
| `send_to_role()` | An alle mit Rolle senden |

## Beispiele

### Einfache Planungs-Anfrage

```python
from OrbitronMessageSystem import (
    create_orchestrator_communicator,
    get_message_bus,
)

# Setup
bus = get_message_bus()
bus.start()

orch = create_orchestrator_communicator()
orch.connect()

# Planung anfragen
result = orch.request_planning(
    request="Refactor authentication module",
    context={
        "current_implementation": "session-based",
        "target": "JWT-based",
    },
)

if result:
    plan = result.payload.get("plan")
    print(f"Plan: {plan['title']}")
```

### Mit Callback

```python
def on_planning_complete(response):
    if response.metadata.get("success"):
        plan = response.payload["plan"]
        print(f"✓ Plan received: {plan['title']}")
    else:
        print(f"✗ Error: {response.metadata.get('error')}")

request_id = orch.request_planning_async(
    request="Implement feature X",
    callback=on_planning_complete,
)
```

### Status-Updates

```python
# Vom Planner
planner.send_status(
    status="working",
    details={
        "current_task": "Analyzing requirements",
        "progress_percent": 25,
    },
)
```

## Prioritäten

| Priorität | Verwendung |
|-----------|------------|
| CRITICAL | Sofortige Verarbeitung nötig |
| HIGH | Wichtige Anfragen |
| NORMAL | Standard-Priorität |
| LOW | Kann verzögert werden |
| BACKGROUND | Bei Idle-Zeit verarbeiten |

## Fehlerbehandlung

```python
# Timeout bei Planungs-Anfrage
result = orch.request_planning(
    request="Complex task",
    timeout_ms=120000,  # 2 Minuten
)

if result is None:
    print("Planning request timed out")

# Fehler senden
orch.send_error(
    error_code="PLANNING_FAILED",
    error_message="Could not create plan",
    original_message_id=request_id,
)
```

## Erweiterung

Neue Agenten-Typen können einfach hinzugefügt werden:

```python
from OrbitronMessageSystem import AgentCommunicator, AgentRole

class ReviewerCommunicator(AgentCommunicator):
    def __init__(self, agent_name: str = "reviewer"):
        super().__init__(agent_name, AgentRole.REVIEWER)
    
    def request_review(self, code: str) -> Optional[Message]:
        return self.send_command(
            command="review_code",
            args={"code": code},
            recipient_role=AgentRole.REVIEWER,
        )
```
