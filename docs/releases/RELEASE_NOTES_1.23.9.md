# Guardians of the LANaxy 1.23.9

- Automatische Proxmox-Node-Erkennung über `/api2/json/nodes`.
- Node-Feld ist nicht mehr zwingend erforderlich.
- Bei genau einem Node wird dieser automatisch verwendet.
- Bei mehreren Nodes nennt LANaxy alle gefundenen Nodes und verlangt eine Auswahl.
- Im Guardian-Formular gibt es den Button „Nodes erkennen“.
- Gespeicherte Token-Secrets werden beim Bearbeiten sicher für die Erkennung weiterverwendet.
- Der KI-Planer lässt den Node standardmäßig leer, damit LANaxy ihn zuverlässig selbst erkennt.
