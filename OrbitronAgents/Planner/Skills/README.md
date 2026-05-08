# Planner Agent Skills - Overview

## Willkommen

Dieses Verzeichnis enthält die Skill-Definitionen für den Planner Agent. Diese Dateien definieren, wie der Planner denken, analysieren und planen soll.

## Skill-Dateien

| Datei | Zweck |
|-------|-------|
| `01_planning_philosophy.md` | Grundprinzipien und Philosophie des Planner Agents |
| `02_task_analysis.md` | Wie Aufgaben analysiert und bewertet werden |
| `03_plan_structure.md` | Struktur und Format von Plänen |
| `04_agent_assignment.md` | Zuweisung von Schritten zu Agenten |
| `05_risk_management.md` | Risikoanalyse und -management |
| `06_communication.md` | Kommunikationsrichtlinien und Output-Format |

## Verwendung

Der Planner Agent lädt diese Dateien beim Start und verwendet sie als Kontext für seine Planungsaufgaben. Die Dateien sind in Markdown verfasst und können bei Bedarf angepasst werden.

## Erweiterung

Um neue Skills hinzuzufügen:

1. Erstelle eine neue `.md` Datei mit einer zweistelligen Nummer (z.B. `07_new_skill.md`)
2. Folge dem bestehenden Format mit klaren Überschriften
3. Füge praktische Beispiele hinzu
4. Aktualisiere diese Übersicht

## Wichtige Konzepte

### Der Planner ist ein reiner Denk-Agent

- **Tut**: Analysieren, Strukturieren, Planen, Dokumentieren
- **Tut NICHT**: Ausführen, Implementieren, Dateien ändern

### Planungsprozess

1. **Verstehen** - Anfrage und Kontext verstehen
2. **Analysieren** - Komplexität und Risiken bewerten
3. **Zerlegen** - In handhabbare Schritte aufteilen
4. **Strukturieren** - Abhängigkeiten und Prioritäten definieren
5. **Dokumentieren** - Klaren, ausführbaren Plan erstellen

### Output

Jeder Plan sollte:
- Klare Ziele haben
- Atomare Schritte enthalten
- Abhängigkeiten modellieren
- Agenten zuweisen
- Risiken dokumentieren
- Akzeptanzkriterien definieren
