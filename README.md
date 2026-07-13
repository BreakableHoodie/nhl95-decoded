# NHL 95 (Genesis) — Decoded

A reverse-engineering deep-dive into `NHL 95 (USA, Europe).gen`, the 1994
Sega Genesis classic — full static (Ghidra) + live (BlastEm debugger)
analysis of its data formats and game logic.

**New here? Start with [`docs/OVERVIEW.md`](docs/OVERVIEW.md) — what we
found, in plain English, no assembly required.**
**Want the proof? [`docs/FINDINGS.md`](docs/FINDINGS.md) is the full
technical write-up** — every claim backed by ROM addresses, disassembly,
and live-debugger evidence.

## Why should you care?

This started from one real bug report and grew into answers to questions
the NHL 95 community has argued about for 30 years:

- **Is "hot/cold streaks" real, or just flavor text?** It's real — fully
  traced end to end, from the exact RNG algorithm (a 32-bit LCG seeded once
  per boot off the Genesis's V-counter hardware) through to which player
  gets picked hot/cold each game, confirmed live against the actual
  on-screen announcement. See [§5](docs/FINDINGS.md#5-hotcold-streaks--confirmed-real-mechanism-partially-traced).
- **What's the actual formula behind a player's Overall Rating?** Solved
  two independent ways: statistically (a fixed linear combination of 12
  specific nibbles out of the game's 7-byte attribute block, live-validated
  to within ~2 points of the ROM's own output), and then confirmed a second
  time by decoding the ROM's own UI-widget bytecode directly — the exact
  set of nibbles the formula uses is bit-for-bit identical to a parameter
  found sitting in the ROM itself, not just inferred from outside data.
  Every named stat (Agility, Shot Power, Checking, etc.) is mapped the same
  way. See [§6](docs/FINDINGS.md#6-player-rating-bytes--jersey-number-solved-overall-rating-formula-solved-and-rom-confirmed-exact-weights--opcode-still-open).
- **The bug report that started this whole project**: Boston's Bryan
  Smolinski shows up cloned at two positions at once in the Line Editor.
  Root-caused to a specific stale-data condition — and checking all 208
  line/team combinations in the game confirmed it's the *only* one, a
  genuine one-off 1994 shipping bug, not a general glitch.
  See [§3](docs/FINDINGS.md#3-bug-smolinski-line-editor-clone-root-caused-live-confirmed).
- **The full 7-line system** (Sc1/Sc2/Chk/PP1/PP2/PK1/PK2) mapped and
  confirmed byte-for-byte against a live penalty kill — including *why*
  the in-game Line Editor sometimes shows only one line and sometimes
  shows all seven, a real UI-behavior gotcha this project hit before it
  understood the setting driving it. Mainly useful if you're building
  tools against this ROM (a save editor, another stats tracker) and need
  to know which internal slot is actually the penalty-kill unit.

## What's in this repo

- **`docs/OVERVIEW.md`** — the plain-English version of every finding below,
  no ROM addresses or assembly required.
- **`docs/FINDINGS.md`** — the living document. Every finding, with the
  reasoning and evidence behind it, root-cause first.
- **`docs/full_roster_database.json`** — every player's name, jersey
  number, and attribute bytes, extracted from the ROM.
- **`docs/external_sources/`** — our derived comparison data (ROM-predicted
  vs. third-party stats), used to validate the formulas above. Raw
  third-party scrapes are excluded — see below.
- **`tools/`** — the actual scripts and live-debugger tooling used to do
  this work: a Ghidra data-dump script, a persistent BlastEm
  debugger-console daemon (`nhl95_daemon.py`/`nhl95ctl.py`) for scripted
  live tracing over SSH, and the statistical correlation scripts behind
  the rating-formula work.

**Not included, on purpose:** the ROM file itself (Sega's copyrighted
binary), the Ghidra project database (it embeds analyzed ROM bytes), and
two raw third-party data scrapes used only for cross-validation. None of
those are ours to redistribute. If you want to reproduce this work, get
your own legally-obtained copy of the ROM (US/Europe, no header, 2MB,
product ID T-50856) and re-run the Ghidra import described in `CLAUDE.md`.

## Method, if you're doing similar work

Two techniques here generalize well beyond this one ROM:

1. **External-dataset correlation to crack an opaque data format.** Rather
   than trying to derive the Overall Rating formula from disassembly alone,
   fitting the ROM's raw attribute bytes against an independent,
   already-published stat list (from a game FAQ) turned an opaque 7-byte
   block into a fully solved, live-validated formula in one session.
2. **Live-vs-static verification as the actual bar for "solved."** Several
   findings here were fit or hypothesized statistically first, then proven
   (or revised) by reading real values off the running emulator via a
   scripted debugger console — see `docs/FINDINGS.md` for more than one
   case where the live check caught a wrong hypothesis before it got
   written down as fact.

## Credits

This project drew on several existing community resources to get started,
and is grateful for all of them: nhl-95.com's ratings data and the
GameFAQs community FAQ this project also used were both valuable,
good-faith starting points that made the correlation work in `FINDINGS.md`
possible in the first place. Sega Retro's NHL 95 page was an independently
useful developer/manual-sourced reference throughout.
