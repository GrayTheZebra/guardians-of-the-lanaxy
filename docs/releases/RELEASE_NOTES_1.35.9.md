# Guardians of the LANaxy 1.35.9

- Guardian-Abhängigkeiten greifen nun bereits bei `warning`, nicht erst bei `critical`.
- Abhängige Folgefehler erhalten den Status `blocked`.
- `blocked`-Ereignisse lösen keine eigene Beacon-Nachricht mehr aus.
- Auch die Wiederherstellung eines zuvor blockierten Guardians wird nicht doppelt gemeldet.
- Bereits geplante Wiederholungen und Eskalationen des Folgefehlers werden beim Blockieren verworfen.
