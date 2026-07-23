# Installation

## Voraussetzungen

- Debian oder Ubuntu
- Root-Zugriff
- Internetzugang
- freie TCP-Portnummer 8090

## Ein-Befehl-Installation

```bash
curl -fsSL https://lanaxy.de/install.sh | sudo bash
```

Der Befehl lädt ausschließlich das aktuelle stabile GitHub Release und prüft vor der Installation die veröffentlichte SHA-256-Prüfsumme.

## Nach der Installation

```bash
lanaxy doctor
```

Die Weboberfläche ist über `http://SERVER-IP:8090` erreichbar.

## Fehlerdiagnose

```bash
systemctl status lanaxy.service lanaxy-web.service --no-pager
journalctl -u lanaxy.service -n 100 --no-pager
journalctl -u lanaxy-web.service -n 100 --no-pager
```
