#!/usr/bin/env python3
"""
Unattended-game instrumentation: runs CPU-vs-CPU games via nhl95ctl.py and
polls known WRAM addresses at a fixed interval, logging every value change
to a CSV. Built to answer "run many games, catch the interesting event"
questions cheaply -- faceoffs (#3), injuries (#9), hot/cold-modifier
confirmation (#1), AI/difficulty behavior (#6) -- without hand-driving the
debugger through screenshots for each one.

This is deliberately *not* a machine-learned game-playing agent. The
built-in CPU AI already plays full, realistic games unattended (see
CLAUDE.md's CPU-vs-CPU recipe) -- what was missing was scale and logging,
not skill. See FINDINGS.md/chat for the fuller reasoning.

Requires nhl95_daemon.py already running (see CLAUDE.md) with a game in
progress and both controllers parked under CPU.

Usage (run ON the VM, or via SSH from the repo):
    python3 nhl95_monitor.py watch --seconds 300 --interval 1.0 --out log.csv
    python3 nhl95_monitor.py watch --frames 3000 --interval-frames 15 --out log.csv

WATCH_ADDRESSES below is the known-address table -- extend it as more
addresses get confirmed (see FINDINGS.md for what's independently verified
vs. still a guess). Every entry is read as an unsigned byte via `p/x`
unless width=2 is given (word read).

Score/clock/period addresses are not yet in this table -- worth doing
next (see GitHub issue tracker), but a blind live memory search isn't the
way: BlastEm's `s FILENAME` full-RAM-dump command (which would make a
before/after diff trivial) turned out to only exist inside the Z80
sub-debugger, not the main 68k prompt -- sending it there gets silently
misparsed as the unrelated `s` (step-into) command instead, one
instruction at a time, which is both slow and not what you want. A static
approach (find the score-display code via xref/string search the way
other UI elements were cracked in FINDINGS.md sec 6) is more likely to
pay off than more live polling.
"""
import argparse
import csv
import re
import socket
import sys
import time
import os

SOCK_PATH = os.path.join(os.path.expanduser("~"), ".nhl95ctl.sock")

# Confirmed-address table. See FINDINGS.md for the write-up behind each one.
# Extend this as more get pinned down (score/clock are TODO as of this
# writing -- see the in-progress memory-diff search in the same session
# that created this file).
WATCH_ADDRESSES = {
    "hot_home": (0xFFFFBB62, 2),   # candidate table, see FINDINGS.md sec 5
    "cold_home": (0xFFFFBB64, 2),
    "hot_away": (0xFFFFBB66, 2),
    "cold_away": (0xFFFFBB68, 2),
}


def _raw(line, timeout=90.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK_PATH)
    s.sendall((line + "\n").encode())
    buf = b""
    s.settimeout(timeout)
    while b"<<<END>>>" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return buf.split(b"<<<END>>>")[0].decode(errors="replace")


def read_addr(addr, width=1):
    suffix = "w" if width == 2 else "b"
    resp = _raw(f"raw p/x 0x{addr:X}.{suffix}")
    m = re.search(r":\s*([0-9a-fA-F]+)", resp)
    return int(m.group(1), 16) if m else None


def poll_once():
    return {name: read_addr(addr, width) for name, (addr, width) in WATCH_ADDRESSES.items()}


def watch(seconds, interval, out_path):
    """Poll all watched addresses every `interval` seconds, log any value
    that changed since the last poll. Advances game time itself via
    runframes so this doesn't depend on anything else driving the game --
    point it at an already-started CPU-vs-CPU game and leave it running."""
    frames_per_tick = max(1, int(interval * 60))  # NTSC-ish; good enough for polling cadence
    last = {}
    t0 = time.time()
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t_seconds", "field", "old", "new"])
        f.flush()
        while time.time() - t0 < seconds:
            _raw(f"runframes {frames_per_tick}", timeout=max(10.0, frames_per_tick * 0.3))
            now = poll_once()
            t = round(time.time() - t0, 1)
            for k, v in now.items():
                if last.get(k) != v:
                    writer.writerow([t, k, last.get(k), v])
                    f.flush()
                    print(f"[{t:7.1f}s] {k}: {last.get(k)} -> {v}")
            last = now
    print(f"Done. Log written to {out_path}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--seconds", type=float, default=120.0)
    w.add_argument("--interval", type=float, default=1.0, help="seconds of game time per poll")
    w.add_argument("--out", default="nhl95_monitor_log.csv")
    args = p.parse_args()
    if args.cmd == "watch":
        watch(args.seconds, args.interval, args.out)


if __name__ == "__main__":
    main()
