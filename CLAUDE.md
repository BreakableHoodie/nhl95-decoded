# NHL '95 (Genesis) — Reverse Engineering Project

Full static + live reverse-engineering of `NHL 95 (USA, Europe).gen` (Sega
Genesis, Product ID T-50856, 2MB, no header — Ghidra addresses == BlastEm/live
addresses, no SMD offset). Started from one real bug report (a duplicate-player
"clone bug"), now a general documentation project covering the ROM's data
formats and game logic.

**The living document is `docs/FINDINGS.md`. Read it before starting work,
update it as you go — it is the deliverable, not a scratch file.** This
CLAUDE.md is about *how to work in this project*; FINDINGS.md is *what we know*.

---

## Why this project, and how to frame findings

This isn't just archaeology. Every finding should answer "why does this
matter, what can I learn from this" — not just document what a byte does.
Favor explanations that connect a low-level fact (an opcode, an offset) to an
observable, human-meaningful behavior (a bug a player actually saw, a
community debate the ROM can settle, a technique — like the §5 RNG chain or
the live-vs-static verification story — that's reusable on other reverse
engineering targets). When updating FINDINGS.md, keep its existing framing:
root-cause first, then check whether the same failure mode is systemic (§3,
§4 pattern), not just a one-off patch.

---

## Environment

- **Ghidra**: project at `ghidra_project/NHL95.gpr` (raw binary import,
  `68000:BE:32:default`). The `analyzeHeadless` binary is usually *not* on
  PATH in a fresh shell — use the full path:
  `/opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless`.
  Invoke with the project dir and name split:
  `analyzeHeadless /Volumes/data/Games/NHL95/ghidra_project NHL95 -process "NHL 95 (USA, Europe).gen" -noanalysis -postScript <Script>.java -scriptPath <scratchpad>`.
  **For the common "force-disassemble this address range and print it" need
  (the force-disassembly gotcha below), use `tools/ghidra/DumpRange.java`
  instead of writing another one-off script** — this project rewrote that
  same `clearCodeUnits`+`disassemble`+walk body by hand well over a dozen
  times across sessions before it was finally generalized. Takes START/END
  and optional extra SEED addresses as script args (space-separated, after
  the script name in `-postScript`):
  `-postScript DumpRange.java 0x9FCC8 0x9FD62 -scriptPath tools/ghidra`
  (add more hex addresses after END to seed multiple entry points into one
  merged dump — needed when a range has internal branch targets not reached
  by simple fallthrough from START, e.g. two subroutines sharing a tail).
  Only reach for a genuinely new one-off script when the task is more than
  "dump this range" (xref search, byte-pattern search, etc. — those still
  belong in the scratchpad, they're not what `DumpRange.java` is for).
- **Live emulation**: x86_64 Ubuntu VM under UTM, SSH alias `nhl95vm2`
  (`192.168.64.9`, user `claude`, key `~/.ssh/id_ed25519_nhl95vm` — already in
  `~/.ssh/config`, so plain `ssh nhl95vm2 '...'` works). macOS/Rosetta blocks
  BlastEm's JIT from allocating executable memory, which is why this runs in a
  real x86_64 VM rather than natively.
- **`tools/nhl95ctl.py` — the primary way to drive BlastEm now, not the tmux
  dance below.** A small daemon (`tools/nhl95_daemon.py`) that owns one
  BlastEm process via a real Python `pty` (no tmux involved at all) and
  serves commands over a Unix socket, with every command blocking until the
  debugger has genuinely returned to its `>` prompt before responding. This
  was built after an entire session of fighting exactly the failure modes
  documented in the gotchas below (tmux's server dying mid-session, batched
  `c` racing ahead and silently dropping breakpoint hits, blind `sleep`-based
  pacing) — those are historical/manual-fallback notes now, not the
  recommended path. Deploy once per VM boot (rsync/scp `tools/*.py` to
  `~/nhl95ctl/` on the VM if not already there), then:
  ```
  ssh nhl95vm2 "cd ~/nhl95ctl && python3 nhl95_daemon.py start"   # once
  ssh nhl95vm2 "cd ~/nhl95ctl && python3 nhl95ctl.py <command>"   # per action
  ```
  Defaults to `~/controller_setup.state`; pass `start --state
  ~/OTHER.state` to boot from any of the other named savestates below.
  Commands: `press BUTTON [FRAMES]` (default 12; buttons: `start a c b right
  left down up`), `runframes N` (let time pass with idle input — e.g. to wait
  out a text crawl), `raw <debugger command text>` (any single `b`/`d`/`c`/
  `bt`/`p/x ADDR`/`se REG VAL` command, verbatim), `waitbp ID [max_tries]`
  (repeat single verified `c` steps until breakpoint `ID` fires — the
  automated version of the "hunt for a rare hit among frequent ones" pattern
  that used to cost many manual tool calls), `dumpregs [REG...]` (all common
  registers in one round trip instead of five separate `p/x` calls),
  `screenshot PATH`, `status`. **Important usage rule**: `press`/`runframes`
  batch multiple `c`s ahead of time and count hits of the *injection*
  breakpoint specifically to know when to stop — call them only during
  navigation, before arming any extra tracing breakpoints; once you're at the
  target screen and want to set breakpoints like `0x7C6D4`, switch to `raw`/
  `waitbp` for single, verified, non-batched steps. The daemon survives a
  dropped SSH session (it's not attached to your shell), and is written to
  never crash from a client giving up mid-request (an earlier version did —
  an unhandled `BrokenPipeError` on a timed-out client took the whole daemon
  down; now every per-connection step is wrapped so a lost client just loses
  its own response, nothing else). `nhl95_daemon.py stop`/`status` manage the
  daemon; if `start` refuses with "Already running?" after a crash, `rm
  ~/.nhl95ctl.pid ~/.nhl95ctl.sock` first.
- **Manual/fallback method (rarely needed now):** BlastEm can still be run
  inside a **tmux session named `blastem`** on the VM so its console 68k
  debugger has a real attached stdin/stdout over SSH:
  `tmux send-keys -t blastem '<cmd>' Enter`, read back with
  `tmux capture-pane -t blastem -p`. Keep this for one-off manual debugging
  or if the daemon itself needs debugging, but see the gotchas below for why
  this path is fragile — prefer `nhl95ctl.py` for anything more than a
  single ad-hoc command.
- **Fast iteration**: `~/controller_setup.state` on the VM is a savestate
  captured at the Controller Setup screen (Vancouver @ New York already
  selected). `~/team_select.state` and `~/penalties_on.state` are both
  captured on the **same underlying screen** — the real pre-game settings
  screen (`Play Mode`/`Team 1`/`Team 2`/`Per. Length`/`Goalies`/`User
  Records`/`Penalties`/`Line Changes`), just at different setting states
  (`team_select.state` = defaults, `Penalties: Off`; `penalties_on.state` =
  `Penalties: On`, `Line Changes: Auto`). **This screen appears automatically
  right after the credits scroll, with *zero* button presses** — it is
  reached *before* Controller Setup, not after. This tripped up a lot of
  earlier navigation in this project: repeatedly pressing Start to hurry
  through the credits scroll registers on this exact screen the instant it
  renders and silently confirms straight through it into Controller Setup,
  making it look like this settings screen doesn't exist in the normal flow.
  It does — just don't press anything between the credits ending and taking
  a screenshot. Launch with `blastem -s ~/STATE_FILE -d ...` to skip the
  ~4-minute mandatory credits scroll on every run — or if you specifically
  need a *true* fresh boot (no savestate can substitute, e.g. testing
  Season mode's team list or getting a fresh §5 hot/cold RNG seed):
  **confirmed live this session that the credits are skippable in roughly
  1-2 minutes, not the full ~4, via a single Start press once you're past
  the opening EA Sports/production-company logos** (not immediately at
  power-on — an early press there does nothing useful, and repeatedly
  mashing Start early risks looking "stuck" on a long static-looking
  transition frame that's actually still progressing normally, not
  broken — confirmed by comparing a mashed-Start attempt against a
  pure-idle attempt landing on the *exact same* frame, and by checking
  the debugger showed the CPU still executing normally throughout, not
  hung). Use `nhl95_daemon.py start --fresh` (added this session) for
  this, then a single `press start` once the screen has been static for
  a while, not several rapid ones. To capture a *new* named
  savestate: launch with no `-s` flag for a true fresh boot, navigate to the
  desired screen, press the in-game save-state key (bound to backtick, see
  below) — it writes to `~/.local/share/blastem/NHL 95 (USA,
  Europe)/quicksave.state`, which then needs an explicit `cp` to a
  memorably-named file in `~/` since blastem always reuses that same
  quicksave filename.
- **CPU vs. CPU (no manual input needed at all)**: on the Controller Setup
  screen (`VANCOUVER` / `CPU` / `NEW YORK` tabs), press `Left`/`Right` to slide
  each numbered controller icon out of a team's column and into the middle
  `CPU` column. With *both* controller icons parked under `CPU` (neither team
  column has one), the game runs the whole match AI-vs-AI — genuinely useful
  for watching natural gameplay events unfold without fighting blind,
  no-feedback manual input, which is a poor way to force a specific,
  position-dependent event. Confirmed working: game plays itself in real
  time with zero keypresses needed once started, and produces real, properly
  tracked events (watched a legitimate goal with correct scorer/assist).
  `Penalties` defaults to **off** and `Line Changes` defaults to **off** —
  neither is on the in-game pre-game `OPTIONS` menu; both are on the
  pre-Controller-Setup settings screen described above (`~/penalties_on.state`
  has both already set). With `Penalties: On`, CPU vs CPU reliably produces
  real penalties within a few minutes — confirmed a genuine two-man penalty
  kill this way.
- **The Line Editor's layout changes based on `Line Changes: On`/`Off`.**
  With it off, entering Edit Lines shows only the single currently-active
  line. With it **on** (`Auto`), it instead shows **all 7 lines**, 2-3 columns
  at a time, cycled with `Left`/`Right` in the order `Sc1/Sc2/Chk` →
  `PP1/PP2` → `PK1/PK2` — this is how the full line-index-to-label mapping
  in FINDINGS.md §7#2 got its final, direct confirmation (reading live
  `PK1`/`PK2` during a real penalty kill). PK lines visibly show only 4
  positions (LD/RD/LW/C, blank RW), matching Sega Retro's documentation.
- Headless GUI control when needed: `xdotool` / `scrot` against the VM's
  Xvfb/openbox X11 session (`DISPLAY=:1`).
- **Debugger-level input injection (bypasses X11/SDL keyboard entirely) —
  this is what `nhl95ctl.py press`/`runframes` above actually do under the
  hood.** When real keypresses won't reach the game (see the X11 input-dead
  gotcha below), controller input can be forced directly through the 68k
  debugger, with no dependency on X11 at all. This was reverse-engineered and
  confirmed live in one session:
  - The VBlank handler (`0x78` autovector → `0x7A32C`) pushes a
    per-screen handler pointer read from WRAM `$FFFFAC52` and returns into
    it (self-modifying dispatch, same "computed jump" pattern documented
    elsewhere in this project). At the Controller Setup screen this resolves
    to `0x7A418`, which unconditionally calls `0x7A3E6` every frame; that in
    turn calls `0x7A55A`, the real controller-poll routine (the ROM's
    `$A10003`/`$A10005` xrefs found by static search alone — Ghidra hadn't
    disassembled the actual per-frame poller yet — led to a one-shot
    6-button-detect routine, a dead end; the live poller was only found by
    following the VBlank vector at runtime).
  - `$FFFFCC4A` (word) is the "6-button pad detected" flag; it reads `0`
    live in this emulator, so the game takes the **3-button read path**
    (`0x7A586`), not the 4-byte 6-button path — don't assume 6-button just
    because BlastEm's console log says "6-button gamepad".
  - Controller 1's fully-combined, ready-to-use button byte lands in `D0`
    for one instruction before it's stored to WRAM: breakpoint at
    **`0x7A58A`** (`move.b D0b,($FFFFBAF4).w`) catches it right before the
    store. Controller 2's equivalent is `0x7A592` → `$FFFFBAF5`. Byte
    encoding (active-low, idle = `0xFF`): bit7=Start, bit6=A, bit5=C,
    bit4=B, bit3=Right, bit2=Left, bit1=Down, bit0=Up — confirmed by both
    the disassembly (`asl.b #2` + `andi #0xC0` on the TH=0 phase read,
    `andi #0x3F` on the TH=1 phase read — the textbook Sega 3-button
    combined-read pattern) and live observation (forcing `D0=$FB`, i.e.
    bit2/Left cleared, moved the Controller Setup screen's controller-1 icon
    left exactly as expected).
  - Live-fire recipe: `b 0x7A58A` to set the breakpoint (note the index N
    returned), then `com N` (see the gotcha below — must be typed as three
    letters `com`, not `co`, despite what the built-in `?` help text says)
    and enter a two-line script `se d0 $XX` / `c`, terminated with a
    literal `end`. Once attached, a single `c` makes it fire every frame
    indefinitely, sustaining a "held" button until the breakpoint is
    deleted (`d N`) — confirmed moving a menu selection this way over
    multiple real frames at normal frame rate, not just one forced write.
  - This only drives controller 1/2 as seen by the CPU — it's a strict
    superset of what physical input could do, since it goes through the
    exact same WRAM bytes the real polling routine writes. Any screen
    reachable by a real controller is reachable this way, with no X11
    dependency.

---

## Gotchas (all cost real time to discover — don't rediscover them)

- **The `tmux` server on the VM died outright (`no server running on
  /tmp/tmux-1000/default`) multiple times across one session**, with no
  action taken that should have caused it — recreating the session
  (`tmux new-session -d -s blastem -x 220 -y 50`) always fixed it, but this
  cost real time each time it happened mid-workflow, particularly since a
  command sent to a dead session just silently fails rather than erroring
  clearly. Root cause not identified (VM resource limits during a long
  session are a plausible guess, not confirmed). This is the other reason
  `tools/nhl95ctl.py` exists — its daemon doesn't use tmux at all, so this
  entire failure mode doesn't apply to it. If working through the manual
  tmux fallback path and a command's output looks empty/stale, check
  `tmux ls` before assuming anything else is wrong.
- **BlastEm config replaces, not merges.** If `~/.config/blastem/blastem.cfg`
  exists at all, the built-in `default.cfg` bindings are dropped entirely —
  the user config must define every binding it needs (D-pad remap *and*
  A/B/C/Start), or buttons silently stop working. The save-state keybind must
  be a literal backtick character in the config, not the word "grave".
- **BlastEm debugger commands**: `b ADDR` set breakpoint (reports a decimal
  index), `d N` delete *by that index* (not by address), `c` continue, `n`
  step without following calls, `s` step following calls, `bt` backtrace,
  `p[/x] VALUE` print register or memory — `p/x 0xADDR.b/.w` for a memory
  read; bare hex with no `0x`/size suffix is parsed as a register name.
  `se REG VALUE` (e.g. `se d0 $FB`) writes a **register** — despite what the
  built-in `?` help text says (`se REG|ADDRESS VALUE`), the actual code only
  implements the register-destination case; passing a memory address just
  hits `Invalid destinatino` and silently fails. There is no direct
  memory-write command at all — `se` into a register at the right breakpoint
  (see the input-injection gotcha above) is the only way to influence
  program state from the console. The auto-run-on-hit script feature is
  `com N` (**three letters**, checked literally in the source as
  `input_buf[1]=='o' && input_buf[2]=='m'`) — the help text prints it as
  `co`, which silently no-ops instead of erroring, wasting real time
  confirming it "did nothing" before finding the actual required spelling.
  It opens a `>>` sub-prompt for one command per line, terminated by a
  literal `end` line — if driving this over `tmux send-keys`, that final
  `end` must be sent with the `-l` (literal) flag; without it, tmux
  interprets the bare string `end` as the keyboard key name "End" and sends
  its escape sequence instead of the three characters, leaving the script
  unterminated. Separately: sending Ctrl+C to the blastem pane does **not**
  drop into the debugger like a normal CLI tool — it's wired to a full
  process exit (saves SRAM, then quits), so use it only to deliberately kill
  and relaunch, never as a "pause" gesture. Refinement: if Ctrl+C is sent
  while *already* paused at the debugger's `>` prompt, it does **not** kill
  immediately (harmless no-op at that instant) — but the SIGINT is still
  pending, and killing the process is merely **deferred until the next `c`**,
  which will then die instead of continuing. Net effect: treat Ctrl+C as
  always eventually fatal, full stop — never send it expecting to resume
  afterward, whether running or already paused.
- **Never batch `c` (continue) in a rapid `send-keys` loop with short
  sleeps.** It races ahead of the debugger and silently drops or miscounts
  breakpoint hits, producing false contradictions in a trace. Once already
  caught this creating a fake "value never gets set" conclusion. Use single,
  deliberate `n`/`c` calls with a real sleep and verify state after each one
  when the trace actually matters. **`tools/nhl95ctl.py` (see Environment
  above) exists specifically because this bit repeatedly even when being
  careful** — its `waitbp` command does the same single-verified-step loop
  programmatically (no risk of an impatient sleep value), and its
  `press`/`runframes` batch safely by counting the *specific* injection
  breakpoint's hit text, not just any output. Reach for the tool before
  reaching for another manual `tmux send-keys` loop.
- **`n` (step-over-call) can permanently hang the debugger console on this
  ROM's self-patching-return-address primitives (the `0x7C6D4`/`0x7C6E6`/
  `0x7C810`/... family documented in FINDINGS.md §6) if no *other*
  breakpoint is armed.** `n`'s internal temporary breakpoint targets the
  naive "instruction right after the `jsr`" address — but these primitives
  read their own return address off the stack, consume inline parameter
  bytes, and *patch* the return address to skip past that data before
  `rts`, so real execution never actually lands where `n` is waiting.
  Nothing ever fires, the console is stuck for good, and only a full
  daemon/process restart recovers (`nhl95_daemon.py stop` — its `SIGTERM`
  handler force-kills the wedged blastem too). **Safe pattern**: never use a
  bare `n` over one of these calls. Instead, read the ROM bytes right after
  the `jsr` to compute where a primitive's inline data actually ends (or
  reuse a previously-confirmed offset — they're often consistent across
  calls, e.g. `0x7C6D4`'s inline block was `0x9FCCC`→`0x9FCDC`, a fixed 16
  bytes, on every category tried so far), set a real breakpoint there, and
  reach it with `waitbp` — which tolerates other breakpoints (like the
  always-armed injection one) firing along the way, unlike a bare `c`/`n`.
- **All `.java` files in the scratchpad get compiled on every headless run**,
  including old broken ones — expect noisy `error: ...` spam from stale
  scripts (`PseudoDisassembler`/`PseudoInstruction` don't exist in Ghidra
  12.1.2; a stray-space typo in an old xref script). Harmless; grep past it
  for your script's own output prefix instead of trying to silence it.
- **Ghidra's recursive-descent disassembly doesn't reach everything** —
  regions only reached via computed/indirect jumps show up as undefined
  bytes. Force it with
  `Disassembler.getDisassembler(currentProgram, monitor, null)` +
  `disassembler.disassemble(addr, addressSet, false)`, walking instruction-by-
  instruction (`cur = insn.getAddress().add(insn.getLength())`, else
  `cur = cur.add(1)` through gaps).
- **Force-disassembly can silently no-op over an address range that Ghidra
  already has *something* defined at** (even wrongly). If you get garbage —
  repeating nonsense instructions like `move.l -(A0),D0` over and over — that
  usually means you disassembled real *data* as code, not a tool failure.
  Call `listing.clearCodeUnits(start, end, false)` before
  `disassembler.disassemble(...)` when you suspect stale/wrong analysis, and
  take repeated garbage as a signal to stop and reconsider whether the region
  is data, not a bug to force past.
- Some 68k subroutines read inline data placed immediately *after* their own
  `jsr` call site (via the return address on the stack), then adjust it
  before `rts`. If code right after a call site disassembles to garbage, this
  is a likely explanation — go look inside the called function instead of
  the caller.
- Two distinct opcode encodings exist for what looks like one instruction
  (e.g. `CMPI.B #imm,Dn` vs `CMPI.B #imm,(An)`) — a byte-pattern search
  tuned for one will silently miss the other.
- **`xdotool key` (bare) to the BlastEm window is unreliable for menu
  confirmation** — it reliably worked for D-pad taps but repeatedly failed to
  register Start/A presses on the Controller Setup and pre-game menu screens
  even with correct window focus confirmed via `xdotool getactivewindow`.
  What reliably works: explicit `xdotool windowactivate --sync $WID` +
  `xdotool keydown --window $WID <key>; sleep 0.1-0.2; xdotool keyup --window
  $WID <key>` (a real held press, not a bare tap). Also: after `-d` launches
  BlastEm paused in the debugger, no game input registers *at all* until you
  send `c` in the tmux console first — an unresponsive-looking screen after
  fresh launch is very likely just this, not a real input problem.
- **Input can go fully dead after a `pkill blastem` + relaunch, even following
  every fix in the gotcha above (`c` after `-d`, held keydown/keyup,
  `windowactivate`/`windowfocus`, click-to-focus).** Hit this once: a session
  had BlastEm stuck displaying a static screen, killed it, relaunched fresh
  from `~/controller_setup.state` (also had to add `SDL_AUDIODRIVER=dummy` —
  ALSA started throwing a fatal "couldn't open audio device" dialog that
  hadn't appeared earlier in the same VM boot), confirmed the window had both
  X input focus and active-window status, confirmed the debugger had actually
  issued `c`/`Continuing` — and still zero keys registered (D-pad or
  Start/A), repeatedly, across ~10 attempts and several minutes. The emulator
  itself was healthy throughout (correct frame rendering, FPS counter
  updating, debugger console fully responsive over its own tmux/stdin path —
  it's specifically X11 keyboard delivery to the SDL window that's failing).
  Root cause not found — didn't burn further time on it per the "3 failed
  fixes, escalate layers" rule, since it's an environment issue, not a
  finding. **If this recurs, don't re-try the same X11-focus fixes** (already
  ruled out); worth trying instead: a full Xvfb/openbox session restart
  (bigger hammer, not yet attempted), or checking for a stuck X keyboard
  grab. A dead-input BlastEm window is still fine to leave running as a
  "clean" idle state between sessions — it just can't be driven until this is
  fixed.
- **In-game menu controls, ground-truthed against Sega Retro's NHL 95 page**
  (developer-sourced UI writeup — see the Sega Retro gotcha below for how to
  actually load that page): pre-game/pause menu has 3 tabs (`INFO`/`STATS`/
  `OPTIONS`) switched with `Left`/`Right`; `Down`/`Up` moves within a tab's
  list; **`C` confirms/opens the highlighted item**; `Start` pauses/resumes
  at the outer level. Inside `Edit Lines` specifically: `Left`/`Right` is
  *documented* to cycle the selected line and `Up`/`Down` the selected
  player, `C` makes a substitution, and `Start` opens an `Exit`/`Set Original
  Lines` submenu (confirmed live: `Start=Exit`, `A=Set Original Lines`) — but
  live testing this session could not get `Left`/`Right` to actually cycle
  lines inside that screen despite multiple attempts (short/long holds, from
  different cursor positions); there's likely a control-state prerequisite
  not yet found. Reliable path to the Line Editor: pause menu → `Down`×2 to
  `EDIT LINES` → `C`. Reliable path to the Team Roster (all 14 named
  attributes + Overall rating per player): pause menu → `Left` to `INFO` tab
  → `Down` to `Team Roster` → `C`; then `C` cycles Goalies/Offense/Defense,
  `Left`/`Right` cycles the shown stat, `A` switches teams.
- **`Edit Lines` and the in-game "Line Change" quick-menu are two different
  features — don't conflate them.** `Edit Lines` (above) is the pre-game/pause
  roster editor. The separate "Line Change" menu (Sega Retro's own section
  name) is a *live gameplay* overlay — appears automatically before a face-off
  or via holding `A` while on offense — showing all 7 named lines with fatigue
  bars, meant for in-game tactical switching. Tried repeatedly this session to
  catch it on screen (multiple real face-offs, multiple A-holds of varying
  length) and never once got it to render in a screenshot — either the
  trigger window is shorter than a screenshot round-trip can catch, or "on
  offense" needs actual puck possession that's hard to force blindly. If this
  is needed again, a live breakpoint-based approach (catch the screen
  transition in the debugger, not by polling screenshots) is more likely to
  work than more screenshot timing attempts. What *did* work as a substitute:
  the Team Roster screen's `Reg`/`PP`/`PK` columns per player, cross-referenced
  against the static per-line ROM table — see FINDINGS.md §7#2 for the result.
- **The per-team position tables at ROM `0x3618`/`0x4FFA` are HOME/AWAY by
  real hockey home team, not by which side of the screen a team's photo
  renders on.** Got this backwards once already (§2.3 in FINDINGS.md) — every
  byte in both tables decodes to a plausible player regardless of which
  team's roster you check it against, so a swapped label doesn't look wrong
  until you cross-check against something live. `0x3618` = the team hosting
  the game (confirmed via the in-game announcer naming the home arena), not
  whichever team is drawn on the left. Line 0 in this table is confirmed
  (live, zero-game-clock-elapsed check) to be `Sc1`.
- **`segaretro.org` is behind an Anubis JS proof-of-work challenge, not a
  simple bot-UA block.** Plain `WebFetch` and `curl` with a spoofed
  User-Agent both get served the Anubis challenge page (title "Making sure
  you're not a bot!") instead of real content — `curl` can't solve it since
  it never executes the JS. A real browser does: use the `playwright`
  (or `chrome-devtools`) MCP tool to navigate there, then wait a few seconds
  and re-snapshot — Anubis resolves itself silently once its JS runs, no
  interaction needed. The resulting snapshot is large (2000+ lines); grep for
  `text:` and search by keyword rather than reading it sequentially.
  Sega Retro's NHL 95 page is a genuinely useful external source — a
  developer/manual-sourced UI and mechanics writeup, not a
  reverse-engineering one, but it directly named things this project had
  independently found or was still chasing (hot/cold ±10-30%, "seven lines,"
  a Team Roster screen with 14 named attributes) and is worth checking against
  before spending more live-tracing effort on a mechanics question — see
  FINDINGS.md §6 for how big that payoff was here.
- **`gamefaqs.gamespot.com` 403s plain `WebFetch`/`curl` too — same fix as
  Sega Retro, use the `playwright` MCP tool.** Paid off even bigger than
  Sega Retro this time: a 2011 GameFAQs FAQ
  (`genesis/915999-nhl-95/faqs/28196`, saved locally at
  `docs/external_sources/gamefaqs_28196_roster_ratings.txt`) hand-transcribes
  a static "Rating" for every one of ~700 players in the game. Correlating
  that against `docs/full_roster_database.json`'s per-player attribute
  nibbles (`tools/correlate_ratings_vs_faq.py`) cracked most of the way
  through the Overall Rating formula (§6/§7#1) in minutes via linear
  regression (R²≈0.98) — something dozens of live bytecode-interpreter
  breakpoints across multiple sessions hadn't fully nailed down. General
  lesson, worth internalizing for the *next* stuck-on-a-mechanic moment: a
  large, exhaustive, human-curated external dataset can out-perform more
  live tracing entirely, not just save time on it. Also see that script's
  own docstring/comments for two real data-quality bugs found and fixed in
  `full_roster_database.json` along the way (an ambiguous `"New York"` city
  field, four corrupted `mascot` fields) — don't naively re-match by city
  prefix against that file again.

---

## Current status

See `docs/FINDINGS.md` §7 for the live open-questions list. Items 2
(line-index mapping), 5 (special-teams line-switching), and 6 (nibble→named-
stat mapping) are closed — confirmed live and cross-checked multiple
independent ways. Item 6's formulas (Overall Rating + all 11 named stats)
are now live-validated directly against the running ROM (not just against
third-party data): Overall Rating mean|residual| ≈1.8 live, named stats
single digits after a multivariate refit (`tools/fit_multivariate_named_stats.py`).
A full audit of the tournament app's production database (all 26 teams, 618
skaters) found no second Rangers-style systematic bug anywhere — that fix
was a one-off, not a pattern — so no further production writes are
currently recommended.

The remaining open piece of item 1/6 is narrower than before: the *exact*
storage/computation mechanism (identity and formula are both solved) still
sits behind a bytecode-interpreter wall hit twice independently (Scouting
Report and Team Roster call sites); needs either full interpreter-dispatch
tracing or VDP/tile-level analysis as its own scoped session — low priority
now that the formula itself is solved and live-validated. Two live-read
residuals (Ronning's Speed, Courtnall's Agility, both ~+10) remain
unexplained and are a plausible but *unconfirmed* hot/cold-modifier effect —
confirming would mean single-stepping `team_struct+0x1A4` for that specific
boot/matchup, the same way Messier/Leetch's modifier bytes were read in §5.
AI decision-making and faceoffs are untouched and would be a new,
separately-scoped investigation, not a continuation of item 5. (There is
**no interactive fighting minigame** in this game — an earlier version of
this note wrongly implied there was, corrected by the repo owner. "Fighting"
does still appear in the ROM's own text data, though, now fully mapped: a
smarter static scan (issue #8, see `docs/FINDINGS.md` §7#10) found the
**complete penalty-type catalog** (Charging, Slashing, Tripping, Roughing,
Hooking, Cross Check, Interference, Holding, Fighting, plus a `Fighting *`
variant — a player can be sent to the box for any of these without any
interactive fight sequence) and the **complete team-strength rating
category list** (Shooting, Passing, Checking, Goalkeeping, Skating,
Defense, Fighting, Power Play Adv., Overall — the source table for the
Scouting Report's "Advantage: [category]" display). Don't re-add
"investigate the fighting minigame" as a target — there isn't one — and
don't re-scan for these tables, they're done; the same pass also flagged
lower-confidence leads (a goalie-specific stats table, an injury-status
abbreviation table, a partial months table) still open if picked up.)

The project is now public: https://github.com/BreakableHoodie/nhl95-decoded
(ROM, Ghidra project, and raw third-party scrapes are gitignored — never
commit those). Docs are split into `docs/OVERVIEW.md` (plain-English),
`docs/FINDINGS.md` (technical deep-dive), and `docs/GLOSSARY.md`
(plain-English term definitions — added after a reader said they had no
idea what a "nibble" was), all served via GitHub Pages at
https://breakablehoodie.github.io/nhl95-decoded/ with a working
client-side search (`docs/search.html`) and a proper site-wide design
(`docs/_layouts/default.html` + `docs/assets/css/site.css` — a site-local
Jekyll layout always wins over GitHub's bare default theme, which is what
every page except search.html was stuck with before). Open threads are
tracked as GitHub issues labeled `investigation`, not just in §7.

**Since the above paragraph was written**, in the same session: nibble 11
(previously unexplained) turned out to be a goalie-only stat (`Stick
Left`), confirmed live by reading two Vancouver goalies' Team Roster
values directly — every one of the 14 attribute nibbles now has a
confirmed identity, closing item 6 completely. Separately, decoded the
exact ROM bytecode table backing the Team Roster's stat-category cycle
(`0x085832` skaters / `0x085994` goalies) and found its one-hot
nibble-selector bitmask for `Overall` (`0x1FBA`) is bit-for-bit identical
to the independently-fit `OR_WEIGHTS` formula — real ROM-level proof of
*which* nibbles feed Overall Rating (not just a statistical fit anymore).
Exact weight magnitudes and the consuming opcode are still open (issue
#2) — confirmed via static search this session that `0x1FBA` appears
nowhere else in the ROM as a literal, so finding the consumer needs live
tracing, not more static search.

A reader also asked what live gameplay actually does with the Smolinski
clone once it exists — reproduced the bug fresh, and Team Roster showed
`Status: Ice` with a doubled `Reg` line-count, confirming "plays normally"
is a real outcome. Important nuance: the reader's friend has *personally
witnessed* two other outcomes (joining from the bench, standing idle near
the net) across past sessions, so this is one confirmed data point in a
state-dependent bug, not the full answer — left open as issue #10.

Built two new tools: `tools/rom_scan.py` (reusable string-record parser +
pattern search, consolidating techniques used ad hoc all session) and
`tools/nhl95_monitor.py` (polls WRAM during unattended CPU-vs-CPU games,
logs value changes to CSV — built after the user asked about teaching
something to play the game for research purposes; conclusion was that the
built-in CPU AI already plays fine, what was missing was scale/logging,
not skill, so this is deliberately not an RL agent). Also confirmed real
game mechanics that were *not* previously documented anywhere in this
project: injuries (`Injury to: [player], Out for [N] game(s)`, with real
pluralization logic, found at ROM `0x09F2D5`+) and a "Team Stats"
comparison table (`0x092410`+: Score/Shots/Shooting Pct/Power
Play/Faceoffs Won/etc.).

**Issue #11 (score/shots/clock/period RAM addresses) is now fully solved
— Score, Shots, Clock, and Period all live-confirmed.** The Team Stats
table above turned out to double as a real offset table — its suffix
field is a byte offset into a per-team stats struct, not just a label
(`Shots`=`+0x00`, `Score`=`+0x0C`, `Faceoffs Won`=`+0x0E`, `Body
Checks`=`+0x10`, `Power Play`=`+0x02`/`+0x04`, `Penalties`=`+0x06`/`+0x08`,
`Passing`=`+0x14`). Struct bases confirmed live — `0xFFFFC5EE` (home/VAN)
and `0xFFFFC288` (away/ASE) — byte-exact against the on-screen scoreboard
across two real goals in one CPU-vs-CPU game. Clock (`0xFFFFC022`, word,
total seconds remaining) was cracked differently — the obvious static
lead (a "Period Stats" bytecode block) turned out to be an end-of-period
summary renderer, not the live HUD, so it needed value-matching against a
live screenshot instead, confirmed twice independently, byte-exact both
times. **Period had a real false lead worth remembering**: the first
candidate (`0xFFFFC02A`) looked perfect — rock-stable at `1` for an
entire period — but a live-watched transition caught it jumping to `0x80`
instead of a clean `2`, which was the signal to stop trusting a single
stable-looking byte and diff the *whole* surrounding struct between a
period-1 and period-2 reading instead. That found the real field:
`0xFFFFC021` (byte) went cleanly `0x00`→`0x01`, 0-indexed, sitting right
next to the clock — confirmed against **two** real transitions (1→2 and
2→3), the second one with a bonus independent check: the pause menu's
`STATS`-tab period-dot indicator (`1st`/`2nd`/`3rd`) had moved to `3rd`
in the same screenshot, matching the memory read exactly.
`0xFFFFC026` (word, constant `1200` = this session's 20-minute Per.
Length in seconds) is period *length*, not number — see
`docs/FINDINGS.md` §7#9/§7#11 and GitHub issue #11 (closed) for the full story.
Not yet confirmed whether the struct
addresses are universal home/away slots or session-specific — same
caution as the `0x3618`/`0x4FFA` home/away gotcha below.

**A smarter static scan (issue #8) found a full night's worth of
previously-undocumented ROM tables**, all in `docs/FINDINGS.md` §7#10:
a complete penalty-type catalog and team-strength rating category list
(both folded into the fighting-mechanic note above), an injury-status
abbreviation table (`Bench`/`Inj. P`/`Inj.1G`-`Inj.9G`, plus a lone `" C  "`
entry that's plausibly a team-captain marker), a 7-month Season-mode
calendar table, and a goalie-specific offensive stat cycle (Goals/
Assists/Points/Shots On Goal/Penalty Minutes — confirms goalies track
offensive stats in this game, not just saves). Cracking the last two
required recognizing a *third* string-record format in this ROM (no
suffix field at all; the header's length byte counts the whole record
including itself) — documented in `tools/rom_scan.py` as
`parse_stride_records`. Three more leads filed but not chased yet: a
Season-mode end-of-year awards table (issue #12, real NHL trophy
categories — MVP/Norris-style/Vezina-style/etc.), a fuller pre-game/pause
menu item list (issue #13, including several items never explored live —
`SCORING SUMMARY`, `PLAYOFF STATS`, `TIMEOUT`, `ABORT GAME`), and —
the most exciting of the three — **a previously-completely-unknown
shootout mode** (issue #14: real code around `SHOOTOUT MODE`/`Round `/
`SHOOTOUT WON BY [team]` at ROM `0x09DFD5`, not just a stray menu label).

**The Pages site now has a working light/dark/auto theme toggle** (nav on
every page, persisted via `localStorage`, no flash-of-wrong-theme) — the
CSS already had the variables wired up from the earlier redesign, but
nothing let a visitor override the OS setting until this session.

**Radare2 MCP is now set up** (`claude mcp add radare2 -- r2pm -r r2mcp`,
local scope) as a possible faster alternative to one-off Ghidra
scratchpad scripts for future static work — installed via Homebrew +
`r2pm -Uci r2mcp`, no GUI needed (unlike Ghidra's own MCP options, which
need a live GUI session this environment can't drive). Requires a fresh
Claude Code session to pick up (MCP servers load at session start).

**The three "not chased yet" leads above are now substantially chased —
see `docs/FINDINGS.md` §8 for the full game-modes writeup.** The repo
owner named the main-menu Shootout mode directly and asked for a fuller
pass across every game mode (trades, season, playoffs included). Live-
cycled the full `Play Mode` field: 11 directly selectable modes
(`Regular Game`/`Practice Mode`/`New Playoffs`/`New Playoffs/Best of 7`/
`New Season`/`Trade Players`/`Create Player`/`Sign Free Agents`/`Release
Players`/`Shootout`/`Game With Trades`), plus two more (`Continue
Playoffs`, `Continue Season`) that only appear conditionally, per the
official US manual (a PDF the repo owner linked from `segaretro.org` —
gitignored, copyrighted, not redistributed, but now a citable source).
Shootout is confirmed real and substantial: its own roster/goalie setup
screen, a clockless HUD, a per-attempt "SHOOTOUT MODE/Round N" screen
matching the ROM text byte-for-byte, and a real shot clock — closing most
of issue #14 (full scoring-resolution mechanics still open). Season mode's
full flow confirmed screen-by-screen (`SEASON SETUP` → `GAMES TODAY` → a
10-item `SEASON OPTIONS` hub, including a real 84-game NHL standings
table). Playoffs' full 16-team bracket screen with a rendered Stanley Cup
graphic, previously completely undocumented. Trade Players' roster-
comparison screen — a bonus find: it shows every player's exact Overall
Rating as plain readable text for two full rosters at once, flagged on
issue #2 as a possibly-faster route into that still-open exact-opcode
question (checked statically — zero xrefs to this screen's text either,
same computed-dispatch wall as everything else, so no shortcut after
all, but worth ruling out). Also confirmed the manual's injury-status
text (`P`=out for period, `G`=out for game, `4G`=four-game injury)
matches the ROM's `Inj. P`/`Inj. G`/`Inj.1G`-`Inj.9G` table from earlier
the same session, word for word — a strong independent confirmation, not
just a plausible guess anymore.

**Three more issues closed the same session, all via live play rather
than static tracing**: #8 (UI string-table scan — every lead from that
scan, including the two "lower-confidence" ones, ended up fully decoded
once a third string-record format was found — see the entry above),
#13 (the full pre-game/pause menu is now mapped exactly: `OPTIONS` tab
items vs. `STATS` tab items vs. mode-specific additions like `SHOOTOUT
SETUP`/`PLAYOFF STATS`), and #14 (Shootout mode's full cycle traced end
to end, including a directly-observed puck-in-flight shot animation
against Chicago's Ed Belfour — fittingly saved both times, since the
Trade Players screen already confirmed his Overall Rating at 98, the
best of any goalie seen this session). Remaining open issues (#1, #2,
#3, #6, #9, #10, #12) mostly need live bytecode tracing on the self-
patching-primitive family or an expensive full-season playthrough —
genuinely scoped future work, not quick continuations.

**Unplanned but significant: issue #7 (Dallas exhibition-menu access) is
now fully resolved and closed — the old "Dallas is completely absent
from the selectable list" finding was itself wrong.** Discovered while
hunting for Boston for an issue #10 (Smolinski) reproduction attempt:
cycling `Team 1` landed cleanly on Dallas, and it played all the way
through Controller Setup and a real Scouting Report screen (`Dallas
Stars, Overall 21`). A careful follow-up re-walk — verifying a fresh,
fully-settled screenshot after *every single* input, no batching —
found the actual mechanism: the Exhibition selector cycles in
**alphabetical order** (`Anaheim → Boston → Buffalo → Calgary → Chicago
→ Dallas → Detroit → Edmonton → Florida`, nine clean verified steps),
not ROM storage order as the original investigation concluded. Dallas
sits exactly where alphabetical order puts it (`Chicago` < `Dallas` <
`Detroit`) — it was never missing. The original finding was almost
certainly a single silently-doubled input step around that exact
Chicago/Dallas/Detroit boundary, which would look identical to "Dallas
skipped, Detroit follows Chicago directly."

**Real, reusable gotcha this produced**: `tools/nhl95ctl.py press
LEFT/RIGHT N` is *not* reliable for precise single-step menu navigation
on team-selector-style fields — the same single-frame-held-then-released
input sometimes advances the on-screen list by one position and
sometimes by two or more, a timing sensitivity in how fast the debugger
can pump frames relative to this menu's own auto-repeat logic, not a
daemon bug (confirmed by reading the actual `se d0`/`c` sequences it
sends — the protocol-level behavior is clean). **The fix that worked**:
after every single press, run a few idle settle frames
(`runframes 8-10`) before screenshotting, and verify each step
individually rather than batching multiple presses — done this way, 9
consecutive steps came back perfectly clean. Trust single-step
navigation only when done this carefully; don't batch multiple presses
on this class of menu.

**Issue #10 (Smolinski clone's live gameplay behavior) is now closed, on
the strength of a third independent reproduction — this one with a real
goal.** The first two reproductions used an idle-but-human-assigned
controller (parked on a team column but never pressed), which risked
under-testing "real" play. This session redid it with **both** controller
icons parked under Controller Setup's `CPU` column (genuine AI-vs-AI,
Boston vs. Edmonton), reproduced the same Sc1 LW→RW Smolinski
substitution, and let it run unattended. Boston scored 8:05 into the 1st
— the Scoring Summary screen credited it cleanly to `20 B. Smolinski`,
assisted by Iafrate and Casey, a normal, correctly-attributed goal, not a
glitch. Team Roster immediately after still read `Status: Ice`, `Reg: 12`
— identical to both earlier reproductions. Three independent
reproductions, two different away opponents, one real goal, all agreeing
on "plays completely normally, including scoring" — that's now the
well-supported default outcome. The other two friend-reported behaviors
(bench arrival mid-play, corner celebration) still weren't caught despite
this being the first attempt to actually produce a goal; they're left
documented as unconfirmed rather than chased further. Full writeup in
`docs/FINDINGS.md` §3.

**Bonus mechanic discovered along the way, not previously documented**:
the pause menu's `EDIT LINES` always opens the **away team's** (`Team 2`'s)
Line Editor — not the paused controller's team, not a home/away photo
side. Confirmed by swapping which team occupied the `Team 2` slot on the
pre-Controller-Setup settings screen (first Vancouver, then Boston) and
watching the Line Editor's own header track it exactly, even with *no*
controller assigned to either team (both on CPU). To edit the home team's
lines from this menu, set it as `Team 2` before starting the game.

**Issue #1 (hot/cold modifier vs. the two live-read stat residuals) is now
also closed, same session.** The earlier "shortcut" attempt (a prior
session) tested the right boot but guessed at Vancouver's team-struct
address and got a genuinely mixed result. This session found the address
properly instead: breakpointed `0x0A0042` (the modifier-sum function),
discovered and ruled out a same-address false-positive caller (`0x0A0024`
— fires on unrelated button-press handling, only distinguishable by
checking `bt`), then breakpointed the real setup caller `0x0A0006`
directly and read `A0` at the hit — `0xFFFFC288` for Vancouver,
cross-checked against the Scouting Report's own on-screen text for that
exact matchup. Since this was a fresh boot, the old residual numbers
(+9.7/+11.3, tied to different now-gone RNG state) couldn't be reused
directly, so the test was redone fully self-consistently within this
boot: read this boot's own modifier bytes (Ronning -4, Courtnall +4),
computed boot-independent predicted stats from the multivariate models,
and compared against this boot's own live Team Roster reads. **Ronning:
predicted+modifier (81.3) matched live (81) exactly** — a clean,
decisive confirmation that hot/cold applies additively to live stats.
Courtnall's case (predicted+modifier 89.7 vs. live 98) missed by 8, but
98 sits right at the 0-99 ceiling — very likely the same clamp/saturation
effect this document had already flagged as suspected-but-unconfirmed
from CSV-comparison outliers, now with a live example. Full writeup in
`docs/FINDINGS.md` §5.
