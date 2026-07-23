# Guardians of the LANaxy 1.31.0

## Proxmox-Assistent
- Dreistufiger Ablauf: Scan, Änderungsvorschau, Bestätigung.
- Zeigt Neuanlagen, Aktualisierungen, übersprungene Objekte und konkrete Feldänderungen.
- Liest QEMU-/LXC-Konfigurationen und zeigt USB- sowie PCI-Passthrough-Zuordnungen.
- Erkennt Proxmox-Backup-Jobs und fasst das letzte gefundene Backup je VM/LXC zusammen.
- Vorhandene Guardians werden weiterhin erkannt und optional aktualisiert.

## PBS-Assistent
- Dreistufiger Ablauf mit Änderungsvorschau.
- Erkennt Namespaces, Remotes, Datastores, Backup-Gruppen, Snapshots, Verify-/Prune-/Sync-/GC-Jobs.
- Liest Subscription, verfügbare Updates und letzte Tasks soweit von der PBS-API verfügbar.
- Backup-Guardians unterstützen Namespaces.
- Neuer PBS-Remote-Prüfmodus und gesammelte Anlage von Remote-Guardians.
- Jobdaten werden mit passenden Taskinformationen angereichert.
