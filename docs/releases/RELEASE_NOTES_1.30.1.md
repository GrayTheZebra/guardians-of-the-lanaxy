# Guardians of the LANaxy 1.30.1

- Behebt den Startabbruch, wenn `inventory_intelligence.py` bei einem unvollständig entpackten Update fehlt.
- `miniguard_manager.py` enthält eine sichere Rückfallimplementierung, damit LANaxy trotzdem startet.
- `update.sh` prüft alle neuen Pflichtdateien und importiert zentrale Module, bevor Dienste gestoppt werden.
- Bei einem unvollständigen oder nicht importierbaren Update bleibt die laufende Installation künftig online.
