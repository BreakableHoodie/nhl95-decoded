# NHL 95 — What We Found (plain-English version)

This page explains the findings without any assembly code, memory
addresses, or emulator jargon — just what's actually true about how the
game works, and why it matters if you've ever played it. If you want the
byte-level proof behind any of this, the technical write-up is
[`FINDINGS.md`](FINDINGS.md); every claim here has a matching, evidenced
section over there. Run into an unfamiliar word anywhere (including on
this page)? Check the [`GLOSSARY.md`](GLOSSARY.md) — plain-English
definitions for every technical term used, including things like "nibble"
that even this page uses without explaining.

- ["Hot and cold streaks" are 100% real](#hot-and-cold-streaks-are-100-real--heres-exactly-how-they-work)
- [We cracked the exact formula behind every player's rating](#we-cracked-the-exact-formula-behind-every-players-rating)
- [The Line Editor "clone" bug — root cause found](#the-line-editor-clone-bug--root-cause-found-and-its-just-one-player)
- [The full 7-line system](#the-full-7-line-system-confirmed-against-a-real-penalty-kill)
- [Want the details?](#want-the-details)

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
data. We now have it, checked two completely independent ways:

- **Statistically**, by fitting the ROM's raw attribute bytes against an
  outside stat list, then checking predictions directly against the
  running game — within about 2 points of the real, live number for
  Overall Rating, single digits for the other stats.
- **Then confirmed a second time from the ROM itself.** While digging
  through the game's on-screen text data for an unrelated reason, we found
  the exact ROM table the game uses to decide which raw attributes feed
  into Overall Rating — and it matched our statistically-fitted formula
  exactly, bit for bit. That's no longer a best-fit guess; it's read
  directly out of the game's own code.

## The Line Editor "clone" bug — root cause found, and it's just one player

The bug report that started this whole project: assign Boston's Bryan
Smolinski to right wing on the top line, and he shows up listed at *both*
left wing and right wing at once, instead of normally swapping with
whoever was there. This turned out to be a real, specific bug in the
game's own code (not a corrupted ROM, not an emulator quirk) — a
duplicate-player safety check scans the wrong slot first and gets fooled
by a stale, leftover data entry.

**We checked every line on every team (all 208 line/position
combinations) for the same underlying condition, and Smolinski's is the
only one in the entire game.** So if you've never seen this personally,
that's why — it's a genuine, reproducible 1994 shipping bug, but a real
one-off, not a general glitch anyone could stumble into. Full technical
root-cause, including the exact bad byte, is in `FINDINGS.md` §3.

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
