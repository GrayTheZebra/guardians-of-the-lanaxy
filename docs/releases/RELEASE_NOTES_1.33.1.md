# Guardians of the LANaxy 1.33.1

- Der Update-Vorabtest ist vollständig in `update.sh` enthalten.
- Der Updater hängt nicht mehr selbst von `release_validation.py` ab.
- Fehlende Update-Dateien werden gesammelt und einzeln aufgelistet.
- Neue Pflichtdateien werden geprüft, bevor Python-Imports oder Dienststopps erfolgen.
- Python-Syntax und wichtige LANaxy-Imports werden weiterhin vor dem Update geprüft.
