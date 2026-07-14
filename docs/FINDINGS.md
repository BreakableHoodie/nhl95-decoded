# NHL '95 (Genesis) — Reverse Engineering Findings

ROM: `NHL 95 (USA, Europe).gen` — Product ID T-50856, 2MB, no header (raw .bin layout,
Ghidra addresses == BlastEm/live addresses, no SMD offset).

This document is the living record of what we've confirmed about the ROM's internal
data formats and game logic, built via static analysis (Ghidra) cross-checked against
live emulation (BlastEm, run under a 68k instruction-level debugger).

**Why this matters, beyond the game itself:** this started as one player's report of
a weird bug and a question — is this just him, or could it happen to anyone? Rather
than patch the symptom, every finding here traces back to the actual byte and
instruction responsible, then checks whether the same failure mode shows up anywhere
else in the data (see §3, §4) — the same "root-cause it, then check if it's systemic"
instinct that matters in any debugging work, just made easier to see clearly because
the target is small and finite. It's also a working demonstration of static analysis
(Ghidra) and live tracing (an instruction-level debugger) used *together* — several
findings here (§5 especially) would have been wrong if we'd trusted the static
disassembly alone; live verification against a running system is what actually
confirmed them. The toolchain (a Ghidra project, a scripted VM, a debugger workflow,
and fast savestate-based iteration) isn't NHL-95-specific — it's a reusable template
for understanding any closed, undocumented binary with no source and no docs. And a
few of these findings (§5 in particular) settle questions the NHL94/95 fan community
has argued about for years without ever opening the ROM to check.

---

## Contents

- [1. Toolchain / methodology](#1-toolchain--methodology)
- [2. ROM data layout](#2-rom-data-layout-offsets-are-rom-file-offsets-unless-stated-as-ram)
  - [2.1 Per-team master record](#21-per-team-master-record)
  - [2.2 Player name records](#22-player-name-records--fully-solved-name--jersey-number)
  - [2.3 Per-line position table](#23-per-line-position-table-8-bytesline-8-linesteam)
- [3. Bug: Smolinski line-editor clone](#3-bug-smolinski-line-editor-clone-root-caused-live-confirmed)
- [4. Anomaly scan of the player database](#4-anomaly-scan-of-the-player-database-rosterjersey-data)
- [5. Hot/cold streaks](#5-hotcold-streaks--confirmed-real-mechanism-partially-traced)
- [6. Player rating bytes / Overall Rating formula](#6-player-rating-bytes--jersey-number-solved-overall-rating-formula-solved-and-rom-confirmed-exact-weights--opcode-still-open)
- [7. Open questions / candidate next steps](#7-open-questions--candidate-next-steps) — 12 numbered items, roughly priority order; closed ones are struck through inline, no separate anchors (they're list items, not headings) — Ctrl+F the item number if jumping to one directly
- [8. Game modes — mapped via live exploration and the official manual](#8-game-modes--mapped-via-live-exploration-and-the-official-manual)
  - [8.1 The full `Play Mode` list](#81-the-full-play-mode-list)
  - [8.2 Shootout](#82-shootout--real-live-confirmed-and-richer-than-the-static-find-suggested)
  - [8.3 Season and Playoffs](#83-season-and-playoffs--the-full-manual-documented-flow-live-confirmed-screen-by-screen)
  - [8.4 Trade Players](#84-trade-players--and-an-unplanned-lead-for-the-overall-rating-research-issue-2)
  - [8.5 Full pre-game/pause menu](#85-full-pre-gamepause-menu--fully-mapped-and-closed-issue-13-closed)

**How to read this**: sections are long because they're a *history*, not
just a result — an earlier hypothesis getting corrected two paragraphs
later is kept in on purpose (see the fighting-mechanic and "Out for 08"
corrections in §7 for two honest, recent examples), not tidied away. If
you just want the current answer, §5 and §6 both open with a **quick
reference** (a diagram, a table) before the narrative — read that, skip
the rest unless you want the evidence trail. [`OVERVIEW.md`](OVERVIEW.md)
skips the trail entirely if that's all you want, and
[`GLOSSARY.md`](GLOSSARY.md) explains every technical term (nibble, ROM,
breakpoint, and so on) in plain English if any of the vocabulary here is
unfamiliar.

---

## 1. Toolchain / methodology

- **Static analysis**: Ghidra project at `ghidra_project/NHL95.gpr`, imported as raw
  binary, `68000:BE:32:default`. Custom headless Java scripts (kept in the session
  scratchpad) do recursive disassembly seeding, function dumps, and ROM byte-pattern
  searches with alignment validation.
- **Live/dynamic analysis**: x86_64 Ubuntu VM under UTM (`nhl95vm2`, genuine QEMU
  emulation — required because macOS/Rosetta blocks BlastEm's JIT from allocating
  executable memory). BlastEm built from source (`~/blastem-src`, `make OPT=-O2`),
  run inside a `tmux` session on the VM so its console-based 68k debugger has a real
  attached stdin/stdout, controllable over SSH. Game input driven headlessly via
  `xdotool` against an Xvfb/openbox X11 session.
- **Key gotcha**: BlastEm's config loading (`config.c: load_overrideable_config`) does
  **not** merge a user `blastem.cfg` with the built-in `default.cfg` — if a user config
  exists at all, it's used *exclusively*. A custom config that only remaps the D-pad
  (done to work around an unexplained default-arrow-key input issue in this VM/X11
  setup) silently drops the A/B/C/Start bindings entirely. Fixed by writing a full
  config that includes both the remapped directions and the standard button bindings.
  Keyboard mapping in use: `j/k/h/l` = down/up/left/right (D-pad), `a`=A, `s`=B, `d`=C,
  `enter`=Start. (Default `blastem.cfg` binds keyboard `c`/`b` to debug-view toggles,
  *not* the gamepad C/B buttons — worth remembering if revisiting this.)
- **Debugger command reference** (BlastEm, 68k): `b ADDR` set breakpoint, `d N` delete
  breakpoint *by index* (decimal, shown when the breakpoint was set — not by address),
  `c` continue, `n` step (no follow), `s` step (follows bsr/jsr), `bt` backtrace,
  `p[/x] VALUE` print register or memory (`p/x 0xADDR.b` for a byte read — bare hex
  without `0x`/`.b` is parsed as a register name, not a memory address).

---

## 2. ROM data layout (offsets are ROM file offsets unless stated as RAM)

### 2.1 Per-team master record

26 real NHL teams (1994-95 season) stored back-to-back starting at ROM `0xDB8`
(Anaheim) through `0x55A8` (Washington). Team order as stored: Anaheim, Boston,
Buffalo, Calgary, Chicago, Detroit, Edmonton, Florida, Hartford, Los Angeles,
Dallas, Montreal, New Jersey, NY Islanders, NY Rangers, Ottawa, Philadelphia,
Pittsburgh, Quebec, San Jose, St. Louis, Tampa Bay, Toronto, Vancouver, Winnipeg,
Washington — this is **alphabetical by city name**, with exactly one exception:
Los Angeles sits before Dallas, not after.

Two more tables of the exact same shape sit immediately before the real teams, at
`0x834` and `0xB04` — these are **not unused/hidden**; they're real All-Star rosters
(confirmed selectable in-game), each mixing star players from many different real
teams (e.g. `0x834` includes Roy, Messier, Lindros, Bourque, Jagr all in one roster).

**Menu→ROM order — ⚠️ superseded, kept for the record, see the resolution
right below.** The original theory here was that the in-game Team 1/Team 2
exhibition selector cycles in *exactly* ROM storage order, with **Dallas
completely absent from the selectable list** (skipping ROM index 10
entirely) and both All-Star rosters appended at the wrap point instead of
appearing where they're actually stored — attributed to Dallas being a
brand-new 1993-94 relocation from Minnesota, plausibly added to the roster
data too late to get wired into the menu's team-count/loop. This turned
out to be wrong; see below.

**Resolved: the menu order is alphabetical, not ROM order, and Dallas was
never missing.** Two independent lines of evidence settled it. First,
Dallas is directly selectable and fully playable: cycling `Team 1` right
from `Chicago` in Exhibition mode landed cleanly on `Dallas`, and it played
through a full Controller Setup → Scouting Report sequence with a real,
internally-consistent `Dallas Stars — Overall 21`; separately, Season
mode's `Games Today` schedule browser independently shows a genuine
"Detroit at Dallas" fixture, selectable exactly like every other matchup.
Second, a careful re-walk of the Exhibition menu — verifying a fresh,
fully-settled screenshot after *every single input*, no batching — produced
nine clean, unambiguous transitions: `Anaheim → Boston → Buffalo → Calgary
→ Chicago → Dallas → Detroit → Edmonton → Florida`, exact alphabetical
order, with Dallas sitting exactly where alphabetical sorting puts it. This
is not the ROM storage order claimed above (which has Dallas between Los
Angeles and Montreal) — it's a real, separate menu→team lookup table after
all, just alphabetically sorted rather than "scrambled," including both
All-Star rosters sorting after `Washington` at the wrap point, exactly as
originally observed.

**What actually went wrong in the original investigation**: almost
certainly the same input-timing failure mode this project only diagnosed
by accident, much later (see CLAUDE.md's gotcha) — a single button input
occasionally advancing the on-screen list by two positions instead of one,
from how fast the debugger can pump frames relative to this menu's own
edge-detection/auto-repeat logic. A single silently-doubled step right
around Chicago/Dallas/Detroit would look *exactly* like "Dallas is
missing, Detroit follows Chicago directly" — the original claim,
precisely. The lesson worth keeping: a good real-world explanation for
*why* a bug would exist (Dallas really was a brand-new relocation) is not
evidence that it *does* exist. GitHub issue #7 closed with this
resolution.

Each team record is laid out as:

```
[ 64-byte line/position table  (8 lines x 8 bytes) ]
[ variable-length player name records, back to back ]
[ team city string \0 ] [ abbreviation \0 ] [ mascot name \0 ] [ arena name \0 ]
[ ... unidentified trailing bytes / palette-looking data ... ]
[ next team's 64-byte line table starts here ]
```

Detected programmatically by scanning for 8 consecutive 8-byte groups where
byte0==0x01 and byte7==0x00 (true for every line, every team — see §2.3).

### 2.2 Player name records — FULLY SOLVED (name + jersey number)

Format, fully decoded and verified against 8 known jersey numbers read directly off
screenshots (Oates=12, Stumpel=22, McKim=45, Smolinski=20, Marois=33, Neely=8,
Bourque=77, Iafrate=43 — all 8/8 match exactly, no exceptions):

```
[0x00]                  record marker
[LEN byte]              total size of the fields below, in bytes
[LEN-2 bytes]           player name, ASCII, exactly LEN-2 bytes long, NOT
                         null-terminated (the name simply ends where the jersey
                         byte begins — no delimiter needed since LEN is authoritative)
[1 byte]                jersey number, BCD-encoded (e.g. byte 0x22 = number "22").
                         Verified 8/8 against known values, no invalid-BCD exceptions
                         found across all 26 teams' full rosters.
[1 byte]                unknown — NOT reliably BCD (several players have values with
                         nibbles >9, e.g. 0xa3, 0xb4), so likely a different scale or
                         a packed bitfield (handedness/position sub-code?). Not decoded.
[6 bytes]                unknown — presumably rating/attribute bytes (speed, shot,
                         checking, etc. in the usual EA Sports style). Raw values
                         captured for every player but individual byte meanings not
                         decoded — would need to cross-reference against the code that
                         drives the Scouting Report "advantage" comparison to pin down
                         definitively (not yet done).
```

Total record size = `2 + LEN`. Records are back-to-back with no padding between them.
Roster index (see §2.3) = 1-based sequential position of the record within a team's
block (goalies are records 1, 2; skaters follow from record 3 onward, in
game-consistent line order — e.g. Boston: 1=Casey, 2=Riendeau, 3=Oates(!) ... 6=
Smolinski, 8=Neely, 18=Bourque, 20=Iafrate).

**Full database extracted**: all 26 teams, every player, name + roster index + jersey
number + raw 7-byte unknown-attribute block, dumped to
[`full_roster_database.json`](./full_roster_database.json).

**Still open**: semantic meaning of the 7 unknown bytes per player (1 "unknown1" +
6 "trailer"). Next step would be finding the Scouting Report advantage-calculation
code in Ghidra and tracing which byte offsets it reads.

### 2.3 Per-line position table (8 bytes/line, 8 lines/team)

This is the table read/written by the Line Editor's substitution logic (ROM function
`0x095A60`, see §3). Confirmed via live register/memory tracing against Boston's Sc1
line while reproducing the clone bug.

| Byte offset | Meaning | Scanned by dup-check loop? |
|---|---|---|
| +0 | Always a goalie's roster index in every team observed (Boston: `01`=Casey). Constant per team across all 8 lines. Purpose unconfirmed — possibly "primary goalie" reference, unrelated to the 5 skater slots. | No |
| +1 | LD | Yes |
| +2 | RD | Yes |
| +3 | LW | Yes |
| +4 | C | Yes |
| +5 | RW | Yes |
| +6 | "Extra" slot — holds a real roster index (a plausible depth player) in every team, but is not shown anywhere on the Line Editor screen. Purpose unconfirmed. | Yes — and checked **first** |
| +7 | Always `0x00` in every line/team observed. Likely "unused" or a sentinel/flag. | No |

Line order within the 8-line/64-byte block is *inferred*, not independently verified:
Sc1 (confirmed — matches the live Line Editor screen and Ghidra-traced write target),
then presumably Sc2, Sc3, Pp1, Pp2, Pk1, Pk2, and an 8th line of unknown purpose.
**Open item**: confirm this ordering by watching which of the 8 blocks changes when
selecting Sc2/Pp1/Pk1/etc. in-game.

**Independent confirmation via a completely different code path (Scouting Report
screen, not the Line Editor), plus a corrected team-label swap.** Live-traced the
pointer the Scouting Report's "advantage" computation (`0x0009FE56`/`0x0009FE90`,
see §6) dereferences for each team: ROM `0x3618` and `0x4FFA`. Reading those bytes
directly from the ROM file, both are clean `01 .. .. .. .. .. .. 00`-framed 8-byte
records, and **byte `+4` is `0x03` in both** — a plausible "Center" match regardless
of which team owns which address, since `roster_index 3` happens to be each team's
own franchise center (Ronning for VAN, Messier for NYR). *Correction from an earlier
pass through this section*: the addresses were initially labeled `0x3618 = VAN`,
`0x4FFA = NYR`, matching which side of the screen each team's photo appeared on.
That labeling was backwards — see below, live verification showed `0x3618` is
actually **New York's** table and `0x4FFA` is **Vancouver's**. The code's internal
HOME/AWAY struct terminology tracks the real hockey home team (confirmed by the
in-game announcer: "welcome to a sold out Madison Square Garden, home of the
Rangers"), not which side of the screen a team's photo renders on — an easy trap
since every byte in both tables decodes to a plausible player regardless of which
team's roster you decode it against, so nothing about the data itself flags the
swap. Only cross-checking against the live Line Editor caught it.

**Line 0 = Sc1, confirmed exactly by live verification.** Reached the live Line
Editor (navigation, worth recording since it took real trial and error): from the
pre-game menu (`START GAME`/`INSTANT REPLAY`/`EDIT LINES`/`CHANGE GOALIE`) or the
in-game pause menu (`RESUME GAME` replaces `START GAME`), press Down twice to
highlight `EDIT LINES`, then confirm with the **C button** — not Start (Start just
resumes/toggles pause regardless of the highlighted row) and not A (does nothing on
this menu). This opens a `"<TEAM> LINE EDITOR"` screen showing `Sc1 Line` with its 5
skater slots (LD/RD/LW/C/RW) by name; C again on a highlighted slot opens a `Select
Player`/`Status` sub-screen listing every player at that position with an Ice/Bench
column.

Checked this **immediately after a fresh Controller Setup, with zero game-clock
time elapsed** (to rule out fatigue-substitution or save-state drift): live NYR
`Sc1 Line` read **LD Leetch, RD Zubov, LW Graves, C Messier, RW Larmer** — roster
indices 18/20/8/3/15. Decoding ROM `0x3618` line 0 with the *corrected* team
assignment (NYR, not VAN) gives byte-for-byte the same five values. Exact match,
zero elapsed game time, immediately after a clean savestate reload — as solid a
confirmation as this project has produced. **Line 0 in the 64-byte block is Sc1.**
Re-decoded both tables with corrected team labels for the record — VAN's line 0 is
now Lumme/Brown–Courtnall/Ronning/Bure, the real 1994-95 Canucks top line, which
reads far more sensibly than the mismatched version from the earlier (swapped-team)
decode.

Lines 1-7's exact labels (Sc2/Sc3/Pp1/Pp2/Pk1/Pk2/?) are still unconfirmed — tried
cycling within the Line Editor screen itself (L/R, A, Up) looking for a way to step
to the next line type without backing all the way out, found none. The clustering
pattern noted earlier still holds and reads more sensibly now: NYR lines 0/1/4 share
the Leetch-Graves-Messier core (varying only the RD/RW slot — Zubov vs Beukeboom,
Larmer vs Anderson), while line 3 (Wells/Karpotsev D, Tikkanen-Nemchinov-Noonan
forwards) skews toward energy/checking personnel, consistent with a scoring-lines
vs. PK-unit split. Confirming those labels individually would need re-entering the
Line Editor once per line type from the pause menu (there may be a separate on-field
"select line" control, not yet found) and reading each — mechanical, not blocked on
anything new.

---

## 3. Bug: Smolinski line-editor clone (root-caused, live-confirmed)

**Symptom**: In Boston's Sc1 line, assigning Bryan Smolinski (already at LW) to RW
leaves him listed at *both* LW and RW simultaneously, instead of normally swapping
with whoever was at the target position.

**Root cause**: ROM function `0x095A60` (14 instructions, no sub-calls) implements
the "does this player already exist elsewhere on this line" duplicate check that's
supposed to run before every substitution:

```
095A60  movem.l  a1/a0/d2/d1/d0,-(sp)
095A64  lea      (0x16C,a2),a0        ; a0 = base of this team's line-position table
095A68  move.w   d2,d1
095A6A  andi.w   #-8,d1               ; d1 = (target slot) rounded down to multiple of 8
095A6E  lea      (0,a0,d1.w),a1       ; a1 = base of THIS line's 8-byte block
095A72  moveq    #5,d1
095A74  cmp.b    (1,a1,d1.w),d0b      ; scan offsets a1+6,+5,+4,+3,+2,+1, in that order
095A78  dbeq     d1,095A74            ; stop at first match
095A7C  bne.w    095A86               ; no match anywhere -> skip the swap-back
095A80  move.b   (0,a0,d2.w),(1,a1,d1.w)  ; match found -> swap it with old target occupant
095A86  move.b   d0,(0,a0,d2.w)       ; always: write new player into target slot
095A8A  movem.l  (sp)+,d0-d2/a0-a1
095A8E  rts
```

The scan always visits offset **+6 first**, before any of the five real position
slots. Boston's Sc1 ROM data (`01 12 14 06 03 08 06 00`) has Smolinski's roster
index (`06`) at *both* offset+3 (his real LW slot) and offset+6 (the unlabeled extra
slot) — almost certainly a stale/uncorrected entry from whoever built the roster data
in 1994, likely predating his promotion to the top line. Because +6 is checked before
+3, the loop matches immediately at the wrong slot, "swaps" with it (silently
overwriting that extra slot with the displaced player's index), and never reaches the
real LW slot — which is why LW still shows Smolinski while RW also gets him.

**Scope — is anyone else affected?** We extracted this exact 8-byte block for all
26 teams x 8 lines (208 blocks) and checked whether offset+6 duplicates any of
offsets +1..+5. **Exactly one hit, in the entire game: Boston / Sc1 / LW /
Smolinski.** Every other team's offset+6 holds a different player than any of that
line's five starters, so the scan never finds a false match for them. This is
consistent with a one-off shipped data-entry mistake specific to Boston's roster
table, not a general engine flaw — the swap logic itself is otherwise "working as
designed," just fragile to this exact kind of stale duplicate.

Verified end-to-end live: breakpointed `0x095A60`, single-stepped through the
compare/branch, and confirmed via direct RAM reads (`p/x 0xADDR.b`) that offset+3
(LW) is untouched throughout, offset+6 gets overwritten with the displaced RW
player's index, and offset+5 (RW) receives Smolinski — exactly matching the on-screen
clone.

**Follow-up, suggested by a reader: what does live gameplay actually do with him
once the clone exists?** The question came with real context that matters:
the reader relayed a friend's *first-hand* account of having seen **three
different outcomes** from this exact bug across past play sessions — normal
play, appearing to join mid-shift from the bench, and standing idle near the
opponent's net while the game continues around him. That's eyewitness
testimony of real variance, not three guesses — which means a single
reproduction proving one outcome doesn't settle the question; if anything it
predicts the bug is *state-dependent*, not fixed.

Reproduced the bug fresh this session anyway, as a first data point (Boston
vs. Vancouver, Sc1, substituted Smolinski from LW onto RW via the in-game
Line Editor's "Select Player" sub-menu — confirmed it doesn't exclude a
player already on the line, which is exactly the precondition for this bug)
and started a real game with the corrupted line active. Paused mid-shift and
checked the live Team Roster screen's `Status` column — the same live
indicator already used elsewhere in this document (§6) to distinguish
`Bench` from an active player. **Result for this one reproduction: Smolinski
showed `Status: Ice`**, same as a normally-playing teammate, with `Reg`
(regular-line) reading **`12`** instead of the normal single line number — a
real, live-visible artifact of the corruption, consistent with the
line-appearance-counting logic (the same kind already documented in §7 item
2) tallying him twice because his roster index legitimately occupies two
slots on the one line.

**What this does and doesn't prove.** This is one confirmed data point — the
"normal play" outcome is real and reproducible, not just a hypothesis. It is
*not* proof that the other two reported outcomes don't happen; given the
friend's account, they very plausibly do, under conditions this single
reproduction didn't hit (which stoppage/faceoff the corrupted line first gets
used at, whether Smolinski has puck possession when a shift change fires,
timing relative to a line change, etc. are all untested variables). The
likely underlying mechanism — the game's per-shift lineup logic walking the
line's 5 position slots (LD/RD/LW/C/RW) and instantiating a player for each,
with two slots resolving to the same roster index — is consistent with *any*
of the three outcomes depending on exactly how the engine's shift-change and
possession-handling code reacts to seeing one roster index twice in the same
lineup pass, not just the "two independent copies" explanation floated
earlier. Properly answering "why three different outcomes" needs repeated
reproductions across different in-game moments (start of a shift, mid-shift
after a change, right as he takes possession) and ideally a direct read of
the live on-ice-slot table, not a single pass. Left open in issue #10 with
this fuller context.

**Second independent reproduction, a later session: same outcome again.**
Boston vs. Vancouver, same substitution (Smolinski LW→RW on Sc1 via the
Line Editor), a fresh boot rather than a reused save state. Played roughly
a minute of real game time (idle/autonomous — neither controller was
actively driven) without a goal, then paused and read the Team Roster:
**`Status: Ice`, `Reg` reading `12`** — identical to the first
reproduction. Two independent data points now support "plays normally" as
a real, repeatable outcome, not a fluke of the first attempt's specific
timing. The other two reported behaviors (bench arrival mid-play, corner
celebration after a goal) still weren't caught — this attempt didn't
produce a goal at all, so the "corner celebration" hypothesis specifically
remains completely untested, not just unconfirmed. Still an open item for
whoever picks it up next, but the "normal play" outcome is now on
solid ground rather than a single anecdote.

**Third independent reproduction, genuine CPU-vs-CPU, and this time with a
real goal.** Both prior reproductions used an idle-but-human-assigned
controller (a controller icon parked on a team column but never actually
pressed) — worth distrusting as a full substitute for real play, since an
idle "human" puck-carrier may just coast rather than shoot. This attempt
instead parked *both* controller icons under the Controller Setup screen's
`CPU` column (Boston vs. Edmonton), reproduced the same Sc1 LW→RW
Smolinski substitution, and let the game run autonomously for real. Boston
scored **8:05 into the 1st period, and the Scoring Summary screen credited
it cleanly**: `BOS 20 B. Smolinski`, assisted by `43 A. Iafrate` and
`30 J. Casey` — a normal, correctly-attributed goal scored by the
cloned player himself, not a UI glitch or a phantom entry. Immediately
after, the Team Roster read **`Status: Ice`, `Reg: 12`** — identical to
both earlier reproductions. This is the strongest data point yet for the
"plays completely normally" outcome: not just present and skating, but
actively participating in the scoring play and getting properly credited
for it. The other two friend-reported behaviors (bench arrival mid-play,
corner celebration after a goal) *still* weren't caught, despite this being
the first reproduction to actually produce a goal — no unusual celebration
was visible in the post-goal replay/faceoff transition. Three independent
reproductions across two sessions, two different away opponents (Vancouver,
Edmonton), and now one real goal all agree on the same outcome, which makes
"normal play, including scoring" the well-supported default behavior of
this bug; the other two reported outcomes remain unconfirmed and are either
rarer/state-dependent or specific to conditions not yet hit. Closing issue
#10 on that basis.

Boston went on to win the game 3-2, and the final Scoring Summary made the
point even harder to argue with — **the cloned Smolinski scored twice**,
not once:

```
Per  Time  Tm   Goal/Assist              P/S
 1   8:05  BOS  20 B. Smolinski
                43 A. Iafrate
                30 J. Casey
 1   8:44  EDM  39 D. Weight
                9 S. Corson
 2   0:26  EDM  8 Z. Ciger
                39 D. Weight
                21 I. Kravchuk
 3   5:02  BOS  20 B. Smolinski
 3   7:04  BOS  43 A. Iafrate
```

Both Smolinski goals are clean, normal, individually-attributed entries —
one assisted, one solo — sitting alongside three other perfectly ordinary
goals from other players in the same box score. No full injury occurred
anywhere in this game either (see GitHub issue #9 for that side quest,
narrowed rather than closed — a single ~30-minute game apparently isn't
enough real estate to reliably trigger one).

**Bonus mechanic found while chasing this reproduction: the pause menu's
`EDIT LINES` always opens the away team's (`Team 2`'s) Line Editor,
regardless of which controller — or whether any controller at all — is
assigned to that team.** With both controllers parked under CPU (no
controller-to-team association exists at all in that configuration),
`EDIT LINES` still opened cleanly for whichever team was set as `Team 2` on
the pre-Controller-Setup settings screen. Confirmed by deliberately
swapping which team occupied the `Team 2` slot (first Vancouver, then
Boston) and watching the Line Editor's own team header change to match —
not tied to the controller that paused, a home/away photo side, or any
other candidate. This is the practical reason earlier sessions could only
ever reach the away team's lines from that menu (e.g. the Vancouver
Line Editor opened during the penalty-kill investigation above): it isn't
a controller-focus quirk, it's a fixed away-team default. To edit the
*home* team's lines from this menu, set it as `Team 2` on the settings
screen before starting the game.

---

## 4. Anomaly scan of the player database (roster/jersey data)

With the jersey-number field cracked, we swept all 26 teams for two things: (a)
duplicate jersey numbers within a single team, and (b) exact-duplicate 7-byte
unknown-attribute blocks within a team (which would indicate a copy-pasted stat
line, the same "forgot to change one field" pattern that caused the Smolinski bug).

**No duplicate attribute blocks found** — every player on every roster has a unique
7-byte unknown-attribute value, so that particular bug class doesn't recur elsewhere.

**Three duplicate jersey numbers found**, verified byte-for-byte against raw ROM data
(not a parsing artifact):

| Team | Number | Players |
|---|---|---|
| Los Angeles Kings | #14 | Kevin Todd, Gary Shuchuk |
| Ottawa Senators | #24 | Rob Burakowsky, Steve Konroyd |
| Toronto Maple Leafs | #22 | Ken Baumgartner, Mike Gartner |

Caveat: unlike the Smolinski case, we can't yet tell whether these reflect a genuine
data-entry slip or an accurate mid-season roster/number change (players *can*
legitimately share a number across a season if one left the team and another took
it, or after a trade). Also spotted in passing: Toronto's "Ken Baumgartner" is stored
as `Ken Baumgartnr` — missing the middle "e" — a plain typo in the shipped name data,
unrelated to the jersey question.

**Jersey-as-lookup-key check: no evidence found, reasonably confident but not
exhaustively proven.** Byte-pattern-searched the ROM for every call site of the
confirmed decimal digit-print routine (`0x0007D154`) — 81 distinct sites — and
sampled a cross-section of their immediate context. They're wildly varied and
mostly unrelated to jerseys at all (calendar text like "PLAYOFFS DAY", injury
report text like "Out for..."), confirming this routine is a generic shared
utility, not something that isolates jersey-specific usage by searching around it.
More decisive: every single subsystem mapped this session — the per-line position
table (§2.3), the Team Roster screen's Lines/Rating columns, the Scouting Report's
advantage calculation, the Line Editor's substitution logic (§3) — uses **roster
index** as the internal player identifier, never jersey number. Jersey number
(BCD-encoded, per §2.2) only ever showed up as a displayed text label next to a
name, never as an array index, comparison operand, or lookup key, anywhere we
looked. That's a real, evidence-based pattern, not just an absence of a positive
result — but it's circumstantial (built from what this session happened to trace),
not an exhaustive proof of absence. **Working conclusion**: the 3 duplicate jersey
numbers above are very likely cosmetic/harmless, not a second Smolinski-class bug —
there's no internal mechanism found that would ever collide on them, unlike the
Smolinski bug, which collided on roster index, the value everything actually keys
on.

---

## 5. Hot/cold streaks — confirmed real, mechanism partially traced

**Quick reference — the whole chain, end to end** (narrative and evidence
for each step below):

```
 Console boot
     │
     ▼
 VDP H/V-beam counter read (0x00085D34)  ──▶  seeds a 32-bit LCG
     │                                          at WRAM 0xFFFFCC6A
     │                                          (locked in ONCE per
     │                                          boot — not re-rolled by
     │                                          replaying/reloading)
     ▼
 0x0083E88: loop 416x, each iteration
     RNG(18) - 9   (range -9..+8, signed)
     │
     ▼
 one byte written per player into
 team_struct + 0x1A4 + player_index
 (16 bytes/team, the "modifier table")
     │
     ▼
 0x0A0042/0x0A0672/0x0A0692: sum 13 of the
 16 modifier bytes per player (skip 2 fixed
 offsets — matches "except weight and
 fighting" from a community guide)
     │
     ▼
 bubble-sort all candidates' [index, sum]
 descending
     │
     ├─▶ highest sum  = this game's "hot" player
     └─▶ lowest sum   = this game's "cold" player
              │
              ▼
     name written to 0xFFFFBB62-0xFFFFBB6A,
     shown on the Scouting Report screen
```

The community strategy guides (nhl94.com forum guide, segathon.com) both describe a
"players vary ±10% per game" hot/cold mechanic but explicitly say they can't confirm
whether it's real or "just fluff." We can now confirm **it's real** — there is
dedicated, unambiguous ROM content for it, found by searching for the phrase "hot
streak" in the ROM.

At ROM `0xA0700`-ish there's a full templated intro-script table for the Scouting
Report screen, using single-character tokens as substitution markers, e.g.:

```
For the =, < is on a hot streak, but | is off his game.
For the *, > is on a hot streak, but \ is off his game.
```

(`=`/`*` = home/away team name, `<`/`>` = that team's hot player name this game,
`|`/`\` = that team's cold ("off his game") player name this game — confirmed live:
we saw "For the Rangers, Sergei Zubov is on a hot streak, but Brian Leetch is off his
game," and separately "Pavel Bure is off his game" for Vancouver.) This proves the
game genuinely does randomly designate one hot and one cold skater per team, per
game — it's not fixed ROM data (no player is hard-coded as perpetually hot/cold; the
name is substituted into the template live) and not "just fluff" as the community
suspected.

**What's still open**: the exact selection code. First two attempts (breakpoint-sweep
`0x067000`-`0x07C000`, then `0x09C000`-`0x0A6000` while already sitting on the
screen) failed because cycling matchups with A/C only *redisplays* an
already-made selection — the pick happens once, at the Controller Setup → Scouting
Report transition, which we weren't watching yet.

**Third attempt made real progress.** After identifying and excluding 3 pathologically
hot generic routines (`0x0A1584`, `0x0A15C4`, `0x0A1674` — a tight per-character
text-glyph-draw loop that fires hundreds of times during the credits scroll alone and
made the region untraceable), we re-armed the remaining ~123 breakpoints *before*
Controller Setup, paused auto-continue right at that screen, and single-stepped the
actual transition into Scouting Report. This mapped a real call chain:

```
0x09C9A (dispatcher)
  -> 0x09F590 -> 0x09FFF4 (clr.w $FFFFBB5A — resets a RAM scratch word)
  -> 0x0A0042 -> 0x0A0672 -> 0x0A0692  (loop; a1 holds a fixed ROM pointer
       to 0x16AD26 — a table of small, mostly-sequential 16-bit values,
       e.g. 0,1,1,1,2,3,4,5,1,1,1,6,8,9,9,9,10,11 — looks like a category/
       index lookup table, not yet identified; this loop builds up a small
       RAM buffer around 0xFFFFBB5A-0xFFFFBB70, observed holding values
       like 6, 19, 12, 17 partway through)
  -> 0x09F89A -> 0x09FF08 (separate loop, see below)
```

**Ruled out as a false lead**: `0x09FF08`/`0x0A00F0` loop repeatedly executes
`cmpi.w #$1000, $FFFFD27E.w` / `bgt 0xA026A`. We initially suspected this was a
random-vs-threshold gate for hot/cold eligibility, but traced the compared RAM value
across many iterations and it just decreases slowly (49 → 45 → 44 → ...), nowhere
near the 0x1000 threshold, so the branch never fires in any realistic window — this
looks like an unrelated per-frame background counter (possibly music/sound-driver
timing) that happens to run in the same address range, not the hot/cold gate.

**Mechanism now identified — confirmed live.** Correcting an earlier mistake: the
`0x09FF08`/`0x0A00F0` loop was *not* a dead end, it just needed to be followed
further. `0x0A00F0` is the actual message-template interpreter — it walks the intro
text character by character and switches on exactly the token bytes we found in the
ROM string (`$`,`{`,`}`,`[`,`]`,`<`,`>`,`|`,`\`,`#`,`%`,`=`,`*`,`^`,`;`). (Our first
attempt to find this via static analysis searched for `CMPI.B #imm,Dn` opcode
encoding and found nothing — the real code uses `CMPI.B #imm,(A2)`, a different
opcode, which is why the search missed it.)

The four tokens we care about each call a small, near-identical function:

| Token | Meaning | Function | Reads selector at | Reads candidate table at | Team struct |
|---|---|---|---|---|---|
| `<` | home hot name | `0x0A055A` | `0xFFFFBB5C` | `0xFFFFBB64` | `-0x3D78` |
| `>` | away hot name | `0x0A0588` | `0xFFFFBB5A` | `0xFFFFBB62` | `-0x3A12` |
| `\|` | home cold name | `0x0A05B6` | `0xFFFFBB60` | `0xFFFFBB68` | `-0x3D78` |
| `\` | away cold name | `0x0A05E4` | `0xFFFFBB5E` | `0xFFFFBB66` | `-0x3A12` |

Each reads a "selector" word, doubles it (word-array indexing), and uses it as an
offset into a small candidate table (`0xFFFFBB62`-`0xFFFFBB6A`, i.e. all four
functions read from the *same* 4-word table, just starting 2 bytes apart from each
other) to get the final player index — same `-1` storage convention as the sort
routine below (the stored value is the real roster index minus 1).

**Verified live against ground truth.** With selector = 0 (its value at the moment we
inspected it), the home-hot table read gives `0x13` (19) → real index 20 = **Zubov**,
and the home-cold table read gives `0x11` (17) → real index 18 = **Leetch** — both
exactly matching what we independently saw rendered on screen ("Sergei Zubov is on a
hot streak, but Brian Leetch is off his game"). This is about as close to proof as
static+live tracing gets.

**How the candidate table gets filled — the rating/sort formula (also answers §6).**
Traced `0x0A0042` (called from `0x0A0006`, part of the same setup sequence) in detail:
for up to 6 candidate players it sums 13 of the 16 bytes in a *separate*, more
detailed per-player attribute record (a table at ROM `~0x207C28`, 130 bytes/record —
distinct from the smaller name-record table in §2.2), explicitly skipping 2 fixed
byte offsets in each 16-byte block (loop counter values 9 and 13 are excluded from
the running sum) — a strong match for the community guide's "attributes are summed,
except weight and fighting." It then bubble-sorts the 6 `[index, sum]` pairs
descending by sum. The highest-sum player is the natural "hot" pick, the lowest-sum
the "cold" pick — consistent with everything above.

One instance we single-stepped through resolved its per-team candidate-table base
address using an index value (23) that computed a ROM address (`0x2087D6`) beyond the
2MB ROM (confirmed against the raw file and cross-checked live — the emulator returned
open-bus-looking `0xFFxx` garbage there). We're not fully certain whether that was a
genuinely invalid edge case in this specific call, or whether we misjudged which
register/offset holds the "team select" value — it didn't end up mattering for the
final answer since the *candidate table* the hot/cold functions actually read
(`0xFFFFBB62`-`0xFFFFBB6A`) checked out correctly against known results regardless.

**Likely found the random component.** Set a single clean breakpoint at `0x0A0042`
and caught it firing 3+ times during the Controller Setup → Scouting Report
transition, each time with a different team-struct pointer in `A0`. The attribute
source it reads from (`A2 = A0+0x1A4`, per-team RAM, 16 bytes/player) was **all
zero** on the first two calls — meaning this RAM area isn't populated yet that
early — but by the third call it held small **signed** byte values (observed range
roughly -9 to +8), which is a different character entirely from a 0-99 rating scale.
Something between the 2nd and 3rd call populates it; we have not yet identified that
specific populating code.

Applying the exact same sum formula (11 of the 16 bytes per player, skipping relative
offsets 9 and 13, same as §5/§6) to this table for our two known hot/cold picks:

- Messier (NYR, real roster index 3, this game's **hot** pick): sum = **+7**
- Leetch (NYR, real roster index 18, this game's **cold** pick): sum = **-12**

That's a large, correctly-signed gap (hot player positive, cold player strongly
negative) using the *same* summing logic that selects hot/cold in the first place —
strong circumstantial evidence this table *is* the per-game random variance the
community guides describe ("attributes vary ±10% each game... a little bit of
randomness to each one, from -3 to +2" — small signed per-attribute deltas is exactly
this shape).

**Confirmed randomized — and found exactly when it gets locked in.** Ran a proper
test: captured Messier's and Leetch's modifier bytes, then reproduced the identical
matchup (NYR vs Vancouver, same players) three more times under increasingly
different conditions —

1. Reloaded the same Controller-Setup savestate, waited a different amount of time
   before pressing Start: **identical bytes**.
2. Fresh boot from power-on (not from savestate), skipped the credits at a
   completely different real-world pace than any previous run: **identical bytes**.
3. Same fresh boot, but with the persistent `save.sram` file removed first:
   **completely different bytes**, both for Messier and Leetch.

That's conclusive: the modifier values are **not** re-rolled by input timing, by
reloading a state, or by simply replaying — they're locked in once per boot, and the
lock-in draws on something tied to the SRAM/backup-RAM area (real hardware would
likely seed this from something like a free-running counter read once at boot,
persisted from then on for that session — consistent with a `Loaded SRAM from...`
line always appearing in the log on normal boots). This fully validates the original
question this whole side-quest was chasing: hot/cold **is** genuinely random from the
player's perspective (every fresh power-on gives different modifiers, and therefore
plausibly different hot/cold picks), while also explaining why naive "does it change
if I just wait longer" testing would (wrongly) suggest otherwise — the randomness is
resolved once, early, and then stable for the rest of that session, not re-rolled
per-screen or per-attempt. `save.sram` was restored to its original state afterward
so `controller_setup.state` remains valid for future work.

Still open: whether hot/cold changes a player's effective in-game rating during
actual play, or is purely narrative/display.

**Follow-up: traced the seeding code, found the mechanism is more layered than
originally modeled.** Set a breakpoint directly on `0x0A0042` and single-stepped
(not batch-continued, to avoid missing hits) through the *first* home-team call from
`0x9FFF4`. Confirmed definitively: with `A2` still zero at that point, all 6
candidates summed to `0`, no swaps occurred in the sort, and `0x0A0672` (which only
ever copies exactly **one** candidate — the DBF loop count is hard-coded to run once,
it is not a "pick the best" search itself, sorting order is what makes position 0 the
right one) wrote `0x0000` to `0xFFFFBB64` — i.e. this very first pass produces a
placeholder/meaningless result (a goalie's index), not Zubov. Confirmed this by
reading `0xFFFFBB64` after *every single instruction* through the rest of that call
and into the start of the away-team call — it stayed `0` throughout.

Continuing to trace forward, `0x0A0672` (home slot) gets hit **again**, later, this
time with `A2` populated and the 6 candidates carrying real signed sums (one of them
being Messier at `+7`, matching §5's earlier finding exactly) — but *this* pass's
own 6-candidate pool didn't include Zubov's stored index either, and by the time we
checked again after that call fully resolved, `0xFFFFBB64` had already become `0x13`
(19, Zubov) as expected. In other words: **`0xFFFFBB62`-`0xFFFFBB6A` is reused
scratch memory for more than one category's "best/worst of N" computation** (very
likely once per Scouting Report category — Overall, hot/cold, and each position
matchup all appear to route through the same `0x0A0042`/`0x0A0672`/`0x0A0692`
machinery), not a dedicated hot/cold-only table computed exactly once. The
end-visible result (Zubov hot, Leetch cold) is real and has now been reproduced and
directly observed forming correctly multiple times.

**Resolved — it's not "many categories," it's the same function called twice.**
Went static instead of continuing to single-step: dumped `0x09F590` (the caller of
the hot/cold setup) in full. It calls `0x09FFF4` (hot/cold setup) **twice** — once
immediately (line `9F596`, before any per-team data exists — this is the
placeholder/zero-data pass), then again at line `9F618`, **after** two calls to a
function at `0x0083E88` (once per team). That second call is what makes the
difference: `0x0083E88` is the code that populates `team_struct+0x1A4` in the first
place. So there's no mystery "third category" — it's the exact same hot/cold-setup
function, deliberately invoked twice, with the real population step sandwiched in
between.

**Bonus: `0x0083E88` turned out to be the full random-generation chain**, closing out
the *other* open item from this list in the same pass:

```
0083E88  loops 416 times (0x19F down to 0), each iteration:
             D0 = 9
             jsr 0x0007C62E          ; returns RNG(18) - 9  (range -9..+8, matches observed data exactly)
             write result byte into team_struct[0x1A4 + loop_index]

0007C62E  D0' = RNG(D0*2) - D0       ; i.e. RNG(18) - 9
0007C63A  32-bit LCG core:
             seed(0xFFFFCC6A, regular work RAM, NOT SRAM) = seed * CONST + 1  (mod 2^32)
             result = ((seed >> 8) * range) >> 16          ; scaled to [0, range)
```

And the **seed's initial value** — the actual entropy source — is set by:

```
00085D34  move.w (0x00C00008).l,(0xffffcc6a).w
00085D3C  move.w (0x00C00008).l,(0xffffcc6c).w
```

(and a second, near-identical copy at `0x000A12AE`/`0x000A12B6`, presumably a
different re-init path). `0x00C00008` is the Genesis VDP's **H/V beam-position
counter** — a free-running hardware register tied to real video-scan timing. Reading
it once, at a boot-time point whose *exact instruction count* varies with the boot
path taken, is the classic, well-documented Genesis-era trick for a "random-enough"
seed. This is a complete, satisfying explanation for every earlier test result:

- Reloading the same savestate with a different wait: no effect, because the counter
  was already sampled (and the seed already committed to RAM) long before the
  savestate was even captured — nothing after that point can retroactively change it.
- Fresh boot, different real-world pacing, same SRAM: no effect, because the game's
  own boot code between power-on and the sampling point is fixed-length — how long
  *we* waited before pressing Start doesn't change the CPU's cycle-exact path through
  that code.
- Fresh boot, SRAM removed: **large effect**, because the boot code path measurably
  changes when there's no save data to load (we directly observed a different splash
  screen appear only in that case) — a different instruction count before the sample
  point means the free-running counter gets caught at a different phase, producing a
  different seed.

This fully closes out both remaining §5/§6 threads: the per-game randomness is real,
now traced to its exact hardware source, and the modifier table's shape/range
(`RNG(18)-9`) is now an exact formula rather than an observed pattern.

**Workflow note for future sessions**: getting through NHL '95's ~4-minute mandatory
credits scroll before every test was the single biggest time cost in this
investigation. Fixed by capturing a BlastEm save state right at the Controller Setup
screen (`~/controller_setup.state` on the VM) and launching with
`blastem -s controller_setup.state -d ROM`, which boots directly into the debugger at
that exact point in a few seconds. (Needed two config fixes to get there: BlastEm's
save-state keybind must be the literal backtick character in `blastem.cfg`, not the
word "grave"; and a custom `blastem.cfg` fully replaces the default bindings rather
than merging, so it must explicitly include every binding you need, not just the ones
you're changing.)

**Issue #1 closed: the hot/cold modifier mechanism is now directly, cleanly confirmed
to apply additively to live-displayed named stats — via a fully self-consistent,
same-boot test, not a stale residual comparison.** The earlier "shortcut" attempt
(§7 item 6's writeup) tested the *original* residual-measurement boot but guessed
at the team-struct base address and got a genuinely mixed result. Redone properly this
session with the address-finding method the issue called for, on a **fresh boot**
(so the specific old residual numbers, +9.7/+11.3, belong to different, no-longer-
reproducible RNG state and can't be reused directly — but the *mechanism* can be
tested self-consistently against this boot's own numbers instead):

- Found Vancouver's live team-struct base with a verified call chain, not a guess:
  breakpointed `0x0A0042` (the modifier-sum function) and, after ruling out a
  same-address false-positive caller (`0x0A0024`, fires on unrelated button-press
  handling with a *stable* `A0` — a real gotcha, cost real time before checking `bt`
  caught it), confirmed the real setup-sequence caller is `0x0A0006`. Breakpointing
  `0x0A0006` directly and reading `A0` at the hit gave `0xFFFFC288` for Vancouver —
  independently cross-checked against the Scouting Report's own text for this exact
  matchup ("Cliff Ronning is off his game"), which matches the sign of the byte read
  below. This is the first time this project has confirmed a team-struct base via the
  fully-verified method rather than reusing an address borrowed from an unrelated call
  site (score/clock's `0xFFFFC5EE`/`0xFFFFC288`, only ever confirmed as *this-session*
  home/away slots for a different purpose).
- Read the modifier bytes directly: `team_struct+0x1A4+3` (Ronning) = `0xFC` = **-4**;
  `team_struct+0x1A4+7` (Courtnall) = `0x04` = **+4** (roster indices straight from
  `full_roster_database.json`, the same field independently confirmed correct via
  Messier=3/Leetch=18 earlier in this section).
- Computed **boot-independent** predicted values from the multivariate models
  (`docs/external_sources/multivariate_stat_models.json`, fixed ROM nibbles only, no
  RNG involved) for the same two (player, stat) pairs the original residuals flagged:
  Ronning's Top Speed = **85.3**, Courtnall's Agility = **85.7**.
  Read this boot's own live values off the Team Roster screen: Ronning's Speed =
  **81**, Courtnall's Agility = **98**.

**The addressing chain, visually:**

```
Vancouver's team_struct base: 0xFFFFC288
(confirmed live via the 0x0A0006 -> 0x0A0042 call chain,
cross-checked against the on-screen "Ronning is off his game")
    │
    │  + 0x1A4  (start of the modifier table)
    ▼
16-byte modifier table — one signed byte (-9..+8)
per roster index, written once per boot by 0x0083E88
    │
    ├── + roster_index 3 (Ronning)
    │       0xFFFFC42F = 0xFC = -4
    │       (matches "Cliff Ronning is off his game" on screen)
    │
    └── + roster_index 7 (Courtnall)
            0xFFFFC433 = 0x04 = +4
            (matches Courtnall's positive Agility residual)
```

- **Ronning: predicted + modifier = 85.3 + (-4) = 81.3, live = 81 — an exact match.**
  This is a clean, decisive, same-boot confirmation that the hot/cold modifier is
  applied additively to the displayed named stat, not just correlated with it.
- **Courtnall: predicted + modifier = 85.7 + 4 = 89.7, live = 98 — an 8-point miss.**
  Rather than contradicting the model, this lands on a different, already-suspected
  effect: 98 sits right at the edge of the 0-99 display range, and a "linear fit
  under-predicts near the ceiling" clamp/saturation pattern was already flagged
  earlier in this document (§6) from the CSV-comparison outliers, without a live
  example to confirm it. Courtnall's Agility is that live example — the additive
  model likely still holds underneath, but the displayed value gets clamped (or the
  true relationship saturates) before it can show the full predicted+modifier total.

Net effect: the mechanism question is answered (hot/cold modifiers are a real,
additive contribution to live named stats, confirmed on a clean mid-range case), and
the two original outlier residuals are now understood as **two different effects**
rather than one — Ronning-style cases are explainable by the modifier directly,
Courtnall-style cases near the ceiling need the clamp/saturation behavior accounted
for too. Closing GitHub issue #1 on this basis; the exact clamp formula (if the
engine even models it explicitly, versus just truncating a computed value into a
byte) is a smaller, separate loose end, not blocking.

---

## 6. Player rating bytes — jersey number solved, Overall Rating formula solved and ROM-confirmed (exact weights + opcode still open)

**Quick reference — every nibble of the 14-nibble attribute block, final
state.** The rest of this section is the narrative of how each row below
was found (several were wrong on the first pass and corrected on a later
one — kept in for transparency, see the "Live validation" and "Major
breakthrough" subsections below for the full story). If you just want the
answer:

| nibble | stat (skaters) | stat (goalies) | in Overall Rating? | how confirmed |
|---|---|---|---|---|
| 0 | Weight (physical, not 0-99) | Weight | no | ROM bytecode table |
| 1 | Agility | Agility | **yes** | statistical + ROM bytecode |
| 2 | Top Speed | Speed | **yes** | statistical + ROM bytecode |
| 3 | Off. Awareness | *(n/a)* | **yes** | statistical + ROM bytecode |
| 4 | Def. Awareness | Def. Awareness | **yes** | statistical + ROM bytecode + live (goalies) |
| 5 | Shot Power | Puck Control | **yes** | statistical + ROM bytecode + live (goalies) |
| 6 | Checking | *(n/a)* | **yes** | statistical + ROM bytecode |
| 7 | Handed (categorical) | Glove Hand (categorical) | no | ROM bytecode + live (goalies) |
| 8 | Stick Handling | *(n/a)* | **yes** | statistical + ROM bytecode |
| 9 | Shot Accuracy | *(n/a)* | **yes** | statistical + ROM bytecode |
| 10 | Endurance | Stick Right | **yes** | statistical + ROM bytecode |
| 11 | *(unused for skaters)* | Stick Left | no (skaters) | live only — goalie-only stat |
| 12 | Pass Accuracy | Glove Right | **yes** | statistical + ROM bytecode |
| 13 | Aggressiveness | Glove Left | no | statistical + ROM bytecode |

*"In Overall Rating?" reflects the skater formula (`OR_WEIGHTS` in
`tools/build_rom_verified_stats.py`) — the goalie Overall formula uses a
different, only partially-confirmed subset, see the "Nibble 11 resolved"
and "Major breakthrough" subsections.*

---

Cross-referenced the displayed position "advantage" numbers against known players'
raw attribute bytes, live: on the Scouting Report screen, Vancouver's Cliff Ronning
showed `72` and NY Rangers' Mark Messier showed `79` for the Center matchup. Neither
number appears as a raw byte (decimal or BCD) anywhere in either player's stored
7-byte unknown-attribute block (Ronning: `55 54 32 19 c3 51 41`; Messier:
`95 44 33 49 93 42 53`) — confirming the displayed number is **computed**, not a
single stored rating, from the small name-record table in §2.2.

**Partially resolved — the formula is real, but this specific value only accounts
for part of it.** Set a clean breakpoint at `0x0A0042` and traced 3+ live invocations
during the actual Controller Setup → Scouting Report transition for this exact
matchup. The per-team candidate-index table it reads from (ROM base `0x207C28`)
turned out to read as open-bus garbage in this emulator regardless of address probed
(same `0xFFxx`-ish pattern at every offset we checked) — so that specific lookup path
looks unreliable to use for verification, at least as we traced it. However, the
*attribute sum itself*, computed from the separate per-team RAM table at
`A0(team struct)+0x1A4`, gave real, structured (if small and signed) data — see §5.
Summing the same 11 bytes for Messier (this matchup's Center, shown as `79`) gives
`+7`, not `79` — so this RAM table is clearly a *component* of the final number
(very likely the random per-game modifier, per §5), not the whole thing by itself.
We have not yet located the separate **base rating** table that this modifier
presumably adds to in order to produce the final displayed `79`/`72` — that would be
the base-attribute source described by the community guides (small integers,
multiplied by 5). See §5 for the full trace and the Messier/Leetch modifier-sum
comparison.

**Follow-up session: the Scouting Report screen is the same hot/cold system,
confirmed visually — but the base-rating source is still not found, and three
concrete storage hypotheses are now ruled out.** Live-verified that the `COLD`/`HOT`
badge shown on this exact screen (e.g. Vancouver's Pavel Bure tagged `COLD`,
displayed `93`) is the same mechanic traced in §5 — the screen that sparked this
whole sub-investigation is a direct visual readout of the RNG chain, which is worth
knowing on its own. Chasing the actual render pipeline for the big number
(`0x0009FBE2`, the function driving this screen) revealed it's a **bytecode-style
widget interpreter**: calls like `0x0007C810`/`0x0007C6D4` read their own return
address off the stack to find an inline parameter block placed immediately after
their own `jsr`, consume it, then patch the stack's return address before `rts` so
execution resumes *past* the data — not at the next instruction. This is why linear
static disassembly of this function kept producing nonsense (`move.l -(A0),D0`
repeating) right after each call site: those bytes are legitimately data, not
misdisassembled code. Practical effect: this screen can't be fully understood by
static analysis alone; it requires live tracing, and even that is noisy because the
interpreter reuses the same generic subroutines (e.g. `0x0007D154`, a real,
confirmed decimal-to-ASCII digit converter) for many unrelated on-screen numbers, so
breaking inside a shared subroutine doesn't tell you *which* caller/value you've
caught without also checking the call site's return address (`bt`).

Three specific hypotheses for where the final number lives, tested and ruled out:
- **Not a stored byte in the live WRAM HOME/AWAY team-struct region.** Captured a
  live matchup change (Center `Ronning 72 / Messier 79` → `right forward`
  `Bure 93 (COLD) / Larmer 83`) and byte-scanned ~256 bytes around both team struct
  bases (`0xFFFFC280`–`0xFFFFC2FF`, `0xFFFFC5E0`–`0xFFFFC65F`). Found exactly one
  coincidental match (`0xFFFFC60E == 0x4F == 79`) that turned out to be **static** —
  it stayed `79` across unrelated categories instead of tracking the visible number,
  and `93`/`83` didn't appear anywhere in either region for the Bure/Larmer screen.
  Ruled out as the storage location.
- **Not a single byte in the compact ROM player record.** Read the raw ROM bytes
  around Messier's (`0x3684`) and Ronning's (`0x5066`) name records directly from the
  `.gen` file — confirmed the record layout (`[00][length][name][jersey BCD][7-byte
  attr block]`) is exactly as documented in §2.2, but neither `72` nor `79` appears
  anywhere in a 64-byte window around either player's record.
- **Not a simple nibble-sum of the 7-byte attribute block**, with or without the
  first (duplicate-of-`unknown1`) byte included, across all 4 known data points
  (Messier 79/mod `+7`, Ronning 72, Bure 93/`COLD`, Larmer 83) — no consistent
  offset between any nibble-sum variant and the displayed/estimated base number.

**Net effect:** the earlier "Messier's base might just be 72, same as Ronning's
displayed total" coincidence remains unconfirmed and is now weaker, not stronger —
if it were that simple it likely would have shown up in one of the checks above.
A fourth hypothesis is now also closed: the `A0≈0x3618`/`0x4FFA` ROM
pointer-dereference from `0x0009FE56` (flagged as "still unexplored" in the prior
pass through this section) turned out to be the **same per-line position table from
§2.3** — confirmed `A0` is constant across categories (not per-position as hoped),
and the byte it reads is a *roster index* (see §2.3's independent-confirmation
note), not an attribute or rating. That whole code path computes only the small
"advantage" arrow, not the displayed number — a real, useful cross-reference for
§2.3, but a dead end for this specific question.

Four storage/computation hypotheses tried, four dead ends, all with concrete
evidence rather than guesswork. That's a genuine "escalate layers" signal: the next
step, if resumed, should be VDP/tile-level tracing (watching what tile writes land
in the exact screen cells under each player's photo) rather than any further
WRAM/ROM byte-scanning or generic-subroutine breakpoints — that whole layer has now
been tried from several angles and consistently comes up empty.

**Breakthrough via external documentation, not more tracing: the number is the
player's "Overall Rating" stat, confirmed by an exact live cross-screen match.**
Consulted Sega Retro's NHL 95 page (a developer-sourced UI/mechanics writeup, not a
reverse-engineering source) for context and it directly named several things we'd
independently found or were still chasing:
- Confirms the hot/cold mechanic from §5 by name and gives the actual magnitude:
  streaks "affect performance in the game by ±10-30%" — a percentage swing, not a
  flat additive amount, which reframes how the §5 modifier likely combines with the
  base number (see below).
- Confirms "Edit Lines... there are seven lines" — matches the 7-entry `Sc1/Sc2/
  Chk/PP1/PP2/PK1/PK2` label table found in ROM at `0x8A02C` (see §2.3/§7#2) and
  explains the 8th data block's absence from the UI (only 7 are user-facing).
- Documents a **Team Roster** screen (pre-game menu → `Left` to the `INFO` tab →
  `Down` to `Team Roster` → `C`) showing, per line player: "status..., **overall
  rating**, energy level, agility, speed, handedness, offensive awareness, defensive
  awareness, shot power, shot accuracy, pass accuracy, stick handling, weight,
  endurance, aggressiveness, and checking ability" — 14 named attributes, matching
  our 14-nibble (7-byte) unknown attribute block almost exactly in count. Likely the
  names for those still-undecoded nibbles, pending order confirmation.

Reached that Team Roster screen live (Rangers, `Offense` category, `Overall` stat —
cycle position category with `C`, cycle stat with `Left`/`Right`, switch teams with
`A`): **Mark Messier's Overall Rating reads `79`** — an exact match for the number
shown on the Scouting Report screen for the same player, same game session. This
directly answers the conceptual question this whole section has been chasing: the
Scouting Report's big number *is* the player's Overall Rating stat, not some other
composite. Also captured (same screen, `Defense` category): Kovalev 82, Nemchinov
73, MacTavish 65, Olczyk 60, and Vancouver's Ronning 72 (already known) — a clean,
externally-labeled set of six data points.

Tested whether **Overall Rating is a simple sum of the 14 attribute nibbles** —
ruled out: Ronning and MacTavish have the *same* nibble-sum (60) but different
Overall Ratings (72 vs. 65), so any real formula must weight specific attributes
differently (consistent with "Overall" being a genuine weighted composite of named
stats like speed/shooting/checking, not a flat total) — a real formula reversal
needs to know which nibble is which named attribute, not just guess-and-sum.

Found the likely render call site live: breakpointed the confirmed digit-print
routine (`0x0007D154`) while this Team Roster screen redrew after a category
switch, and got a clean first hit — `D0 = 0x51 = 81`, called from `0x00085627`
(`jsr 0x0007D154`, itself reached via `0x000854B6: jmp (a0)`) — very plausibly
Brian Leetch's Overall Rating (81 fits an elite, Norris-caliber defenseman).
Follow-up hits in the same batch were **not** trustworthy: one showed a mid-loop
step (`7D190: bne`) instead of a fresh breakpoint hit, the exact batched-`c`-race
symptom already documented in `CLAUDE.md` — repeated here despite the warning, so
worth restating: this needs single, verified `c`/`n` steps to redo cleanly, not
another batch. Static disassembly around `0x00085627` hit the same "no function,
misaligned data" wall as everywhere else in this ROM's UI-widget code, so the exact
computation is still unconfirmed — but the *identity* of the number (Overall
Rating) is now settled, which was the actual open question, independent of exactly
where/how it's computed.

**Follow-up: re-traced the correct call site carefully, confirmed it's a genuine
bytecode-interpreter handler, still didn't crack the source.** The address in the
paragraph above had a typo — the real call site is `0x0008562C`, not `0x00085627`
(off by 5 bytes; setting a breakpoint at the wrong address silently never fires,
which cost real time before the mistake was caught). With the correct address,
got a clean, unambiguous catch: `D0 = 0x4D = 77` at the exact moment the Team
Roster screen was mid-render on the Goalies/Overall view — an exact match for
Mike Richter's Overall rating, caught with the screen visibly still blank below
the header (i.e., genuinely mid-draw, not a stale read).

Full register dump at the breakpoint: `A2`/`A3 = 0xFFFFC288` (the HOME team
struct base referenced throughout this document), `A4 = 0xFFFFC43C` (struct
base + `0x1B4`, not previously explored), `A1 = 0xFFFFBBBC` (near the §5
hot/cold candidate-table region), `A0 = 0x85604` (a nearby ROM address, likely
handler-local parameter bytes). Checked the raw bytes at and around every one
of these — **none contain `0x4D` (77) directly**, ruling out a simple
"D0 is just loaded from `*A4`" (or `*A1`, or `*A0`) hypothesis. `bt` shows the
real caller is `0x000854B6: jmp (a0)` — a **computed jump**, not a normal
`bsr`/`jsr` — confirming `0x8562C` is one handler in a genuine bytecode/jump-table
interpreter, the same architecture already found driving the Scouting Report
screen (§6, `0x0009FBE2`). Static disassembly forward from `0x8562C` itself
works fine (`jsr 0x7D154` → `jsr 0x7C6E6` → `jsr 0x7C810` → data), matching that
known pattern exactly, but disassembling *backward* from it hits the same
"misaligned/no function" wall as everywhere else in this interpreter's code —
because there likely isn't a conventional "function start" to find; execution
arrives via the dispatch table, not a call chain a linear disassembler can
follow.

**Honest assessment**: this is now the *second* independent screen (Scouting
Report, and now Team Roster) where chasing the exact render computation runs
into the same custom-bytecode-interpreter wall, each time after real, genuine
progress (finding the call site, ruling out direct-memory-read hypotheses).
That's a strong, repeated signal rather than a one-off: fully cracking the
Overall Rating formula requires either interpreting this bytecode VM properly
(tracing the dispatch loop itself, from wherever it reads the "which handler"
index, not just the handler it lands on) or the VDP/tile-level approach flagged
earlier — both are genuinely bigger, dedicated efforts, not a quick continuation
of what's already been tried. Recommend treating this as its own scoped
follow-up rather than more ad-hoc live tracing.

**Follow-up session: cracked the dispatch/indexing mechanism itself — the
specific gap flagged above — using the new debugger-level input-injection
technique (see CLAUDE.md) to reach the Scouting Report screen and single-step
through a live category transition (team `Overall` → the `Center` position
matchup) without fighting blind input.** Breakpointed the known re-entry point
`0x0009FBE2` and caught a clean hit via `bt`: called from `0x0009F97C` ←
`0x0009F8F4` ← `0x0009C9A` (a normal `bsr`/`jsr` chain this time, not a
computed `jmp (a0)`). At entry, `D0 = $FFFFD262` = `6` — this WRAM word is the
**current category/state index** driving the whole screen. Single-stepping
(carefully, one verified `n` at a time — batching this raced ahead and
silently skipped the very hit being chased, the exact `CLAUDE.md` gotcha)
revealed the actual dispatch primitive at `0x0009FCB6`-`0x0009FCC8`: a classic
**variable-length-record skip loop** — `A1` seeded to a table base
(`$0009FDEC` in this instance), then `dbf D0,...` repeatedly does
`add.w (A1),A1`, i.e. each record's own leading word is its length in bytes,
and the loop advances `A1` past `D0+1` records to land on the one the current
index selects. This is a generic list-walker, reused throughout the
interpreter for different tables — this is *the* answer to "where does the
interpreter get its handler index," independent of which specific table is
being walked at any given call site.

For this specific call, the table at `$0009FDEC` turned out to be fully
static and readable straight from the ROM file (confirmed offline, no further
live tracing needed): six fixed `0x12`-byte (2-byte length + 16-byte ASCII)
records — `"center"`, `"left forward"`, `"right forward"`,
`"left defenseman"`, `"right defenseman"`, `"goalie"` — obviously the Scouting
Report's six position-matchup category labels. `D0=6` walks *past all six*,
landing exactly at `$0009FE58`, which is where real 68k code resumes (the
`jsr $0007C6D4` widget-interpreter call already known from earlier in this
section) — i.e. index `6` isn't "the goalie label," it's "skip the whole
label table, we're not on a named-position category" (matches the on-screen
state at the moment of the catch: mid-transition into a per-player spotlight
segment, not one of the six position matchups).

**Net effect**: the dispatch *mechanism* (index variable, generic skip-loop,
length-prefixed record format) is now a confirmed, reusable fact about this
interpreter, and a genuinely new ROM data table (the six position-label
strings at `$0009FDEC`) is fully solved as a side effect. The Overall Rating
*number*'s own computation is still not found — this trace explains how the
interpreter picks *which* on-screen category/label to show, not how the
`72`/`79`-style numeric values are computed once a category is selected — but
this closes real ground on the recommendation above ("tracing the dispatch
loop itself") and gives a concrete, working method (breakpoint the known
re-entry point, catch `bt` + the index register, then either single-step the
skip-loop live or — much faster — replicate it statically against the ROM
file in Python once the table base is known) to keep pushing the same way on
the *next* handler a given index resolves to, rather than starting the next
session's tracing from scratch.

**Same-session continuation: found the exact call site where the Scouting
Report hands its rating number to the digit-print routine, and narrowed down
*which* of five chained interpreter primitives actually computes it.**
Navigated live to the `Center` matchup (Ronning/Messier) and breakpointed the
confirmed digit-print routine `0x0007D154` (already known from the Team
Roster screen's `0x0008562C` call site — this is the Scouting Report's own,
previously unknown, equivalent). Got a clean hit: **`D0 = 0x4F = 79`**, an
exact match for Messier's Overall Rating, called from **`0x0009FD6A`**. `bt`
confirms this is reached through the same `0x9FBE2` → `0x9F97C` → `0x9F8F4`/
`0x9F8CE` → `0x9C9A` chain as the dispatch trace above.

Disassembling `0x0009FCCC`–`0x0009FD62` (between the skip-loop's exit and the
digit-print call) shows the interpreter executing a **sequence of five
different bytecode primitives in a row**, each consuming its own inline
parameter block immediately following its own `jsr` (the same
read-return-address/patch-it-back trick documented earlier in this section) —
`0x0007C6D4`, `0x0007C6E6`, `0x0007C810`, `0x0007CF16`, `0x0007D258` — before
falling into `move.w D0,($FFFFD26A).w` (caching the value to WRAM) and then
`jsr $0007D154`. This is a genuine bytecode *program*, not a single opaque
call — a clearer structural picture than previously documented.

Breakpointed all five primitives plus the digit-print routine and caught a
**second, independent data point on the same trace**: the `Goalie` matchup
(Vancouver's Kirk McLean `70` vs. NY Rangers' Mike Richter `77` — the `77`
independently re-confirms the exact value this project already found for
Richter via the Team Roster screen, now cross-checked on a second screen).
**`D0` was already `0x4D` = `77` at the entry to the *third* primitive,
`0x0007C810`** — i.e. before that call and everything after it even runs.
Since the loop-counter left in `D0` right after the skip-loop (`dbf`) exits is
not `77`/`79`, the actual computation must happen **inside the first or
second primitive specifically — `0x0007C6D4` or `0x0007C6E6`** — not in the
three primitives that follow, and not in the digit-print routine itself
(confirming, again, that `0x7D154` is purely a display formatter, consistent
with every earlier session's finding about it). This cuts the search space
for the real formula from "five unknown primitives plus the interpreter
dispatch" down to two specific, named ROM addresses.

**Recommended next step, concretely scoped**: repeat this exact live setup
(breakpoints at `0x7A58A` for navigation, `0x9FBE2` for the render re-entry,
and — this time — `0x7C6D4` and `0x7C6E6` specifically) on a fresh matchup,
and check `D0` (and the inline parameter bytes each primitive consumes,
readable directly from ROM right after its `jsr`) at the entry *and* exit of
each of those two calls to see which one changes `D0` from something else
into the final rating value. That single register-state check is likely
enough to identify the exact computation without needing to fully reverse
either primitive's general-purpose behavior.

**Same-session follow-up: ran exactly that check, using the new
`tools/nhl95ctl.py` live-debugger controller (see CLAUDE.md) instead of
manual tmux choreography — first real validation that the tool holds up for
actual tracing work, not just navigation.** Breakpointed `0x9FCCC` (the
`0x7C6D4` call site) and used `n` (step-over-calls) to check `D0` before and
after each primitive in turn, on the **team-level `Overall` widget**
(Vancouver `75` / NY Rangers `79` — the same numbers as the very first
example in this section, but this is the team logo+number box, not the
player-matchup box; a related but distinct render from the `Center`
Ronning/Messier trace above). Confirmed **`D0` is unchanged (`$FFFF`)
across all of primitive 1 (`0x7C6D4`) *and* primitive 2 (`0x7C6E6`)** —
neither touches it. Between primitive 2 and primitive 3, genuine
non-opaque, directly-disassemblable code runs (not another inline-data
primitive call): sets `$FFFFAC42`/`$FFFFAC48` (`24`/`2` — plausibly VDP/DMA
or timing parameters, not investigated further), loads `A2 = $FFFFC288`
(the already-known HOME team struct base), loads `D4` from a ROM pointer at
`0x00085846` (an unexplored table, likely per-category), checks a flag at
`$FFFFD274`, then **`move.w $FFFFD266.w,D0`** — this is where `D0` actually
gets a new value for the first time, straight from WRAM, no computation
visible in this stretch of code.

The value: **`D0 = 7` on the first team-widget iteration of this loop, `D0 =
14` on the second (Vancouver → NY Rangers)** — incrementing by exactly `7`,
matching the *already-known* 7-byte per-player attribute-block stride from
earlier in this section (Messier's block, Ronning's block, etc. are each 7
bytes). Strong circumstantial evidence `$FFFFD266` is an **offset into that
same per-player 7-byte attribute data**, not the rating itself — consistent
with every earlier hypothesis in this section that the final number is
*computed*, not stored directly. This offset then gets passed into
primitive 3 (`0x0007C810`) as what is very likely a parameter, not raw data.

Stepped **into** `0x7C810` this time (`s`, not `n`) rather than over it:
it's short and follows the exact same "read own return address off the
stack to find inline data, patch it, `rts`" pattern already documented for
the other primitives — meaning the real work happens in a callee at
**`0x0007C822`** (reached via a plain `bsr`, not the inline-data trick),
which this session stepped over rather than into. Also confirmed `0x7C810`
gets called **more than once per widget** (a second `jsr $7C810` follows the
first, at a different call site, before the whole loop returns to
primitive 1 for the *next* widget/team) — consistent with "once per digit"
or "once per sub-element" rather than one call producing the whole number.

**The chain traced so far, visually** (ruled-out steps vs. the still-open target):

```
skip-loop exit (D0 = category index, now spent)
    │
    ▼
primitive 1 (0x7C6D4) ── RULED OUT, D0 untouched
    │
    ▼
primitive 2 (0x7C6E6) ── RULED OUT, D0 untouched
    │
    ▼
real 68k code (not a primitive): A2 = team struct,
D0 = WRAM $FFFFD266 (a +7-stride offset into the
per-player attribute block)
    │
    ▼
primitive 3 (0x7C810) ── called ≥2x per widget,
forwards to 0x7C822
    │
    ▼
0x7C822 ── STILL OPEN, the real candidate. One call
traced: parses padding, discards D0 without using it
as an index — check its OTHER call site(s) next
    │
    ▼
primitives 4 (0x7CF16) and 5 (0x7D258) ── not yet traced
    │
    ▼
digit-print (0x7D154) ── confirmed pure formatter
    │
    ▼
displayed rating (e.g. Messier: 79)
```

**Net effect**: primitives 1 and 2 are now ruled out with direct evidence
(not just inference), narrowing the real candidate to **`0x0007C822`**
(reached from inside primitive 3) plus the `$FFFFD266`/`+7`-stride offset
mechanism feeding it — a smaller, sharper target than "somewhere in five
primitives" was three paragraphs ago. Recommended next step: breakpoint
`0x0007C822` directly (not `0x7C810`, which just forwards to it), and watch
what it does with the `D0` offset — in particular whether it indexes into
the *same* per-player 7-byte attribute block already fully mapped out
earlier in this document, which would finally connect the known raw bytes
to the displayed rating. This thread was traced on the **team-level**
`Overall` widget; re-confirming the same call sequence on the **player**
`Center`/`Goalie` matchups (already known to reach `0x7C6D4`→`0x7C6E6`→
`0x7C810` in the same order) would confirm both widgets share this code
before investing further tracing effort into `0x7C822` itself.

**Same-session continuation: did exactly that confirmation on the player
`Left Forward` matchup, and it mostly holds up — with one genuine new
wrinkle.** Re-armed breakpoints at each known checkpoint in turn (rather
than single-stepping blind) and confirmed, byte-for-byte identical to the
`Overall` team widget: primitives 1 (`0x7C6D4`) and 2 (`0x7C6E6`) leave `D0`
untouched, the same real code block runs after them (`$FFFFAC42=$18`,
`$FFFFAC48=$2`, `A2=$FFFFC288`, `D4` from ROM pointer `0x00085846`, a flag
test at `$FFFFD274`), and `D0` gets loaded from `$FFFFD266` — **`7` again**,
exactly matching the team widget's first iteration. This is strong
confirmation the two widgets share this exact code path, not just the same
call *addresses* coincidentally.

**The wrinkle: followed `D0=7` into `0x7C822` this time (stepped in, not
over) and it turned out to be a dead end for *this specific call* — it's
parsing a padding/whitespace string from its own inline data (`D3` reads a
length-prefix word, then a byte-at-a-time loop at `0x7C840` reads and
sign-extends characters, immediately clobbering `D0` with the *string byte*,
discarding the offset value entirely without ever using it as an index.**
The inline data behind this particular call is mostly `0x20` (space)
padding, consistent with this being a layout/spacing operation, not the
numeric lookup. **Conclusion: the `$FFFFD266` offset is not consumed by
*this* invocation of `0x7C822` — either it was already consumed earlier
(before primitive 3 was even called, silently, somewhere in the "real code"
block above that this session read but didn't fully trace instruction-by-
instruction) or it's consumed by a *different* one of `0x7C810`'s multiple
per-widget calls (recall: confirmed to fire more than once per widget) than
the one this session happened to follow.**

Also recorded a real operational hazard while chasing this, worth knowing
for next time: single-stepping *over* a call with no other breakpoint armed
(`n` on a `jsr`) can **permanently hang the debugger** on this ROM's
self-patching-return-address primitives — `n`'s internal temporary
breakpoint lands at the naive "next instruction" address, which these
primitives never actually return to (they patch the return address to skip
their own inline data first), so nothing ever fires and the console is
stuck for good; only a full daemon/process restart recovers. Full
recipe/gotcha now in CLAUDE.md — the safe pattern is: read the inline data
length from the ROM to compute the real next address, set a real breakpoint
there, and use `waitbp` (which tolerates *other* breakpoints firing along
the way), never a bare `n` over one of these calls.

**Recommended next step**: instead of following the first `0x7C822` call
found, systematically catch *every* `jsr $7C810` in one widget's render pass
(confirmed ≥2 per widget) and check `D0` at each entry — the offset is
"spent" somewhere in that set, just not the one instance traced this
session.

**Later session: tried a different screen entirely (Team Roster, not
Scouting Report) and found the value finalized even earlier than
expected — plus a promising static lead that direct live testing
disproved, documented honestly rather than published as a confirmed
result.** Team Roster's Overall-Rating render was already known to reach
`0x0007D154` (digit-print) from a call site at `0x0008562C` (see the
"Follow-up session" above — Richter's `77` caught there). Disassembling
the surrounding bytes (`tools/ghidra/DumpRange.java`) shows this call site
sits inside a short handler starting at `0x8561C`:

```
0008561C  movem.l (SP)+,{D0 D7}     ; restores D0 (and D7) from the stack
00085620  beq.w 0x0008562A
00085624  jsr 0x0007D258.l          ; primitive 5
0008562A  moveq #4,D1
0008562C  jsr 0x0007D154.l          ; digit-print (confirmed formatter)
00085632  jsr 0x0007C6E6.l          ; primitive 2
00085638  jsr 0x0007C810.l          ; primitive 3
```

Breakpointed `0x00085638` during a genuine Team Roster redraw (Vancouver,
Offense, `Overall` category — cycled away to `Status` and back to force a
fresh render) and read `D0` at each hit: **`0x41`=65, `0x3E`=62, `0x2D`=45,
`0x47`=71 — an exact, in-order match for Carson/Craven/McIntyre/Courtnall's
displayed ratings**, all 4 checked hits correct (the 5th, presumably
Ronning's `76`, fired too but wasn't individually read). This is
decisive: **`D0` already holds the finished rating by the very first
instruction of this handler** (`movem.l (SP)+,{D0,D7}`, a stack
*restore*, not a computation) — meaning the real arithmetic completes
*before* the computed-jump dispatch (`0x000854B6: jmp (a0)`) even reaches
this handler, most plausibly pushed onto the stack by whatever code calls
into the dispatch in the first place. That's a genuinely different, and
narrower, target than anything chased so far in this section.

**A clean-looking static lead, ruled out by direct live testing.**
Immediately preceding this handler in ROM (`0x000855E4`-`0x000855FA`) sits
unambiguous, non-self-patching 68k code that looks exactly like the tail
end of a ratings formula:

```
000855E4  add.w D0w,D0w                    ; D0 *= 2 (word-array index)
000855E6  move.w (0x34,A2,D0w*0x1),D0w     ; D0 = word at [A2+0x34+D0]
000855EA  ext.l D0
000855EC  divu.w #0x28,D0                   ; D0 /= 40
000855F0  cmp.w #0x64,D0w                   ; compare to 100
000855F4  ble.w 0x0008562A                  ; <=100: fall through
000855F8  moveq #0x64,D0                    ; >100: clamp to 100
000855FA  bra.w 0x0008562A
```

A per-player word lookup (`A2` being the already-confirmed team-struct
base), scaled down by 40, clamped at 100 — precisely the shape a "sum
weighted nibbles into a bigger integer, then compress to a 0-99 display
range" formula would take, and a clean, direct explanation for the
clamp/saturation effect independently suspected from live stat readings
elsewhere in this document (see the issue #1 writeup in §5 — Courtnall's
Agility landing at 98 instead of a predicted 89.7). **It looked like the
answer. It isn't, or at least isn't reached from here**: breakpointed
`0x000855E4` directly and triggered two independent, genuine Team Roster
redraws (`Status`→`Overall` cycles) — it never fired, despite the roster
correctly redrawing with the right ratings both times. This block is real
ROM code, but not on the execution path for *this* render; either it
belongs to a different caller/widget (a plausible guess: the Scouting
Report's numeric widget, this section's original context, never actually
tested against this specific address) or is reached by some other
category/state this session didn't hit. Recorded here specifically so a
future session doesn't re-spend time on the same plausible-looking
address without checking it live first — exactly the "static analysis
can look right and still be wrong" trap this project has been caught by
before (see the `GLOSSARY.md` entry on the distinction).

**Net effect**: the search space is narrower than ever — the real
computation is now known to complete *before* a specific, reachable
dispatch point (`0x000854B6`) rather than somewhere inside a five-primitive
chain — but the exact instruction is still unfound.

**Same-session follow-up: found the dispatch is a real jump table, but
"trace its caller" turned out to be the wrong framing — `jmp` doesn't
push a return address, so there's no caller to walk back to.**
Disassembling immediately before `0x000854B6` shows the actual mechanism:

```
000854AE  lea (0xE,PC),A0            ; A0 = table base = 0x000854C0
000854B2  adda.w (0x0,A0,D4w*0x1),A0 ; A0 += word at [A0 + D4]  (byte-offset index, not *2)
000854B6  jmp (A0)
```

A real PC-relative jump table, indexed by `D4` — **not `D0`**, which this
session had been reading instead (an easy mistake: both are live and
plausible-looking at the breakpoint). Read the table directly from the
ROM file (no live tracing needed, it's static data): the first several
entries resolve to a tight, plausible cluster of nearby addresses
(`0x0855E6`, `0x085648`, `0x08566A`, `0x085600`, `0x085606`, ...,
`0x0854CA` — the last matching this session's own live D0=3 observation
exactly, strong circumstantial confirmation the table itself is real and
correctly located) — but several other entries in the same 16-word span
resolve to wildly distant, implausible addresses (`0x082500`, `0x0884F2`,
`0x08BEC0`, ...), each 20,000+ bytes away from the tight cluster. That's
not a data-corruption signal so much as a scope-of-the-table one: either
the real table is shorter than 16 entries (with genuine unrelated code or
a second table starting partway through what this session read as one
block), or `D4`'s value isn't a simple sequential 0-14 category index the
way `D0`'s was assumed to be — this session did not confirm which.

**Honest assessment and a concretely scoped stopping point.** This is
the *third* distinct sub-thread this project has chased on this exact
question (the five-primitive Scouting-Report chain in earlier sessions;
the Team-Roster handler-entry point and the ruled-out clamp lead earlier
this session; now this dispatch table) — each one real, each one
narrowing the target, none yet reaching the actual arithmetic. Per this
project's own "escalate after repeated attempts at the same layer" rule,
this is a natural pause point rather than a fourth guess. **Concretely
scoped for whoever picks this up next**: breakpoint `0x000854B2`
specifically (right where `D4` is consumed) during a Team-Roster-Overall
redraw, read `D4` directly (not `D0`) to get the *real* index for the
`Overall` category, then re-derive the table entry for that exact index
from the static read above — that pins down whether the table really has
noisy/out-of-range entries or whether this session simply mis-identified
which index register mattered.

**Breakthrough via a completely different method: external data correlation,
not more live tracing.** The user pointed at a GameFAQs guide
(`docs/external_sources/gamefaqs_28196_roster_ratings.txt`, saved locally —
Chris Zawada/"antseezee", Final version 2011) that hand-transcribes a static
per-player "Rating" for all ~700 players in the game, one line each:
`# jersey - Name - Position - Rating`. This project already has
`docs/full_roster_database.json` (built earlier, one entry per team with
each player's ROM address, jersey, and `attr7_hex` — the 7-byte/14-nibble
"unknown attribute block" from §2.2/§6) — meaning both sides of a real
correlation were already sitting in this repo, unused together until now.

Matched all 618 FAQ entries to their `full_roster_database.json` record by
team + jersey number (617/618 matched; one bad FAQ jersey number for a
single player). **Linear regression of Overall Rating against the 14
attribute nibbles gives R² ≈ 0.90 immediately** — already far too strong to
be coincidence for a "computed, not stored" value this project has spent
multiple sessions chasing. Two data-quality problems in the existing tooling
initially masked how strong the fit really is, both worth recording since
they'll bite anyone reusing this JSON again:
- **`full_roster_database.json` has two entries with `city: "New York"`**
  (Islanders and Rangers) and a naive `city`-prefix match resolves to
  whichever the JSON lists first — every Rangers player was silently getting
  matched against `New York Islanders`' roster data. This alone produced a
  spurious "New York Rangers is an outlier" signal (25-point residuals) that
  looked like a real anomaly until traced back to the matching code, not the
  game data.
- **Four `mascot` fields in the same JSON are corrupted** — `Los Angeles`,
  `New Jersey`, `San Jose`, and `Tampa Bay` all show an arena name (e.g.
  `"Brendan Byrne Arena"`) instead of the team nickname, evidently a
  mis-extraction from whatever script originally built this file. Harmless
  once you match by an explicit `(city, mascot)` pair instead of trusting
  the mascot string's content, but worth fixing at the source if this file
  gets regenerated.
- Also found (and worked around) a **genuine in-ROM jersey-number collision**:
  Toronto has both Ken Baumgartner and Mike Gartner wearing `#22` (a
  realistic mid-season roster event), which a jersey-only match can't
  disambiguate — resolved by falling back to last-name similarity when a
  jersey number has more than one candidate on a team.

With both fixed (explicit `(city, mascot)` team keys, name-disambiguated
jersey collisions), the fit becomes very strong and *uniform across every
team* — no more per-team bias:
- **Skaters (F/D), n=563, 12 of the 14 nibbles** (dropping nibble 0 — the
  high nibble of the byte already flagged as a probable duplicate/derived
  value elsewhere in this section — and nibble 7, which also carries ~zero
  weight): **R² = 0.979, mean |residual| = 1.36, max |residual| = 7.4**
  across all 26 teams. Per-team mean residual is under ±1 point for every
  team once the matching bugs above are fixed — the earlier "Rangers
  anomaly" fully disappears.
- **Goalies (G), n=54, using the 10 nibbles that are ever nonzero for
  goalies** (positions 6-9 of the 14 are *always* `0` for every goalie in
  the dataset — a real structural difference from skaters, not noise):
  **R² = 0.980, mean |residual| = 1.80, max |residual| = 4.5**.
- **Snapping the skater weights to small integers** — `[2,2,3,1,1,1,1,2,1,0,1,0]`
  for nibbles `[1,2,3,4,5,6,8,9,10,11,12,13]` respectively, plus a constant
  of `≈12` — still gives **R² = 0.971, mean |residual| = 1.58**, barely
  worse than the exact float fit. Very plausibly close to the real integer
  arithmetic the game itself performs (nibble 0 contributing weight 0 fits
  the "duplicate of unknown1" theory exactly; nibbles 11 and 13 also drop to
  weight 0, meaning the low nibble of two of the seven bytes may not matter
  at all).

**What this does and doesn't prove**: this is strong statistical evidence
that Overall Rating is (very close to) a fixed linear combination of
specific nibbles in the already-fully-mapped 7-byte attribute block — a
real formula, not a black box — and narrows *where* in that block the
signal lives (specific nibbles, specific weights) far more precisely than
any single live trace has so far. It is *not* itself a disassembly-verified
proof of the exact 68k arithmetic; the remaining ~2% variance and the
handful of 5-7 point outliers (concentrated among the lowest-rated
"enforcer"-type players, e.g. Grimson/Twist/Cronin/Shannon, hinting at a
possible floor/clamp or an extra term at the low end) are still open. The
natural next step is now much narrower than before: use this weight vector
as a *hypothesis* to test against the live interpreter trace (§ above) —
specifically, check whether the primitive that actually reads player
attribute data (still unidentified — see the `0x7C810`/multi-call-site
lead) multiplies by something close to these same small integers.

---

## 7. Open questions / candidate next steps

**Live-tracked as GitHub issues, not just here**: every open item below (plus
a few new ones — goalie-stat cross-validation, AI/difficulty, and mapping
more of the UI string-table system) has a corresponding
issue at
[github.com/BreakableHoodie/nhl95-decoded/issues](https://github.com/BreakableHoodie/nhl95-decoded/issues),
labeled `investigation`. This section stays the narrative record of *why*;
the issues are the actionable backlog.

Roughly in priority order (see chat for discussion):

~~Map the multiple `0x0A0042`/`0x0A0672`/`0x0A0692` passes~~ — **done**: it's the
same `0x09FFF4` hot/cold-setup function called twice from `0x09F590` (an early
placeholder pass before per-team data exists, then a real pass after
`0x0083E88` populates it), not multiple categories sharing scratch memory.

~~Find the exact instruction that seeds the modifier table~~ — **done**: full chain
traced from the VDP H/V-counter hardware read (`0x00085D34`) through the LCG core
(`0x0007C63A`) to the `RNG(18)-9` scaling (`0x0007C62E`) to the 416-byte population
loop (`0x0083E88`). See §5.

1. ~~Identify what the displayed number *is*~~ — **done**: it's the player's
   **Overall Rating** stat, confirmed by an exact live match (Messier: 79 on both
   the Scouting Report and the Team Roster screen, same game session). See §6.
   **Exact nibble-set: now ROM-confirmed** (not just statistically inferred) —
   see §6 item 6's "major breakthrough" write-up: a decoded ROM bytecode
   table's `Overall`-widget parameter is bit-for-bit the OR of exactly the
   nibbles the independently-fit weight formula uses. **Still open**: the
   precise integer weights and the actual 68k opcode that consumes this
   bitmask. Five hypotheses already ruled out with real evidence (live WRAM
   struct scan, raw ROM player-record scan, nibble-sum arithmetic, the
   `A0≈0x3618` ROM pointer path, and direct memory reads at every register
   pointer live at the render call site, `0x0008562C`) — that call site is
   confirmed to be one handler inside a genuine bytecode/jump-table
   interpreter (reached via `jmp (a0)`, not a normal call), the same
   architecture already found driving the Scouting Report screen. The
   newly-confirmed bitmask is now a concrete, verified input to look for
   when tracing that handler — a substantially narrower target than "trace
   an unknown interpreter" was before.

   **Later session: narrowed further, live-confirmed the value is already
   final before the render handler even starts, and ruled out one
   plausible-looking static lead by testing it directly.** Breakpointed
   `0x0008562C`'s handler entry (`0x8561C`) during a real Team Roster
   redraw and confirmed `D0` already equals the exact displayed rating
   for 4 of 5 players checked (Carson/Craven/McIntyre/Courtnall, all exact
   matches) at the handler's very first instruction — a stack *restore*,
   not a computation, meaning the real arithmetic finishes before the
   `0x000854B6: jmp (a0)` dispatch is even reached. A clean, unambiguous
   `divu.w #0x28` (÷40) + clamp-at-100 block sitting right before this
   handler in ROM (`0x000855E4`) looked like exactly the missing formula
   tail — direct ROM evidence for the clamp/saturation effect already
   suspected from live stat readings (§5/issue #1) — but breakpointing it
   directly across two genuine redraws found it never fires from this
   render path; not confirmed, and explicitly not claimed as solved. See
   §6's "Later session" write-up for the full trace and the concretely
   scoped next step (trace backward from the dispatch's own caller). See
   GitHub issue #2.
2. ~~Confirm line 0 = Sc1, the line-label set, and the full line-index mapping~~ —
   **done, all 7 lines mapped.** Live Line Editor
   (checked immediately after a fresh Controller Setup, zero game-clock elapsed)
   gave an exact, byte-for-byte match for NYR `Sc1 Line` = ROM `0x3618` line 0
   (LD Leetch/RD Zubov/LW Graves/C Messier/RW Larmer, once corrected for a
   team-label swap caught in the same pass — see §2.3). The full label *set* is
   confirmed from ROM `0x8A02C` and Sega Retro's dedicated "Line Change" section
   (distinct from "Edit Lines" — see the CLAUDE.md gotcha): **Sc1, Sc2 (scoring),
   PP1, PP2 (power play, called "Pw1/Pw2" in the wiki's prose but stored as
   literal `PP1`/`PP2` text in ROM), PK1, PK2 (penalty killing), Chk (checking
   line — "bigger and harder-hitting... ideal for playing defense")**, and
   critically "**Sc1 starts each period**" — explaining why the Line Editor
   defaults to showing Sc1.

   Tried to reach the wiki-documented in-game "Line Change" quick-menu (holds
   `A` on offense, or appears automatically before a face-off) live, across
   several real face-offs and A-holds — never caught it on screen (either the
   trigger window is too narrow for screenshot-based polling, or "on offense"
   requires puck possession states harder to force blindly than expected).
   Abandoned that path in favor of a cleaner one: the Team Roster screen's
   `Reg`/`PP`/`PK` columns (§6) show *which numbered line* each player is on
   (e.g. Messier: `Reg=1 PP=1 PK=1,2` = Sc1, PP1, PK1, PK2). Cross-referencing
   4 independent players' Team Roster line-numbers against their raw-ROM
   appearances (as a literal LD/RD/LW/C/RW, not the unlabeled `+6` "extra"
   slot) across the 8 decoded blocks solved 6 of 7 outright, with multiple
   players agreeing on each:
   - **Sc2 = line 2** (Zubov and Lowe's appearance counts both require it)
   - **Chk = line 3** (Nemchinov's *only* appearance anywhere is here, matching
     his *only* assignment, Chk — clean, unambiguous)
   - **PP1 = line 4** (Zubov and Leetch both consistent with this)
   - **PP2 = line 5** (Kovalev and Lowe both consistent with this)
   - **PK2 = line 7** — the strongest result, independently confirmed by
     *three* players at once (Zubov, Lowe, MacTavish all match)
   - **PK1 = line 6 — resolved.** Lines 1 and 6 are near-duplicates (same
     LD=Leetch/RD=Beukeboom/LW=Graves/C=Messier, only RW/`+6`-extra swapped
     between Anderson and Larmer), and neither Beukeboom nor Leetch (present
     on *both* candidates) could disambiguate them. Reading Anderson's and
     Larmer's individual Team Roster rows directly settled it: **Larmer shows
     `PK=1`; Anderson shows no PK credit at all.** Larmer is RW on lines 0 and
     6; line 0 is already Sc1, so his `PK=1` must be line 6. Anderson is RW on
     lines 1 and 4; line 4 is already PP1, and he gets *zero* additional
     credit for his other appearance — meaning **line 1 is not one of the 7
     named UI lines at all**, confirming it as the "8th, unused" block
     flagged since §2.3 was first written. (Side note, not yet explained:
     Larmer's own `Reg` column read `1,2` — both scoring lines — despite no
     static-ROM appearance in line 2; likely live fatigue-substitution drift
     from being deep in an active game for this particular check, unlike the
     zero-game-clock check used for Sc1, so not fully trusted, but it didn't
     affect the PK1 conclusion.)

   **Full mapping**: line 0 = Sc1, line 1 = *(unused 8th block)*, line 2 =
   Sc2, line 3 = Chk, line 4 = PP1, line 5 = PP2, line 6 = PK1, line 7 = PK2.
   Cross-validated by at least two independent players for every entry except
   Sc1 (which had its own exact, independent live confirmation) and PK1
   (confirmed by the Anderson/Larmer contrast above).

   **Independently reconfirmed end-to-end on a second team, via a completely
   different method.** With Penalties and Line Changes both enabled (see the
   settings-screen note in §7#5) and a real penalty kill happening live
   (Vancouver down two players, a genuine `NYR PWR PLAY` indicator on
   screen), the Line Editor — with `Line Changes: Auto` set — turned out to
   show a different layout than before: **all 7 lines, cycled 2-3 at a time
   with Left/Right** (`Sc1/Sc2/Chk` → `PP1/PP2` → `PK1/PK2`), rather than the
   single-line view seen earlier in the session with Line Changes off. Read
   Vancouver's live `PK1` and `PK2` directly: `PK1 = LD Diduck/RD Brown/LW
   Bure/C Craven` and `PK2 = LD Lumme/RD Babych/LW Linden/C McIntyre` — both
   with a **blank RW row**, directly confirming Sega Retro's "penalty killing
   lines... have four members and only one wingman" claim by observation, not
   just documentation. Both match ROM lines 6 and 7 for Vancouver exactly
   (LD/RD/LW/C, blank-RW aside — the raw ROM record still stores an RW byte
   for these lines, e.g. Linden/Adams, but the live UI simply doesn't surface
   it for PK). This confirms the *entire* line-index mapping above end-to-end,
   on a second team, via direct observation rather than Team-Roster-column
   inference — about as solid as this project's evidence gets.

   Offset+0 is confirmed as "team's starting goalie, constant across all 8
   lines" (independently reconfirmed via the Team Roster screen: Richter shows
   on all Reg/PP/PK lines). Offset+6 ("extra" slot) — given the pattern above
   (never contributing to any player's Reg/PP/PK count across dozens of
   cross-checked appearances), is very likely a genuine bench/backup
   reference that simply isn't surfaced by the Team Roster or Line Editor UI,
   not a meaningfully different kind of data.
3. ~~Map the menu→team-index lookup~~ — **done. The menu cycles in
   alphabetical order (not ROM order), and Dallas was never missing** — an
   earlier pass through this item concluded the opposite (ROM order,
   Dallas absent), which turned out to be wrong; see §2.1 for the full
   evidence trail and the root cause of that original mistake. GitHub
   issue #7 closed with this resolution.
4. ~~Check whether jersey number is used as a lookup key anywhere~~ — **checked,
   reasonably confident negative result, not exhaustively proven.** See §4: every
   subsystem mapped this session keys on roster index, never jersey number;
   jersey only ever appears as a displayed BCD label. The 3 duplicate-jersey cases
   are very likely cosmetic. Not a byte-perfect proof of absence, but a real,
   evidence-based conclusion built from this session's full data map, not a guess.
5. ~~Broader engine analysis: observe special-teams line-switching~~ —
   **done, full mapping confirmed live.** The path here took real trial and
   error, worth recording in full since each dead end taught something:
   - Manual blind play (many attempts) never drew a penalty — blind,
     no-real-time-feedback button-mashing is a poor tool for forcing a
     specific, position-dependent event.
   - **CPU vs. CPU** (Controller Setup: slide both numbered controller icons
     into the middle `CPU` column) fixed the input problem — the game plays
     itself, zero manual input, and produces genuine tracked events (watched
     a real goal: Bure, assisted by Ronning). But across two full periods of
     CPU-vs-CPU play, the penalty table stayed completely empty — confirmed
     via the Penalty Summary screen, not assumed.
   - That turned out to be a real settings toggle, not bad luck — but not
     one on the in-game pre-game `OPTIONS` menu (only 4 items). It's on a
     **separate settings screen** (`Play Mode`/`Team 1`/`Team 2`/`Per.
     Length`/`Goalies`/`User Records`/`Penalties`/`Line Changes`) that
     appears **automatically right after the credits scroll, with zero
     button presses** — every earlier session had been blind-mashing Start
     during the credits, which registers on this exact screen the instant it
     appears and silently confirms straight through it. Turned `Penalties`
     and `Line Changes` both to `On`/`Auto` here; saved a reusable
     `~/penalties_on.state` savestate at this exact screen for future
     sessions (see CLAUDE.md).
   - With both settings on, CPU vs CPU produced a real two-man penalty kill
     within a few minutes (`NYR PWR PLAY` on screen, two Vancouver players in
     the penalty box). Paused mid-penalty (freezing the penalty clock) and
     opened Vancouver's Line Editor — which, with `Line Changes: Auto`, now
     showed a genuinely different layout than earlier in the session: **all
     7 lines, cycled 2-3 at a time with Left/Right** (`Sc1/Sc2/Chk` →
     `PP1/PP2` → `PK1/PK2`), rather than the single-line view seen when Line
     Changes was off. Read Vancouver's live `PK1`/`PK2` directly and cross-
     checked against the ROM position table (see §7#2's follow-up for the
     exact match) — confirming the entire line-index mapping end-to-end, on
     a second team, by direct observation.

   AI decision-making and faceoffs remain untouched. This item is closed
   for its original scope (special-teams line-switching); anything further
   here would be a new, separately-scoped investigation. (This game does
   not have an interactive fighting minigame — an earlier version of this
   note wrongly implied otherwise; corrected. "Fighting" does appear twice
   in the ROM's own text data, though: as a real penalty type alongside
   Holding/Checking/etc., and as a team-strength rating category alongside
   Defense/Checking/Goalkeeping/Power Play Adv. — see item 8's injury
   writeup and `tools/rom_scan.py` for how this was found.)

   **Follow-up session: X11 keyboard delivery to BlastEm's window went dead
   (a VM-environment regression, not a ROM finding — see the CLAUDE.md
   gotcha), which forced finding a real fix rather than a workaround.**
   Traced the live controller-poll routine by following the VBlank interrupt
   vector at runtime (`$78` autovector → `0x7A32C` → WRAM `$FFFFAC52`
   function pointer → `0x7A418` → `0x7A3E6` → `0x7A55A`, the actual poller —
   static xref search alone had only found a one-shot 6-button-detect
   routine, a dead end). This produced something more valuable than a
   workaround: a **general, X11-independent way to drive controller input
   directly through the 68k debugger**, confirmed live (forced "Left" via a
   register write at the right breakpoint, watched the Controller Setup
   screen's controller-1 icon move exactly as expected, over real elapsed
   frames, not a single forced write). Full technical writeup — ROM
   addresses, byte encoding, exact debugger command sequence — is in
   CLAUDE.md, since it's a reusable technique rather than a ROM-data
   finding. Practical effect: this project no longer strictly needs working
   X11 input to reach any menu screen a real controller could reach,
   including ones with no savestate yet (e.g. the Scouting Report screen,
   needed for item 1/6's Overall Rating tracing).
6. ~~Map the 14 attribute nibbles to their named stats~~ — **solved and
   live-validated** (Overall Rating: mean|residual| 1.8 live, near-exact;
   named stats: multivariate refit, single digits live for a non-hot/cold
   player — see the "Live validation" subsection below). Full path to get
   there, kept for the record:

   Live-read Messier's stats on the Team Roster screen
   in Sega Retro's documented cycle order: `Overall=79` (Rating column, always
   shown), `Energy=100` (confirmed dynamic/pre-game-default, not a fixed
   attribute — every player reads 100 before a game starts, skip this one),
   `Agility=95`. Then read `Agility` for four more known players: Nemchinov 75,
   MacTavish 70, Kovalev 99, Olczyk 47. **These values rule out the 7-byte/
   14-nibble block as their source** — nibbles only range 0-15, but Agility values
   go up to 99, and neither a raw-byte search of the ROM (`95 75 70 99 47` as a
   contiguous sequence) nor a search near each player's own name record found
   this data anywhere. Coincidentally, Messier's *first attribute byte* (`0x95`)
   read as two BCD digits equals 95 — matching his Agility exactly — but this
   didn't replicate for any of the other four players, so treat it as a
   coincidence, not a lead (the same caution this project has already had to
   apply once before to a suspiciously-matching number). **Conclusion**: the
   7-byte block and these finer-grained (0-99) named stats are two genuinely
   different data sources — worth knowing on its own, since it means item 1's
   Overall Rating formula won't be found by decoding that 7-byte block further.
   The named stats are very likely stored as a separate, not-yet-located
   per-player table (plausibly one full byte per stat, 14 bytes/player) or
   computed via a nibble→0-99 lookup table rather than a direct formula on the
   known bytes. Next step: live-trace the render call site now known from item 1
   (`0x00085627`) specifically while cycling stats on this screen, watching what
   *changes* in the source operand between stat categories — more promising than
   further ROM byte-searching, which has now been tried twice on two different
   value sets and come up empty both times.

   **Follow-up session: solved, via external data correlation — and the
   conclusion above ("7-byte block and named stats are different sources")
   was wrong, for an understandable reason.** The earlier reasoning was
   sound as far as it went (nibbles cap at 15, Agility reads up to 99, no
   raw BCD/byte match found for 4 of 5 known values) but only tested for a
   *direct* value match, not a *scaled linear* one. A second GameFAQs-style
   external source — this time the full spreadsheet behind `nhl-95.com`
   (Jon Morris; the tournament app in the sibling project references it,
   see below), which names Agility/Top Speed/Shot Power/Shot Accuracy/
   Stick Handle/Off. and Def. Awareness/Pass Accuracy/Endurance/Check/Aggro
   per player for ~600 players — correlates *extremely* well against
   specific individual nibbles of the *same* 7-byte block already fully
   mapped out earlier in this document, once a `nibble × scale + offset`
   transform is allowed instead of a direct match:

   | nibble | named stat | r | fitted scale | fitted offset | R² |
   |---|---|---|---|---|---|
   | 1 | Agility | 0.92 | ~14.0 | ~14.4 | 0.85 |
   | 2 | Top Speed | 0.93 | ~14.0 | ~14.4 | 0.87 |
   | 3 | Off. Awareness | 0.95 | ~13.2 | ~17.4 | 0.90 |
   | 4 | Def. Awareness | 0.90 | ~13.0 | ~17.1 | 0.81 |
   | 5 | Shot Power | 0.94 | ~13.7 | ~15.3 | 0.89 |
   | 6 | Check | 0.90 | ~12.1 | ~19.0 | 0.82 |
   | 8 | Stick Handle | 0.89 | ~5.2 | ~22.2 | 0.79 |
   | 9 | Shot Accuracy | 0.93 | ~12.0 | ~20.3 | 0.87 |
   | 10 | Endurance | 0.91 | ~14.3 | ~13.1 | 0.82 |
   | 12 | Pass Accuracy | 0.93 | ~13.2 | ~16.7 | 0.87 |
   | 13 | Aggro | 0.91 | ~15.0 | ~9.7 | 0.84 |

   This is exactly the same set of 11 nibbles already flagged as relevant
   to item 1's Overall Rating formula (nibbles 0, 7, and 11 are — again —
   the ones with no clear signal, consistent across *both* correlation
   exercises now) — strong internal consistency between two completely
   independent analyses run against two different external datasets. Four
   of the CSV's remaining named columns (`Offensive Overall`, `Tough`,
   `Scoring`, `Acc`) correlate more weakly and only against nibbles *already
   claimed* by a stronger match above — these are very likely themselves
   *computed/composite* stats (site-side or game-side), the same pattern
   already established for Overall Rating, not raw stored attributes.

   **Confidence, precisely stated**: very high on *which nibble is which
   named stat* (11 independent (nibble, stat) pairs, each R²=0.79-0.90
   against ~550-600 players, and cross-consistent with the entirely
   separately-derived Overall Rating nibble set). Lower on the *exact*
   scale/offset constants — a single live spot-check (Messier's
   ROM-derived Agility predicts ~85 from this fit; a live Team Roster
   reading earlier in this project showed `95`) didn't match closely, but
   that's expected rather than damning: (a) `nhl-95.com`'s own data has a
   *confirmed* team-wide corruption for the Rangers' Overall Rating (see
   the tournament-app cross-reference work, same session) that plausibly
   extends to its other stat columns for the same team, and (b) any single
   live reading already includes the §5 hot/cold modifier layered on top
   of whatever true base value is stored — a live snapshot is not
   automatically the base value to fit against. Re-fitting with Rangers
   excluded barely moved the numbers (confirms the *mapping* is robust to
   that specific contamination), which is why confidence is high on
   identity and more moderate on the precise constants. **Next step,
   concretely scoped**: live-verify one or two of these mappings the way
   §7#2's line-index mapping was ultimately nailed down — read a specific
   player's named stat directly off the Team Roster screen *and* freeze/
   note whether HOT/COLD is showing at that exact moment, so the comparison
   is against a known modifier state rather than an uncontrolled one.

   **Immediate follow-up: building the full 26-team comparison
   (`tools/build_rom_verified_stats.py`) surfaced a second class of
   contamination in the correlation, distinct from Rangers' Overall Rating
   bug** — nhl-95.com's spreadsheet has at least 13 confirmed **wrong
   jersey numbers** (e.g. Chicago's Gary Suter listed at #20, which in the
   ROM belongs to a completely different player, Darin Kimble), which a
   naive jersey-only join silently turns into nonsense comparisons between
   unrelated players — several of the largest "outliers" in an earlier
   pass at this analysis were purely this artifact, not a real formula or
   data problem. Fixed with a mandatory last-name-similarity sanity check
   on every jersey match, falling back to a team-wide name search when the
   jersey match doesn't resemble the CSV name. After that fix: **n=6116,
   mean|residual|=3.91, median|residual|=3.20** across every named stat for
   every matched player — a real, long tail of individual outliers remains
   (e.g. Detroit's Kozlov/Konstantinov both show 15-37 point residuals
   across multiple stats simultaneously, with jerseys confirmed *correct*
   this time, suggestive of an actual row-level data error in that specific
   part of the source spreadsheet, not a matching bug or a formula flaw).
   Full player-by-player diff saved at
   `docs/external_sources/rom_verified_full_comparison.csv` for reference.
   **Recommendation before using this to mass-replace any production data**
   (as opposed to the narrowly-scoped, individually-verified Rangers
   Overall Rating fix already applied): treat median residual (~3) as the
   real precision floor of this fit, spot-check the largest outliers
   individually before trusting them, and prioritize the live-verification
   step above to tighten the scale/offset constants — this dataset is
   strong enough to *guide* further work but not yet strong enough to
   blindly overwrite 26 teams' worth of production data the way the
   single, individually-confirmed Rangers correction was.

   **Live validation, hot/cold controlled by using un-flagged players — and
   a real finding about the fit's shape, not just its accuracy.** Started a
   live game (Vancouver @ NY Rangers, default matchup) and read 5 Canucks
   forwards (Ronning, Carson, Craven, McIntyre, Courtnall) directly off the
   Team Roster screen — Overall Rating plus 5 named stats each, 30
   (player, stat) pairs total, none of nhl-95.com's CSV involved at all.
   This is a strictly stronger test than another correlation pass: it
   compares the fitted formula against the ROM's own live output.

   Overall Rating validated almost exactly — **mean|residual| = 1.8**
   across the 5 players, including an exact match on Ronning (predicted 77,
   live 77). But the single-nibble named-stat fits from the table above
   broke down badly and unevenly: Agility/Top Speed held up (~5 point mean
   residual), while **Def. Awareness and Shot Power were far worse live
   (mean|residual| 16.4 and 12.0)** than their ~4-point median residual
   against the CSV — and critically, the errors weren't a per-player
   constant offset (which would look like a hot/cold modifier), they
   varied in sign and size per stat for the same player. That pattern means
   the single best-correlated nibble was never the *whole* formula for
   those stats — it was just the dominant term, the same way Overall
   Rating turned out to be a 12-nibble combination rather than any single
   nibble.

   Refitting every named stat the same way Overall Rating was fit —
   multivariate linear regression against all 12 relevant nibbles at once,
   not just the best single one (`tools/fit_multivariate_named_stats.py`,
   R²=0.84-0.96 per stat, all noticeably higher than the single-nibble
   R²=0.79-0.90 from before) — closed most of the live gap: re-tested
   against the same 5 Vancouver players, Def. Awareness dropped to
   mean|residual| 3.5 and Shot Power to 2.3; Off. Awareness to 4.0. Two
   (player, stat) pairs stayed stubbornly high even after refitting —
   Ronning's Top Speed (+9.7) and Courtnall's Agility (+11.3), both
   live *higher* than predicted, both plausibly the §5 hot/cold modifier
   showing through (a positive per-player boost would look exactly like
   this), but this wasn't independently confirmed by reading
   `team_struct+0x1A4` directly in this session — that would need its own
   single-stepped trace through `0x0083E88` for this specific boot/matchup,
   the same way Messier/Leetch's modifier bytes were read in §5, and is the
   natural next step if tightening those two stats further ever matters.

   **Later follow-up, same session: attempted a shortcut, got a genuinely
   mixed result — documented honestly rather than forced into a
   confirmation.** Since this exact BlastEm process never restarted, the
   RNG state behind the Ronning/Courtnall readings above was still live.
   Rather than the full single-stepped `0x0083E88` trace, tried reading
   `team_struct+0x1A4+roster_index` directly using two candidate team-struct
   base addresses captured earlier in this same session's register dumps
   (`0xFFFFC5EE` and `0xFFFFC288` — neither independently re-confirmed as
   Vancouver's struct specifically for *this* call site, a real caveat).
   Both candidates agree on the qualitative pattern: **Courtnall's modifier
   byte is positive** (`+5` or `+2` depending on which base), consistent
   with his elevated Agility residual — but **Ronning's is negative**
   (`-2` or `-7`), the *opposite* direction from his elevated Speed
   residual. That does not cleanly confirm the hot/cold hypothesis for
   both players; if anything it argues against it for Ronning specifically,
   and suggests either (a) his residual has a different, unrelated cause
   (ordinary fit noise, since 12/13 tested pairs already fit within single
   digits and one outlier is not implausible on its own), or (b) the
   modifier doesn't apply as a simple uniform per-player addition to every
   stat the way this shortcut assumed. Genuinely inconclusive — not chased
   further with the full proper trace this session, see GitHub issue #1.

   `build_rom_verified_stats.py` now uses these multivariate models for
   every named stat (Overall Rating's formula was already multivariate).
   Rebuilding the full 26-team comparison with them moved the aggregate
   numbers only modestly (mean|residual| 3.91→3.80, median 3.20→3.10) —
   expected, since the single-nibble fit was already capturing most of the
   signal in bulk, and the CSV's own noise (Rangers, jersey errors,
   Kozlov/Konstantinov) dominates the aggregate stats regardless of which
   formula generates the ROM side. The real payoff of the multivariate
   refit is the *live* accuracy, not the CSV-comparison aggregate — Overall
   Rating is now defensible as near-exact, and the named stats are
   defensible to within single digits for a normal (non-hot/cold) player,
   which is a materially stronger claim than before this check.

   One more pattern worth flagging for future work: several of the largest
   remaining CSV-comparison outliers are named stats near the top of the
   0-99 range (e.g. several players' Shot Accuracy/Check reading 95-98 in
   the CSV, predicted 79-84) — a linear fit consistently under-predicting
   near the ceiling is a classic sign of a clamp or saturation the real
   formula applies that a pure linear model can't reproduce. Not chased
   further this session; worth keeping in mind if the named-stat formulas
   get revisited.

   **Full production-DB audit: no second Rangers-style bug anywhere else.**
   With the formulas now live-validated, ran the same ROM-vs-external
   comparison directly against the tournament app's live production
   database (all 618 skaters, not the raw nhl-95.com CSV) to answer the
   obvious next question — is Rangers' Overall Rating bug a one-off, or are
   other teams silently wrong too? Per-team mean *signed* residual (not
   absolute — signed catches a systematic one-directional bug the way
   Rangers had) is small and has no consistent direction for every one of
   the other 25 teams: it ranges only ±0.9 points, indistinguishable from
   fit noise. The already-applied Rangers fix itself now tracks at +1.18
   mean / 1.45 mean|resid| — back in line with everyone else. **Conclusion:
   Rangers was a one-off data bug in the source spreadsheet, not a pattern
   — no other team needs a wholesale Overall Rating correction.**

   The individual-player-outlier picture is also much cleaner against the
   production DB than against the raw CSV: the worst single-player residual
   anywhere in the entire 618-player database is now only **8 points** (Stu
   Grimson, ANA) — nothing remotely like the 15-37 point Kozlov/Konstantinov
   gap seen in the raw CSV. More interesting: the largest remaining
   residuals cluster almost entirely among **low-rated "enforcer"-type
   players** (Grimson, Smyth, Twist, Shannon, Watters, Maley, Vukota,
   Dineen, Brown, Cronin, Charron — all +5 to +8, i.e. production rates
   them *higher* than the linear formula predicts), independently
   confirming the "possible floor/clamp at the low end" hypothesis flagged
   earlier in this section using a completely different dataset. Reads as a
   real, minor formula-precision gap (the linear fit slightly
   under-predicts a floor the real game formula applies), not a data
   error — and not worth a production write, since there's no clean
   individually-verified correction to make the way the Rangers bug had.
   **Net result: no further production database changes are recommended at
   this time** — the Rangers fix already applied was the one genuine bug.

   **Major breakthrough, found purely statically: the exact nibble-selection
   for Overall Rating is now ROM-confirmed, not just statistically inferred
   — and two previously-unexplained nibbles are identified.** While
   scanning the ROM for the "Face Off" UI string (see item 7 below), found
   and decoded a new, general string-record format used throughout this
   ROM's UI-widget bytecode: `[0x00][tag][0x00][length][text][u16 suffix]`
   (the `tag` byte was assumed constant at first pass and turned out not to
   be — it varies, `0x00`/`0x02`/`0x04`/`0x06`/`0x0A` all appear across the
   rating tables, most commonly `0x0A`; not yet explained, possibly a
   per-widget-type opcode. Caught by testing the reusable version of this
   parser, `tools/rom_scan.py`, against the known-good manual dump before
   trusting it — an earlier, hardcoded-tag version silently missed most of
   the table's entries). At ROM `0x085832` this format reveals the **exact
   source table for the Team
   Roster screen's stat-category cycle** (`Overall`/`Energy`/`Agility`/
   `Speed`/`Handed`/`Off. Awareness`/`Def. Awareness`/`Shot Power`/`Shot
   Accuracy`/`Pass Accuracy`/`Stick Handling`/`Weight`/`Endurance`/
   `Aggressiveness`/`Checking`, immediately followed at `0x085994` by a
   second, goalie-specific version substituting `Glove Hand`/`Puck
   Control`/`Stick Right`/`Stick Left`/`Glove Right`/`Glove Left` for the
   skater-only entries) — an exact, byte-for-byte match to the live Team
   Roster category cycle read earlier this session.

   The 2-byte suffix on every entry except `Overall` and `Energy` is a
   **single set bit** (`0x1000`, `0x0800`, `0x0040`, `0x0400`, ... down to
   `0x0001`) — i.e. a one-hot nibble-selector, not a screen coordinate.
   Decoding it as `bit = 13 - nibble_index` and cross-checking against
   every nibble→stat mapping already established *statistically* earlier
   this section produced a **perfect, zero-discrepancy match across all 13
   mapped stats**:

   | stat | suffix | bit | nibble (predicted `13-bit`) | matches stats work? |
   |---|---|---|---|---|
   | Agility | 0x1000 | 12 | 1 | yes |
   | Speed | 0x0800 | 11 | 2 | yes |
   | Off. Awareness | 0x0400 | 10 | 3 | yes |
   | Def. Awareness | 0x0200 | 9 | 4 | yes |
   | Shot Power | 0x0100 | 8 | 5 | yes |
   | Checking | 0x0080 | 7 | 6 | yes |
   | Handed | 0x0040 | 6 | 7 | **new** |
   | Stick Handling | 0x0020 | 5 | 8 | yes |
   | Shot Accuracy | 0x0010 | 4 | 9 | yes |
   | Endurance | 0x0008 | 3 | 10 | yes |
   | *(unused — see below)* | — | 2 | 11 | n/a |
   | Pass Accuracy | 0x0002 | 1 | 12 | yes |
   | Aggressiveness | 0x0001 | 0 | 13 | yes |
   | Weight | 0x2000 | 13 | 0 | **new** |

   This closes both nibbles that showed "no signal" in the statistical
   named-stat correlation: **nibble 0 is Weight** (a physical attribute,
   not a 0-99 performance stat — exactly why it never correlated against
   any named performance stat), and **nibble 7 is Handed** (Left/Right
   shot, categorical, not continuous — same reason). Nibble 11 remains
   genuinely unmapped even in this direct ROM table — consistent, not
   contradictory, across three fully independent methods now (statistical
   correlation, the live production-DB audit, and this bytecode table).
   One new lead worth flagging: the *goalie* Overall-widget suffix (decoded
   below) includes bit 2 (nibble 11) where the skater one doesn't — plausible
   but unconfirmed hint that nibble 11 might be a goalie-specific attribute
   invisible to any skater-only analysis, not investigated further this
   session.

   **The real prize: `Overall`'s own suffix is not a single bit — it's the
   bitwise OR of every nibble's bit that the independently-fit integer
   `OR_WEIGHTS` formula (derived via linear regression against the 2011
   GameFAQs data, see the "GameFAQs correlation" write-up earlier in this
   section, with zero awareness this bytecode table existed) assigned a
   nonzero weight to.** Computed directly, not by hand:
   `OR_WEIGHTS = {1:2, 2:2, 3:3, 4:1, 5:1, 6:1, 8:1, 9:2, 10:1, 11:0, 12:1,
   13:0}` → OR of `1<<(13-n)` for every `n` with nonzero weight = `0x1FBA`
   — **the exact skater `Overall` suffix found in the ROM, bit for bit.**
   The goalie table's `Overall` suffix (`0x130F`) decodes to nibbles
   `{1,4,5,10,11,12,13}`, a plausible but not yet independently-verified
   goalie-specific input set (no separate goalie weight vector was fit this
   session to cross-check against).

   **What this proves and what it still doesn't**: the *set of nibbles*
   Overall Rating depends on (10 of them, excluding 11 and 13) is now
   ROM-confirmed with zero ambiguity — not inferred from a third-party
   FAQ's noise, but read directly out of the game's own UI-widget bytecode.
   That is real, hard proof this project didn't have before this session.
   What's still open: the *exact integer weights* (is it really `2,2,3,1,
   1,1,1,2,1,1` or some other combination that happens to fit the FAQ data
   almost as well?) and the actual 68k arithmetic that consumes this
   bitmask to produce a number — this bitmask is very likely an argument to
   the same bytecode-interpreter handler family already found blocking
   deeper tracing (§7 item 1's `0x0008562C`/`0x000854B6` wall), telling that
   handler *which* nibbles to sum, not *how* to weight them. Fully cracking
   the weights would mean tracing that handler with this bitmask now known
   as a concrete, verified input to look for — a much narrower target than
   "trace an unknown interpreter" was before this.

   **Nibble 11 resolved, live — it's a goalie-only stat.** All prior named-
   stat correlation work explicitly excluded goalies (no external data
   existed for goalie named stats — checked this session: the nhl-95.com
   CSV has every named-stat column blank for all 54 goalie rows, only
   `ST Overall` is populated, and the GameFAQs FAQ text has no goalie
   attribute mentions beyond a single Rating number either — so a
   statistical correlation the way skaters got one simply isn't possible
   here). Instead, went straight to live verification: switched the Team
   Roster screen to its Goalies view for Vancouver (McLean, Whitmore) and
   read stats directly, cross-checking against the goalie-specific bytecode
   table decoded above.

   - **Agility** (nibble 1, shared bit with skaters): McLean nibble=4 →
     live 70 (predicted ~71 from the skater formula); Whitmore nibble=3 →
     live 50. Same direction, same rough scale as skaters — the mapping
     transfers as expected.
   - **Def. Awareness** (nibble 4, shared bit with skaters): McLean
     nibble=4 → live 78; Whitmore nibble=5 → live 97. Correct direction
     (higher nibble, higher stat).
   - **Glove Hand** (nibble 7 — the *other* previously-unexplained nibble,
     already identified as skaters' `Handed`): both goalies show
     categorical "Righty", not a number — confirms nibble 7 is a
     handedness field for goalies too, exactly consistent with its skater
     identity.
   - **Stick Left, the nibble-11 stat**: McLean nibble=4 → live **75**;
     Whitmore nibble=3 → live **57**. Clean, monotonic, and consistent with
     every other confirmed mapping this session (higher nibble, higher
     stat) — a 2-point line gives scale≈18/nibble, offset≈3, not
     independently statistically validated the way the ≥550-player skater
     fits were, but the *direction and identity* are as solid as any single
     live read in this document gets.

   **Net result**: nibble 11 is **not** unused or vestigial — it's a
   goalie-specific attribute (`Stick Left`, one of the six goalie-only
   stats: Glove Hand, Puck Control, Stick Right, Stick Left, Glove Right,
   Glove Left) that simply never appears in any skater-only analysis
   because skaters don't have it. Every one of the 14 nibbles in the
   7-byte attribute block now has a confirmed identity: 12 performance
   stats (shared or position-specific), 1 physical attribute (Weight,
   nibble 0), and 1 categorical handedness field (nibble 7). Nothing in
   this block is unexplained anymore.

7. **New lead, not yet investigated: faceoffs.** Explicitly out of scope for
   any work so far (see "Current status" in `CLAUDE.md`) — this is a
   starting point for a future, separately-scoped session, not a
   continuation of anything above. Raw string search on the ROM found the
   in-game UI text directly: `Face Off` at ROM `0x89CC6` and `0x89CD4`
   (likely two render contexts, e.g. period-start vs. whistle-stoppage —
   not yet distinguished), and `Faceoffs Won` (a stats-tracking label) at
   `0x924AA` and `0x9255C`. Static analysis comes up empty on both fronts
   tried so far: Ghidra finds **zero cross-references** to any of the four
   addresses (recursive-descent disassembly doesn't reach
   computed/indirect-jump call sites — see the CLAUDE.md gotcha), and a
   raw big-endian longword search for each address as a literal pointer
   also finds **zero hits** anywhere in the ROM (ruling out a simple
   flat string-pointer table). Both results are exactly the pattern already
   seen for Overall Rating's render path (§6 item 1) — strong circumstantial
   evidence the faceoff UI text renders through the *same* bytecode/
   jump-table interpreter already confirmed driving the Scouting Report and
   Team Roster screens, reached via computed dispatch rather than a direct
   call or literal address. **Recommended next step for whoever picks this
   up, with a real tooling constraint already checked**: BlastEm's 68k
   debugger has **no memory watchpoint / break-on-write capability at
   all** — confirmed by reading the full command switch in `debug.c` on the
   VM; only PC-address execution breakpoints (`b`/`c`/`n`/`s`) exist, plus
   `vs`/`vr` for VDP sprite-table/register dumps and nothing else
   VRAM-related. So "just watch for the write" (the obvious first idea)
   isn't directly executable with current tooling — the realistic path is
   the same laborious one that cracked hot/cold: trigger a real faceoff
   live (CPU vs CPU with both controllers parked under `CPU` is an easy way
   to get faceoffs happening with zero manual input), set a PC breakpoint
   somewhere plausible and well before the event, and single-step forward
   through real execution to find the actual code by hand, the way
   `0x0083E88`'s RNG loop was eventually found. Budget this as its own
   multi-step session, not a quick add-on. If solved, the natural follow-on
   question (mirroring hot/cold's "so what, who cares" framing)
   is whether faceoff win probability is driven by a specific player
   attribute — Agility and Off. Awareness are the most plausible
   candidates given their real-hockey analogues, but this is speculation
   pending an actual trace, not a finding.

8. **New lead, not yet investigated (mechanism), but text template fully
   decoded: injuries.** Suggested by the repo owner; confirmed real (not
   assumed — see item 5's fighting correction above for why that check
   matters) via the same raw-string technique: `Injury to:`, `Out for
   period`, `Out for game` all appear in the ROM (`0x09F2D5`-`0x09F33C`).
   Unlike the faceoff strings, these sit inside real, readable code — a
   **third distinct text-rendering pattern** in this ROM (different from
   both the simple string-table format earlier in this section and the
   intro's token-based message interpreter at `0x0A00F0`), built from the
   same self-patching primitive family already known from the CLAUDE.md
   gotchas (`0x7C6D4`/`0x7C810`/`0x7C822`/`0x7CCD2` all appear in this one
   block) plus the already-known digit-print routine (`0x0007D154`, same
   one used for Overall Rating).

   **Corrected a false lead from an earlier pass**: what first looked like
   literal text `"Out for 08"` was a `strings`-scan artifact — the `0` and
   `8` are the first two bytes of real code (`dc 6a 32 3c 00 01 4e b9 ...`)
   that happen to be coincidentally printable ASCII, not part of the
   string at all. The actual fixed text is just `"Out for "` (trailing
   space), followed by genuine templating logic: `jsr $0007D154` inserts
   the real duration number, then `CMPI.W #1,D1` / `BGT` branches between
   two `jsr $0007C810` calls with different inline text — `" game"`
   (singular) vs. `" games"` (plural) — correct English pluralization, not
   a fixed string per injury type. Full template: **"Injury to: [player],
   Out for [N] game(s)"**.

   Still open: what triggers an injury, and where the duration value
   itself is computed/stored — both need live tracing, not more static
   analysis (the same "no memory watchpoints" constraint documented for
   faceoffs in item 7 applies here too). Full byte dumps and the correction
   above in GitHub issue #9.

   **Follow-up session: tried the "let genuine CPU-vs-CPU play run and
   catch the event" approach that worked for issue #10's goal — watched a
   full 3-period game end to end (see §3's box score), zero injuries
   occurred.** A useful negative data point, not a dead end: it suggests
   injuries are a genuinely low-probability per-body-check event, not
   something a single ~30-minute game reliably produces. Narrowed rather
   than closed: the concrete next step is finding a live WRAM signal for
   "an injury just happened" (the same kind of gap clock/period had before
   value-matching cracked them, see item 11) and then using
   `tools/nhl95_monitor.py` to poll across *many* auto-run games instead of
   watching one — not pursued further this session, see issue #9.

   **Later session: tested the specific hypothesis that Exhibition mode's
   zero-injury result was unfair, since Exhibition has no `Injuries` toggle
   at all — only Season mode's own `SEASON SETUP` screen does (`Off` /
   `Single game` / `Multi-game`).** Started a real `New Season`, confirmed
   `Injuries` defaults to **`Multi-game`** already (no change needed),
   then played a genuine CPU-vs-CPU Season game (Quebec @ Ottawa, both
   controllers parked under `CPU`) end to end through a full scoreless
   3-period regulation **and** sudden-death overtime (Ottawa's Yashin won
   it 1-0, assisted by Rumble, at OT 2:11) — zero injuries, same outcome as
   the Exhibition test. This is a second negative data point with the
   *fairest possible* setting (Injuries explicitly on, not defaulted off),
   which weakens rather than supports the "Exhibition just lacks the
   toggle" hypothesis — the more likely explanation remains the
   already-documented one: injuries are simply a low-probability
   per-body-check event that two individual games, regardless of mode,
   aren't guaranteed to produce. Reinforces rather than changes the
   recommended next step above (WRAM signal + bulk unattended runs via
   `tools/nhl95_monitor.py`), which is what this session moved on to next
   — see the tooling note in GitHub issue #9.

   **Bonus, incidental finding from this same game**: this is this
   project's first live-confirmed sudden-death overtime, in Season mode
   with a 5-minute-period `Per. Length` setting — the OT clock counted
   down from a separate allotment (not a continuation of the 3rd period's
   clock), confirming OT is its own timed period, not unlimited sudden
   death. Not chased further (outside this item's scope), but worth a
   pointer for whoever next asks "how does overtime actually work here."

   **Same session, immediately after: the entire injury-trigger mechanism
   was cracked statically, unprompted by any particular live event** — a
   static-analysis detour that turned out to fully answer "what triggers
   an injury," which the two live-play attempts above couldn't. Found by
   force-disassembling the ROM immediately *before* the `Injury to:` text
   block (`0x9F260`-`0x9F142`, via `tools/ghidra/DumpRange.java`) and
   noticing a self-contained helper at `0x9F26A` with the unmistakable
   percent-chance shape already established for hot/cold in §5
   (`move.w #0x64,D0w` / `jsr $0007C63A` / `btst.l #0x1,D0`) sitting right
   next to the announcement text. A raw byte-pattern search of the ROM for
   `jsr $0009F26A` (`4E B9 00 09 F2 6A`) found **exactly one call site**,
   at `0x9F0B0` — a single, dedicated caller, not a shared utility reused
   elsewhere, which is exactly the kind of clean lead this project's past
   wins (Team Stats struct, Overall Rating bitmask) have come from. The
   full routine around that call site (`0x9F040`-`0x9F142`) decodes to a
   complete, gated injury-eligibility check:

   1. `(0x62,A2)` bit 6 picks which team's stats-struct base becomes `A0`
      (`0xFFFFC288` away / `+0x366` = `0xFFFFC5EE` home — the exact two
      addresses already confirmed in item 9 below) — this event is scoped
      to one specific team/player, not global.
   2. `($FFFFBF10).w` bit 1, if already set, skips the *entire* routine —
      a **debounce latch**: this same body-check event won't be re-rolled
      twice. It only gets set again at the very end (step 8), so it must
      be cleared somewhere else per new hit (not yet traced).
   3. A helper at `0x9F260` reads `(0x74,A2)` (byte) `>> 2` from whatever
      struct `A2` points to for this event; a nonzero result also skips
      the routine — read as "this player/hit is already in some
      cooldown/other state, don't double-roll."
   4. `cmp.w #0x3,D0w` / `beq` on the *previous* check's result value
      branches around a `team_struct[D1]+0x68 = -3` write straight to the
      **first real chance roll**: `jsr $0009F26A` (the percent helper
      found above) — `beq` on its result means "roll failed, bail out."
      This is the actual **"was this hit hard enough to risk an
      injury"** check.
   5. On a successful roll: `team_struct[D1]+0x68` gets overwritten again,
      `-3` → `-4` — a small state-machine value in a per-player-or-line
      slot array (index `D1` = `2 × (byte at (0x66,A2))`), plausibly a
      hit-stun/recovery counter being repurposed as an injury-in-progress
      marker. Not fully identified; flagged for a future session.
   6. **Two more gate flags must both be set to continue**:
      `($FFFFBF08).w` bit 3, then `($FFFFD1A7).w` bit 2 — strong
      candidates for "Injuries setting is not Off" and a related
      game-mode/period-context gate respectively, though which bit maps
      to which `SEASON SETUP` menu state (`Off`/`Single game`/
      `Multi-game`) is not yet live-confirmed.
   7. **A second, independent 50% coin-flip**: `D0=100`, `jsr $0007C63A`,
      `cmp.w #0x32,D0w` (50) / `blt` bails below 50 — so even a
      hit that clears every gate above only actually produces an injury
      **half the time**. Combined with step 4's own percent-roll, this is
      a *compound* low-probability event (two independent rolls, not
      one) — which on its own already explains why full live games keep
      coming back scoreless-for-injuries: the two negative live results
      above aren't surprising in hindsight, they're the expected outcome
      of a deliberately rare, doubly-gated mechanic.
   8. **Injury duration, computed live, not fixed per injury type**:
      `D0 = ($FFFFD1A5) − ($FFFFD1A6)` (two live bytes, plausible
      candidates for the current Season's min/max injury-length bounds,
      themselves plausibly tied to the `Single game`/`Multi-game`
      setting), clamped to the range `2..6`, then run through the same
      `$0007C63A` "roll bounded by D0" helper and `+1`'d — producing a
      final duration of roughly **1 to 5 games**. This is the exact
      number that ends up in the already-decoded `"Injury to: [player],
      Out for [N] game(s)"` template (item 8 above/§ elsewhere in this
      list). `$FFFFBF10` bit 1 is set here (closing the loop with step 2's
      debounce), and `jsr $0009F1EA` is called with the computed duration
      in `D0`, a team-level field (`team_struct+0x28`) in `D7`, and a
      player-index-derived value in `D1` — almost certainly the actual
      "write injured status to the roster + trigger the on-screen
      announcement" routine. `0x9F1EA` itself is not yet traced.

   **Why this matters beyond just this one item**: this is the first time
   this project has found a *compound probability gate* (two independent
   rolls plus three flag checks) behind a rare event, rather than the
   single-roll pattern established for hot/cold in §5 — a useful
   reminder that "I ran one game and didn't see X" is weak evidence for
   *any* rare mechanic in this ROM, not just injuries, until the actual
   odds are known. **Concretely scoped next step**: breakpoint
   `0x9F136` (the `jsr $0009F1EA` call site) fires if and only if an
   injury has actually been fully approved — far rarer than the
   `0x9F0B0`/`0x9F26A` first roll, but a clean, unambiguous "an injury
   just happened" signal that the earlier screenshot-watching approach
   never had. Pending live confirmation: set that breakpoint, run bulk
   unattended CPU-vs-CPU games via `runframes`, and when it fires, read
   `D0`/`D1`/`D7` and dump `($FFFFD1A5)`/`($FFFFD1A6)`/`($FFFFBF08)`/
   `($FFFFD1A7)` to confirm the gate-flag and duration hypotheses above
   against real values, then correlate against the next `Injury to:`
   text that actually renders.

9. **Score/Shots RAM addresses — solved, live-confirmed against two real
   goals.** Built for `tools/nhl95_monitor.py` (the unattended CPU-vs-CPU
   instrumentation tool — see §1), which needed to know where the score
   lives so it can catch scoring events without a human watching the
   screen. A first attempt cast a wide net around two candidate addresses
   left over from an unrelated earlier session and watched ~16 real
   minutes of CPU-vs-CPU play with no goal scored — inconclusive, not
   negative, but not efficient either (see GitHub issue #11's opening
   comment).

   The static side of this was already half-solved and just hadn't been
   pushed far enough: the per-game stats screen's label table at ROM
   `0x092410` (`Score`, `Shots`, `Shooting Pct`, `Power Play`, ... — first
   surfaced while chasing item 1's Overall Rating bitmask, see §6) uses the
   same `[u16 length][text, even-padded][u16 suffix]` string-record
   pattern already decoded there, but this table's suffix field turned out
   to mean something different: not a nibble-selector bitmask, but a
   **byte offset into a per-team stats struct** — confirmed by the values
   themselves forming a clean, non-overlapping layout once decoded in full
   (`tools/rom_scan.py parse_string_records` plus a small standalone
   parser for this table's `[length][text][suffix][extra]` framing, extra
   being a second offset for two-part stats):

   | stat | offset | extra |
   |---|---|---|
   | Shots | `0x00` | — |
   | Power Play (goals / opportunities) | `0x02` | `0x04` |
   | Penalties | `0x06` | `0x08` |
   | Attack Zone | `0x0A` | — |
   | **Score** | **`0x0C`** | — |
   | Faceoffs Won | `0x0E` | — |
   | Body Checks | `0x10` | — |
   | Passing | `0x14` | `0x12` |
   | Shooting Pct | *(computed, no offset — suffix/extra both `0xFFFF`)* | |

   (Missed `Passing` in the first pass through this table — caught while
   re-running the smarter scanner for item 10 below, which lists the whole
   table's entries automatically instead of relying on a manual transcription.
   The table also repeats a second time immediately after `Attack Zone`
   (`Score`/`Shots`/`Shooting Pct`/`Breakaways`/.../`Passing` again, missing
   `Power Play`/`PP Minutes`/`PP Shots`/`SH Goals` this time) — not
   investigated further, but flagging so nobody assumes the table is
   single-instance.)

   (`PP Minutes`/`PP Shots`/`SH Goals`/`Breakaways`/`One-Timers`/`Penalty
   Shots` use much larger offsets, `0x0354`-`0x0364` — almost certainly a
   *different*, later structure, plausibly a per-event "which player did
   this" reference table for the end-game box score/three-stars rather
   than a simple per-team counter. Not investigated further; flagging so
   nobody assumes it's the same struct.)

   With real offsets in hand, the only unknown left was the struct's
   *base* address — and the fastest live test isn't waiting for a goal,
   it's waiting for a **shot**, which happens within seconds rather than
   minutes. Read the two candidate bases left over from the first attempt
   (`0xFFFFC288`, `0xFFFFC5EE`) right after the opening faceoff (both
   `+0x00` = 0, plausible pre-shot) — then, remarkably, a real goal
   happened almost immediately (Courtnall from Ronning, `VAN 1 - ASE 0` at
   19:51 in the 1st): `0xFFFFC5EE+0x0C` read exactly **1**, byte-for-byte
   matching the on-screen score. Continued play produced a second VAN goal
   and the away team's first shots; final cross-check against a
   screenshot showing **`VAN 2 - ASE 2`** matched `0xFFFFC5EE+0x0C = 2`
   and `0xFFFFC288+0x0C = 2` exactly, and the Faceoffs-Won/Body-Checks
   offsets read plausible small numbers on both sides too. Full struct
   confirmed, not just the Score field.

   **Confidence: high on the offsets (directly decoded from ROM, not
   guessed), high on the values for this session (multiple exact matches
   against the on-screen scoreboard across two real goals).** Lower on
   whether `0xFFFFC288`/`0xFFFFC5EE` are *universal* home/away struct
   addresses versus this-session-specific slots in a small fixed array —
   this project has already been burned once by assuming a "home/away"
   label was positionally fixed rather than tied to the real home team
   (see the CLAUDE.md gotcha about ROM `0x3618`/`0x4FFA`); worth
   re-verifying with a different matchup/boot before fully trusting these
   two specific addresses as permanent. `tools/nhl95_monitor.py`'s
   `WATCH_ADDRESSES` now uses the confirmed offsets. See GitHub issue #11.

10. **Smarter UI-widget string-table scan (issue #8) — a complete penalty
    catalog, the full team-strength rating category list, and more, found
    purely statically.** Issue #8 asked for a smarter scan of the string-
    record format decoded in §6/§7#9, anchored to the interpreter code
    region (`0x080000`-`0x0A0000`) instead of the whole 2MB ROM, filtering
    for plausible suffix values instead of trusting every printable-looking
    hit. Built one (`tools/rom_scan.py`'s validators, generalized), and
    required hits to cluster into runs of 3+ consecutive valid records —
    isolated single hits are almost always coincidental graphics/tile
    bytes; every genuine table found so far (rating widgets, Face Off,
    stats labels) is several entries in a row. That one filter took the
    scan from drowning in noise to 9 clean, real tables.

    **Complete penalty-type catalog** (ROM `0x089CE0`-`0x089F26`, immediately
    after the `Face Off` strings already known from item 7): **Charging,
    Slashing, Tripping, Roughing, Hooking, Cross Check, Interference,
    Holding, Fighting**, plus a `Fighting *` variant. Every entry uses the
    same `suffix = 0x0004`, strongly suggesting it's a format/category tag
    for "this is a penalty-name label" (the same role the varying `tag`
    byte plays in the rating-widget table), not real per-penalty game data
    like minutes — a plausible explanation for why it doesn't vary between
    Charging and Fighting despite very different real-world penalty
    lengths. Charging/Slashing/Tripping/Hooking/Cross Check/Interference
    each appear in the ROM **exactly twice**, Roughing **three times** —
    plausibly two-or-three separate render contexts (e.g. a penalty-box
    popup vs. a penalty-summary list vs. a play-by-play line), the same
    pattern already flagged for the doubled `Face Off` strings in item 7.
    This fully supersedes the earlier one-off finding that "Fighting"
    merely *exists* in the ROM as a penalty type (see the CLAUDE.md
    fighting-mechanic correction) — it's now a complete, addressed catalog.

    **Full team-strength rating category list** (ROM `0x09F9C4`-`0x09FA52`,
    the source table for the Scouting Report's "Advantage: [category]"
    cycling display — see the `sh7.png` screenshot from this session
    showing "Advantage: Overall"): **Shooting, Passing, Checking,
    Goalkeeping, Skating, Defense, Fighting, Power Play Adv., Overall** —
    9 categories total, completing what CLAUDE.md's "Current status" note
    could previously only partially name. Suffixes here are small
    multi-bit values (`0x000A`, `0x000E`, `0x001A`, ...), not single bits —
    plausible but unconfirmed hint that these team-strength ratings use
    the *same* OR-of-nibble-bits scheme already fully solved for player
    Overall Rating (§6), just composed from different (team-level, not
    per-player) source bytes. Not traced further this session.

    **"Three Stars" criteria table** (ROM `0x096216`-`0x09623A`): `ASSISTS`,
    `SAVES`, `GOALS` — matches the standard real-hockey three-stars
    selection criteria exactly, a clean, high-confidence identification
    even without live confirmation.

    **A third table format, found while chasing down the two tables below
    — no separate suffix field at all.** Both looked malformed at first
    against the `[header][text][suffix]` shape already known from the
    penalty/team-strength/stats tables — the apparent "suffix" bytes kept
    reading as the *next* entry's own header. That's exactly what they
    are: this table family has **no suffix**, and the header's length byte
    counts the *entire* record including itself (`stride = length`, not
    `2 + length`), with text space-padded (not null-padded, unlike the
    months table below) to exactly fill the record. Once decoded with the
    right stride formula both tables resolved completely and cleanly:

    **Injury-status abbreviation table**, fully decoded (ROM `0x085556`-
    `0x0855E4`): `Bench`, `Inj. P`, `Inj. G`, a blank 4-space entry,
    **` C  `**, `Inj. G` again, then `Inj.1G` through `Inj.9G`. Very
    plausibly the Team Roster `Status` column's injured-player display
    (a natural companion
    to the `Injury to: [player], Out for [N] game(s)` announcement text
    from item 8) — issue #9 previously had no lead at all on this UI
    surface. The lone `" C  "` entry sitting in the middle, distinct from
    every `Inj.*`/`Bench` status, is a plausible **team captain marker**
    (the "C" patch shown next to a captain's name) — consistent with
    hockey UI convention, not confirmed live.

    **Independently confirmed against the official manual**, found later
    the same session (the repo owner linked the US Genesis manual,
    `segaretro.org`'s scanned PDF): page 21, under the Team Roster
    `Status` column documentation, states verbatim — *"If a player is
    injured, 'Injury' appears as his status. A 'P' after injury indicates
    'out for the period', while a 'G' indicates 'out for the game'. '4G'
    indicates a four-game injury."* An exact match for the ROM's own
    `Inj. P`/`Inj. G`/`Inj.1G`-`Inj.9G` table, upgrading this from a
    plausible inference to a manual-confirmed identification. The manual
    doesn't mention the `" C  "` entry specifically, so the captain-marker
    guess remains unconfirmed. (The manual PDF itself isn't checked into
    this repo — copyrighted EA/Sega material, same as the other raw
    third-party sources in `.gitignore` — but it's now a citable source
    for claims like this one.)

    **Months table, fully decoded** (ROM `0x08F1E6`-`0x08F228`): `October`,
    `November`, `December`, `January`, `February`, `March`, `April` — 7
    entries, stopping cleanly at April rather than trailing off
    (regular-season months for a 1994 game, not the full calendar year) —
    plausibly a Season-mode calendar/schedule table.

    **Goalie stat-cycle table, also fully resolved** (ROM `0x092AD0`-
    `0x092B94`, same stride format as above once the parser's length cap
    was widened past 20): a compact header row `Saves Shots Save %  `,
    single/short column abbreviations `G`, `A`, `Pts`, `SOG`, `PIM`, then
    the same bracketed `[ Category ]` widget style already known from the
    skater/goalie *attribute* cycle (§6's `[Energy]`/`[Agility]`/...) —
    but for a goalie's *offensive* stat cycle instead: `[ Goals ]`,
    `[ Assists ]`, `[ Points ]`, `[ Shots On Goal ]`, `[ Penalty
    Minutes ]` (plus a `    Goalie Saves   ]` entry immediately before
    them, oddly missing its opening bracket in the ROM data itself — not a
    parsing artifact, the four leading bytes there really are spaces, not
    `[`). Confirms this game tracks goals/assists/points for goalies as a
    real stat cycle, not just saves/save % — a fun, hockey-nerdy detail
    (goalie goals and assists are rare but real in the NHL) that wasn't
    previously known to exist in this ROM's data. Not yet found live on
    any explored screen; the Team Roster's existing goalie attribute cycle
    (§6) is a plausible place a second, stat-focused cycle could live,
    unconfirmed.

    See GitHub issue #8 for the full scan output.

11. **Clock and Period RAM addresses — both solved, both live-confirmed
    against real transitions. Issue #11 fully closed** (§7#9 solved
    Score/Shots; this closes the other half). Static analysis had already
    flagged the "Period Stats"
    bytecode block near ROM `0x094FE0` as an end-of-period box-score
    renderer, but that turned out to be the wrong target — it's a
    *summary* display, not the live per-frame HUD clock. No amount of
    xref-searching was going to find the real render call either (checked
    — zero xrefs to any of these table addresses, same computed-dispatch
    pattern as everything else in this ROM's UI system), so this one
    needed a different approach than the rest of item 10: **value
    matching** against a live screenshot instead of tracing code.

    With a real CPU-vs-CPU game showing `1ST 16:49` on screen, computed
    every plausible encoding of that value (BCD word, total-seconds word,
    frame count) and wrote a small scanner
    (`tools/nhl95_daemon.py`-adjacent, ad hoc for this search) that reads
    a wide WRAM window word-by-word over the existing debugger socket,
    checking each against the candidate list. One clean hit: **`0xFFFFC022`
    (word) = `0x03F1` = 1009 decimal = 16×60+49 — exactly the displayed
    clock, stored as total seconds remaining in the period.** Confirmed a
    second time completely independently: after letting more game time
    pass, `0xFFFFC022` read `0x03E5` (997 = 16:37) and later `0x0390` (912
    = 15:12), both matching a fresh screenshot exactly, byte-for-byte,
    with the score struct (§7#9) simultaneously confirmed still correct
    on the same screenshots (`ASE` scored again mid-check, `VAN 2 - ASE
    3` matched live memory too).

    **Period — solved, live-confirmed against a real transition, but not
    at the address first suspected.** The first candidate tried,
    `0xFFFFC02A` (byte), read `0x01` rock-stable for the entire 1st
    period — a promising sign — but a batch live run set up specifically
    to watch it through a real period boundary caught it changing to
    `0x80` at the transition, not the clean `0x02` a simple 1-indexed
    counter would predict. That was the signal to stop trusting the
    single candidate and instead diff the *whole* surrounding struct
    (`0xFFFFC000`-`0xFFFFC040`) between a period-1 and a period-2 reading.
    One field stood out immediately: **`0xFFFFC021` (byte) went cleanly
    `0x00` → `0x01`** — a 0-indexed period counter (0 = 1st, 1 = 2nd),
    sitting right next to the confirmed clock field (`0xFFFFC022`) in the
    same small match-timing struct, exactly where a period counter would
    structurally belong. Whatever `0xFFFFC02A` actually is, it isn't the
    period number — a real false lead caught by verifying instead of
    accepting the first plausible-looking stable byte. `0xFFFFC026`
    (word) = `0x04B0` = 1200 decimal = 20.0 minutes stayed unchanged
    across the transition, confirming it's period *length* (constant),
    not period number, exactly as suspected.

    Pushed for a second, independent confirmation rather than resting on
    one transition: a further live run watched a real 2nd→3rd boundary
    too. Clock reset cleanly again (`0x0002`→`0x04B0`, i.e. 0:02→20:00
    fresh), and `0xFFFFC021` went `0x01`→`0x02` — a second clean,
    sequential, 0-indexed step, exactly as predicted. This one came with
    an unplanned bonus confirmation: the captured screenshot happened to
    land on the pause menu's `STATS` tab, which shows a literal `1st /
    2nd / 3rd` period indicator with a dot per period — the dot had moved
    to **`3rd`**, an entirely independent, human-readable confirmation of
    the exact same fact the memory read reported, at the exact same
    moment. Both Clock and Period are now confirmed against two
    real transitions each, the same evidentiary tier as Score/Shots (§7#9).

    `tools/nhl95_monitor.py`'s `WATCH_ADDRESSES` includes `clock_seconds`,
    `period`, and `period_length_seconds`, all confirmed, alongside the
    existing Score/Shots entries.

12. **Season-mode end-of-season awards table (issue #12) — fully decoded
    statically, live-reachability partially checked.** Flagged as a lead
    during item 10's scan (found near an unrelated table, only partially
    visible in that scan's window) but not chased at the time. Widening the
    scan window (ROM `0x09C600`-`0x09CC00`) and re-parsing found the
    complete table — but it needed a **fourth string-record format**, not
    the "plain" `[u16 length][text][u16 suffix]` shape the original quick
    check guessed: this table has **no suffix field at all**, just
    `[0x00][u16 length][text, even-padded]` with `length` counting the
    2-byte header plus text (`stride = length`). That's structurally the
    *same* no-suffix convention already known from the injury-status and
    months tables (item 10), just with a 2-byte length field there instead
    of the 1-byte one those tables used — a real gotcha: naively reusing
    `parse_stride_records` (which hard-codes a 1-byte length check) finds
    nothing here, because its strict same-position, no-byte-skipping scan
    never lands on a valid header when the header shape itself is
    different. A one-off 2-byte-length variant of the same scan found the
    complete table cleanly.

    **Nine real trophies, in ROM order** (`0x09C81E`-`0x09C8DC`): `HART
    MEMORIAL TROPHY`, `JAMES NORRIS TROPHY`, `VEZINA TROPHY`, `ART ROSS
    TROPHY`, `WILLIAM JENNINGS TROPHY`, `LESTER B. PEARSON AWARD`, `FRANK
    SELKE AWARD`, `PRESIDENTS TROPHY`, `CONN SMYTHE AWARD` — the complete,
    real 1994-95 NHL awards slate, not a fictionalized subset. Immediately
    followed by their award-criteria description strings, in the same
    order (`0x09C8DC`-`0x09C9DE`): `Most Valuable Player`, `Best
    Defenseman`, `Best Goalkeeper`, `Most Points`, `Goalie with Fewest
    Goals Against`, `NHLPA Most Valuable Player`, `Best Defensive
    Forward`, `Team with Best Regular Season Record`, `Most Valuable
    Player` + `In Playoffs` (Conn Smythe's two-part qualifier) — matching
    each trophy to its real-world criteria exactly (Norris↔defenseman,
    Vezina↔goalkeeper, Art Ross↔points, Jennings↔goals against,
    Selke↔defensive forward, Presidents↔regular-season record, Conn
    Smythe↔playoff MVP). A few blank/space-only records are interleaved
    (visible in the raw parse) — plausibly layout spacers for the
    presentation screen, not missing data.

    **Live-reachability: checked, inconclusive rather than confirmed.**
    Season mode's `SEASON OPTIONS` hub has an `End Season After Today`
    item that looked like a promising shortcut to test this without an
    84-game playthrough — and it does work as a shortcut in the sense that
    selecting it (then `Play Games`) genuinely ends the regular season
    instantly and swaps the whole `SEASON OPTIONS` menu for a shorter
    post-season one topped by `On To Playoffs`, no 84-game grind needed.
    But confirming that and stepping `On To Playoffs` went **straight into
    a real Playoffs Day 1 bracket** (St. Louis/Dallas, Chicago/Anaheim,
    Vancouver/Edmonton) with no awards presentation shown in between. This
    doesn't rule out the table being live-reachable — the presentation may
    only fire after actually completing the *playoffs* too (Conn Smythe
    specifically needs a playoff MVP, which can't be known before a
    champion exists), or `End Season After Today`'s fast-forward path may
    itself skip a ceremony that a natural 84-game completion would trigger
    — but running the single-game, 5-minute-period playoff bracket to a
    real Cup winner to check is a genuinely open-ended follow-up, not
    attempted this session. Recorded as a real, useful negative data point
    rather than left unchecked.

---

## 8. Game modes — mapped via live exploration and the official manual

Prompted by the repo owner naming a mode this project hadn't found yet
(Shootout) and asking for a fuller pass across every game mode, including
trades/season/playoffs. Two sources converged here: live exploration of
the `Play Mode` field on the pre-game settings screen (the same screen
documented in the Environment section of CLAUDE.md), and the official US
Genesis manual (a scanned PDF the repo owner linked from `segaretro.org`
— copyrighted EA/Sega material, gitignored, not redistributed in this
repo, but now a citable source for claims like this section's).

### 8.1 The full `Play Mode` list

Cycling the field live (Right repeatedly) goes through **11 directly
selectable modes** before wrapping back to the start:

**Regular Game → Practice Mode → New Playoffs → New Playoffs/Best of 7 →
New Season → Trade Players → Create Player → Sign Free Agents → Release
Players → Shootout → Game With Trades →** *(wraps to Regular Game)*

The manual (p.6) documents two more that only appear *conditionally* —
consistent with never seeing them during live cycling from a fresh boot:

- **Continue Playoffs** — appears only after winning a playoff series
  (see 8.3).
- **Continue Season** — appears only once a season is in progress.

Manual descriptions, verbatim, for the ones not detailed further below:
*Practice Mode* — "Set up a practice session with up to two skaters (plus
goalie) per side." *Create Player* — create a new player saved to the
free-agent list (36-99 rating range, assigned per-attribute). *Sign Free
Agents* / *Release Players* — move players between team rosters and the
free-agent pool. *Game With Trades* — "Play a single game using the teams
altered by trades you have made" (i.e. Regular Game, but respecting
whatever roster edits Trade Players already made — not chased live this
session).

### 8.2 Shootout — real, live-confirmed, and richer than the static find suggested

Item 10 found `SHOOTOUT MODE`/`Round `/`SHOOTOUT WON BY [team]` text
sitting in real code at ROM `0x09DFD5` and filed it as an open lead
(issue #14), guessing it might be conditional on a tied game. Live
testing found it's actually **both**: a directly selectable Play Mode
(for practicing/testing shootouts on demand — `Per. Length` reads `N/A`
for this mode, since it has none), *and* — per a repo-owner correction —
the real tie-breaker after a scoreless overtime period in normal play.
One nuance worth flagging: the manual's own **Period Length** section
(p.6) states a Regular Season game's overtime "lasts for ten minutes, or
until one team scores ('sudden death'). If neither team scores, the game
ends in a tie" — no shootout mentioned as an automatic follow-up for
Regular Season games specifically. Not independently reconciled this
session (would need to actually play out a scoreless Regular Season OT to
see what really happens) — recorded as a real discrepancy between what
the manual states and what a knowledgeable player recalls, not resolved
either way.

Confirmed live, end to end:
- **Roster/goalie setup**: selecting Shootout leads through the normal
  Controller Setup screen, then a pause-menu item unique to this mode
  (`SHOOTOUT SETUP`, absent from every other mode's pause menu — see
  8.4) opens a dedicated screen: team name + "SHOOTOUT" header, a
  `Shooters`/`Goalie` list (5 shooters, reorderable, plus the starting
  goalie).
- **HUD**: no period/clock display at all (consistent with `Per. Length:
  N/A`) — just team abbreviations and a running score (`LA 0 / ANH 0`).
- **Per-attempt structure**: each attempt opens with a full-screen
  `SHOOTOUT MODE` card naming the exact shooter and goalie by jersey
  number and name (`25 T. Yake vs. 32 K. Hrudey`), the running score, and
  a `Round N` counter — a direct, byte-for-byte live match to the ROM
  text found in item 10 the same session.
- **Shot clock**: a real per-attempt countdown timer (started at `0:25`
  in the attempts observed), separate from the game clock.
- **Turn order**: alternates between the two teams within the same round
  (Anaheim's shooter attempted first, then Los Angeles's, both still
  labeled `Round 1`) rather than each team taking a full round before the
  other goes.

**Follow-up: the no-goal resolution cycle is now confirmed too.** A
second attempt (Chicago's Murphy vs. Detroit's Essensa, `Goalies: Auto
Control` this time) skated in and took a shot with `C`; the attempt
resolved with a referee cutaway (the same face-off-style ref window seen
elsewhere in this ROM) and the score stayed `0-0` on both the HUD and the
next shooter's setup card — confirming the miss/save → referee signal →
next-shooter transition works exactly like a real shootout round, without
needing to distinguish "missed the net" from "goalie made the save" (both
plausibly route through the same no-goal path).

A third attempt (Detroit's real-life sniper Dino Ciccarelli vs. Chicago's
Ed Belfour) produced a genuine, unambiguous **puck-in-flight shot
animation** — the puck visibly airborne between the shooter and the
goalie for several frames, a clearly different visual state from a pass
or a whiff — followed by the same referee-cutaway no-goal resolution,
with the goalie shown holding the puck (a possession indicator) right
after. A fourth attempt against the same goalie produced the identical
outcome. Both shots stopped by Belfour specifically is a fitting result
rather than a frustrating one: the Trade Players screen (§8.4) already
live-confirmed Belfour's Overall Rating at **98**, the highest of any
goalie seen this session — the ROM's own data says he should be
extremely hard to beat, and two real attempts sampled that exactly.

Landing an actual goal to see the scoring-side animation/HUD update
remains a real, narrow, unclosed gap — but it's now clearly a matter of
shot execution (or facing a lesser goalie) rather than any uncertainty
about the mode's mechanics. The full structural cycle (setup → per-
attempt card → shot-in-flight → resolution → next shooter → eventual
`SHOOTOUT WON BY`) is traced end to end, with a real shot animation now
directly observed.

### 8.3 Season and Playoffs — the full manual-documented flow, live-confirmed screen by screen

**Season** (`New Season`): confirmed the complete flow named in
CLAUDE.md's existing notes, now with every screen actually seen:
`SEASON SETUP` (`Period Length`/`Penalties`/`Line Changes`/`Playoffs:
Single Game or Best of 7`/`Injuries: Off, Single game, or Multi-game`) →
`GAMES TODAY` (a real schedule day, e.g. "October 5": Boston at New York,
Pittsburgh at Philadelphia, Detroit at Dallas — the last one a fresh
reconfirmation of the Dallas-via-Season-mode finding from §2.1/§7#3) →
`SEASON OPTIONS`, a 10-item hub matching the manual (p.20-21) exactly:
`Play Games`, `Play Until A Day`, `NHL Standings`, `Team Schedule
Calendar`, `Games Today`, `League Leaders`, `Team Stats`, `Player Stats`,
`Highlights`, `End Season After Today`. Checked `NHL Standings` live: a
real divisional structure (`WESTERN CONFERENCE` / `PACIFIC DIV.`:
Anaheim, Calgary, Edmonton, Los Angeles, San Jose, Vancouver, all `0-0-0`
on a fresh season) with `GR` (games remaining) reading **84** — matching
the real 1993-94 NHL's 84-game regular-season length. `End Season After
Today` is a genuine fast-forward shortcut, not a no-op — see §7 item 12
for what selecting it actually does (skips straight to a post-season
`SEASON OPTIONS` menu topped by `On To Playoffs`) and the awards-table
live-reachability check that motivated trying it.

**Playoffs** (`New Playoffs`): Controller Setup → a full 16-team
**playoff bracket screen with a rendered Stanley Cup graphic** in the
center (previously completely undocumented) — 8 first-round matchups
shown two-conference-side-by-side (confirmed: Edmonton/Toronto,
San Jose/Dallas, Anaheim/Chicago, Winnipeg/Vancouver on one side;
Tampa Bay/Montreal, Ottawa/Boston, Pittsburgh/Florida, New York/Quebec on
the other), with the player's selected Team 1 highlighted — matches the
manual's note that "only Team 1... can advance through the playoffs."
Confirming a pairing leads into the normal Scouting Report → gameplay
flow, same as Exhibition. `Continue Playoffs` (see 8.1) becomes available
after winning a series, per the manual's "Saving the Playoff Tree"
section (p.23) — not tested live this session (would require actually
winning a full series).

### 8.4 Trade Players — and an unplanned lead for the Overall Rating research (issue #2)

Confirmed the full manual-documented flow (p.11): select `Trade Players`,
choose the two trading teams, and a **`TRADE PLAYER` screen shows both
rosters' names, positions, and Overall Ratings side by side** — e.g.
Anaheim's Hebert (G, 52) down to VanAllen (F, 48) against Chicago's
Belfour (G, **98**) and Roenick (F, **94**). `C` marks a player for trade
(a checkmark appears next to their name); the manual's remaining steps
(switch teams with `A`, pick the matching player, confirm with `Start`)
complete the swap.

**Worth flagging for issue #2** (the still-open exact Overall Rating
storage/opcode question): this screen renders every player's Overall
Rating as plain, directly-readable text for an entire two-team roster at
once, without needing to cycle the Team Roster's stat category one player
at a time. If this screen's render path turns out to be simpler than the
bytecode-interpreter call sites already hit twice (Scouting Report, Team
Roster — see §6 item 1), it could be a faster route to finally tracing
the *exact* consuming opcode, or at minimum a much faster way to
bulk-collect live Overall Rating ground truth for future statistical
cross-checks. Not traced this session — a concrete lead, not a finding.

### 8.5 Full pre-game/pause menu — fully mapped and closed (issue #13, closed)

Live-confirmed that a **normal, non-tied Regular Game's** pause
`OPTIONS` tab scrolls through exactly: `RESUME GAME`, `INSTANT REPLAY`,
`EDIT LINES`, `CHANGE GOALIE`, `MANUAL GOALIE`, `TIMEOUT`, `ABORT GAME`
(7 items, confirmed by scrolling to both ends of the list). `SHOOTOUT
SETUP` does **not** appear here — it only appears when `Play Mode:
Shootout` is active (confirmed in 8.2).

The remaining static-only items turned out to belong to a *different*
tab entirely: the pause menu's **`STATS` tab** (separate from `OPTIONS`)
holds `GAME STATS`, `PERIOD STATS`, `PLAYER STATS` in every mode, plus a
4th item, `PLAYOFF STATS`, that only appears during a Playoffs-mode game
— confirmed live the same way `SHOOTOUT SETUP` was, by starting a real
Playoffs game and scrolling the `STATS` tab. This fully explains the
static scan's longer list: it was a union of the `OPTIONS` tab, the
`STATS` tab, and (by strong but not independently re-confirmed analogy)
the `INFO` tab's `TEAM ROSTER`/`SCORING SUMMARY`/`RECORD HOLDERS` items,
across several different modes' menu states — not one master list ever
shown all at once. `SEASON PLAYERS`/`SEASON TEAMS` are presumed to be the
same `STATS`-tab pattern as `PLAYOFF STATS`, just for Season mode instead
of Playoffs — a reasonable inference from the now-confirmed pattern,
not independently checked live.
