# Guardians of the LANaxy 1.31.1

- Korrigiert die Pflichtdateiprüfung in `update.sh`: `inventory_intelligence.py` und `assistant_planner.py` werden jetzt als zwei getrennte Dateien geprüft.
- `assistant_planner` wird zusätzlich im Python-Vorabtest importiert.
- Die laufenden Dienste bleiben bei einem fehlgeschlagenen Vorabtest weiterhin unangetastet.
