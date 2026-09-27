# Guardians of the LANaxy 1.0.6

## Guardians

- Das Menü **„Direkt hinzufügen“** begrenzt seine Höhe jetzt zuverlässig auf den verfügbaren Browserbereich.
- Lange Guardian-Listen werden innerhalb des Menüs vertikal gescrollt, statt aus dem Kartenrahmen herauszulaufen.
- Horizontales Überlaufen wird verhindert.
- Lange Einträge dürfen umbrechen und bleiben vollständig innerhalb des Menüs.
- Die Darstellung bleibt vollständig eckig und konsistent mit dem aktuellen LANaxy-Design.

## Fix

- Behebt einen CSS-Konflikt, bei dem die allgemeine Kontextmenü-Regel `overflow: visible !important` das speziell für die Guardian-Auswahl vorgesehene `overflow-y: auto` überschrieben hat.
