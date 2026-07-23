# Guardians of the LANaxy 1.35.21

- Neuer eigenständiger GET-Webhook-Beacon.
- Sendet ausschließlich status, guardian, message und timestamp als Query-Parameter.
- Vorhandene Query-Parameter der Ziel-URL bleiben erhalten.
- Bearer-Token und zusätzliche Header bleiben möglich; Tokens erscheinen nicht in der URL.
- Formular zeigt die konkrete Beispieladresse und alle übertragenen Parameter.
