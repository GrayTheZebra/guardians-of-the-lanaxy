# Öffentlicher Installer auf lanaxy.de

## Ziel

Nach der Einrichtung ist LANaxy installierbar mit:

```bash
curl -fsSL https://lanaxy.de/install.sh | sudo bash
```

`install.sh` ist nur ein kleiner Bootstrap-Installer. Das eigentliche Programm wird aus dem jeweils neuesten stabilen GitHub-Release geladen und anhand der veröffentlichten SHA-256-Prüfsumme geprüft.

## Installer veröffentlichen

Auf dem Webserver dieses Repository auschecken oder nur `bootstrap.sh` übertragen und anschließend ausführen:

```bash
cd /opt/guardians-of-the-lanaxy
sudo ./scripts/deploy-public-installer.sh
```

Optional können Quelle und Webroot angegeben werden:

```bash
sudo ./scripts/deploy-public-installer.sh /pfad/bootstrap.sh /var/www/lanaxy
```

Danach die passende Beispielkonfiguration in den bereits vorhandenen HTTPS-VHost übernehmen:

- nginx: `deploy/lanaxy.de/nginx-location.conf.example`
- Apache: `deploy/lanaxy.de/apache-location.conf.example`

Anschließend prüfen:

```bash
curl -fsSIL https://lanaxy.de/install.sh
curl -fsSL https://lanaxy.de/install.sh | bash -n
```

## DNS

Wenn `https://lanaxy.de` bereits mit einem gültigen Let's-Encrypt-Zertifikat erreichbar ist, ist keine zusätzliche DNS-Änderung nötig. `/install.sh` liegt auf derselben Domain und benötigt weder eine Subdomain noch einen separaten Record.

Optional kann `www.lanaxy.de` per CNAME auf `lanaxy.de` zeigen; für den Installationsbefehl wird dies nicht benötigt.

## GitHub-Release

Ein Tag wie `v1.0.0` erzeugt über `.github/workflows/release.yml` diese Assets:

- `guardians-of-the-lanaxy.zip`
- `guardians-of-the-lanaxy.zip.sha256`
- `install.sh`
- `install.sh.sha256`

Die Namen des Programmarchivs müssen stabil bleiben, da der Bootstrap-Installer die GitHub-URL `releases/latest/download/...` verwendet.
