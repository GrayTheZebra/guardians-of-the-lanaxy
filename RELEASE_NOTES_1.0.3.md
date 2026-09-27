# Guardians of the LANaxy 1.0.3

## Design

- Neues terminalorientiertes LANaxy-Design mit anthrazitfarbener Hauptfläche und dezent grün getönten Karten.
- Terminal-Grün ist jetzt die primäre Akzentfarbe für aktive Zustände, Buttons, Links und Fokusrahmen.
- Rundungen wurden aus den zentralen UI-Komponenten entfernt, damit LANaxy technischer und eigenständiger wirkt.
- Dashboard, Launchpad, Module Manager, Incidents, System, Guardians und MiniGuards verwenden nun eine gemeinsame visuelle Flächenlogik.
- Historisch getrennte Kartentypen werden über gemeinsame Design-Tokens für Hintergrund, Hover und Rahmen vereinheitlicht.
- Blaue und violette Standardflächen wurden in den betroffenen Kernansichten auf die neue Grün-/Anthrazit-Palette umgestellt.

## Context menus

- Drei-Punkte-Kontextmenüs verwenden nun ebenfalls das Grün-/Anthrazit-Design.
- Z-Index und Overflow-Verhalten wurden korrigiert, damit Menüs nicht mehr hinter oder innerhalb von Karten abgeschnitten werden.
- Hover-Transforms an betroffenen Karten wurden entfernt, um unerwünschte Stacking-Contexts zu vermeiden.

## Frontend

- Das Stylesheet wird mit der LANaxy-Version als Cache-Buster eingebunden, damit neue Designs nach einem Update zuverlässig geladen werden.

## Versioning

- Öffentliche Version auf `1.0.3` erhöht.
