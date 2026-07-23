# Guardians of the LANaxy 1.13.1

## Behoben

- Der Speicherplatz-Guardian wertet ein durch systemd-Härtung sichtbares `ro`-Flag nicht mehr automatisch als echten Read-only-Fehler.
- Die erkannte Mountoption bleibt als `read_only_visible` in den Details erhalten.
- Für eine zuverlässige Schreibbarkeitsprüfung dient weiterhin der optionale kontrollierte Schreibtest.
- Die Guardian-Detailansicht zeigt bei Warning-, Critical- und Unknown-Ergebnissen nun die konkrete Guardian-Meldung statt nur „Test fehlgeschlagen“.

## Kompatibilität

Konfigurationen aus 1.13.0 bleiben unverändert nutzbar.
