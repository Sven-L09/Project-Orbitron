# Task Analysis Guidelines

## Analyse-Framework

Bei jeder Anfrage soll der Planner folgende Aspekte analysieren:

### 1. Zielklarheit
- Was ist das gewünschte Ergebnis?
- Ist das Ziel spezifisch und messbar?
- Gibt es mehrere mögliche Interpretationen?
- Was wäre ein "Erfolg"?

### 2. Kontext
- Welche bestehenden Systeme sind betroffen?
- Gibt es relevante Code-Basis zu berücksichtigen?
- Welche Abhängigkeiten existieren?
- Gibt es zeitliche oder technische Constraints?

### 3. Komplexitätsbewertung

| Level | Beschreibung | Beispiele |
|-------|--------------|-----------|
| **Einfach** | Einzelne, klare Aufgabe | Datei erstellen, einfache Funktion schreiben |
| **Mittel** | Mehrere zusammenhängende Schritte | Feature implementieren mit Tests |
| **Komplex** | Umfassende Änderungen über mehrere Systeme | Architektur-Refactoring, neue Integration |
| **Sehr Komplex** | Strategische Änderungen mit weitreichenden Auswirkungen | System-Redesign, Migration |

### 4. Risikoanalyse

**Technische Risiken:**
- Breaking Changes
- Performance-Impact
- Kompatibilitätsprobleme
- Datenverlust-Risiko

**Prozess-Risiken:**
- Unklare Anforderungen
- Fehlende Ressourcen
- Zeitdruck
- Abhängigkeiten von externen Systemen

### 5. Aufwandschätzung

Für jeden Schritt schätze:
- **Optimistisch**: Best case scenario
- **Realistisch**: Wahrscheinlichster Fall
- **Pessimistisch**: Worst case mit Problemen

Formel: `(Optimistisch + 4×Realistisch + Pessimistisch) / 6`

## Analyse-Output

Jede Analyse sollte enthalten:

```
Zusammenfassung: [Eine klare Beschreibung des Ziels]
Komplexität: [Einfach/Mittel/Komplex/Sehr Komplex]
Geschätzter Gesamtaufwand: [Zeitschätzung]

Haupt-Risiken:
1. [Risiko 1] → Mitigation: [Wie minimieren]
2. [Risiko 2] → Mitigation: [Wie minimieren]

Kritische Annahmen:
- [Annahme 1]
- [Annahme 2]

Empfohlener Ansatz:
[Kurze Beschreibung der Strategie]
```
