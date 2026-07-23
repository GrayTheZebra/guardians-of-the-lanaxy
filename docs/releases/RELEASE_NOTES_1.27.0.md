# Guardians of the LANaxy 1.27.0

- MiniGuard 1.5.0 mit Hardwareinventar für USB, PCI, Datenträger, ZFS, serielle Geräte und Backup-Dateien.
- Proxmox-Assistent übernimmt USB-, PCI-, SMART-, ZFS- und Backup-Guardians aus dem Inventar.
- Proxmox-Backups werden zusätzlich über die API angezeigt.
- Root-Cause-Analyse bewertet ausgefallene direkte und indirekte Abhängigkeiten.
- Stabile Incident-Signaturen unterstützen spätere Bündelung und Cluster-Synchronisation.
- Konfigurationshistorie mit Download und kontrollierter Wiederherstellung.
- Guardian-Export entfernt Secrets standardmäßig; ungeschützter Export muss explizit angefordert werden.
- Cluster-Basis für LANaxy 2.x: stabile Cluster-/Node-ID, vorbereitete Status-API und Join-Token-Grundlage, noch ohne automatisches Failover.
