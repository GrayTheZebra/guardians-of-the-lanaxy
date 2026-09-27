# Guardians of the LANaxy 1.0.7

## MiniGuards

- MiniGuard-Karten wurden kompakter und übersichtlicher aufgebaut.
- Hostname, Agent-Version, Remote-Worker und Fähigkeiten erscheinen in einer kompakten Statuszeile.
- Die Karte verwendet weniger verschachtelte Kacheln und stärker Trennlinien und Typografie.
- Der direkte Button **Agent aktualisieren** bleibt sichtbar.
- Diagnose und Inventaraktualisierung liegen unter **Weitere Aktionen**.
- Der Bootstrap-cURL-Befehl wird nur für ältere Agents ohne direkte Verwaltung gezeigt.

## Automatische MiniGuard-Updates

- Auto-Update kann pro MiniGuard aktiviert oder deaktiviert werden.
- LANaxy vergleicht beim Heartbeat die installierte Agent-Version mit der mit LANaxy ausgelieferten Version.
- Ist der Agent älter, wird automatisch genau ein Update-Auftrag eingereiht.
- Laufende oder wartende Update-Aufträge werden nicht dupliziert.
- Auto-Update respektiert die Aktionsberechtigung `update_agent`.
- Der Update-Auftrag verwendet die tatsächlich gebündelte MiniGuard-Version statt eines hart codierten Versionswerts.

## Diagnose

- Diagnoseergebnisse zeigen jetzt **Alles OK**, Hinweise oder konkrete Probleme statt nur „Aktion abgeschlossen“.
- Konfiguration, Dienststatus, Exit-Status, Update-Bereitschaft und Neustartzähler werden kompakt dargestellt.
- Fehlende optionale Werkzeuge werden erklärt statt nur aufgelistet.
- LANaxy unterscheidet zwischen **Nicht nötig**, **Optional** und **Empfohlen**.
- Zu den Werkzeugen werden Zweck, Handlungshinweis und Links zur jeweiligen offiziellen Dokumentation angezeigt.

## Kompatibilität

- Alte MiniGuard-Datensätze erhalten beim Lesen sichere Defaults für neuere optionale Felder.
- Fehlende `inventory_aliases` oder andere optionale Felder können die MiniGuard-Seite nicht mehr mit HTTP 500 abbrechen.
- Das Template behandelt fehlende Inventar-Aliase zusätzlich defensiv.

## Oberfläche

- Die Sidebar ist wieder 272 px breit.
- Icons in Untermenüs haben eine feste Breite und werden von langen Einträgen nicht mehr zusammengedrückt.
- Dadurch ist das Icon der Konfigurationshistorie wieder sichtbar.

## Konfigurationshistorie

- Zeitstempel verwenden jetzt den zentralen LANaxy-Datums-/Zeitformatter.
- „Ältester Stand“ und Historieneinträge respektieren damit die unter System gewählten Datums- und Zeitformate.
