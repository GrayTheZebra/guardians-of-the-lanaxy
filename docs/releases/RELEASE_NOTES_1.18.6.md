# Guardians of the LANaxy 1.18.6

## MiniGuard Bootstrap

- Installations- und Aktualisierungsbefehle sind deutlich kürzer.
- Root- und sudo-Erkennung erfolgt vollständig im ausgelieferten Bootstrap-Script.
- Agent-ID, Registrierungscode und Update-Modus werden serverseitig eingebettet.
- Das Bootstrap-Script prüft curl und Python 3, lädt den eigentlichen Installer und zeigt verständliche Fortschrittsmeldungen.
- Installation: `curl -fsSL <LANaxy>/miniguard/i/<agent-id>/<code> | sh`
- Aktualisierung: `curl -fsSL <LANaxy>/miniguard/u/<agent-id> | sh`
