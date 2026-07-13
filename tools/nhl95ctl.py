#!/usr/bin/env python3
"""Thin client for nhl95_daemon.py -- see that file's docstring."""
import sys, socket, os

SOCK_PATH = os.path.join(os.path.expanduser("~"), ".nhl95ctl.sock")


def main():
    if len(sys.argv) < 2:
        print("usage: nhl95ctl.py <command> [args...]")
        sys.exit(1)
    line = " ".join(sys.argv[1:])
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCK_PATH)
    except OSError as e:
        print(f"ERR cannot connect to daemon ({e}) -- is it running? (nhl95_daemon.py start)")
        sys.exit(1)
    s.sendall((line + "\n").encode())
    buf = b""
    s.settimeout(90.0)
    try:
        while b"<<<END>>>" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        print("ERR timed out waiting for daemon response")
        sys.exit(1)
    out = buf.split(b"<<<END>>>")[0].decode(errors="replace")
    print(out, end="")


if __name__ == "__main__":
    main()
