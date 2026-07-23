# MiniGuard Foundation – Testmatrix

1. Agent anlegen: Einmaligen cURL-Befehl erhalten; Liste zeigt „Nicht registriert“.
2. Registrierung: Befehl auf Linux-System mit Python 3, curl und systemd ausführen; Liste zeigt Hostname/Version.
3. Heartbeat: Nach spätestens 60 Sekunden „Online“; `systemctl status miniguard` ist active.
4. Einmaligkeit: Derselbe Registrierungsbefehl ein zweites Mal wird abgelehnt.
5. Ablauf: Registrierung mit 5 Minuten Gültigkeit nach Ablauf wird abgelehnt.
6. Authentifizierung: Falsches Bearer-Token am Heartbeat-Endpunkt ergibt HTTP 403.
7. Offline: Agent stoppen; nach drei Minuten wird „Offline“ angezeigt.
8. Deinstallation: `sudo miniguard uninstall`; Binärdatei, Konfiguration und Service werden entfernt.
9. Löschen: Dialog weist vor dem Entfernen ausdrücklich auf lokale Deinstallation hin.
10. Persistenz: Webdienst neu starten; MiniGuard-Einträge bleiben erhalten.

## Remote Checks 1.18.0
11. Systemd: aktiven Dienst via MiniGuard prüfen; falschen Dienstnamen als Critical testen.
12. Storage: `/` prüfen; Grenzwerte künstlich auf Warning/Critical setzen.
13. USB: VID/PID eines vorhandenen Geräts prüfen; falsche VID als Critical.
14. Systemlast: Grenzwerte unter aktuelle Werte setzen.
15. Dateialter: bekannte Datei und absichtlich zu kleine Altersgrenze prüfen.
16. Docker: laufenden Container prüfen; falschen Namen als Critical.
17. Agent stoppen: Remote-Guardian muss nach Timeout UNKNOWN statt falschem Geräte-Critical liefern.

## MiniGuard 1.2 / SMART
- Selbsttest liefert system_info und Werkzeugstatus
- smartctl fehlt -> UNKNOWN mit smartctl_missing
- gesundes SATA/NVMe-Gerät -> OK
- Temperatur über Warning/Critical -> entsprechender Status
- Pending/Uncorrectable/Media Errors/NVMe Critical Warning -> CRITICAL
- ungültiger Gerätepfad -> UNKNOWN, keine freie Kommandoausführung
