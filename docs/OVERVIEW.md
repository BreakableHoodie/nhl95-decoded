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
- [Injuries are real — and rarer than you'd think](#injuries-are-real--and-rarer-than-youd-think)
- [We cracked the exact formula behind every player's rating](#we-cracked-the-exact-formula-behind-every-players-rating)
- [The Line Editor "clone" bug — root cause found](#the-line-editor-clone-bug--root-cause-found-and-its-just-one-player)
- [The full 7-line system](#the-full-7-line-system-confirmed-against-a-real-penalty-kill)
- [Hidden Shootout mode, Playoff bracket, and real trades](#the-game-has-a-hidden-shootout-mode-a-full-playoff-bracket-and-real-trades)
- [We were wrong about Dallas — and caught it ourselves](#we-were-wrong-about-dallas--and-caught-it-ourselves)
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
- **And it isn't just a label — it actually changes the player's stats.**
  We confirmed this directly: predicted a player's Speed rating from the
  ROM's fixed data alone (no randomness involved), then compared it to
  what the game actually displayed live, and the gap matched that
  player's random adjustment almost exactly. So a "cold" player really is
  worse that game, not just narrated as worse.

## Injuries are real — and rarer than you'd think

Old strategy guides mention players getting hurt, but nobody had ever
documented how it actually works — or even confirmed it was a real,
coded mechanic rather than just flavor text. We found the exact code,
and the honest answer to "why have I never seen it happen" is: **it's
not one dice roll, it's two, and both have to go the player's way.**

- After a hit, the game first rolls to decide whether the hit was even
  hard enough to risk an injury at all.
- If that succeeds, a few settings have to be in the right state (one
  of them is almost certainly whether you've turned `Injuries` on in
  Season mode's setup screen at all).
- Then — and this is the part that explains a lot — there's a
  **second, completely independent coin flip.** Even a hit that clears
  every check above only actually produces an injury about half the
  time.
- Only after *both* rolls succeed does the game decide how long the
  player is out for, which isn't a fixed number per injury type — it's
  randomly computed on the spot, working out to roughly 1 to 5 games.

So if you've played this game for years and never seen a real in-game
injury, that's not bad luck or a broken feature — it's two independent
low-probability events stacked on top of each other, exactly as
designed. We confirmed this the hard way: watched two complete games
end to end (one of them with the `Injuries` setting explicitly turned
on) and neither produced a single injury, which used to look like a
dead end until we found the code and realized that outcome is actually
expected, not surprising.

One nice bonus: once an injury *does* happen, the game remembers "how
long is this player out for" using the exact same space-saving trick
it uses for player ratings elsewhere — squeezing two players' status
into a single number instead of giving each player their own full
byte. A neat, very on-brand piece of 1994 cartridge engineering, turning
up in a completely different corner of the game than where we first
found it.

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

**So what actually happens if you play a game with him cloned like that?**
We tried it three separate times, including one full hands-off CPU-vs-CPU
game — and in that game, the cloned Smolinski actually **scored a real
goal**, credited normally on the scoreboard with two real assists, exactly
like any other player. Every attempt agreed: the clone doesn't break the
game or freeze anything, it just quietly plays — and can even score —
as if nothing were wrong. (A couple of players have separately reported
seeing stranger things happen with this exact bug, like the clone
appearing to wander in from the bench mid-play. We looked for that too and
didn't catch it ourselves, so it's noted as unconfirmed rather than ruled
out.)

## The full 7-line system, confirmed against a real penalty kill

The game secretly tracks 7 named lines per team (two scoring lines, a
checking line, two power-play lines, two penalty-kill lines), but which
line is which internally was never documented. We mapped all 7 and then
confirmed the mapping live by watching an actual penalty kill and matching
the players shown against our predicted line — it matched exactly,
including that penalty-kill lines only ever show 4 players (no right wing),
matching how the real rule works.

```
┌─────────────────────────────────────────┐
│  Sc1 → Sc2        two scoring lines      │
│  Chk              checking line          │
│  PP1 → PP2        two power-play lines   │
│  PK1 → PK2        two penalty-kill lines │
│                   (4 players, no RW)     │
└─────────────────────────────────────────┘
        Sc1 is always active first,
        at the start of every period.
```

## The game has a hidden Shootout mode, a full Playoff bracket, and real trades

Most of this project's earlier work focused on Exhibition games — pick
two teams, play one game. It turns out that's only a fraction of what's
actually in the cartridge. Cycling through the game's main setup screen
reveals **11 different modes**, several of which had never been
documented anywhere in this project before:

- **Shootout mode** — a genuine one-on-one skater-vs-goalie mode with its
  own setup screen (pick your 5 shooters and goalie), its own scoreboard,
  and a shot clock for each attempt. It's also how a real game breaks a
  tie after overtime.
- **Season mode** — play (or simulate) an entire 84-game NHL season, with
  real division standings, league leaders, and a team schedule calendar.
- **Playoffs mode** — a full 16-team bracket, complete with a drawn
  Stanley Cup graphic in the middle of the screen, matching the real 1994
  NHL playoff format.
- **Trade Players** — swap players between any two teams' rosters, with
  both full rosters and every player's overall rating shown side by side.
  There's also **Create Player**, **Sign Free Agents**, and **Release
  Players** for building out a custom roster.

None of this changes any of the findings above — it's the same ROM, the
same rating formula, the same hot/cold streaks — but it's a reminder that
this 1994 cartridge packed in a lot more than a single exhibition game.

## We were wrong about Dallas — and caught it ourselves

An earlier version of this research claimed the Dallas Stars were
completely missing from the Exhibition mode's team-select list — a plausible
enough story, since Dallas had only just relocated from Minnesota for the
1993-94 season, right when this game was made. **That claim was wrong, and
we've since corrected it.** Dallas is fully selectable and fully playable;
we walked the entire team list one careful step at a time and confirmed it.
The real story is more mundane: the list cycles in plain **alphabetical
order**, and the original investigation almost certainly mis-counted a
single step around the Chicago/Dallas/Detroit boundary, which looks
identical to "Dallas got skipped" if you're not checking every step
individually.

We're leaving this correction visible rather than quietly editing the old
claim away, because it's a useful reminder for any reverse-engineering
project: a good real-world explanation for why a bug *would* exist isn't
evidence that it *does* exist. Always double back and verify.

## Want the details?

Every finding above has a corresponding section in
[`FINDINGS.md`](FINDINGS.md) with the actual ROM addresses, opcodes, and
live-debugger evidence behind it — including the cases where an initial
hypothesis turned out to be wrong and had to be revised, kept in for
transparency rather than edited out.
