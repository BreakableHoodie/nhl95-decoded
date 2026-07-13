---
title: NHL 95 (Genesis) — Decoded
---

# NHL 95 (Genesis) — Decoded

A reverse-engineering deep-dive into `NHL 95 (USA, Europe).gen`, the 1994
Sega Genesis classic.

**[Read the full write-up →](FINDINGS.md)**

## Why should you care?

This started from one real bug report and grew into answers to questions
the NHL 95 community has argued about for 30 years:

- **Is "hot/cold streaks" real, or just flavor text?** It's real — fully
  traced end to end, from the exact RNG algorithm (a 32-bit LCG seeded once
  per boot off the Genesis's V-counter hardware) through to which player
  gets picked hot/cold each game, confirmed live against the actual
  on-screen announcement.
- **What's the actual formula behind a player's Overall Rating?** Solved
  and live-validated: a fixed linear combination of 12 specific nibbles out
  of the game's 7-byte player attribute block, matching the ROM's own live
  output almost exactly. Every named stat (Agility, Shot Power, Checking,
  etc.) is mapped the same way.
- **A duplicate-player "clone bug" some players hit in the Line Editor** —
  root-caused to a specific self-patching code path, not a mystery glitch.
- **The full 7-line system** (Sc1/Sc2/Chk/PP1/PP2/PK1/PK2), confirmed
  byte-for-byte against a live penalty kill.

Along the way, this also turned up genuine data-quality bugs in a
well-known community stats resource — verified directly against the ROM
rather than assumed.

**[Read the full write-up →](FINDINGS.md)** · [Source on GitHub](https://github.com/BreakableHoodie/nhl95-decoded)
