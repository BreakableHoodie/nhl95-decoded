#!/usr/bin/env python3
"""Thin client for nhl95_daemon.py -- see that file's docstring.

To target a non-default daemon instance (see nhl95_daemon.py's
multi-instance note), either set NHL95CTL_ID=NAME in the environment or
pass --id NAME as the first two arguments -- both select the same
suffixed socket path nhl95_daemon.py's own `start --id NAME` used."""
import sys, socket, os

HOME = os.path.expanduser("~")


def _sock_path(instance_id):
    suffix = f"-{instance_id}" if instance_id else ""
    return os.path.join(HOME, f".nhl95ctl{suffix}.sock")


def _client_timeout(cmd, args):
    """Mirror the daemon's own per-command server-side timeout (see
    cmd_press/cmd_runframes/cmd_waitbp in nhl95_daemon.py) so the client
    doesn't give up on a large batch the daemon is still happily running --
    a flat 90s here caused false "ERR timed out" reports on runframes/press
    calls above ~1500-2000 frames even though the daemon completed them
    fine in the background."""
    try:
        if cmd == "press":
            frames = int(args[1]) if len(args) > 1 else 12
            server_timeout = max(5.0, frames * 0.25)
        elif cmd == "runframes":
            n = int(args[0]) if args else 60
            server_timeout = max(5.0, n * 0.2)
        elif cmd == "waitbp":
            max_tries = int(args[1]) if len(args) > 1 else 500
            server_timeout = max_tries * 3.0
        else:
            server_timeout = 90.0
    except ValueError:
        server_timeout = 90.0
    return max(90.0, server_timeout * 1.5 + 10)


def main():
    argv = sys.argv[1:]
    instance_id = os.environ.get("NHL95CTL_ID", "")
    if argv[:1] == ["--id"]:
        if len(argv) < 2:
            print("usage: nhl95ctl.py --id NAME <command> [args...]")
            sys.exit(1)
        instance_id, argv = argv[1], argv[2:]
    if not argv:
        print("usage: nhl95ctl.py [--id NAME] <command> [args...]")
        sys.exit(1)
    line = " ".join(argv)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(_sock_path(instance_id))
    except OSError as e:
        print(f"ERR cannot connect to daemon ({e}) -- is it running? (nhl95_daemon.py start)")
        sys.exit(1)
    s.sendall((line + "\n").encode())
    buf = b""
    s.settimeout(_client_timeout(argv[0].lower(), argv[1:]))
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
