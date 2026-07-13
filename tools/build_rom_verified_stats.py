#!/usr/bin/env python3
"""
Builds a clean, ROM-verified dataset of every named stat (Overall Rating +
the 11 identified named attributes) for every player in the game, and
diffs it against nhl-95.com's data to find real discrepancies.

Matching is jersey-number-first (fast, usually correct) with a mandatory
last-name similarity sanity check -- a jersey match whose name doesn't
resemble the CSV name at all (e.g. nhl-95.com's "Gary Suter" was listed at
jersey #20, which in the ROM belongs to a completely different player,
Darin Kimble) falls back to a team-wide name search instead of silently
producing a nonsense comparison. This is the bug that inflated several
"outlier" residuals in an earlier pass at this analysis -- see FINDINGS.md
section 6 for the full story.

Named stats use the multivariate per-stat models in
docs/external_sources/multivariate_stat_models.json (built by
tools/fit_multivariate_named_stats.py), not single-nibble fits -- a live
validation against 5 Vancouver players read off the in-game Team Roster
screen showed single-nibble fits breaking down badly for stats like Def.
Awareness (mean|residual| ~16 live) while the multivariate versions held up
much better (~3.5). See FINDINGS.md section 6 for the live validation.

Run from the repo root: python3 tools/build_rom_verified_stats.py
"""
import csv
import json
import re
import difflib
import numpy as np

ROSTER_JSON = "docs/full_roster_database.json"
STATS_CSV = "docs/external_sources/nhl95com_full_stats.csv"
FAQ_TXT = "docs/external_sources/gamefaqs_28196_roster_ratings.txt"
MULTIVARIATE_MODELS_JSON = "docs/external_sources/multivariate_stat_models.json"

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
    'st_overall': 6, 'agility': 8, 'top_speed': 9, 'shot_power': 10,
    'shot_accuracy': 11, 'stick_handle': 12, 'off_awa': 13, 'def_awa': 14,
    'pass_acc': 15, 'endurance': 16, 'check': 17, 'aggro': 18,
}

with open(MULTIVARIATE_MODELS_JSON) as f:
    _mv = json.load(f)
MV_USE_NIBBLES = _mv['use_nibbles']
MV_MODELS = {stat: np.array(w) for stat, w in _mv['models'].items()}

# Overall Rating: weighted sum, integer-snapped candidate from FINDINGS.md sec 6
OR_WEIGHTS = {1: 2, 2: 2, 3: 3, 4: 1, 5: 1, 6: 1, 8: 1, 9: 2, 10: 1, 11: 0, 12: 1, 13: 0}
OR_BIAS = 12

NAME_MATCH_THRESHOLD = 0.5  # last-name similarity below this = reject the jersey match


def last_name(s):
    return re.sub(r'[^a-z]', '', s.lower().split()[-1]) if s.strip() else ''


def find_rom_player(rom_team, jersey, csv_name):
    """Jersey-first match with a mandatory name sanity check; falls back to a
    team-wide name search if the jersey match doesn't resemble the CSV name
    (catches nhl-95.com jersey-number transcription errors)."""
    key = last_name(csv_name)
    candidates = [p for p in rom_team['roster'] if p['jersey_bcd'] == jersey]
    if candidates:
        best = max(candidates, key=lambda p: difflib.SequenceMatcher(
            None, key, last_name(p['name'])).ratio())
        score = difflib.SequenceMatcher(None, key, last_name(best['name'])).ratio()
        if score >= NAME_MATCH_THRESHOLD:
            return best, 'jersey'
    # fallback: search the whole team by name
    best = max(rom_team['roster'], key=lambda p: difflib.SequenceMatcher(
        None, key, last_name(p['name'])).ratio())
    score = difflib.SequenceMatcher(None, key, last_name(best['name'])).ratio()
    if score >= NAME_MATCH_THRESHOLD:
        return best, 'name-fallback'
    return None, 'no-match'


def predict_overall(nibbles):
    return sum(OR_WEIGHTS[i] * nibbles[i] for i in OR_WEIGHTS if OR_WEIGHTS[i]) + OR_BIAS


def predict_named(nibbles, stat):
    x = np.array([nibbles[i] for i in MV_USE_NIBBLES] + [1.0])
    return float(x @ MV_MODELS[stat])


def main():
    with open(ROSTER_JSON) as f:
        rom_teams = json.load(f)
    rom_lookup = {(t['city'], t['mascot']): t for t in rom_teams}

    with open(STATS_CSV) as f:
        rows = list(csv.reader(f))

    mismatches = []
    diffs = []
    for row in rows[1:]:
        if len(row) < 24:
            continue
        team_abbrev, jersey_s, name, pos = row[1], row[2], row[3], row[5]
        if not name.strip() or not jersey_s.strip().isdigit() or team_abbrev not in TEAM_ABBREV_TO_ROM:
            continue
        rom_team = rom_lookup[TEAM_ABBREV_TO_ROM[team_abbrev]]
        jersey = int(jersey_s)
        found, method = find_rom_player(rom_team, jersey, name)
        if found is None:
            mismatches.append((team_abbrev, name, jersey))
            continue
        if method != 'jersey':
            mismatches.append((team_abbrev, name, jersey, '->', found['name'], method))

        nibbles = [int(c, 16) for c in found['attr7_hex']]
        if pos != 'G':
            pred_or = round(predict_overall(nibbles), 1)
            csv_or = row[STAT_COLS['st_overall']].strip()
            if csv_or.isdigit():
                diffs.append((team_abbrev, found['name'], 'st_overall', int(csv_or), pred_or))
            for stat in MV_MODELS:
                v = row[STAT_COLS[stat]].strip()
                if v.isdigit():
                    pred = round(predict_named(nibbles, stat), 1)
                    diffs.append((team_abbrev, found['name'], stat, int(v), pred))

    print(f"Jersey-mismatch corrections applied: {len([m for m in mismatches if len(m) > 3])}")
    print(f"Unresolved (no reasonable name match at all): {len([m for m in mismatches if len(m) == 3])}\n")
    for m in mismatches:
        print(" ", m)

    diffs.sort(key=lambda d: -abs(d[3] - d[4]))
    print(f"\n{'Team':5s} {'Player':22s} {'Stat':12s} {'nhl95.com':10s} {'ROM-pred':9s} resid")
    for d in diffs[:30]:
        resid = d[3] - d[4]
        print(f"{d[0]:5s} {d[1]:22s} {d[2]:12s} {d[3]:10d} {d[4]:9.1f} {resid:+.1f}")

    resids = np.array([d[3] - d[4] for d in diffs])
    print(f"\nn={len(resids)} mean|resid|={np.mean(np.abs(resids)):.2f} median|resid|={np.median(np.abs(resids)):.2f}")

    with open('docs/external_sources/rom_verified_full_comparison.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['team', 'player', 'stat', 'nhl95com_value', 'rom_predicted', 'residual'])
        for d in diffs:
            w.writerow([d[0], d[1], d[2], d[3], d[4], round(d[3] - d[4], 1)])
    print("\nSaved docs/external_sources/rom_verified_full_comparison.csv")


if __name__ == "__main__":
    main()
