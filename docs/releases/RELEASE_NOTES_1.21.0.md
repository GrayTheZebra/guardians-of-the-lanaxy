# Guardians of the LANaxy 1.21.0

## Topology & Maintenance

- Neue Topologieansicht für Guardian-Gruppen und Abhängigkeiten.
- Anzeige von zirkulären und fehlenden Abhängigkeiten.
- Abhängige Fehler werden weiterhin als `blocked` markiert und lösen keine konkurrierenden Root-Cause-Alarme aus.
- Neuer Wartungsplaner für zeitgesteuerte Wartungsfenster.
- Wartungsfenster können einzelne Guardians und komplette Gruppen erfassen.
- Geplante Fenster werden automatisch aktiviert und beendet.
- Betroffene Guardians behalten ihren technischen Unterstatus in den Details, werden aber als `maintenance` geführt.
- Wartungsfenster können deaktiviert oder gelöscht werden.
