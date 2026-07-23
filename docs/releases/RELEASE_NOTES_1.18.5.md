# Guardians of the LANaxy 1.18.5

## Behoben

- USB Guardian wertet einen eindeutigen `/dev/serial/by-id`-Treffer nicht mehr zusammen mit allen USB-Geräten aus `/sys` als mehrdeutig.
- Lokale und über MiniGuard ausgeführte USB-Prüfungen verwenden dieselbe korrigierte Logik.
- Ein eindeutiger `serial-by-id`-Name reicht nun ohne zusätzliche VID/PID/Seriennummer für eine stabile Zuordnung.
