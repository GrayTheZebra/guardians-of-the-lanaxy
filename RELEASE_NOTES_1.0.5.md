# Guardians of the LANaxy 1.0.5

## Launchpad

- Behebt einen HTTP-500-Fehler beim Öffnen von Guardian-Konfigurationen im Launchpad.
- Die gemeinsame Guardian-Konfigurationsroute verwendet keine undefinierte `return_to`-Variable mehr.

## SMART Guardian

- SMART-Guardians können Datenträger eines ausgewählten MiniGuards direkt aus einer Liste auswählen.
- Die Liste zeigt Modell, Größe, Seriennummer und den tatsächlichen Gerätepfad.
- Intern wird weiterhin nur der direkte `/dev/...`-Pfad gespeichert.
- Beim Wechsel des MiniGuards wird die Datenträgerliste automatisch neu geladen.
- Fehlt das gespeicherte Hardwareinventar, fragt LANaxy den MiniGuard live über `hardware_inventory` ab.
- Der Button „Datenträger neu laden“ erzwingt eine Live-Abfrage.
- Die manuelle Eingabe bleibt als Fallback erhalten.
- Die Auswahl steht sowohl im Launchpad als auch im normalen Guardian-Formular zur Verfügung.

## Oberfläche

- Feld-Hilfetexte werden nur noch beim Hover über das Fragezeichen eingeblendet.
- Tastatur- oder Feldfokus blendet den Tooltip nicht mehr automatisch ein.
- Die Tooltip-Farbgebung wurde an das aktuelle Terminal-Grün/Anthrazit-Design angepasst.
