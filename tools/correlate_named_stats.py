#!/usr/bin/env python3
"""
Correlates docs/full_roster_database.json's per-player attribute nibbles
against the named attribute columns (Agility, Top Speed, Shot Power, ...)
in the full nhl-95.com spreadsheet export
(docs/external_sources/nhl95com_full_stats.csv) to identify which nibble
of the 7-byte/14-nibble attribute block corresponds to which named stat.

See FINDINGS.md section 6/7#6 for the full writeup, confidence caveats, and
results (11 of 14 nibbles identified, R^2 0.79-0.90 each). Reuses the same
team-matching approach and pitfalls as tools/correlate_ratings_vs_faq.py --
see that file's comments for the New York/mascot-corruption gotchas in
full_roster_database.json.
"""
import csv
import json
import re
import difflib
import numpy as np

ROSTER_JSON = "docs/full_roster_database.json"
STATS_CSV = "docs/external_sources/nhl95com_full_stats.csv"

TEAM_ABBREV_TO_ROM = {
    'Ana': ('Anaheim', 'Mighty Ducks'), 'Bos': ('Boston', 'Bruins'),
    'Buf': ('Buffalo', 'Sabres'), 'Cgy': ('Calgary', 'Flames'),
    'Chi': ('Chicago', 'Blackhawks'), 'Dal': ('Dallas', 'Stars'),
    'Det': ('Detroit', 'Red Wings'), 'Edm': ('Edmonton', 'Oilers'),
    'Fla': ('Florida', 'Panthers'), 'Hfd': ('Hartford', 'Whalers'),
    'La': ('Los Angeles', 'e Great Western Forum'), 'Mtl': ('Montreal', 'Canadiens'),
    'NJ': ('New Jersey', 'Brendan Byrne Arena'), 'NYI': ('New York', 'Islanders'),
    'NYR': ('New York', 'Rangers'), 'OTT': ('Ottawa', 'Senators'),
    'PHL': ('Philadelphia', 'Flyers'), 'Pit': ('Pittsburgh', 'Penguins'),
    'Que': ('Quebec', 'Nordiques'), 'SJ': ('San Jose', 'San Jose Arena'),
    'STL': ('St. Louis', 'Blues'), 'TBY': ('Tampa Bay', 'Thunderdome'),
    'TOR': ('Toronto', 'Maple Leafs'), 'VAN': ('Vancouver', 'Canucks'),
    'WPG': ('Winnipeg', 'Jets'), 'WSH': ('Washington', 'Capitals'),
}

# CSV column index -> our stat key
STAT_COLS = {
    'agility': 8, 'top_speed': 9, 'shot_power': 10, 'shot_accuracy': 11,
    'stick_handle': 12, 'off_awa': 13, 'def_awa': 14, 'pass_acc': 15,
    'endurance': 16, 'check': 17, 'aggro': 18, 'off_overall': 20,
    'tough': 21, 'scoring': 22, 'acc': 23,
}

# The 11 nibbles this correlation found a clear single-nibble match for --
# same set already identified as relevant to Overall Rating (nibbles 0, 7,
# 11 carry no signal in either analysis).
NIBBLE_TO_STAT = {
    1: 'agility', 2: 'top_speed', 3: 'off_awa', 4: 'def_awa', 5: 'shot_power',
    6: 'check', 8: 'stick_handle', 9: 'shot_accuracy', 10: 'endurance',
    12: 'pass_acc', 13: 'aggro',
}


def last_name(s):
    return re.sub(r'[^a-z]', '', s.lower().split()[-1]) if s.strip() else ''


def load_matched():
    with open(ROSTER_JSON) as f:
        rom_teams = json.load(f)
    rom_lookup = {(t['city'], t['mascot']): t for t in rom_teams}

    with open(STATS_CSV) as f:
        rows = list(csv.reader(f))

    matched = []
    for row in rows[1:]:
        if len(row) < 24:
            continue
        team_abbrev, jersey_s, name, pos = row[1], row[2], row[3], row[5]
        if not name.strip() or not jersey_s.strip().isdigit():
            continue
        if team_abbrev not in TEAM_ABBREV_TO_ROM:
            continue
        rom_team = rom_lookup[TEAM_ABBREV_TO_ROM[team_abbrev]]
        jersey = int(jersey_s)
        candidates = [p for p in rom_team['roster'] if p['jersey_bcd'] == jersey]
        if not candidates:
            continue
        found = candidates[0]
        if len(candidates) > 1:
            key = last_name(name)
            found = max(candidates, key=lambda p: difflib.SequenceMatcher(
                None, key, last_name(p['name'])).ratio())
        entry = {'name': name, 'pos': pos, 'attr7_hex': found['attr7_hex']}
        for stat, idx in STAT_COLS.items():
            v = row[idx].strip()
            entry[stat] = int(v) if v.isdigit() else None
        matched.append(entry)
    return matched


def main():
    matched = load_matched()
    skaters = [m for m in matched if m['pos'] != 'G']
    print(f"Matched {len(matched)} players ({len(skaters)} skaters)\n")

    nibbles = np.array([[int(c, 16) for c in m['attr7_hex']] for m in skaters], dtype=float)

    print(f"{'nibble':7s} {'stat':14s} {'scale':7s} {'offset':7s} {'R2':6s}")
    for nib_idx, stat in NIBBLE_TO_STAT.items():
        vals = np.array([m[stat] if m[stat] is not None else np.nan for m in skaters])
        valid = ~np.isnan(vals)
        x, y = nibbles[valid, nib_idx], vals[valid]
        A = np.vstack([x, np.ones_like(x)]).T
        w, *_ = np.linalg.lstsq(A, y, rcond=None)
        pred = A @ w
        resid = y - pred
        r2 = 1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)
        print(f"n{nib_idx:<6d} {stat:14s} {w[0]:7.3f} {w[1]:7.3f} {r2:6.3f}")


if __name__ == "__main__":
    main()
