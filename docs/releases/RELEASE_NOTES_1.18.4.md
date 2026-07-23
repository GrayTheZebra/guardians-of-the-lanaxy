# Guardians of the LANaxy 1.18.4

## Behoben

- Der MiniGuard-Polling-Endpunkt importiert Flask `jsonify` nun korrekt.
- Dadurch liefern `/api/miniguards/<agent-id>/checks/next` und die Fehlerbehandlung wieder gültige JSON-Antworten statt HTTP 500.
- Der Remote-Check-Dienst wird nach dem nächsten erfolgreichen Poll als aktiv erkannt.

## Ursache

Die MiniGuard-Routen verwendeten `jsonify`, obwohl die Funktion nicht aus Flask importiert war. Auch der Fehlerhandler rief dieselbe nicht importierte Funktion auf, wodurch eine HTML-500-Seite entstand.
