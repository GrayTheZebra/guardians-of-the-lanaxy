# LANaxy 1.35.42

## Incident-Quittierung eindeutig getrennt

- Die Quittierung befindet sich jetzt als eigener Bereich in der Incident-Bearbeitung.
- Eine optionale Quittierungsnotiz kann direkt mitgesendet werden.
- Quittieren weist ausdrücklich darauf hin, dass der Incident offen bleibt.
- Das manuelle Beenden ist räumlich und farblich getrennt und verwendet eine deutlichere Bestätigung.
- Beide Formulare besitzen explizite Submit-Buttons und unterschiedliche Endpunkte.

Die Änderung behebt die Verwechslung, bei der statt `/acknowledge` der Endpunkt `/resolve` aufgerufen wurde.
