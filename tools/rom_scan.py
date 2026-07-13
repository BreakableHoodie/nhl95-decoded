#!/usr/bin/env python3
"""
Reusable static ROM-scanning helpers, factored out of repeated inline
one-off scripts written across this session (the UI string-record parser
that cracked the Overall Rating bitmask, the raw-pointer search, the
Face Off/Injury string hunts -- see FINDINGS.md section 6/7 for what each
of these found).

Import from a scratchpad script, or run directly for a quick scan:
    python3 tools/rom_scan.py strings "injur" "faceoff"
    python3 tools/rom_scan.py records 0x085832 0x086100
    python3 tools/rom_scan.py pointer-search 0x89cc6
"""
import re
import struct
import sys

ROM_PATH = "NHL 95 (USA, Europe).gen"


def load_rom(path=ROM_PATH):
    with open(path, "rb") as f:
        return f.read()


def find_strings(rom, needle, case_insensitive=True):
    """Raw ASCII substring search, returns [(addr, matched_text)]. Cheap
    first pass for "does this concept even appear in the ROM" questions --
    see the fighting-mechanic mistake and the injury/faceoff finds in
    FINDINGS.md for why checking this before assuming is worth the 5
    seconds it costs."""
    hay = rom.lower() if case_insensitive else rom
    n = needle.lower().encode() if case_insensitive else needle.encode()
    out = []
    start = 0
    while True:
        idx = hay.find(n, start)
        if idx == -1:
            break
        end = idx
        while end < len(rom) and 32 <= rom[end] < 127:
            end += 1
        begin = idx
        while begin > 0 and 32 <= rom[begin - 1] < 127:
            begin -= 1
        out.append((begin, rom[begin:end].decode("ascii", errors="replace")))
        start = idx + 1
    return out


def parse_string_records(rom, start, end):
    """Decodes the `[0x00][tag][0x00][length][text][u16 suffix]` UI-widget
    string-record format found at ROM 0x085832 (see FINDINGS.md section 6,
    "Major breakthrough" writeup) -- length counts text+suffix bytes, and
    the suffix is a one-hot nibble-selector bitmask for rating widgets, or
    a signed x/y draw offset elsewhere (e.g. the Face Off strings).

    `tag` varies between tables (0x00 for the simple Face Off-style
    records, 0x0A for the chained rating-widget records) -- an earlier
    version of this function hardcoded tag==0 and silently missed every
    0x0A-tagged record in the rating tables (only found 2 of the ~15
    entries actually present). Caught by testing against the known-good
    manual dump before trusting this as reusable infrastructure -- worth
    remembering next time a "clean" first pass looks too good to be true."""
    records = []
    i = start
    while i < end - 4:
        if rom[i] == 0 and rom[i + 2] == 0:
            tag = rom[i + 1]
            length = rom[i + 3]
            if 4 <= length <= 40:
                text_len = length - 2
                text = rom[i + 4:i + 4 + text_len]
                if all(32 <= c < 127 for c in text):
                    suffix = rom[i + 4 + text_len:i + 4 + text_len + 2]
                    records.append({
                        "addr": i,
                        "tag": tag,
                        "length": length,
                        "text": text.decode("ascii"),
                        "suffix": suffix.hex(),
                        "suffix_int": int.from_bytes(suffix, "big"),
                    })
                    i = i + 4 + text_len + 2
                    continue
        i += 1
    return records


def bitmask_to_nibbles(mask, num_nibbles=14):
    """One-hot bit -> nibble index, per the `bit = (num_nibbles - 1) -
    nibble_index` relationship confirmed exactly against the independently
    statistically-fit skater Overall Rating weights (FINDINGS.md section
    6). Returns the list of nibble indices with their bit set."""
    return [num_nibbles - 1 - bit for bit in range(num_nibbles) if mask & (1 << bit)]


def find_raw_pointer(rom, addr, width=4):
    """Search for `addr` encoded as a literal big-endian pointer anywhere
    in the ROM. A clean miss here (as happened for both the Face Off
    strings and the rating-widget table) means the real reference is
    computed/indirect, not a direct address -- see the CLAUDE.md gotcha on
    Ghidra's recursive-descent disassembly not reaching indirect call
    sites, which applies to pointer literals the same way."""
    pattern = addr.to_bytes(width, "big")
    hits = []
    start = 0
    while True:
        idx = rom.find(pattern, start)
        if idx == -1:
            break
        hits.append(idx)
        start = idx + 1
    return hits


def _main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    rom = load_rom()
    cmd = sys.argv[1]
    if cmd == "strings":
        for needle in sys.argv[2:]:
            hits = find_strings(rom, needle)
            print(f"'{needle}': {len(hits)} hit(s)")
            for addr, text in hits[:10]:
                print(f"  0x{addr:06X}  {text!r}")
    elif cmd == "records":
        start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
        for r in parse_string_records(rom, start, end):
            nibbles = bitmask_to_nibbles(r["suffix_int"]) if bin(r["suffix_int"]).count("1") <= 2 else None
            print(f"0x{r['addr']:06X}  tag=0x{r['tag']:02X}  len={r['length']:3d}  suffix=0x{r['suffix']}"
                  f"{'  nibbles=' + str(nibbles) if nibbles else '':20s}  {r['text']!r}")
    elif cmd == "pointer-search":
        addr = int(sys.argv[2], 16)
        hits = find_raw_pointer(rom, addr)
        print(f"0x{addr:X} as raw pointer: {[hex(h) for h in hits] or 'no hits'}")
    else:
        print(__doc__)


if __name__ == "__main__":
    _main()
