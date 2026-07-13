#!/usr/bin/env python3
"""
Persistent controller daemon for BlastEm's 68k debugger console.

Replaces the tmux send-keys / capture-pane / blind-sleep workflow with a
synchronous, prompt-aware Unix-socket RPC: every command blocks until the
debugger has genuinely returned to its '>' prompt before responding, which
eliminates the "batched c races ahead of the debugger" class of bug entirely
(no more guessing sleep durations, no more silently-dropped breakpoint hits).

One daemon process owns one blastem child via a pty. Multiple short-lived
client connections (one per command) talk to it over a Unix domain socket,
so a dropped SSH session never kills the emulator.

Usage (run ON the VM):
    python3 nhl95_daemon.py start [--state STATEFILE]
    python3 nhl95_daemon.py stop
    python3 nhl95_daemon.py status
Client:
    python3 nhl95ctl.py <command...>
"""
import sys, os, socket, subprocess, pty, select, time, signal, fcntl, struct

HOME = os.path.expanduser("~")
SOCK_PATH = os.path.join(HOME, ".nhl95ctl.sock")
PID_PATH = os.path.join(HOME, ".nhl95ctl.pid")
LOG_PATH = os.path.join(HOME, ".nhl95ctl.log")
ROM = os.path.join(HOME, "NHL 95 (USA, Europe).gen")
BLASTEM_DIR = os.path.join(HOME, "blastem-src")
BLASTEM_BIN = os.path.join(BLASTEM_DIR, "blastem")

# Active-low combined-read byte, confirmed live this session:
# bit7=Start bit6=A bit5=C bit4=B bit3=Right bit2=Left bit1=Down bit0=Up
BUTTON_BITS = {
    "start": 0x80, "a": 0x40, "c": 0x20, "b": 0x10,
    "right": 0x08, "left": 0x04, "down": 0x02, "up": 0x01,
}
INJECT_ADDR = "0x7A58A"
IDLE = 0xFF


def log(msg):
    with open(LOG_PATH, "a") as f:
        f.write(f"{time.time():.3f} {msg}\n")


class BlastemSession:
    def __init__(self, statefile):
        master, slave = pty.openpty()
        self.master = master
        env = os.environ.copy()
        env["SDL_AUDIODRIVER"] = "dummy"
        env["DISPLAY"] = ":1"
        cmd = [BLASTEM_BIN, "-s", statefile, "-d", ROM]
        self.proc = subprocess.Popen(
            cmd, cwd=BLASTEM_DIR, stdin=slave, stdout=slave, stderr=slave,
            env=env, preexec_fn=os.setsid, close_fds=True,
        )
        os.close(slave)
        fl = fcntl.fcntl(self.master, fcntl.F_GETFL)
        fcntl.fcntl(self.master, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        self.inject_bp = None
        # wait for the initial -d auto-break, then arm the input-injection breakpoint
        self._wait_prompt(timeout=10)
        resp = self._raw(f"b {INJECT_ADDR}")
        # "68K Breakpoint N set at ..."
        for tok in resp.split():
            if tok.isdigit():
                self.inject_bp = int(tok)
                break
        log(f"session up, inject_bp={self.inject_bp}")

    def _read_chunk(self, timeout):
        r, _, _ = select.select([self.master], [], [], timeout)
        if not r:
            return b""
        try:
            return os.read(self.master, 65536)
        except OSError:
            return b""

    def _wait_prompt(self, timeout=8.0, idle_grace=0.06):
        """Block until output goes quiet right after a '>' prompt char."""
        deadline = time.time() + timeout
        out = b""
        while time.time() < deadline:
            chunk = self._read_chunk(0.1)
            if chunk:
                out += chunk
                continue
            # no data pending right now -- are we sitting right after a prompt?
            stripped = out.rstrip(b" \r\n")
            if stripped.endswith(b">"):
                more = self._read_chunk(idle_grace)
                if not more:
                    return out.decode(errors="replace")
                out += more
                continue
            if out and time.time() > deadline - (timeout * 0.5):
                # got *something* but never a clean prompt -- avoid hanging forever
                continue
        return out.decode(errors="replace")

    def _raw(self, line, timeout=8.0):
        os.write(self.master, (line + "\n").encode())
        return self._wait_prompt(timeout)

    def alive(self):
        return self.proc.poll() is None

    # ---- public ops -------------------------------------------------
    def cmd_raw(self, args):
        return self._raw(" ".join(args))

    def _burst(self, lines, expect_hits, timeout):
        """Write many newline-terminated debugger commands in one shot (the
        debugger's stdin is processed strictly in order via fgets, so queuing
        is safe as long as no command's content depends on a prior command's
        *output* -- which none of these do), then read until we've seen
        `expect_hits` hits of the *injection* breakpoint specifically (not
        just any breakpoint -- if another breakpoint is armed and fires mid-
        burst, it silently consumes one queued `c` to resume past it, which
        would desync a generic "any Breakpoint text" count). This is why
        press/runframes are documented as navigation-phase-only: call them
        before arming any extra tracing breakpoints, then add those once
        you're at the target screen and switch to raw/waitbp for single,
        verified steps."""
        marker = f"Breakpoint {self.inject_bp} hit".encode()
        os.write(self.master, ("\n".join(lines) + "\n").encode())
        deadline = time.time() + timeout
        out = b""
        while time.time() < deadline:
            chunk = self._read_chunk(0.15)
            if chunk:
                out += chunk
                if out.count(marker) >= expect_hits and out.rstrip(b" \r\n").endswith(b">"):
                    more = self._read_chunk(0.05)
                    if not more:
                        break
                    out += more
                continue
            if out.rstrip(b" \r\n").endswith(b">"):
                break
        return out.decode(errors="replace")

    def cmd_press(self, args):
        button = args[0].lower()
        frames = int(args[1]) if len(args) > 1 else 12
        if button not in BUTTON_BITS:
            return f"ERR unknown button {button!r}, choices: {list(BUTTON_BITS)}"
        if self.inject_bp is None:
            return "ERR injection breakpoint not armed"
        value = IDLE & ~BUTTON_BITS[button] & 0xFF
        log(f"press {button} frames={frames} value={value:#x}")
        lines = []
        for i in range(frames):
            lines += [f"se d0 ${value:X}", "c"]
        lines += [f"se d0 ${IDLE:X}", "c"]
        timeout = max(5.0, frames * 0.25)
        out = self._burst(lines, expect_hits=frames + 1, timeout=timeout)
        return f"OK pressed {button} for {frames} frames\n" + out[-500:]

    def cmd_runframes(self, args):
        """Run N frames with idle input (uses the same injection breakpoint as a
        frame-pump so we get single, verified steps instead of a blind sleep)."""
        n = int(args[0]) if args else 60
        timeout = max(5.0, n * 0.2)
        out = self._burst(["c"] * n, expect_hits=n, timeout=timeout)
        return f"OK ran {n} frames\n" + out[-500:]

    def cmd_waitbp(self, args):
        """Continue one step at a time (never batched -- the stop condition is
        data-dependent) until breakpoint id `target` fires, or max_tries is hit.
        This is the direct automated replacement for the manual "send c, check
        tail for the rare breakpoint, repeat" loop that cost real time earlier
        -- each _raw() call already blocks for a genuine fresh prompt, so there
        is no batching-induced race here."""
        if not args:
            return "ERR usage: waitbp <breakpoint_id> [max_tries]"
        target = int(args[0])
        max_tries = int(args[1]) if len(args) > 1 else 500
        for i in range(max_tries):
            out = self._raw("c", timeout=3.0)
            if f"Breakpoint {target} hit" in out:
                return f"OK hit after {i + 1} continues\n" + out
        return f"ERR breakpoint {target} not hit after {max_tries} tries"

    def cmd_dumpregs(self, args):
        """All common registers in one call -- replaces the 5+ separate `raw
        p/x REG` round trips this project's manual sessions kept doing."""
        regs = args if args else ["d0", "d1", "d2", "a0", "a1", "a2", "a3", "a4", "pc"]
        out = {}
        for r in regs:
            resp = self._raw(f"p/x {r}", timeout=3.0)
            val = "?"
            for ln in resp.splitlines():
                if ln.strip().startswith(f"{r}:"):
                    val = ln.split(":", 1)[1].strip()
            out[r] = val
        return "OK " + " ".join(f"{r}={v}" for r, v in out.items())

    def cmd_screenshot(self, args):
        path = args[0] if args else "/tmp/nhl95ctl_shot.png"
        subprocess.run(["scrot", "-o", path], env={**os.environ, "DISPLAY": ":1"},
                        check=False)
        return f"OK {path}"

    def cmd_status(self, args):
        return f"OK alive={self.alive()} inject_bp={self.inject_bp}"


def serve(statefile):
    if os.path.exists(SOCK_PATH):
        os.remove(SOCK_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    srv.listen(4)
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    session = BlastemSession(statefile)

    def handle_sigterm(signum, frame):
        log("sigterm, killing blastem")
        try:
            os.killpg(os.getpgid(session.proc.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            os.remove(SOCK_PATH)
        except Exception:
            pass
        try:
            os.remove(PID_PATH)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    log("daemon serving")
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        # Every step below (recv, command dispatch, sendall) can raise -- most
        # commonly a BrokenPipeError when a client gives up and closes its end
        # before we finish (e.g. a short client-side timeout on a long-running
        # command). None of that should ever take the daemon down: a dead
        # client just means this one response is lost, not that blastem dies.
        try:
            data = b""
            conn.settimeout(2.0)
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if data.endswith(b"\n"):
                        break
            except socket.timeout:
                pass
            line = data.decode(errors="replace").strip()
            log(f"cmd: {line}")
            parts = line.split()
            if not parts:
                resp = "ERR empty command"
            else:
                name, args = parts[0], parts[1:]
                fn = getattr(session, f"cmd_{name}", None)
                if fn is None:
                    resp = "ERR unknown command " + name
                else:
                    try:
                        resp = fn(args)
                    except Exception as e:
                        resp = f"ERR exception {e!r}"
            conn.sendall(resp.encode() + b"\n<<<END>>>\n")
        except Exception as e:
            log(f"connection handling error (non-fatal): {e!r}")
        finally:
            try:
                conn.close()
            except Exception:
                pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    action = sys.argv[1]
    if action == "start":
        statefile = os.path.join(HOME, "controller_setup.state")
        if "--state" in sys.argv:
            statefile = sys.argv[sys.argv.index("--state") + 1]
        if os.path.exists(PID_PATH):
            print("Already running? (remove", PID_PATH, "if stale)")
            sys.exit(1)
        pid = os.fork()
        if pid == 0:
            os.setsid()
            devnull = os.open(os.devnull, os.O_RDWR)
            os.dup2(devnull, 0)
            log_fd = os.open(LOG_PATH, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
            os.dup2(log_fd, 1)
            os.dup2(log_fd, 2)
            serve(statefile)
            os._exit(0)
        else:
            print(f"daemon starting, pid={pid}")
    elif action == "stop":
        if os.path.exists(PID_PATH):
            with open(PID_PATH) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"stopped {pid}")
            except ProcessLookupError:
                print("not running (stale pidfile removed)")
            for p in (PID_PATH, SOCK_PATH):
                if os.path.exists(p):
                    os.remove(p)
        else:
            print("not running")
    elif action == "status":
        if not os.path.exists(PID_PATH):
            print("stopped")
        else:
            with open(PID_PATH) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                print(f"running pid={pid}")
            except ProcessLookupError:
                print("stopped (stale pidfile)")
                os.remove(PID_PATH)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
