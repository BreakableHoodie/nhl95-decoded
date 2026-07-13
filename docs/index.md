---
title: NHL 95 (Genesis) — Decoded
---

# NHL 95 (Genesis) — Decoded

A reverse-engineering deep-dive into `NHL 95 (USA, Europe).gen`, the 1994
Sega Genesis classic.

**New here? [Read the plain-English version →](OVERVIEW.md)** — what we
found, no assembly required.
**Want the proof? [Read the full technical write-up →](FINDINGS.md)** —
every claim backed by ROM addresses and live-debugger evidence.

## Why should you care?

This started from one real bug report and grew into answers to questions
the NHL 95 community has argued about for 30 years:

- **Is "hot/cold streaks" real, or just flavor text?** It's real — fully
  traced end to end, from the exact RNG algorithm (a 32-bit LCG seeded once
  per boot off the Genesis's V-counter hardware) through to which player
  gets picked hot/cold each game, confirmed live against the actual
  on-screen announcement.
- **What's the actual formula behind a player's Overall Rating?** Solved
  two independent ways: statistically (live-validated to within ~2 points
  of the ROM's own output), then confirmed a second time by decoding the
  ROM's own UI-widget bytecode directly — the exact nibbles the formula
  uses are bit-for-bit identical to a parameter found sitting in the ROM
  itself. Every named stat (Agility, Shot Power, Checking, etc.) is mapped
  the same way.
- **The bug report that started this whole project**: Boston's Bryan
  Smolinski shows up cloned at two positions at once in the Line Editor.
  Root-caused to a stale-data condition — checking all 208 line/team
  combinations confirmed it's the *only* one, a genuine one-off 1994
  shipping bug, not a general glitch.
- **The full 7-line system** (Sc1/Sc2/Chk/PP1/PP2/PK1/PK2) mapped and
  confirmed byte-for-byte against a live penalty kill — including *why*
  the Line Editor sometimes shows one line and sometimes shows all seven.

**[Plain English →](OVERVIEW.md)** · **[Full technical write-up →](FINDINGS.md)** · **[Search →](search.html)** · [Source on GitHub](https://github.com/BreakableHoodie/nhl95-decoded)
