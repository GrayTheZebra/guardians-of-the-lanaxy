import time
from typing import Any

import requests


def get_json(url: str, timeout: int = 3) -> dict[str, Any]:
    started = time.monotonic()

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        return {
            "ok": True,
            "ms": int((time.monotonic() - started) * 1000),
            "data": data,
            "status_code": response.status_code,
        }
    except (requests.RequestException, ValueError) as error:
        return {
            "ok": False,
            "ms": int((time.monotonic() - started) * 1000),
            "error": str(error),
        }
