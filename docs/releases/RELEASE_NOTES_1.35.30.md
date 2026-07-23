# LANaxy 1.35.30

- Proxmox- und PBS-Assistenten übernehmen bei USB-Geräten automatisch die eindeutige Seriennummer und den `/dev/serial/by-id`-Pfad.
- USB-Guardians aus den Assistenten werden nicht mehr nur anhand von VID/PID angelegt.
- Geräte mit identischem USB-Seriell-Chip, etwa SONOFF Zigbee- und Z-Wave-Sticks mit `10c4:ea60`, werden getrennt überwacht.
- Vorschau und Bestandserkennung verwenden den eindeutigen USB-Identifier.
- Der MiniGuard akzeptiert sowohl den vollständigen `/dev/serial/by-id`-Pfad als auch nur den Symlink-Namen.
- MiniGuard-Agent auf 1.7.3 erhöht.
