# Guardians of the LANaxy 1.28.0

## USB-Hardwareinventar
- MiniGuard 1.6.0 ergänzt `udevadm`-Daten und `/dev/serial/by-id`.
- USB-Einträge erhalten Modell, Hersteller, Seriennummer, stabilen Gerätepfad und Treiber.
- Bekannte USB-IDs werden verständlicher beschrieben.
- Bei generischen CP210x-/CH340-Chips wird transparent als wahrscheinliche, nicht sichere Zuordnung gekennzeichnet.

## PBS-Assistent
- Neuer Assistent für Proxmox Backup Server.
- Erkennt Datastores, Backup-Gruppen, Verify-, Prune-, Sync- und GC-Jobs.
- Legt Datastore-, Backup-Alter- und Job-Guardians gesammelt an.
- Automatische Abhängigkeiten zum PBS-Server und Datastore.
- Optionaler Updates-/Neustart-Guardian über MiniGuard.
- PBS Guardian unterstützt jetzt Server-, Datastore-, Backup- und Jobmodus.

## Guardian-Verwaltung
- Filter und Aktionen sind in zwei getrennte Zeilen aufgeteilt.
- Neuer direkter Einstieg zum PBS-Assistenten.
