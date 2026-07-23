# Guardians of the LANaxy 1.16.0

## Infrastructure Integration Pack

### Docker Container Guardian
- Docker Engine über lokalen Unix-Socket oder HTTP/HTTPS prüfen
- Container über Name oder ID überwachen
- Laufzustand, Docker-Healthcheck, Neustartzähler und Mindestlaufzeit prüfen
- verständliche Fehler bei fehlendem Socket, fehlenden Rechten und Docker-API-Fehlern

### Proxmox API Guardian
- API-Token-Authentifizierung
- Proxmox-Node, LXC/QEMU-Gast oder Storage prüfen
- Gaststatus und Mindestlaufzeit überwachen
- Storage-Aktivität und Belegungsgrenzen auswerten
- TLS-Prüfung optional deaktivierbar

Beide Guardians sind in Module Manager, Launchpad, Dashboard, Rules, Incidents und die einheitliche Testausgabe integriert.
