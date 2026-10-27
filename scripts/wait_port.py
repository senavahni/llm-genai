"""Tunggu sampai host:port menerima koneksi TCP.  Pemakaian: wait_port.py HOST PORT [TIMEOUT_S]"""

import socket
import sys
import time


def wait_port(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    host, port = sys.argv[1], int(sys.argv[2])
    timeout_s = float(sys.argv[3]) if len(sys.argv) > 3 else 30
    if wait_port(host, port, timeout_s):
        print(f"{host}:{port} siap")
        return 0
    print(f"{host}:{port} tidak siap setelah {timeout_s:g} detik", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
