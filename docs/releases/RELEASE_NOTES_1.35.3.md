# Guardians of the LANaxy 1.35.3

## Bedienung
- Neue Guardians erhalten automatisch einen eindeutigen Namen, zum Beispiel `SMART`, `SMART 2` und `SMART 3`.
- Die Kontexthilfe ist nun ein schwebendes Fenster. Beim Einklappen steht die gesamte Seitenbreite weiter zur Verfügung.

## System
- System-MQTT muss unter System explizit aktiviert werden.
- Deaktiviertes MQTT erscheint neutral grau statt als roter Fehler.
- Erst aktiviertes, aber nicht verbundenes MQTT wird als Fehler dargestellt.
- Datums- und Zeitformate werden nach dem Speichern über einen sauberen Redirect neu geladen.
- Die Formatvorschau ist nun tatsächlich Bestandteil der Systemseite und nicht mehr außerhalb des Jinja-Blocks platziert.
