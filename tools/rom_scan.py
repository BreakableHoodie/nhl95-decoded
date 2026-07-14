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
    python3 tools/rom_scan.py scan-tables 0x80000 0xa0000
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


def parse_plain_records(rom, start, end):
    """Decodes the second string-record format found while solving issue
    #11 (the per-game stats table at ROM 0x092410): `[u16 length][text,
    even-padded][u16 suffix]` -- no leading tag/zero-byte framing, unlike
    parse_string_records' `[0x00][tag][0x00][length]` header. `length`
    counts text(+pad)+suffix, same convention as the tagged format. The
    suffix means different things in different tables (a struct byte
    offset for the stats table, a fixed category tag for the penalty-type
    and team-strength tables found via scan_for_tables below) -- don't
    assume one meaning without checking, see FINDINGS.md section 7#8/#9/#10."""
    records = []
    i = start
    while i < end - 4:
        length = (rom[i] << 8) | rom[i + 1]
        if 4 <= length <= 40 and i + 2 + length <= end:
            text_area = rom[i + 2:i + length]  # text(+pad), excludes the 2-byte suffix
            core = text_area.rstrip(b"\x00")
            if core and all(32 <= c < 127 for c in core) and len(text_area) - len(core) <= 1:
                suffix = int.from_bytes(rom[i + length:i + 2 + length], "big")
                records.append({
                    "addr": i, "length": length, "text": core.decode("ascii"),
                    "suffix": f"{suffix:04x}", "suffix_int": suffix,
                })
                i += 2 + length
                continue
        i += 1
    return records


def parse_stride_records(rom, start, end, max_length=32):
    """Decodes a third string-record format, found while re-examining the
    injury-status and months tables (FINDINGS.md section 7#10) after they
    didn't cleanly fit either format above: `[0x00][length][text, SPACE-
    or NULL-padded]`, no suffix field at all. The key difference from
    parse_plain_records: `length` here counts the record's *own 2-byte
    header too* (stride = length, not 2 + length) -- getting this backwards
    is exactly what made these two tables look malformed at first (the
    next record's header kept getting misread as a trailing suffix field
    on the previous one). Stops at the first non-matching byte rather than
    skipping ahead by 1, since this format's tables pack records back-to-
    back with no gap -- a real mismatch means the table ended, not noise
    to scan past (unlike scan_for_tables' byte-at-a-time approach, which
    expects gaps and noise)."""
    records = []
    i = start
    while i < end:
        if not (rom[i] == 0 and 4 <= rom[i + 1] <= max_length):
            break
        length = rom[i + 1]
        text = rom[i + 2:i + length]
        stripped = text.rstrip(b"\x00")
        if not stripped or not all(32 <= c < 127 for c in stripped):
            break  # a genuinely blank/space-only record (e.g. the injury table's "    ") is still valid
        records.append({"addr": i, "length": length, "text": text.decode("ascii", errors="replace")})
        i += length
    return records


def _plausible_suffix(v):
    """Loose filter for scan_for_tables: keep suffixes that look like real
    structured data (a sentinel, a one-hot bitmask, or a small offset/tag)
    rather than noise from graphics/tile bytes coincidentally decoding as
    printable text. Generous by design -- the real noise filter is
    cluster_runs' run-length requirement, not this."""
    if v == 0xFFFF:
        return True
    if v != 0 and (v & (v - 1)) == 0:
        return True
    return v < 0x0800


def scan_for_tables(rom, start, end, tagged_tag_range=(0, 40)):
    """Combined tagged+plain scan used to find issue #8's new tables
    (penalty catalog, team-strength categories, three-stars criteria --
    see FINDINGS.md section 7#10). Returns raw hits from both formats,
    sorted by address; feed to cluster_runs to drop isolated false
    positives."""
    hits = []
    for rec in parse_string_records(rom, start, end):
        if _plausible_suffix(rec["suffix_int"]):
            rec = dict(rec, fmt="tagged")
            hits.append(rec)
    for rec in parse_plain_records(rom, start, end):
        if _plausible_suffix(rec["suffix_int"]):
            rec = dict(rec, fmt="plain")
            hits.append(rec)
    return sorted(hits, key=lambda r: r["addr"])


def cluster_runs(hits, max_gap=24, min_run=3):
    """Groups hits into runs where consecutive records sit within max_gap
    bytes of each other, dropping runs shorter than min_run. Real tables
    are always several entries in a row; isolated hits are almost always
    coincidental ASCII-looking graphics/tile data -- this one filter is
    what made scan_for_tables usable instead of drowning in noise."""
    runs, cur = [], []
    for h in hits:
        if cur and h["addr"] - cur[-1]["addr"] > max_gap:
            if len(cur) >= min_run:
                runs.append(cur)
            cur = []
        cur.append(h)
    if len(cur) >= min_run:
        runs.append(cur)
    return runs


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
    elif cmd == "scan-tables":
        start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
        hits = scan_for_tables(rom, start, end)
        runs = cluster_runs(hits)
        print(f"{len(hits)} raw candidate records, {len(runs)} runs of >=3 after clustering\n")
        for run in runs:
            addrs = f"0x{run[0]['addr']:06X}-0x{run[-1]['addr']:06X}"
            texts = [r["text"] for r in run]
            print(f"{addrs}  ({len(run)} entries, fmt={run[0]['fmt']}): {texts}")
    elif cmd == "stride-records":
        start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
        for r in parse_stride_records(rom, start, end):
            print(f"0x{r['addr']:06X}  len={r['length']:3d}  {r['text']!r}")
    else:
        print(__doc__)


if __name__ == "__main__":
    _main()
