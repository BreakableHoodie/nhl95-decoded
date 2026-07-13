#!/usr/bin/env python3
"""
Refits each named stat (Agility, Top Speed, ...) as a multivariate linear
regression against all 12 relevant attribute nibbles, instead of the single
best-correlated nibble used in the original correlate_named_stats.py pass.

Motivation: a live-verification check against 5 Vancouver players read
directly off the in-game Team Roster screen (see FINDINGS.md section 6)
showed the single-nibble fits breaking down badly for some stats -- e.g.
Def. Awareness mean|residual| of ~16 live, far worse than the ~4 point
median residual the single-nibble fit showed against the nhl-95.com CSV
itself. Overall Rating, by contrast, was already fit multivariately (12
nibbles at once, see section 6 item 1) and validated almost exactly live
(mean|residual| 1.8 across the same 5 players). Refitting every named stat
the same way closed most of the gap: Def. Awareness dropped to mean
|residual| ~3.5 live, Shot Power to ~2.3.

Outputs docs/external_sources/multivariate_stat_models.json, consumed by
build_rom_verified_stats.py.

Run from the repo root: python3 tools/fit_multivariate_named_stats.py
"""
import csv
import json
import re
import difflib
import numpy as np

ROSTER_JSON = "docs/full_roster_database.json"
STATS_CSV = "docs/external_sources/nhl95com_full_stats.csv"
OUT_JSON = "docs/external_sources/multivariate_stat_models.json"

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

STAT_COLS = {
    'agility': 8, 'top_speed': 9, 'shot_power': 10, 'shot_accuracy': 11,
    'stick_handle': 12, 'off_awa': 13, 'def_awa': 14, 'pass_acc': 15,
    'endurance': 16, 'check': 17, 'aggro': 18,
}

# Same 12 nibbles established as relevant to Overall Rating and every named
# stat (nibbles 0, 7, 11 carry no signal in any analysis run so far).
USE_NIBBLES = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]

NAME_MATCH_THRESHOLD = 0.5


def last_name(s):
    return re.sub(r'[^a-z]', '', s.lower().split()[-1]) if s.strip() else ''


def find_rom_player(rom_team, jersey, csv_name):
    key = last_name(csv_name)
    candidates = [p for p in rom_team['roster'] if p['jersey_bcd'] == jersey]
    if candidates:
        best = max(candidates, key=lambda p: difflib.SequenceMatcher(
            None, key, last_name(p['name'])).ratio())
        if difflib.SequenceMatcher(None, key, last_name(best['name'])).ratio() >= NAME_MATCH_THRESHOLD:
            return best
    best = max(rom_team['roster'], key=lambda p: difflib.SequenceMatcher(
        None, key, last_name(p['name'])).ratio())
    if difflib.SequenceMatcher(None, key, last_name(best['name'])).ratio() >= NAME_MATCH_THRESHOLD:
        return best
    return None


def main():
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
        if not name.strip() or not jersey_s.strip().isdigit() or team_abbrev not in TEAM_ABBREV_TO_ROM:
            continue
        if pos == 'G':
            continue
        rom_team = rom_lookup[TEAM_ABBREV_TO_ROM[team_abbrev]]
        found = find_rom_player(rom_team, int(jersey_s), name)
        if found is None:
            continue
        entry = {'attr7_hex': found['attr7_hex']}
        for stat, idx in STAT_COLS.items():
            v = row[idx].strip()
            entry[stat] = int(v) if v.isdigit() else None
        matched.append(entry)

    print(f"Matched {len(matched)} skaters")
    nibbles = np.array([[int(c, 16) for c in m['attr7_hex']] for m in matched], dtype=float)

    models = {}
    print(f"{'stat':14s} {'R2':6s}")
    for stat in STAT_COLS:
        vals = np.array([m[stat] if m[stat] is not None else np.nan for m in matched])
        valid = ~np.isnan(vals)
        X = nibbles[valid][:, USE_NIBBLES]
        y = vals[valid]
        A = np.hstack([X, np.ones((X.shape[0], 1))])
        w, *_ = np.linalg.lstsq(A, y, rcond=None)
        pred = A @ w
        resid = y - pred
        r2 = 1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)
        models[stat] = list(w)
        print(f"{stat:14s} {r2:6.3f}")

    with open(OUT_JSON, 'w') as f:
        json.dump({'use_nibbles': USE_NIBBLES, 'models': models}, f, indent=2)
    print(f"\nSaved {OUT_JSON}")


if __name__ == "__main__":
    main()
