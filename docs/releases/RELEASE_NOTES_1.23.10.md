# Guardians of the LANaxy 1.23.10

- Proxmox-Erkennung um VMs und LXC-Container erweitert.
- Neuer Button „VMs/LXCs erkennen“ im Gast-Modus.
- LANaxy ruft QEMU-VMs und LXC-Container des ausgewählten Nodes ab.
- Auswahl zeigt Gasttyp, ID, Name und Status.
- Bei Auswahl wird die VM-/LXC-ID gesetzt und der Gasttyp automatisch angepasst.
- Bei genau einem Gast erfolgt eine automatische Auswahl.
- Fehlt der Node bei einem Einzel-Node-System, wird er gleichzeitig automatisch erkannt.
- Der KI-Planer darf VM-/LXC-ID leer lassen, wenn sie nicht ausdrücklich genannt wurde.
