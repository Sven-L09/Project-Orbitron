# Agent Assignment Guidelines

## Verfügbare Agenten

Der Planner sollte bei der Zuweisung von Schritten die folgenden Agenten-Typen berücksichtigen:

### Orchestrator
- **Rolle**: Koordination, Kontext-Management, Entscheidungen
- **Stärken**: Gesamtübersicht, Kontext-Verständnis, Benutzer-Interaktion
- **Verwendung für**: High-Level Koordination, komplexe Entscheidungen

### Planner (Selbst)
- **Rolle**: Strategie, Planung, Analyse
- **Stärken**: Strukturierung, Risikoanalyse, Aufwandschätzung
- **Verwendung für**: Plan-Erstellung, komplexe Analysen

### Code-Implementierer (zukünftig)
- **Rolle**: Code schreiben, Features implementieren
- **Stärken**: Programmierung, Code-Generierung, Refactoring
- **Verwendung für**: Implementation-Schritte

### Reviewer (zukünftig)
- **Rolle**: Code-Review, Qualitätssicherung
- **Stärken**: Fehlerfinden, Best-Practices, Optimierung
- **Verwendung für**: Review/Validation-Schritte

### Kernel (Tools)
- **Rolle**: Datei-Operationen, System-Interaktion
- **Stärken**: Direkte Dateisystem-Zugriffe, Tool-Ausführung
- **Verwendung für**: File-Ops, einfache Automatisierung

## Zuweisungs-Strategie

### 1. Nach Schritt-Typ

| Schritt-Typ | Empfohlener Agent |
|-------------|-------------------|
| Research/Analysis | Planner oder Orchestrator |
| Design/Architecture | Planner |
| Implementation | Code-Implementierer |
| Review/Validation | Reviewer |
| Deployment | Orchestrator oder Kernel |

### 2. Nach Komplexität

- **Einfache Aufgaben** (1-2 Schritte): Kernel direkt
- **Mittlere Aufgaben** (3-10 Schritte): Spezialisierter Agent
- **Komplexe Aufgaben** (10+ Schritte): Orchestrator mit Sub-Agenten

### 3. Nach Kontext-Anforderung

- **Hoher Kontext nötig**: Orchestrator (hat Memory)
- **Spezialisiertes Wissen**: Dedizierter Agent
- **Kein Kontext nötig**: Kernel direkt

## Zuweisungs-Notation

Im Plan verwende:

```json
{
  "assigned_to": "agent_type:specific_agent",
  "rationale": "Warum dieser Agent?"
}
```

Beispiele:
- `"assigned_to": "kernel"` - Direkte Tool-Ausführung
- `"assigned_to": "orchestrator"` - High-Level Koordination
- `"assigned_to": "planner"` - Planung/Analyse
- `"assigned_to": "code:python"` - Python-Code spezialisiert
- `"assigned_to": "reviewer"` - Code-Review

## Parallelisierung

### Wann parallelisieren?

- Unabhängige Schritte können parallel ausgeführt werden
- Keine gemeinsamen Ressourcen
- Keine sequentiellen Abhängigkeiten

### Darstellung im Plan

```json
{
  "phase": "1",
  "parallel_groups": [
    ["step-001", "step-002", "step-003"],
    ["step-004", "step-005"]
  ]
}
```

## Fallback-Strategien

Für jeden Schritt, überlege:

1. **Was wenn der Agent nicht verfügbar ist?**
   - Alternative Agenten definieren
   - `fallback_to`: ["alternative1", "alternative2"]

2. **Was wenn der Schritt fehlschlägt?**
   - Retry-Logik
   - Eskalationspfad
   - Rollback-Plan

3. **Was wenn es länger dauert?**
   - Timeout definieren
   - Checkpointing
   - Partial completion akzeptabel?

## Beispiel-Zuweisung

```json
{
  "steps": [
    {
      "id": "step-001",
      "description": "Analysiere bestehende Code-Struktur",
      "assigned_to": "planner",
      "rationale": "Benötigt strategische Analyse und Planung"
    },
    {
      "id": "step-002",
      "description": "Erstelle neue Konfigurationsdatei",
      "assigned_to": "kernel",
      "rationale": "Einfache Datei-Operation, kein Kontext nötig"
    },
    {
      "id": "step-003",
      "description": "Implementiere Hauptlogik",
      "assigned_to": "code:python",
      "rationale": "Erfordert Python-Expertise",
      "fallback_to": ["orchestrator"]
    },
    {
      "id": "step-004",
      "description": "Review und Testing",
      "assigned_to": "reviewer",
      "rationale": "Unabhängige Qualitätsprüfung"
    }
  ]
}
```
