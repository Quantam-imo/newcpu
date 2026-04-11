#!/usr/bin/env python3
"""
AstroQuant CDP Proxy — Windows side
====================================
Runs on Windows. Listens on the WSL2-facing network adapter (e.g. 192.168.x.x:9222)
and transparently forwards all TCP traffic to Chrome's DevTools Protocol endpoint
at 127.0.0.1:9222 (Windows loopback).

This bridges the WSL2 networking gap:
  WSL2 backend  →  192.168.x.x:9222  →  [this proxy]  →  127.0.0.1:9222  →  Chrome

Usage (auto-called by launch_chrome_windows.sh):
  pythonw.exe cdp_proxy_windows.py 192.168.16.1
  python.exe  cdp_proxy_windows.py 192.168.16.1
"""

import socket
import threading
import sys
import os
import time
import logging

LISTEN_PORT = 9222
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 9222
LOG_FILE = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "cdp_proxy.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        # StreamHandler only when running in console (python.exe not pythonw.exe)
    ],
)
log = logging.getLogger("cdp_proxy")


def _pipe(src: socket.socket, dst: socket.socket, label: str) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def _handle_client(client: socket.socket, addr) -> None:
    log.info("Connection from %s", addr)
    server = None
    for attempt in range(10):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.settimeout(3)
            server.connect((TARGET_HOST, TARGET_PORT))
            server.settimeout(None)
            break
        except OSError as exc:
            log.warning("Chrome CDP not ready (attempt %d): %s", attempt + 1, exc)
            try:
                server.close()
            except OSError:
                pass
            server = None
            time.sleep(1)
    else:
        log.error("Chrome CDP at %s:%d unreachable — dropping connection from %s",
                  TARGET_HOST, TARGET_PORT, addr)
        try:
            client.close()
        except OSError:
            pass
        return

    t1 = threading.Thread(
        target=_pipe, args=(client, server, "client→chrome"), daemon=True
    )
    t2 = threading.Thread(
        target=_pipe, args=(server, client, "chrome→client"), daemon=True
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    log.info("Connection from %s closed", addr)


def main() -> None:
    listen_host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((listen_host, LISTEN_PORT))
    except OSError as exc:
        log.error("Cannot bind to %s:%d — %s", listen_host, LISTEN_PORT, exc)
        log.error("Another process may already be using port %d on this IP.", LISTEN_PORT)
        sys.exit(1)
    srv.listen(100)
    log.info(
        "AstroQuant CDP Proxy listening on %s:%d → %s:%d",
        listen_host, LISTEN_PORT, TARGET_HOST, TARGET_PORT,
    )

    while True:
        try:
            client, addr = srv.accept()
            threading.Thread(
                target=_handle_client, args=(client, addr), daemon=True
            ).start()
        except OSError as exc:
            log.error("Accept error: %s", exc)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
