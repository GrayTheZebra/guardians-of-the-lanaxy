from copy import deepcopy


EXACT_HELP = {
    "name": (
        "Ein frei wählbarer Anzeigename. Er wird später in Übersichten, "
        "Meldungen und Auswahlfeldern angezeigt."
    ),
    "id": (
        "Die eindeutige interne Kennung. Leer lassen, damit LANaxy sie "
        "automatisch aus dem Namen erzeugt."
    ),
    "interval": (
        "Zeit zwischen zwei automatischen Prüfungen. Kleine Werte erkennen "
        "Ausfälle schneller, erzeugen aber mehr Netzwerkverkehr."
    ),
    "timeout": (
        "So lange wartet LANaxy auf eine Antwort, bevor der Versuch als "
        "fehlgeschlagen gilt."
    ),
    "retries": (
        "Anzahl aufeinanderfolgender Fehlversuche, bevor der Zustand auf "
        "Critical wechselt. Kurze Störungen lösen dadurch nicht sofort Alarm aus."
    ),
    "host": (
        "Hostname oder IP-Adresse des Zielsystems, so wie sie vom LANaxy-Host "
        "erreichbar ist."
    ),
    "port": (
        "TCP-Port des Dienstes. Verwende den Port, auf dem die Anwendung "
        "tatsächlich lauscht."
    ),
    "user": (
        "Benutzername für die Anmeldung. Leer lassen, wenn der Dienst keine "
        "Authentifizierung benötigt."
    ),
    "username": (
        "Benutzername für die Anmeldung. Leer lassen, wenn der Dienst keine "
        "Authentifizierung benötigt."
    ),
    "password": (
        "Passwort für die Verbindung. Der Wert wird in der LANaxy-Konfiguration "
        "gespeichert und in der Oberfläche nicht im Klartext angezeigt."
    ),
    "token": (
        "Geheimer Zugriffstoken des externen Dienstes. Er wird von LANaxy für "
        "die Authentifizierung verwendet."
    ),
    "bot_token": (
        "Token des Telegram-Bots von BotFather. Es identifiziert und "
        "authentifiziert den Bot gegenüber Telegram."
    ),
    "chat_id": (
        "Zielchat für Telegram-Nachrichten. Im Beacon-Editor kann LANaxy nach "
        "Chats suchen, nachdem der Bot dort eine Nachricht erhalten hat."
    ),
    "url": (
        "Vollständige Adresse inklusive http:// oder https://, die LANaxy "
        "aufrufen oder überwachen soll."
    ),
    "method": (
        "HTTP-Methode für den Aufruf. GET liest Daten, POST übermittelt Daten."
    ),
    "base_topic": (
        "MQTT-Basistopic der Anwendung. Bei Zigbee2MQTT ist dies normalerweise "
        "zigbee2mqtt."
    ),
    "keepalive": (
        "Zeitintervall, in dem die MQTT-Verbindung aktiv gehalten wird. Der "
        "Standardwert funktioniert für die meisten Broker."
    ),
    "enabled": (
        "Legt fest, ob die Komponente nach Abschluss des Launchpads sofort aktiv ist."
    ),
    "group": (
        "Optionale organisatorische Gruppe. Sie erleichtert Filterung und "
        "Darstellung, verändert aber nicht die eigentliche Prüfung."
    ),
}

CONTAINS_HELP = [
    (
        ("frontend", "port"),
        "Port der Weboberfläche bzw. des Frontend-Dienstes.",
    ),
    (
        ("mqtt", "host"),
        "Hostname oder IP-Adresse des MQTT-Brokers, den diese Komponente verwendet.",
    ),
    (
        ("mqtt", "port"),
        "TCP-Port des MQTT-Brokers. Ohne TLS ist 1883 üblich.",
    ),
    (
        ("mqtt", "user"),
        "MQTT-Benutzername. Nur erforderlich, wenn der Broker eine Anmeldung verlangt.",
    ),
    (
        ("mqtt", "password"),
        "Passwort des MQTT-Benutzers. Es wird als geheimer Wert behandelt.",
    ),
    (
        ("coordinator", "type"),
        "Wähle USB für lokal angeschlossene Sticks oder TCP/PoE für einen "
        "über das Netzwerk erreichbaren Coordinator.",
    ),
    (
        ("coordinator", "host"),
        "IP-Adresse oder Hostname des Netzwerk-Coordinators.",
    ),
    (
        ("coordinator", "port"),
        "TCP-Port des Netzwerk-Coordinators beziehungsweise ser2net-Dienstes.",
    ),
    (
        ("topic",),
        "MQTT-Topic, auf dem die erwarteten Daten veröffentlicht werden.",
    ),
    (
        ("path",),
        "Pfad auf dem Zielsystem oder innerhalb einer URL.",
    ),
    (
        ("expected",),
        "Wert oder Inhalt, den LANaxy als erfolgreiches Ergebnis erwartet.",
    ),
    (
        ("threshold",),
        "Grenzwert, ab dem LANaxy eine Warnung oder einen Fehler meldet.",
    ),
    (
        ("critical",),
        "Grenzwert für einen kritischen Zustand.",
    ),
    (
        ("warning",),
        "Grenzwert für eine Warnung.",
    ),
]


def field_help(key, field):
    existing = str(field.get("help", "") or "").strip()
    if existing:
        return existing

    normalized = key.lower().replace("-", "_")
    leaf = normalized.split(".")[-1]

    if normalized in EXACT_HELP:
        return EXACT_HELP[normalized]
    if leaf in EXACT_HELP:
        return EXACT_HELP[leaf]

    for fragments, description in CONTAINS_HELP:
        if all(fragment in normalized for fragment in fragments):
            return description

    label = str(field.get("label", key))
    field_type = str(field.get("type", "text"))

    if field_type == "checkbox":
        return f"Aktiviert oder deaktiviert die Option „{label}“."
    if field_type == "select":
        return (
            f"Wähle die für deine Umgebung passende Einstellung für „{label}“."
        )
    if field_type == "number":
        return (
            f"Numerischer Wert für „{label}“. Der voreingestellte Wert ist "
            "für typische Installationen geeignet."
        )
    if field.get("secret"):
        return (
            f"Geheimer Wert für „{label}“. Er wird in der Oberfläche später "
            "nicht im Klartext angezeigt."
        )

    return (
        f"Wert für „{label}“. Trage die Angabe so ein, wie sie auf dem "
        "überwachten System oder beim externen Dienst konfiguriert ist."
    )


def enrich_schema(schema):
    result = deepcopy(schema)
    for key, field in result.items():
        field["launchpad_help"] = field_help(key, field)
    return result
