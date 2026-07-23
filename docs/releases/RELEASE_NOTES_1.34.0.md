# Guardians of the LANaxy 1.34.0

## Kontexthilfe
- Feste Hilfespalte auf großen Bildschirmen.
- Einklappbare Hilfe auf kleineren Ansichten.
- Seitenspezifische Erklärungen, Schritte und Hinweise.
- Feldhilfe beim Fokussieren von Eingaben.
- Auswahlabhängige Hilfe für Aktionen, Beacon-Typen, Ausführungsquelle und Schweregrad.
- Zentrale Pflege in `help_content.py`.

## Fehlerkorrektur
- `/system` verwendete nicht definierte Variablen `runtime`, `state` und `service_status`.
- Die Seite verwendet nun die bereits geladenen Laufzeit- und Zustandsdaten und ermittelt die Dienste vor dem Readiness-Aufruf.
