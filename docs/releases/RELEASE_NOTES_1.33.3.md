# Guardians of the LANaxy 1.33.3

- `/health` serialisiert Backup-Metadaten ohne `Path`-Objekte.
- Unerwartete Healthcheck-Fehler liefern strukturiertes JSON statt HTTP 500.
- Der Update-Healthcheck wartet mit bis zu fünf Versuchen auf den Webdienst.
- Bei einem Fehler wird die vollständige Health-Antwort im Terminal ausgegeben.
