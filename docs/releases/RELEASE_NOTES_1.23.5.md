# Guardians of the LANaxy 1.23.5

- Zahlenfelder akzeptieren Komma- und Punktdarstellung.
- Ganzzahlige Sekundenwerte wie `60,0`, `60.0` oder `60` werden einheitlich als `60` gespeichert.
- Bereits vorhandene Dezimalwerte lassen sich wieder bearbeiten.
- KI-Pläne lösen vorhandene Beacons deterministisch über Name oder ID auf.
- Ein im Prompt ausdrücklich genannter vorhandener Beacon wird der erzeugten Rule zugeordnet.
- Bei genau einem aktiven Beacon genügt eine ausdrückliche Beacon-Anforderung zur eindeutigen Auswahl.
- Bestehende Beacons werden nicht dupliziert.
