# LANaxy 1.35.61

- Der Dienstbenutzer `lanlord` wird der Gruppe `systemd-journal` hinzugefügt.
- Diagnose-ZIPs können dadurch die Journale von `lanaxy.service` und `lanaxy-web.service` lesen.
- `journalctl --quiet` unterdrückt den irreführenden Berechtigungshinweis in den Diagnose-Dateien.
- Es werden keine Root-Rechte oder allgemeinen sudo-Berechtigungen an den Webdienst vergeben.
