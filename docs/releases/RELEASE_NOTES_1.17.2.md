# Guardians of the LANaxy 1.17.2

- MiniGuard installation is now idempotent for the same registered agent.
- Existing registrations for a different agent are detected before registration and explained clearly.
- HTTP registration errors now show the actual LANaxy error instead of a Python traceback with only HTTP 400.
- Re-running the installer refreshes the binary and restarts the service.
