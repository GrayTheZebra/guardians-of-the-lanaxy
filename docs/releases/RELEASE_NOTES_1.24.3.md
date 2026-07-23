# Guardians of the LANaxy 1.24.3

- Behebt einen Internal Server Error im Proxmox-API-Guardian-Formular.
- Jinja griff bei `section.keys` auf die Dict-Methode statt auf die Feldliste zu.
- Modusabhängige Abschnittsdaten verwenden jetzt expliziten Dictionary-Zugriff.
