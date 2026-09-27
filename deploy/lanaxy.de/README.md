# Öffentlicher Installer und Deinstaller auf lanaxy.de

## Ziel

Nach der Einrichtung ist LANaxy installierbar mit:

```bash
curl -fsSL https://lanaxy.de/install.sh | sudo bash
```

und wieder deinstallierbar mit:

```bash
curl -fsSL https://lanaxy.de/uninstall.sh | sudo bash
```

`install.sh` ist der öffentliche Bootstrap-Installer. Das eigentliche Programm wird aus dem jeweils neuesten stabilen GitHub-Release geladen und anhand der veröffentlichten SHA-256-Prüfsumme geprüft.

`uninstall.sh` entfernt die LANaxy-Systemintegration und bietet wahlweise eine vollständige Entfernung oder den Erhalt von Konfiguration und Daten.

## Installer und Deinstaller veröffentlichen

Auf dem Webserver dieses Repository auschecken und anschließend ausführen:

```bash
cd /opt/guardians-of-the-lanaxy
sudo ./scripts/deploy-public-installer.sh
```

Das Skript veröffentlicht gleichzeitig:

- `/install.sh`
- `/uninstall.sh`

Optional können Installer-Quelle und Webroot wie bisher angegeben werden:

```bash
sudo ./scripts/deploy-public-installer.sh /pfad/bootstrap.sh /var/www/lanaxy
```

Optional kann als drittes Argument eine abweichende Deinstaller-Quelle angegeben werden:

```bash
sudo ./scripts/deploy-public-installer.sh /pfad/bootstrap.sh /var/www/lanaxy /pfad/uninstall.sh
```

Danach die passende Beispielkonfiguration in den bereits vorhandenen HTTPS-VHost übernehmen:

- nginx: `deploy/lanaxy.de/nginx-location.conf.example`
- Apache: `deploy/lanaxy.de/apache-location.conf.example`

Anschließend prüfen:

```bash
curl -fsSIL https://lanaxy.de/install.sh
curl -fsSL https://lanaxy.de/install.sh | bash -n
curl -fsSIL https://lanaxy.de/uninstall.sh
curl -fsSL https://lanaxy.de/uninstall.sh | bash -n
```

## DNS

Wenn `https://lanaxy.de` bereits mit einem gültigen Let's-Encrypt-Zertifikat erreichbar ist, ist keine zusätzliche DNS-Änderung nötig. `/install.sh` und `/uninstall.sh` liegen auf derselben Domain und benötigen weder eine Subdomain noch einen separaten Record.

Optional kann `www.lanaxy.de` per CNAME auf `lanaxy.de` zeigen; für die Installations- und Deinstallationsbefehle wird dies nicht benötigt.

## GitHub-Release

Ein Release erzeugt unter anderem diese Assets:

- `guardians-of-the-lanaxy.zip`
- `guardians-of-the-lanaxy.zip.sha256`
- `install.sh`
- `install.sh.sha256`
- `uninstall.sh`
- `uninstall.sh.sha256`

Die Namen des Programmarchivs müssen stabil bleiben, da der Bootstrap-Installer die GitHub-URL `releases/latest/download/...` verwendet.
