# Risk Management Guidelines

## Risiko-Kategorien

### Technische Risiken

#### Code/Implementation
- **Breaking Changes**: Änderungen könnten bestehende Funktionalität zerstören
- **Performance**: Neue Implementierung könnte langsamer sein
- **Kompatibilität**: Funktioniert nicht mit allen Ziel-Systemen
- **Technical Debt**: Schnelle Lösung erzeugt zukünftige Probleme

#### Integration
- **API Changes**: Externe APIs ändern sich
- **Dependency Issues**: Bibliotheken haben Konflikte
- **Environment**: Funktioniert lokal aber nicht in Produktion
- **Data Migration**: Datenverlust oder -korruption

### Prozess-Risiken

#### Planung
- **Scope Creep**: Anforderungen werden während der Umsetzung erweitert
- **Unklare Anforderungen**: Was genau gewünscht ist, ist nicht definiert
- **Fehlende Informationen**: Wichtige Details fehlen
- **Wechselnde Prioritäten**: Wichtigkeit ändert sich während der Arbeit

#### Ressourcen
- **Zeit**: Nicht genug Zeit verfügbar
- **Expertise**: Benötigtes Wissen fehlt
- **Zugriff**: Kein Zugriff auf notwendige Systeme
- **Abhängigkeiten**: Externe Blocker

## Risiko-Bewertung

### Matrix: Eintrittswahrscheinlichkeit × Impact

| | **Geringer Impact** | **Mittlerer Impact** | **Hoher Impact** |
|---|---|---|---|
| **Wahrscheinlich** | ⚠️ Beobachten | ⚠️ Mitigation planen | 🚨 Kritisch |
| **Möglich** | ✅ Akzeptieren | ⚠️ Beobachten | ⚠️ Mitigation planen |
| **Unwahrscheinlich** | ✅ Akzeptieren | ✅ Akzeptieren | ⚠️ Beobachten |

### Impact-Level

- **Gering**: Lokale Auswirkung, leicht zu beheben
- **Mittel**: Mehrere Komponenten betroffen, moderate Behebungszeit
- **Hoch**: System-weit, schwer zu beheben, Daten betroffen

## Mitigation-Strategien

### 1. Vermeiden (Avoid)
Ändere den Plan um das Risiko zu eliminieren

**Beispiele:**
- Nutze stabile APIs statt experimenteller Features
- Vermeide komplexe Abhängigkeiten
- Nutze bewährte Patterns statt neuer Ansätze

### 2. Minimieren (Mitigate)
Reduziere Wahrscheinlichkeit oder Impact

**Beispiele:**
- Füge umfangreiche Tests hinzu
- Implementiere Fallback-Mechanismen
- Mache inkrementelle Änderungen
- Dokumentiere Annahmen

### 3. Transferieren (Transfer)
Übertrage das Risiko an andere

**Beispiele:**
- Nutze managed Services
- Delegiere an spezialisierte Agenten
- Nutze etablierte Bibliotheken statt Eigenbau

### 4. Akzeptieren (Accept)
Lebe mit dem Risiko, aber sei vorbereitet

**Beispiele:**
- Dokumentiere das Risiko
- Plane Zeit für Problemlösung ein
- Erstelle Rollback-Plan

## Risiko-Dokumentation

Jedes identifizierte Risiko sollte dokumentiert werden:

```json
{
  "risks": [
    {
      "id": "risk-001",
      "description": "Klare Beschreibung des Risikos",
      "category": "technical|process|resource",
      "probability": "high|medium|low",
      "impact": "high|medium|low",
      "mitigation": "Strategie zur Bewältigung",
      "owner": "Wer ist verantwortlich",
      "status": "open|mitigated|closed|accepted"
    }
  ]
}
```

## Risiko-Monitoring

Während der Plan-Ausführung:

1. **Regelmäßige Reviews**
   - Sind neue Risiken aufgetreten?
   - Haben sich Risiken verändert?
   - Sind Mitigationen wirksam?

2. **Early Warning Signs**
   - Verzögerungen in frühen Schritten
   - Qualitätsprobleme
   - Unklarheiten bei der Umsetzung
   - Widerstand im System

3. **Escalation**
   - Wann wird ein Risiko zum Orchestrator eskaliert?
   - Wer entscheidet über Plan-Änderungen?
   - Was sind die Trigger für Re-Planung?

## Rollback-Strategien

Für jeden kritischen Schritt, plane:

### Backup-Strategie
- Was muss vorher gesichert werden?
- Wie wird der vorherige Zustand wiederhergestellt?
- Wie lange dauert ein Rollback?

### Checkpoints
- An welchen Punkten ist ein Rollback noch möglich?
- Wie erkennt man, dass ein Rollback nötig ist?
- Wer autorisiert den Rollback?

### Beispiel
```json
{
  "step": "step-005",
  "rollback": {
    "trigger": "Tests schlagen fehl oder Performance < 80%",
    "action": "Stelle config.json.backup her",
    "estimated_time": "5 Minuten",
    "authorization": "orchestrator"
  }
}
```

## Lessons Learned

Nach jedem Plan:

1. **Welche Risiken sind eingetreten?**
2. **Haben die Mitigationen funktioniert?**
3. **Was wurde übersehen?**
4. **Wie können wir das nächste Mal besser planen?**

Dokumentiere Erkenntnisse für zukünftige Pläne.
