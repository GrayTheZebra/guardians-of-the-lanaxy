# Guardians of the LANaxy 1.13.0

## Neue Guardians

### HTTP/HTTPS Guardian

- GET- und HEAD-Prüfungen
- einzelne Statuscodes und Statusbereiche
- Timeout sowie Warning-/Critical-Grenzen für Antwortzeiten
- Redirect-Steuerung
- eigene Header und Bearer-Token
- Textsuche und JSON-Pfad-Prüfung
- TLS-Validierung und Warnung vor Zertifikatsablauf
- differenzierte Fehlerdetails für Verbindung, Timeout und TLS

### Systemd Service Guardian

- Unit-Existenz
- ActiveState und SubState
- Aktivierungszustand
- Neustartzähler
- Mindestlaufzeit nach Neustart
- Exit- und Result-Informationen in den Details

### Speicherplatz Guardian

- Pfad- und optionale Mountpoint-Prüfung
- freie Bytes und Prozent
- Warning-/Critical-Grenzen in Prozent und MB
- Inode-Auslastung
- Read-only-Erkennung
- optionaler kontrollierter Schreibtest
- Dateisystem-, Quelle- und Mountoptionen in den Details

## Oberfläche und Integration

- Mehrzeilige Guardian-Konfigurationsfelder werden unterstützt.
- Bearer-Token werden als Secret behandelt.
- Alle neuen Guardians werden automatisch durch Module Manager und Launchpad erkannt.
- Bestehende Dashboard-, Incident-, Rule-, Test- und ZIP-Funktionen bleiben kompatibel.
