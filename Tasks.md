# Orbitron — Aufgaben & Verbesserungen

> Stand: 24. Mai 2026 · Komplettanalyse des Projekt-Codebase
> **Update:** P0/P1/P2 Tasks implementiert am 24. Mai 2026

---

## 🔴 Kritische Probleme

### 1. Kein Unit-Test-Framework
- [x] Test-Infrastruktur aufbauen: `pytest` + `conftest.py` + Fixtures für Kernel, Agenten, MessageBus
- [x] Unit-Tests für `OrbitronKernel.kernel` (Session-Management, Tool-Dispatch, Skill-Registry)
- [x] Unit-Tests für `OllamaConnector` (Retry-Logik, Timeout-Handling, Error-Klassifizierung)
- [x] Unit-Tests für `FileOperations` (Pfad-Traversal-Schutz, Encoding, Edge Cases)
- [x] Unit-Tests für `AutonomousAgent` (Tool-Call-Parsing, Loop-Abbruch, Urgency-Logic)
- [x] Unit-Tests für `MessageBus` (Pub/Sub, Request/Response, Timeout, Persistence)
- [x] Unit-Tests für `AgentContext` (Scope-Verwaltung, Expiration, Persistence)
- [x] Integration-Tests für Orchestrator → Planner → Executor → Tester Pipeline

### 2. Fehlerbehandlung & Resilienz
- [x] `OllamaConnector.chat()` — bei `json.JSONDecodeError` crasht der Parser; Error-Handling für malformed responses
- [x] `ServiceSystem.run_forever()` — bei unerwarteten Exceptions im Main-Loop stirbt das System; Global Exception Handler fehlt
- [x] `AsyncTaskQueue._worker_loop()` — bei Exception im Task-Prozessor wird die Task nicht als FAILED markiert; Queue kann stecken bleiben
- [x] `TelegramBotService._poll_loop()` — bei Network-Errors kein Exponential-Backoff; kann Rate-Limited werden
- [x] `CalendarService._api_request()` — bei Token-Refresh-Fehler wird der alte (abgelaufene) Token weiterverwendet
- [x] `PandocGenerator.markdown_to_docx()` — bei Pandoc-Fehlern wird temp-file nicht aufgeräumt (`tmp_md` wird nur im `try`-Block gelöscht, nicht im `finally`)
- [x] `KernelBridge.chat_with_session()` — bei Exception wird die Session nicht bereinigt; Memory-Leak über Zeit

### 3. Sicherheitsprobleme
- [x] `FileOperations._resolve_path()` — Path-Traversal-Schutz existiert, aber `kernel._dispatch_tool()` hat KEINE Validierung der `path`-Parameter bevor Tools aufgerufen werden
- [x] `kernel.run_command` — Shell-Injection möglich; keine Sanitization des `command`-Parameters
- [ ] `.env`-Datei enthält `GOCSPX-` Client Secrets im Klartext (test_calendar_oauth.py); `.env` sollte in `.gitignore` sein
- [ ] `CalendarService` — Service-Account-Credentials werden im Memory gehalten; bei Memory-Dump wären sie lesbar
- [ ] Telegram-Bot-Token in `.env` — kein Rotation-Mechanismus, kein Secret-Management

---

## 🟡 Architektur-Verbesserungen

### 4. Orchestrator Pipeline — End-to-End-Flow stabilisieren
- [x] Orchestrator `think()` → `plan()` → `execute()` → `test()` Pipeline als einheitlicher Flow implementieren (aktuell sind die Brücken-Methoden teilweise stubs)
- [ ] Planner-Agent: Autonomer Loop funktioniert, aber die `PlannerSkill`-Klasse ist ein Legacy-Stub mit leeren Tool-Handlern (`_handle_analyze_task` gibt nur ein leeres Dict zurück)
- [ ] Executor-Agent: `execute_goal()` Methode existiert, aber der Übergang vom Orchestrator zum Executor ist nicht sauber dokumentiert — welcher Prompt wird verwendet?
- [ ] Tester-Agent: `test_quality()` Methode fehlt in der gelesenen Datei; nur der AutonomousAgent-Loop ist implementiert
- [ ] Retry-Logik: Wenn der Tester "poor" meldet, sollte der Orchestrator automatisch einen neuen Executor-Run mit den Tester-Feedback anstoßen (aktuell nicht implementiert)

### 5. Session & Kontext-Management
- [x] `SessionManager` im Kernel — wird in `__init__` referenziert aber die Klasse ist nicht im gelesenen Code definiert (muss in kernel.py sein oder importiert werden)
- [x] Telegram-Chat-Sessions werden per `chat_id` verwaltet, aber es gibt kein Session-Timeout/Cleanup — über Tage/Wochen wächst der Memory unbegrenzt
- [x] `MemoryStore.short_term` ist auf 20 Einträge limitiert, aber `long_term` hat kein Limit — `facts.json` wächst unbegrenzt
- [x] `AgentContext` hat `MAX_ENTRIES_PER_SCOPE = 100`, aber es gibt keine Garbage-Collection für abgelaufene Entries (nur bei `get()` werden sie entfernt, nicht proaktiv)
- [ ] Kontext-Dateien (IDENTITY.md, SOUL.md, USER.md) werden bei jedem `get_full_context()` neu geladen — Caching existiert, aber kein Invalidation-Mechanismus wenn sich die Dateien ändern

### 6. Message System — Lücken schließen
- [x] `MessageBus._deliver_message()` — Broadcast-Nachrichten werden an ALLE Handler gesendet, auch an den Sender selbst (Loop-Gefahr)
- [x] `MessageBus` — keine Dead-Letter-Queue; Nachrichten die nicht zugestellt werden können, gehen verloren (`messages_dropped` wird nur gezählt)
- [ ] `OrchestratorCommunicator` — in `agent_api.py` definiert, aber die Klasse wird in den Bridge-Modulen nicht verwendet (dort wird direkt `AgentCommunicator` instanziiert)
- [ ] `PlannerCommunicator` und `TesterCommunicator` — in `message_types.py` referenziert, aber nicht im gelesenen Code definiert
- [ ] Async Request/Response — `send_to_role()` mit `wait_for_response=True` blockiert den Thread; bei mehreren gleichzeitigen Requests kann das zum Deadlock führen

### 7. Konfiguration & Deployment
- [x] Kein `pyproject.toml` oder `setup.py` — Projekt kann nicht als Package installiert werden (`pip install -e .`)
- [x] `requirements.txt` ist unvollständig — fehlt: `python-docx`, `playwright`, `google-auth-oauthlib`, `google-api-python-client`, `python-telegram-bot` (oder was auch immer für den Bot verwendet wird)
- [ ] Kein Docker-Support — für den Zug-Betrieb wäre ein Container ideal
- [ ] Kein systemd-Service oder Process-Manager — `main.py` läuft als nacktes Python-Skript
- [ ] Logging rotiert nicht — Log-Dateien wachsen unbegrenzt in `~/.orbitron/logs/`
- [ ] Keine Health-Check- oder Monitoring-Endpoints

---

## 🟢 Feature-Verbesserungen

### 8. Telegram-Bot — Alltagstauglichkeit
- [x] Markdown-Formatierung für Antworten (Telegram unterstützt MarkdownV2)
- [ ] Datei-Empfang: Nutzer können Dokumente/Bilder an den Bot senden, die im Workspace gespeichert werden
- [ ] Sprachnachrichten-Transkription (Whisper API oder lokal)
- [ ] Konversations-Kontext über mehrere Nachrichten hinweg (aktuell wird jeder Task unabhängig verarbeitet)
- [x] `/cancel` Kommando zum Abbrechen des aktuellen Tasks
- [x] Fortschritts-Updates bei langlaufenden Tasks (z.B. "Executor arbeitet... 3/10 Schritte erledigt")

### 9. Word/Dokument-Erstellung — "Besser als führende KI-Anbieter"
- [ ] Inhaltsverzeichnis-Generierung funktioniert, aber TOC-Update in Word erfordert manuelles Aktualisieren — automatisches TOC-Refresh via `python-docx`
- [ ] Tabellen-Formatierung: Aktuell nur einfache Markdown-Tabellen — professionelle Tabellen mit Zellen-Verbindung, Farb-Header etc.
- [ ] Bild-Einbettung: MarkdownBuilder hat `add_image()`, aber der PandocGenerator übergibt Bildpfade nicht korrekt an Pandoc
- [ ] PDF-Export: Zusätzlich zu DOCX auch PDF-Generierung (Pandoc → PDF via LaTeX oder WeasyPrint)
- [ ] E-Mail-Export: Dokument direkt als E-Mail-Vorlage formatieren
- [ ] Versionskontrolle: Alte Dokumentversionen behalten und diffbar machen

### 10. Calendar-Integration — Alltagserleichterung
- [ ] OAuth2-Flow für den Telegram-Bot: Aktuell funktioniert der OAuth2-Flow nur im Test-Skript (`test_calendar_oauth.py`), nicht im laufenden System
- [x] Token-Refresh automatisieren: Aktuell muss der Token manuell erneuert werden
- [x] Natürlichsprachige Termin-Erkennung: "Morgen um 15 Uhr" → korrekte ISO-8601-Zeitzonen-Konvertierung (Europe/Berlin)
- [x] Termin-Konflikterkennung: Vor dem Erstellen eines Termins prüfen, ob es Überschneidungen gibt
- [ ] Termin-Erinnerungen: Proaktive Benachrichtigung über anstehende Termine via Telegram
- [ ] Wiederkehrende Termine unterstützen


### 11. QuickResponder — Intelligente Schnellantworten
- [ ] Kontext-Gedächtnis: QuickResponder hat kein Gedächtnis über vorherige Nachrichten — bei Folgefragen wird immer der volle Pipeline gestartet
- [ ] Kalender-Keywords sind hardcodiert — sollten konfigurierbar oder via ML erweiterbar sein
- [ ] Action-Keywords sind Deutsch-spezifisch — Internationalisierung fehlt
- [ ] QuickResponder nutzt nur Kernel-Tools (file ops) — könnte erweitert werden: Git-Status, System-Info, etc.
- [ ] Fallback-Strategie: Wenn die LLM-Klassifizierung fehlschlägt (JSON-Parse-Error), wird `None` zurückgegeben → Task geht an den Orchestrator, aber ohne sinnvolle Fehlermeldung

### 12. Reflection Engine — Lernfähigkeit verbessern
- [x] `ReflectionEngine` ist implementiert, wird aber vom Orchestrator nicht automatisch nach jedem Task aufgerufen
- [x] USER.md-Updates: Die ReflectionEngine kann Empfehlungen generieren, aber es gibt keinen Mechanismus, diese automatisch in USER.md zu schreiben
- [ ] Muster-Erkennung: `_detect_patterns()` und `_generate_recommendations()` sind in der gelesenen Datei nicht vollständig implementiert
- [ ] Cross-Task-Learning: Reflections werden gespeichert, aber nicht in den System-Prompt des Orchestrators eingebunden

---

## 🔵 Code-Qualität & Wartbarkeit

### 13. Code-Duplikation & Konsistenz
- [x] `_load_dotenv()` ist 3x implementiert: `kernel.py`, `ServiceSystem.py`, `main.py` — in ein gemeinsames Utility-Modul auslagern
- [x] Datums-Formatierung (`months_de` Dict) ist 4x dupliziert: `ExecutorAgent.py`, `TesterAgent.py`, `QuickResponder`, `docx_post_processor.py` — in ein `utils/dates.py` Modul auslagern
- [ ] `AgentSkill`-Basisklasse in `kernel.py` und `skill_base.py` — zwei verschiedene Basisklassen für denselben Zweck
- [ ] `ToolDefinition` in `agent_tools.py` und `AgentSkill._tools` in `kernel.py` — parallele Tool-Registrierungssysteme
- [ ] `ExecutionState` und `StepResult` in `execution_state.py` — werden im ExecutorAgent importiert, aber der Agent hat auch eigene Tracking-Variablen (`_file_operations`, `_files_read`)

### 14. Typisierung & Dokumentation
- [ ] Keine `py.typed` Marker — Typ-Checker können die Package-Typen nicht finden
- [ ] Viele `dict[str, Any]` Return-Types — sollten zu benannten Dataclasses oder TypedDicts werden
- [ ] Fehlende Docstrings in mehreren Modulen (besonders `execution_state.py`, `skill_base.py`)
- [ ] Keine API-Dokumentation (Sphinx/MkDocs) für die Module
- [ ] `Orchestrator.py` ist >400 Zeilen — sollte in Submodule aufgeteilt werden (ContextLoader, MemoryStore, etc.)

### 15. Logging & Observability
- [ ] Logging ist konsistent (gut!), aber es gibt keine strukturierte Log-Ausgabe (JSON-Logs für ELK-Stack)
- [ ] Keine Metriken: Wie lange dauert ein Task im Durchschnitt? Wie oft schlägt der Executor fehl?
- [ ] `LifetimeLogger` speichert Events im Memory — bei einem Crash sind alle Events weg (kein Flush-on-Signal)
- [ ] Kein Tracing: Welcher Task lief durch welche Agenten? Wo war der Flaschenhals?

---

## 🟣 Neue Features — "Orbitron als Alltagshelfer"

### 16. Zugfahrten-Modus
- [ ] Progressive Response: Bei langen Tasks Zwischenergebnisse an Telegram senden (nicht erst am Ende)
- [ ] Task-Queue visualisieren: `/queue` Kommando zeigt Position und geschätzte Wartezeit
- [ ] Auto-Save: Ergebnisse automatisch im Workspace speichern, auch wenn die Telegram-Verbindung abbricht

### 17. Persönlicher Assistent
- [ ] USER.md automatisch aktualisieren: Präferenzen, häufige Aufgaben, Projekte
- [ ] Gewohnheiten erkennen: "Du fragst jeden Montag nach deinen Terminen" → proaktiver Reminder
- [ ] Notiz-System: "Merke dir X" → speichert in USER.md oder eigenem Notizen-File
- [ ] Task-Templates: Häufige Aufgaben als Vorlagen (z.B. "Wochenbericht erstellen", "Sitzungsprotokoll")
- [ ] Kontext über Sessions hinweg: Letzte 5 Konversationen als Kontext für neue Tasks

### 18. Entwickler-Erfahrung verbessern
- [ ] CLI-Interface neben Telegram: `orbitron chat "..."` für schnelle Kommandozeilen-Nutzung
- [ ] Web-Dashboard: Status, Task-Queue, Logs, Metriken in einem einfachen Web-UI
- [ ] Hot-Reload: Änderungen an IDENTITY.md, SOUL.md, USER.md ohne Neustart übernehmen
- [ ] Debug-Modus: Ausführliche Logs was jeder Agent tut, welche Tools aufgerufen werden, etc.
- [ ] Konfigurations-Validierung: Beim Start prüfen ob alle Abhängigkeiten installiert sind, .env korrekt ist, etc.

### 19. Erweiterte Test-Fähigkeiten
- [ ] Snapshot-Testing: Generierte Dokumente gegen Referenz-Dokumente vergleichen
- [ ] Performance-Testing: Ladezeiten und Ressourcenverbrauch messen
- [ ] Accessibility-Audit: WCAG-Konformität automatisch prüfen

---

## 📋 Priorisierung (Vorschlag)

| Priorität | Task-# | Begründung |
|-----------|--------|------------|
| P0 | 1, 2, 3 | Ohne Tests und Stabilität ist alles andere auf Sand gebaut |
| P1 | 4, 5, 6 | Pipeline muss zuverlässig end-to-end funktionieren |
| P1 | 8, 10 | Telegram + Calendar = Kern-Nutzungsszenario |
| P2 | 9, 11, 12 | Word + QuickResponder = täglicher Mehrwert |
| P2 | 13, 14, 15 | Code-Qualität für langfristige Wartbarkeit |
| P3 | 16, 17, 18, 19 | Neue Features für den Alltagshelfer-Anspruch |

---

*Erstellt durch vollständige Codebase-Analyse am 24. Mai 2026*