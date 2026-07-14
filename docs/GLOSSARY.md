# Glossary

Plain-English definitions for the technical terms used throughout
[`FINDINGS.md`](FINDINGS.md) and [`OVERVIEW.md`](OVERVIEW.md). If a term
you hit isn't here, it's a gap — the project welcomes a nudge to add it.

---

**Bit** — the smallest unit of data a computer stores: a single 0 or 1.
Everything else on this page (bytes, nibbles, bitmasks) is just a
specific-sized group of bits.

**Bitmask** — a number used as a set of on/off switches, one per bit,
rather than as a normal quantity. This project's biggest single find (the
exact formula behind a player's Overall Rating) came from decoding a
bitmask in the ROM where each "on" bit meant "this specific stat counts
toward the rating."

**Breakpoint** — an instruction to the debugger: "pause the program the
instant execution reaches this exact spot." Used throughout this project
to catch the game in the act of computing something, mid-frame.

**Byte** — 8 bits together, able to hold a number from 0 to 255. The basic
unit ROM and RAM are organized in.

**Bytecode / interpreter** — some parts of this ROM don't drive the
screen with plain 68k CPU instructions directly; instead there's a small
"mini programming language" built out of custom data (the bytecode) that
a separate piece of code (the interpreter) reads and acts on, one
instruction at a time — similar in spirit to how a modern web browser
interprets JavaScript rather than running it as raw machine code. Several
of this project's hardest problems (like exactly how Overall Rating gets
computed) come down to this interpreter being much harder to trace
statically than ordinary code.

**Clamp / saturation** — when a game caps a computed value at some fixed
ceiling or floor rather than letting it go arbitrarily high or low (e.g.
"stop at 99, however big the real formula's answer is"). This project
found live evidence of it near the top of the 0-99 stat range: a player's
predicted stat plus their random hot/cold adjustment landed higher than
the displayed number, consistent with the display quietly capping at the
ceiling rather than the underlying formula being wrong.

**Debugger** — a tool that lets you pause a running program, inspect its
memory and registers, and step forward one instruction at a time. This
project uses BlastEm's built-in debugger (see below) to watch the ROM's
code execute live, instead of only reading it as still data.

**Disassembly / disassembler** — raw ROM bytes, on their own, are just
numbers. A disassembler translates those numbers back into readable 68k
CPU instructions (like `move.w d0,d1` or `jsr $0007C810`) — the same way
you might translate encoded text back into a sentence. "Disassembling" a
region of the ROM means running it through this translation.

**Emulator** — software that behaves exactly like the original Sega
Genesis hardware, so an unmodified ROM file will run and play normally on
a modern computer. This project uses **BlastEm**, an open-source Genesis
emulator that happens to include a real instruction-level debugger — the
combination is what makes "live tracing" possible at all.

**Ghidra** — a free static-analysis tool (originally built by the NSA,
now open source) used to load the raw ROM file and turn it into organized,
labeled disassembly, find cross-references, and search for byte patterns
— all without actually running the game.

**Hex / hexadecimal** — a way of writing numbers in base 16 instead of
the usual base 10, using digits `0-9` then `A-F`. Written with a `0x`
prefix throughout this project (`0x1FBA`, `0x085832`). Programmers use hex
because it lines up cleanly with bytes and bits (two hex digits = exactly
one byte) in a way ordinary decimal numbers don't.

**LCG (linear congruential generator)** — a specific, simple, well-known
algorithm for generating a sequence of "random" numbers from a starting
"seed" value. This ROM's hot/cold streak mechanic (§5) is powered by one.

**Live tracing** — watching the ROM's code actually execute, in a running
emulator, as opposed to only reading it as still bytes. See "static
analysis" below for the contrast — this project uses both, and several
findings turned out to need live tracing specifically because they were
wrong when guessed from static analysis alone.

**Nibble** — half a byte: 4 bits, a number from 0 to 15. This project's
central, most-reused concept — nearly every player attribute in this ROM
(Agility, Overall Rating, Shot Power, etc.) turned out to live in one
specific nibble of a shared 7-byte block per player. Named because it's
"a small bite" of a byte.

**Opcode** — the part of a CPU instruction that says *what to do*
(as opposed to *what data* to do it with). "`move`," "`jsr`," and "`cmpi`"
are opcodes; the ROM addresses and register names next to them are the
data those opcodes act on.

**RAM** — memory that holds data which changes while the game is running
(the current score, where players are on the ice, whose turn it is) — as
opposed to ROM, which never changes. See **WRAM** below for the specific
kind this project deals with.

**Register** — a small, extremely fast storage slot built directly into
the CPU chip itself (as opposed to RAM, which is a separate chip the CPU
has to reach out to). The 68k CPU in the Genesis has registers named
things like `D0`-`D7` and `A0`-`A7`; this project's live-tracing notes
constantly mention "what was in D0" because that's often where a
just-computed value briefly sits before being stored somewhere permanent.

**RNG (random number generator)** — any mechanism a program uses to
produce unpredictable values. See **LCG** above for the specific
technique this ROM uses.

**ROM** — "Read-Only Memory": the game cartridge's actual, fixed data —
every instruction, every string of text, every player's stats — exactly
as it was in 1994, unchanging. The `.gen` file this whole project is
built from *is* this ROM, byte for byte. Contrast with **RAM**.

**Savestate** — a complete snapshot of the emulator's exact state (every
byte of RAM, every register, everything) saved to a file, so you can jump
back to that exact moment instantly instead of replaying from a fresh
boot every time. This project keeps several savestates (like
`controller_setup.state`) purely to skip the ~4-minute mandatory credits
scroll during repeated testing.

**SRAM (Save RAM)** — a small, separate block of memory backed by a
battery in the cartridge itself, which is why save data survives being
powered off — unlike ordinary **WRAM** (below), which loses everything the
instant the console loses power. This project traced the hot/cold streak
RNG's seed to something tied to this SRAM/backup-RAM area: removing the
save file changed the boot sequence's exact timing enough to produce a
genuinely different random seed, which is how the seeding mechanism was
pinned down.

**Static analysis** — studying the ROM's code and data without ever
running it — reading raw bytes, disassembling instructions, searching for
patterns. Contrast with **live tracing** above. Both matter here: static
analysis is faster and safer to iterate on, but this project found real
cases where it produced a wrong answer that only live tracing caught.

**Struct (structure)** — a block of related data fields stored together at
fixed byte offsets, like a form with labeled boxes at known positions. If
a "team stats struct" starts at address `X`, then `X+0x00` might always
hold Shots and `X+0x0C` might always hold Score, for *any* team's struct —
learn the shape once (the offsets) and it works everywhere the struct is
reused. Several of this project's cleanest findings are exactly this: a
struct's shape found by reading ROM data, then confirmed live by checking
those offsets against two different teams' scoreboards at once.

**VDP (Video Display Processor)** — the Genesis's dedicated graphics
chip, separate from the main 68k CPU. Mentioned mainly in the context of
things this project *hasn't* fully cracked yet, where reading what the
VDP is actually drawing (rather than tracing the CPU code that tells it
what to draw) is flagged as a possible alternative approach.

**WRAM (Work RAM)** — the specific block of RAM the Genesis's main CPU
uses for its own working data (as opposed to video or sound RAM). Nearly
every RAM address in this project's findings — player structs, the
hot/cold modifier table, the current game clock — lives in WRAM.

**Xref / cross-reference** — a record of "what other code or data points
to this address." A key static-analysis technique: if you want to know
what *uses* a particular table, you look for cross-references to it. This
project repeatedly ran into ROM regions where xrefs come up empty even
though the data is clearly used — a sign the reference is computed at
runtime rather than written down anywhere literal, which is itself a
useful finding about how the ROM is built.

---

Two terms that describe *methods* rather than single facts, worth calling
out on their own:

**"Root-cause it, then check if it's systemic"** — this project's core
working habit (see the intro to [`FINDINGS.md`](FINDINGS.md)): when
something looks broken, trace it all the way back to the exact byte and
instruction responsible, then check the *entire* dataset for the same
condition, rather than assuming one observed case is the whole story.

**Independent confirmation** — finding the same answer two genuinely
different ways (e.g. a statistical fit against outside data, *and*
decoding the ROM's own bytecode table) is much stronger evidence than
either one alone, especially when neither method knew about the other's
result in advance. Several of this project's highest-confidence findings
rest on exactly this.
