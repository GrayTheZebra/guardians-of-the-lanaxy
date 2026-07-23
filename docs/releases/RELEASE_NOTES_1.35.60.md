# LANaxy 1.35.60

## Korrektur

- MiniGuard-AJAX-Aktionen verwenden nun das HTML-`action`-Attribut des Formulars ausdrücklich über `getAttribute("action")`.
- Das versteckte Feld `name="action"` kann dadurch die Ziel-URL nicht mehr als benannte Formulareigenschaft überschreiben.
- Behebt `Ungültige Serverantwort (HTTP 404)` bei Diagnose, Inventar, Protokoll, Update, Agent-Neustart, Token-Rotation, Rollback und Host-Neustart.
