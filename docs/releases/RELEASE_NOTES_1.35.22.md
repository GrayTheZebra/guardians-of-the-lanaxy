# Guardians of the LANaxy 1.35.22

- GET-Webhook erhält eine frei editierbare Query-Vorlage.
- Standard: `status={status}&guardian={guardien}&message={text}&timestamp={date}`.
- Unterstützt feste Zusatzparameter, etwa `action=red_on` für ioBroker.
- Dynamische Werte werden automatisch URL-kodiert.
- Unterstützte Platzhalter: status, guardian/guardien, message/text, timestamp/date, title und kind.
