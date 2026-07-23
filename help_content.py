from __future__ import annotations

PAGE_HELP = {
    "dashboard": {
        "title": "Übersicht",
        "intro": "Hier siehst du auf einen Blick, ob LANaxy und die überwachten Systeme funktionieren.",
        "steps": ["Zuerst rote und gelbe Guardians prüfen.", "Offene Incidents zeigen zusammengehörende Störungen.", "Die Bereitschaftsanzeige prüft LANaxy selbst."],
        "tips": ["Grün bedeutet, dass aktuell kein Problem erkannt wurde.", "Ein ausgegrauter Guardian ist deaktiviert oder wartet auf eine Abhängigkeit."],
    },
    "guardian_management": {
        "title": "Guardian-Verwaltung",
        "intro": "Guardians sind einzelne Prüfungen, zum Beispiel für einen Dienst, Datenträger oder Host.",
        "steps": ["Über „Guardian hinzufügen“ einen Prüftyp auswählen.", "Name, Ziel und Prüfintervall eintragen.", "Mit „Prüfen“ das Ergebnis kontrollieren."],
        "tips": ["Mit Gruppen bleibt eine größere Installation übersichtlich.", "Massenbearbeitung erscheint erst nach Auswahl mindestens eines Guardians."],
    },
    "guardian_select": {"title":"Guardian auswählen","intro":"Wähle aus, was überwacht werden soll. LANaxy zeigt danach nur die dafür nötigen Felder.","steps":["Nach Kategorie oder Namen suchen.","Den passendsten Guardian auswählen.","Im nächsten Schritt Zugangsdaten und Ziel eintragen."],"tips":["Für normale Webseiten reicht meist HTTP/HTTPS.","Für fremde Geräte ohne Spezialintegration eignen sich Ping, TCP oder HTTP."]},
    "guardian_create": {"title":"Guardian einrichten","intro":"Dieses Formular legt eine neue Überwachung an. Die Hilfe passt sich an das aktive Feld und an Auswahlen an.","steps":["Einen verständlichen Namen vergeben.","Ziel und Zugangsdaten eintragen.","Intervall und Fehlergrenzen zunächst auf den Standardwerten lassen.","Speichern und anschließend einmal manuell prüfen."],"tips":["Secrets werden verschlüsselt beziehungsweise nicht im Export ausgegeben.","Abhängigkeiten verhindern unnötige Folgealarme."]},
    "guardian_edit": {"title":"Guardian bearbeiten","intro":"Hier änderst du eine bestehende Prüfung. Leere Secret-Felder behalten normalerweise den gespeicherten Wert.","steps":["Nur die nötigen Felder ändern.","Speichern.","Danach eine manuelle Prüfung starten."],"tips":["Eine Änderung des Guardian-Typs ist riskanter als das Anlegen eines neuen Guardians."]},
    "guardian_detail": {"title":"Guardian-Details","intro":"Diese Seite zeigt Konfiguration, aktuellen Zustand, Verlauf und Aktionen eines Guardians.","steps":["Aktuelle Meldung und Zeitstempel prüfen.","Bei Bedarf „Jetzt prüfen“ ausführen.","Erst danach Konfiguration oder Abhängigkeiten ändern."],"tips":["Ein Folgefehler kann durch einen übergeordneten Guardian unterdrückt werden."]},
    "incidents_page": {"title":"Incidents","intro":"Incidents bündeln Störungen, damit nicht jede einzelne Fehlermeldung separat bearbeitet werden muss.","steps":["Kritische offene Incidents zuerst öffnen.","Ursache und betroffene Systeme prüfen.","Quittieren, Notiz ergänzen und nach Behebung erneut prüfen."],"tips":["„Quittiert“ bedeutet gesehen, nicht behoben.","Behobene Incidents werden nach erfolgreicher Prüfung geschlossen."]},
    "incident_detail": {"title":"Incident bearbeiten","intro":"Hier dokumentierst du eine Störung und siehst Ursache, Folgefehler und Timeline.","steps":["Priorität kontrollieren.","Ursache und betroffene Guardians prüfen.","Notiz oder Verantwortlichen festlegen.","Nach der Behebung die automatische Wiederherstellung prüfen."],"tips":["Incidents werden automatisch beendet, sobald der Guardian wieder einen gesunden Zustand meldet."]},
    "notification_channels": {"title":"Beacons","intro":"Beacons versenden Meldungen, zum Beispiel per E-Mail, MQTT oder Webhook.","steps":["Einen Kanal anlegen.","Testnachricht senden.","Erst danach einer Rule zuordnen."],"tips":["Retries helfen bei kurzen Netzwerkfehlern.","Ruhezeiten gehören in die Rule, nicht in den Kanal."]},
    "notification_channel_create": {"title":"Beacon einrichten","intro":"Hier legst du fest, wohin LANaxy Nachrichten sendet.","steps":["Typ auswählen.","Empfänger beziehungsweise Ziel eintragen.","Speichern und Testnachricht senden."],"tips":["Webhook eignet sich für viele Dienste ohne eigene Integration.","Zugangsdaten nicht in Namen oder Beschreibung schreiben."]},
    "notification_channel_edit": {"title":"Beacon bearbeiten","intro":"Ändere Ziel, Zugangsdaten oder Wiederholungsversuche eines Benachrichtigungskanals.","steps":["Einstellungen anpassen.","Speichern.","Testnachricht senden."],"tips":["Drei Versuche mit fünf Sekunden Abstand sind für die meisten Systeme ausreichend."]},
    "notification_rules": {"title":"Rules","intro":"Rules entscheiden, wann ein Beacon benachrichtigt wird.","steps":["Auslöser auswählen.","Schweregrad und betroffene Guardians festlegen.","Beacon zuordnen.","Rule testen."],"tips":["Zu breite Rules erzeugen schnell zu viele Nachrichten.","Eine Recovery-Meldung ist meist sinnvoll."]},
    "notification_rule_create": {"title":"Rule einrichten","intro":"Diese Regel verbindet einen Zustand mit einer oder mehreren Benachrichtigungen.","steps":["Auslöser und Schweregrad wählen.","Guardians oder Gruppen einschränken.","Beacon auswählen.","Vorschau beziehungsweise Test verwenden."],"tips":["Beginne mit einer einfachen Critical-Rule für alle Guardians."]},
    "notification_rule_edit": {"title":"Rule bearbeiten","intro":"Hier änderst du Auslöser, Filter und Empfänger einer bestehenden Regel.","steps":["Änderung durchführen.","Speichern.","Regel testen."],"tips":["Nach Änderungen an Filtern immer prüfen, ob noch die gewünschten Guardians getroffen werden."]},
    "miniguards_page": {"title":"MiniGuards","intro":"MiniGuards führen Prüfungen direkt auf entfernten Hosts aus und liefern Hardwareinventar.","steps":["Online-Status und Version prüfen.","Inventar abrufen.","Erst bei Problemen Diagnose oder Logs verwenden."],"tips":["LANaxy- und MiniGuard-Version müssen kompatibel sein.","Gefährliche Aktionen sind standardmäßig gesperrt."]},
    "proxmox_assistant": {"title":"Proxmox-Assistent","intro":"Der Assistent erkennt typische Proxmox-Komponenten und erstellt passende Guardians.","steps":["Proxmox-Zugang auswählen.","Scan starten.","Vorschau sorgfältig prüfen.","Nur gewünschte Einträge anwenden."],"tips":["Bestehende Guardians werden aktualisiert statt dupliziert.","API-Token mit möglichst wenigen Rechten verwenden."]},
    "pbs_assistant": {"title":"PBS-Assistent","intro":"Der Assistent erkennt PBS-Datastores, Backup-Gruppen und übliche Jobs.","steps":["PBS-Zugang auswählen.","Scan starten.","Vorschau prüfen.","Guardians anlegen oder aktualisieren."],"tips":["Backup-Alter ist für den Alltag meist wichtiger als jeder einzelne Task.","Nicht unterstützte Spezialjobs können zunächst übersprungen werden."]},
    "system_page": {"title":"System","intro":"Hier verwaltest du LANaxy selbst: Dienste, Sicherheit, Backups, MQTT und Diagnose.","steps":["Bereitschaftsanzeige prüfen.","Bei Problemen zuerst Diagnose und Dienststatus ansehen.","Vor größeren Änderungen ein Backup erstellen."],"tips":["Ein gelber Backup-Hinweis blockiert den Betrieb nicht.","Passwortänderungen melden aktive Sitzungen ab."]},
    "config_history": {"title":"Konfigurationshistorie","intro":"Jede relevante Konfigurationsänderung wird als Revision gespeichert.","steps":["Revision auswählen.","Diff prüfen.","Nur bei Bedarf wiederherstellen."],"tips":["Ein Restore ersetzt die aktuelle Konfiguration und startet LANaxy neu."]},
    "guardian_import": {"title":"Importvorschau","intro":"Die Vorschau zeigt genau, welche Guardians übernommen, umbenannt oder übersprungen werden.","steps":["Status jeder Zeile prüfen.","ID-Anpassungen kontrollieren.","Import bestätigen."],"tips":["Secrets werden aus sicheren Exporten nicht übernommen und müssen neu eingetragen werden."]},
    "topology_page": {"title":"Topologie","intro":"Die Topologie zeigt Abhängigkeiten zwischen Guardians und hilft bei der Ursachenanalyse.","steps":["Übergeordnete rote Knoten zuerst prüfen.","Verbindungen zu Folgefehlern nachvollziehen."],"tips":["Zu viele Abhängigkeiten machen die Auswertung unnötig kompliziert."]},
    "protocol_page": {"title":"Protokoll","intro":"Das Protokoll zeigt technische Ereignisse und Prüfresultate.","steps":["Nach Schweregrad oder Guardian filtern.","Zeitpunkt und Detailmeldung vergleichen."],"tips":["Für Supportfälle zusätzlich ein Diagnosepaket erstellen."]},
}

DEFAULT_HELP = {
    "title": "Hilfe zu diesem Bereich",
    "intro": "Diese Seite gehört zur Verwaltung von LANaxy. Die wichtigsten Schritte und Hinweise erscheinen hier passend zur aktuellen Auswahl.",
    "steps": ["Felder von oben nach unten ausfüllen.", "Änderungen speichern.", "Das Ergebnis anschließend prüfen."],
    "tips": ["Unsichere Werte zunächst auf den vorgeschlagenen Standardwerten lassen."],
}

SELECTION_HELP = {
    "action": {
        "delete": "Löscht die ausgewählten Einträge. Diese Aktion lässt sich nicht immer rückgängig machen.",
        "disable": "Deaktiviert Prüfungen, ohne ihre Konfiguration zu löschen.",
        "enable": "Aktiviert die ausgewählten Prüfungen wieder.",
        "check": "Startet sofort eine Prüfung der ausgewählten Guardians.",
        "dependencies": "Setzt gemeinsame Abhängigkeiten. Folgealarme werden unterdrückt, wenn eine Abhängigkeit ausfällt.",
        "intervals": "Ändert Intervall, Timeout, Retries oder Ausführungsquelle gemeinsam.",
    },
    "type": {
        "email": "Versendet Nachrichten über einen SMTP-Server. Vor Verwendung unbedingt eine Testnachricht senden.",
        "mqtt": "Veröffentlicht Meldungen auf einem MQTT-Topic. Retain nur aktivieren, wenn der letzte Zustand dauerhaft sichtbar bleiben soll.",
        "webhook": "Sendet einen HTTP-Aufruf an ein fremdes System. URL und optionale Header sorgfältig prüfen.",
        "discord": "Sendet Meldungen über einen Discord-Webhook.",
        "telegram": "Sendet Meldungen über einen Telegram-Bot und eine Chat-ID.",
    },
    "execution_source": {
        "local": "Die Prüfung läuft direkt auf dem LANaxy-Server.",
        "miniguard": "Die Prüfung läuft auf dem ausgewählten MiniGuard und eignet sich für lokale Hardware- oder Dateizugriffe.",
    },
    "severity": {
        "warning": "Warning meldet eine Einschränkung, bei der der Dienst oft noch nutzbar ist.",
        "critical": "Critical steht für einen echten Ausfall oder eine unmittelbar notwendige Reaktion.",
    },
}

def help_for_endpoint(endpoint: str | None):
    endpoint = endpoint or ""
    if endpoint in PAGE_HELP:
        return PAGE_HELP[endpoint]
    aliases = {
        "index": "dashboard",
        "guardians_page": "guardian_management",
        "guardian_new": "guardian_create",
        "guardian_update": "guardian_edit",
        "beacons_page": "notification_channels",
        "rules_page": "notification_rules",
        "system": "system_page",
        "config_history_page": "config_history",
        "guardian_import_confirm": "guardian_import",
    }
    return PAGE_HELP.get(aliases.get(endpoint, ""), DEFAULT_HELP)
