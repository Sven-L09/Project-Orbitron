# Plan Structure Guidelines

## Plan-Format

Jeder Plan sollte folgende Struktur haben:

### Header
```json
{
  "id": "einzigartige-plan-id",
  "title": "Klarer, beschreibender Titel",
  "description": "Detaillierte Beschreibung des Ziels und Kontexts",
  "status": "draft|active|completed|archived",
  "created_at": "ISO-Timestamp",
  "updated_at": "ISO-Timestamp"
}
```

### Metadaten
```json
{
  "metadata": {
    "priority": "critical|high|medium|low",
    "tags": ["relevant", "tags"],
    "estimated_duration": "Gesamtschätzung",
    "target_completion": "Zieldatum",
    "owner": "Verantwortlicher Agent/Typ"
  }
}
```

### Schritte
```json
{
  "steps": [
    {
      "id": "step-001",
      "description": "Klare, ausführbare Beschreibung",
      "status": "pending|in_progress|completed|blocked",
      "depends_on": ["step-xxx"],
      "estimated_time": "z.B. 30m, 2h, 1d",
      "priority": "critical|high|medium|low",
      "assigned_to": "Agent/Tool",
      "acceptance_criteria": ["Messbare Kriterien"],
      "notes": "Zusätzliche Informationen"
    }
  ]
}
```

## Schritt-Typen

### 1. Research/Analysis
- **Zweck**: Informationen sammeln, verstehen
- **Output**: Dokumentation, Entscheidungsgrundlage
- **Beispiele**: Code-Analyse, API-Dokumentation lesen

### 2. Design/Architecture
- **Zweck**: Struktur und Architektur definieren
- **Output**: Design-Dokument, Diagramme
- **Beispiele**: Klassen-Design, API-Design

### 3. Implementation
- **Zweck**: Code schreiben, Features implementieren
- **Output**: Funktionierender Code
- **Beispiele**: Funktion implementieren, Tests schreiben

### 4. Review/Validation
- **Zweck**: Qualität sicherstellen
- **Output**: Review-Bericht, Test-Ergebnisse
- **Beispiele**: Code-Review, Testing

### 5. Deployment/Integration
- **Zweck**: In Produktion bringen
- **Output**: Deployed System
- **Beispiele**: Release, Migration

## Prioritäts-Level

### Critical
- Blockiert andere Schritte
- Muss zuerst erledigt werden
- Hohes Risiko bei Fehlschlag

### High
- Wichtig für den Erfolg
- Sollte früh erledigt werden
- Signifikanter Impact

### Medium
- Standard-Priorität
- Kann parallelisiert werden
- Normaler Aufwand

### Low
- Nice-to-have
- Kann verschoben werden
- Geringer Impact

## Abhängigkeiten

### Arten von Abhängigkeiten

1. **Sequentiell**: Schritt B kann erst nach A beginnen
2. **Input**: Schritt B benötigt Output von A
3. **Resource**: Beide Schritte brauchen dieselbe Ressource
4. **Soft**: B wäre einfacher, wenn A fertig ist

### Darstellung
```
A ──► B ──► C
     │
     ▼
     D
```

Oder als Liste:
- `step-002` depends_on: `["step-001"]`
- `step-003` depends_on: `["step-002"]`
- `step-004` depends_on: `["step-002"]`

## Acceptance Criteria

Jeder Schritt sollte klare Akzeptanzkriterien haben:

**Gute Kriterien sind:**
- Spezifisch und messbar
- Testbar (ja/nein Entscheidung möglich)
- Unabhängig von Implementierungsdetails
- Realistisch

**Beispiele:**
- ✅ "Die Funktion `calculate_total` gibt korrekte Summen für alle Testfälle zurück"
- ❌ "Die Funktion funktioniert gut"
- ✅ "Alle Unit-Tests bestehen mit >90% Coverage"
- ❌ "Der Code ist getestet"

## Plan-Validierung

Vor Fertigstellung prüfen:
- [ ] Sind alle Schritte atomar und ausführbar?
- [ ] Sind Abhängigkeiten korrekt modelliert?
- [ ] Gibt es keine Zyklen in den Abhängigkeiten?
- [ ] Sind alle Schritte einem Agenten/Tool zugeordnet?
- [ ] Sind Akzeptanzkriterien für jeden Schritt definiert?
- [ ] Ist die Gesamtschätzung realistisch?
- [ ] Sind Risiken dokumentiert?
