import json
import os
import socket
import threading
from pathlib import Path

from guardian_manager import load_guardian


SOCKET_PATH = Path("/run/lanaxy/guardian-test.sock")
MAX_REQUEST_SIZE = 1024 * 1024


def _read_json(connection):
    chunks = []
    total = 0
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_REQUEST_SIZE:
            raise ValueError("Guardian-Testanfrage ist zu groß.")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    return json.loads(raw.decode("utf-8"))


def _write_json(connection, payload):
    connection.sendall(
        json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    )


class GuardianTestServer:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.server = None

    def start(self):
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOCKET_PATH.unlink(missing_ok=True)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o660)
        server.listen(8)
        server.settimeout(1.0)

        self.server = server
        self.thread = threading.Thread(
            target=self._serve,
            name="guardian-test-ipc",
            daemon=True,
        )
        self.thread.start()

    def _serve(self):
        while not self.stop_event.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with connection:
                try:
                    request = _read_json(connection)
                    check = request.get("check")
                    if not isinstance(check, dict):
                        raise ValueError("Guardian-Konfiguration fehlt.")
                    result = load_guardian(check).run()
                    _write_json(
                        connection,
                        {
                            "ok": result.level == 0,
                            "result": result.to_dict(),
                        },
                    )
                except Exception as error:
                    _write_json(
                        connection,
                        {
                            "ok": False,
                            "error": str(error),
                        },
                    )

    def stop(self):
        self.stop_event.set()
        if self.server is not None:
            try:
                self.server.close()
            except OSError:
                pass
        if self.thread is not None:
            self.thread.join(timeout=2)
        SOCKET_PATH.unlink(missing_ok=True)


def test_guardian_via_service(check, timeout=30):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(SOCKET_PATH))
        _write_json(client, {"check": check})
        response = _read_json(client)
    finally:
        client.close()

    if not isinstance(response, dict):
        raise RuntimeError("Ungültige Antwort des Guardian-Testdienstes.")
    return response
