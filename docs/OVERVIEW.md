# NHL 95 — What We Found (plain-English version)

This page explains the findings without any assembly code, memory
addresses, or emulator jargon — just what's actually true about how the
game works, and why it matters if you've ever played it. If you want the
byte-level proof behind any of this, the technical write-up is
[`FINDINGS.md`](FINDINGS.md); every claim here has a matching, evidenced
section over there.

## "Hot and cold streaks" are 100% real — here's exactly how they work

Old strategy guides always mentioned that players go on hot or cold
streaks, but it was never clear whether that was a real mechanic or just
flavor text on top of a fixed roster. **It's real, and we traced the whole
thing:**

- The instant you power on the game (or load it in an emulator), it grabs
  one piece of hardware-level randomness and uses it to "roll the dice"
  once for every single player on every team — a small random adjustment,
  roughly -9 to +8, gets attached to each player.
- Those numbers get added up per player, and whoever comes out highest
  becomes that game's "hot" player; whoever's lowest becomes "cold." That's
  the player you see named on the pre-game Scouting Report.
- **The important, previously-undocumented part: this only happens once
  per power-on.** Restarting a game, reloading a save, or replaying the
  same matchup over and over will *not* re-roll it — you'll get the exact
  same hot/cold players every time, for that entire play session. Only
  turning the console off and back on gives you new streaks. If you ever
  wondered why hot/cold seemed to "not change" no matter how many times you
  replayed a game, this is why — and it also confirms it genuinely is
  random, just resolved earlier than most people would guess.

## We cracked the exact formula behind every player's rating

Every player has a hidden "Overall Rating" plus 11 more specific stats
(Agility, Speed, Shot Power, Checking, etc.). Nobody had previously
published the actual math the game uses to compute these from its raw
data. We now have it, and checked it directly against the running game
(not just against outside sources) — predictions come within about 2
points of the real, live number for Overall Rating, and within single
digits for the other stats.

One side effect of doing this rigorously: we found real errors in a
well-known, long-used fan stats resource for this game. Most notably, an
**entire team's Overall Ratings were wrong across the board** — every
Ranger was rated too low by anywhere from 5 to 16 points. Nothing else we
checked showed a similar team-wide problem; that was a one-off data-entry
bug, not a sign the rest of the numbers are unreliable.

## The Line Editor "clone" bug — root cause found

Some players occasionally saw a duplicate/glitched player name appear in
the line editor. This turned out to be a real, specific bug in the game's
own code (not corrupted ROMs, not an emulator quirk) — a piece of code
that patches its own return address to skip over inline data made an
off-by-one-style mistake under a specific condition. Full technical
root-cause is in `FINDINGS.md` §3; the short version is that it's a real
bug in the original 1994 game, reproducible, and now explained.

## The full 7-line system, confirmed against a real penalty kill

The game secretly tracks 7 named lines per team (two scoring lines, a
checking line, two power-play lines, two penalty-kill lines), but which
line is which internally was never documented. We mapped all 7 and then
confirmed the mapping live by watching an actual penalty kill and matching
the players shown against our predicted line — it matched exactly,
including that penalty-kill lines only ever show 4 players (no right wing),
matching how the real rule works.

## Want the details?

Every finding above has a corresponding section in
[`FINDINGS.md`](FINDINGS.md) with the actual ROM addresses, opcodes, and
live-debugger evidence behind it — including the cases where an initial
hypothesis turned out to be wrong and had to be revised, kept in for
transparency rather than edited out.
