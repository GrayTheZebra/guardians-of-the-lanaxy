# Guardians of the LANaxy 1.14.2

## Behoben

- Dashboard-Widgets wechseln nun korrekt in vier Größenstufen: 1/4, 2/4, 3/4 und 4/4.
- Der erste Klick auf „Größe“ vergrößert ein kleines Widget sichtbar auf die normale Breite.
- Der zweite Klick wechselt anschließend auf die breite Darstellung mit 3/4 Breite.

## Ursache

Die CSS-Klassen `widget-size-small` und `widget-size-normal` verwendeten beide `grid-column: span 1`. Der interne Größenwert wurde zwar beim ersten Klick geändert, die sichtbare Breite blieb jedoch identisch.
