import re
import socket
import subprocess
import time
from typing import Any


PING_TIME_PATTERN = re.compile(r"time[=<]([\d.]+)\s*ms")


def ping(host: str, timeout: int = 2) -> dict[str, Any]:
    started = time.monotonic()

    try:
        process = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "ok": False,
            "ms": int((time.monotonic() - started) * 1000),
            "error": str(error),
        }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    match = PING_TIME_PATTERN.search(process.stdout)
    measured_ms = round(float(match.group(1)), 2) if match else elapsed_ms

    result: dict[str, Any] = {
        "ok": process.returncode == 0,
        "ms": measured_ms,
    }

    if process.returncode != 0:
        result["error"] = process.stderr.strip() or process.stdout.strip()

    return result


def tcp_check(host: str, port: int, timeout: int = 2) -> dict[str, Any]:
    started = time.monotonic()

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "ok": True,
                "ms": int((time.monotonic() - started) * 1000),
            }
    except OSError as error:
        return {
            "ok": False,
            "ms": int((time.monotonic() - started) * 1000),
            "error": str(error),
        }
