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

**Menu→ROM order, fully mapped live (see §7#3 for the investigation).** The
in-game Team 1/Team 2 exhibition selector cycles in *exactly* ROM storage order
with one single, striking exception: **Dallas is completely absent from the
selectable list** — cycling hits `... Hartford → Los Angeles → Montreal ...`,
skipping ROM index 10 entirely, despite Dallas having a full, valid roster stored
in the ROM (playable in no menu we've found so far). The two All-Star rosters
(stored *before* the real teams in ROM) appear at the *end* of the menu cycle
instead — the full loop is `Anaheim → Boston → ... → Washington → All Stars East
→ All Stars West → (wraps to) Anaheim`. Real-world context: the Dallas Stars were
a brand-new 1993-94 relocation from Minnesota, active for barely one season before
this ROM shipped — the simplest explanation is Dallas was added to the roster data
late and never got wired into the exhibition team-count/loop, leaving it as a
fully-modeled but functionally unreachable team in the shipped game (at least via
this menu — Season mode is untested). This resolves the "implies a separate
menu→index lookup table" framing from earlier in this section: there isn't a
scrambled lookup table to find — the menu walks ROM order directly, it's just
missing one entry and has two extras appended at the wrap point.

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

---

## 6. Player rating bytes — jersey number solved, "Overall Rating" identity confirmed, exact storage/formula still open

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
   **Exact storage/computation: still open, now with a much clearer picture of
   why.** Five hypotheses ruled out with real evidence (live WRAM struct scan,
   raw ROM player-record scan, nibble-sum arithmetic, the `A0≈0x3618` ROM
   pointer path, and — newest — direct memory reads at every register pointer
   live at the correct render call site, `0x0008562C`). That call site is
   confirmed to be one handler inside a genuine bytecode/jump-table interpreter
   (reached via `jmp (a0)`, not a normal call), the same architecture already
   found driving the Scouting Report screen — this is now a *repeated* result
   across two independent screens, not a one-off. **Recommend treating this as
   its own scoped follow-up** (either properly tracing the interpreter's
   dispatch loop, or the VDP/tile-level approach) rather than continuing
   ad-hoc live tracing, which has now been tried from many angles across two
   sessions with consistent, well-evidenced negative results.
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
3. ~~Map the menu→team-index lookup~~ — **done, and more interesting than
   expected.** Live-cycled the full Team 1 selector from a fresh boot (title
   screen → credits → exhibition options screen; new reusable savestate at
   `~/team_select.state` on the VM for future sessions). The menu walks ROM
   order directly — **Dallas is simply missing from the selectable list
   entirely** (despite having a complete, valid roster in the ROM), and the two
   All-Star rosters are appended at the wrap point instead of appearing where
   they're stored. See §2.1 for the full writeup and the likely explanation
   (Dallas was a brand-new 1993-94 relocation, probably added to the data too
   late to get wired into the menu's team count/loop).
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

   AI decision-making, faceoffs, and fighting remain untouched. This item is
   closed for its original scope (special-teams line-switching); anything
   further here would be a new, separately-scoped investigation.

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
