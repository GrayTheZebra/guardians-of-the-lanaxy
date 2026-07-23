# Guardians of the LANaxy 1.33.2

- Der Update-Vorabtest kompiliert Python-Dateien in ein temporäres Verzeichnis.
- Vorhandene root-eigene `__pycache__`-Verzeichnisse werden nicht mehr beschrieben.
- Modulimporte laufen mit `PYTHONDONTWRITEBYTECODE=1` und `python3 -B`.
- Schreibrechte im Projektverzeichnis werden nicht mehr fälschlich als Syntaxfehler gemeldet.
