# LANaxy 1.18.2 – MiniGuard Queue Fix

- Reworked MiniGuard inter-process locking with a fresh lock handle per request.
- Runtime lock moved to `/run/lanaxy/miniguards.lock`.
- Atomic registry writes now use unique temporary files and fsync.
- MiniGuard check APIs always return JSON errors and log the underlying exception.
- Prevents HTTP 500 responses caused by queue lock/write races.
