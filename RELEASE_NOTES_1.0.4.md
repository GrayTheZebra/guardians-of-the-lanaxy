# Guardians of the LANaxy 1.0.4

## System

- Die Systemseite ist jetzt in sieben logische Tabs gegliedert:
  - Allgemein
  - Zugriff & Sicherheit
  - Daten & Aufbewahrung
  - Backups
  - Netzwerk
  - Diagnose
  - Erweitert
- Der zuletzt geöffnete System-Tab wird im Browser gespeichert.
- Bestehende Hash-Links wie `#maintenance`, `#system-mqtt`, `#control` und `#diagnostics` öffnen automatisch den passenden Tab.
- Statuspunkte in den Tabs machen relevante Zustände schneller sichtbar.

## Konfigurationshistorie

- Der Menüeintrag verwendet jetzt ein eigenes Historien-/Datei-Icon.
- Die Historienseite zeigt Anzahl, Speicherbedarf, Aufbewahrungsdauer und ältesten Stand.
- Suche und Filter nach geändertem Bereich wurden ergänzt.
- Sicherheitsrelevante Änderungen werden markiert.
- Bereits vorhandenes Wiederherstellen bleibt erhalten.
- Die gesamte Konfigurationshistorie kann jetzt über einen bestätigten Löschvorgang geleert werden.
- Die konfigurierte Aufbewahrungsregel kann manuell sofort angewendet werden.

## Aufbewahrung

- Die automatische Aufbewahrung der Konfigurationshistorie erfolgt jetzt nach Alter statt nach einer maximalen Anzahl von Revisionen.
- Das Zahlenfeld arbeitet in Tagen.
- `0` und `-1` bedeuten unbegrenzte Aufbewahrung.
- Die Aufbewahrungsregel wird zentral über den ConfigService angewendet.
- Die alte Einstellung `config_history_keep` wird beim Speichern der neuen Aufbewahrung entfernt.

## Fixes

- Die getestete Historienseite verwendet ausschließlich vorhandene Jinja-Funktionen und vermeidet den zuvor in der Testfassung aufgetretenen HTTP-500-Fehler.
