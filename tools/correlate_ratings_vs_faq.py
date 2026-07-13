#!/usr/bin/env python3
"""
Correlates docs/full_roster_database.json's per-player attribute nibbles
against the static "Rating" values in the GameFAQs roster listing
(docs/external_sources/gamefaqs_28196_roster_ratings.txt) to test whether
Overall Rating is a linear combination of specific attribute nibbles.

See FINDINGS.md section 6 for the full writeup and results (R^2 ~0.98).
Two team-matching pitfalls in full_roster_database.json are handled
explicitly here (see FAQ_TO_ROM below and its comment) -- don't revert to a
naive city-prefix match, it silently misattributes every Rangers player to
the Islanders' roster.
"""
import json
import re
import difflib
import numpy as np

ROSTER_JSON = "docs/full_roster_database.json"
FAQ_TXT = "docs/external_sources/gamefaqs_28196_roster_ratings.txt"

# full_roster_database.json has two entries with city == "New York"
# (Islanders and Rangers), and four corrupted `mascot` fields that hold an
# arena name instead of a team nickname (LA/NJ/SJ/TB) -- an explicit
# (city, mascot) map avoids both pitfalls.
FAQ_TO_ROM = {
    'Anaheim Mighty Ducks': ('Anaheim', 'Mighty Ducks'),
    'Boston Bruins': ('Boston', 'Bruins'),
    'Buffalo Sabres': ('Buffalo', 'Sabres'),
    'Calgary Flames': ('Calgary', 'Flames'),
    'Chicago Blackhawks': ('Chicago', 'Blackhawks'),
    'Dallas Stars': ('Dallas', 'Stars'),
    'Detroit Red Wings': ('Detroit', 'Red Wings'),
    'Edmonton Oilers': ('Edmonton', 'Oilers'),
    'Florida Panthers': ('Florida', 'Panthers'),
    'Hartford Whalers': ('Hartford', 'Whalers'),
    'Los Angeles Kings': ('Los Angeles', 'e Great Western Forum'),
    'Montreal Canadiens': ('Montreal', 'Canadiens'),
    'New Jersey Devils': ('New Jersey', 'Brendan Byrne Arena'),
    'New York Islanders': ('New York', 'Islanders'),
    'New York Rangers': ('New York', 'Rangers'),
    'Ottawa Senators': ('Ottawa', 'Senators'),
    'Philadelphia Flyers': ('Philadelphia', 'Flyers'),
    'Pittsburgh Penguins': ('Pittsburgh', 'Penguins'),
    'Quebec Nordiques': ('Quebec', 'Nordiques'),
    'San Jose Sharks': ('San Jose', 'San Jose Arena'),
    'St. Louis Blues': ('St. Louis', 'Blues'),
    'Tampa Bay Lightning': ('Tampa Bay', 'Thunderdome'),
    'Toronto Maple Leafs': ('Toronto', 'Maple Leafs'),
    'Vancouver Canucks': ('Vancouver', 'Canucks'),
    'Washington Capitals': ('Washington', 'Capitals'),
    'Winnipeg Jets': ('Winnipeg', 'Jets'),
}


def last_name_key(s):
    return re.sub(r'[^a-z]', '', s.lower())


def load_matched():
    with open(ROSTER_JSON) as f:
        rom_teams = json.load(f)
    rom_lookup = {(t['city'], t['mascot']): t for t in rom_teams}

    faq_text = open(FAQ_TXT).read()
    player_re = re.compile(r"^# (\d+) - (.+?) - ([GFD]) - (\d+)$", re.M)
    blocks = re.split(r'^@@ (.+?) @@$', faq_text, flags=re.M)

    matched, misses = [], []
    for i in range(1, len(blocks), 2):
        team_full = blocks[i].strip()
        body = blocks[i + 1]
        rom_team = rom_lookup[FAQ_TO_ROM[team_full]]
        for m in player_re.finditer(body):
            jersey, name, pos, rating = int(m.group(1)), m.group(2).strip(), m.group(3), int(m.group(4))
            candidates = [p for p in rom_team['roster'] if p['jersey_bcd'] == jersey]
            if not candidates:
                misses.append((team_full, jersey, name, pos, rating))
                continue
            found = candidates[0]
            if len(candidates) > 1:
                # real in-ROM jersey-number reuse (e.g. Toronto #22:
                # Baumgartner and Gartner) -- disambiguate by last name
                key = last_name_key(name)
                found = max(candidates, key=lambda p: difflib.SequenceMatcher(
                    None, key, last_name_key(p['name'])).ratio())
            matched.append((team_full, jersey, name, pos, rating, found))
    return matched, misses


def fit(nibbles_2d, ratings, keep_idx, label):
    X = nibbles_2d[:, keep_idx]
    X1 = np.hstack([X, np.ones((X.shape[0], 1))])
    w, *_ = np.linalg.lstsq(X1, ratings, rcond=None)
    pred = X1 @ w
    resid = ratings - pred
    r2 = 1 - np.sum(resid ** 2) / np.sum((ratings - ratings.mean()) ** 2)
    print(f"{label}: n={len(ratings)} R2={r2:.4f} "
          f"mean|resid|={np.mean(np.abs(resid)):.3f} max|resid|={np.max(np.abs(resid)):.3f}")
    print(f"  weights (nibbles {keep_idx} + bias): {np.round(w, 3).tolist()}")
    return w, resid


def main():
    matched, misses = load_matched()
    print(f"Matched {len(matched)} players ({len(misses)} misses: {misses})\n")

    nibbles, ratings, positions = [], [], []
    for _, _, _, pos, rating, found in matched:
        nibbles.append([int(c, 16) for c in found['attr7_hex']])
        ratings.append(rating)
        positions.append(pos)
    nibbles = np.array(nibbles, dtype=float)
    ratings = np.array(ratings, dtype=float)
    positions = np.array(positions)

    skater_mask = (positions == 'F') | (positions == 'D')
    fit(nibbles[skater_mask], ratings[skater_mask],
        keep_idx=[1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13], label="Skaters (F+D)")

    goalie_mask = positions == 'G'
    fit(nibbles[goalie_mask], ratings[goalie_mask],
        keep_idx=list(range(14)), label="Goalies (all 14 nibbles, most are structurally 0)")


if __name__ == "__main__":
    main()
