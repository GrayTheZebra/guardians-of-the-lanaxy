# LANaxy 1.35.29

## USB-Inventar

- USB-Geräte mit identischer Vendor-/Product-ID werden über ihre konkrete Bus-/Device-Instanz zu `/dev/serial/by-id` zugeordnet.
- SONOFF Zigbee- und Z-Wave-Sticks mit demselben CP210x-Chip werden nicht mehr als dasselbe Gerät dargestellt.
- Eine mehrdeutige VID/PID-Zuordnung verwendet nicht mehr fälschlich den ersten gefundenen Gerätenamen.
- MiniGuard-Agent auf Version 1.7.2 angehoben.
