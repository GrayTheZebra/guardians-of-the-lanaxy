# Guardians of the LANaxy 1.35.1

## Installation
- MQTT ist bei Neuinstallationen vollständig optional und standardmäßig deaktiviert.
- LANaxy startet ohne MQTT-Broker.
- `lanaxy doctor` bewertet deaktiviertes MQTT nicht als Fehler.
- Neutrale `examples/config.yaml` ohne persönliche Infrastruktur- oder Zugangsdaten.
- Release und Bootstrap prüfen, dass die Konfigurationsvorlage enthalten ist.
- Der Bootstrap verwendet `C.UTF-8`, um Locale-Warnungen auf minimalen Debian-Systemen zu vermeiden.
- Am Ende der Installation wird die konkrete Webadresse ausgegeben.
