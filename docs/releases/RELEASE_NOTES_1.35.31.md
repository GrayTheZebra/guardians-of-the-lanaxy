# LANaxy 1.35.31

- USB-Guardians prüfen einen vollständig angegebenen `/dev/serial/by-id/...`-Pfad nun direkt mit `lexists()`.
- Die Erkennung ist dadurch nicht mehr ausschließlich von der zuvor per `glob()` erzeugten Geräteliste abhängig.
- Gilt für lokale USB-Guardians und Prüfungen über MiniGuard.
- Diagnoseausgaben enthalten den tatsächlich verwendeten `serial_by_id_match`.
