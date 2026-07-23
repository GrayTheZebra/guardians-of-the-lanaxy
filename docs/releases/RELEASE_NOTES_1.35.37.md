# LANaxy 1.35.37

## PBS-Assistent

- Die Quellenauswahl zeigt nur noch echte PBS-Server-Guardians an.
- Aus dem Assistenten erzeugte Datastore-, Backup-, Job- und Remote-Guardians werden nicht mehr fälschlich als API-Quelle angeboten.
- Die serverseitige Validierung akzeptiert ebenfalls ausschließlich Guardians im Prüfmodus `server` als PBS-Quelle.
- Die automatische Vorauswahl bei genau einer Quelle berücksichtigt nur noch echte PBS-Server-Verbindungen.
