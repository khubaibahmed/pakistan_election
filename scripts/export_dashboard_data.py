from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "pakistan_elections.sqlite"
DATA_DIR = ROOT / "data"


def clean_value(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def rows(conn: sqlite3.Connection, query: str, params=()):
    return [
        {key: clean_value(value) for key, value in dict(row).items()}
        for row in conn.execute(query, params)
    ]


def candidate_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def period_constituency_label(period_label: str | None, fallback: str) -> str:
    if not period_label or ":" not in period_label:
        return fallback
    label = period_label.split(":", 1)[1].strip()
    label = re.sub(r"^na\s*-?\s*(\d+)", r"NA-\1", label, flags=re.I)
    return label[:5].upper() + label[5:].title() if label.upper().startswith("NA-") else label.title()


def dump(name: str, payload) -> None:
    path = DATA_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"wrote {path.name}: {path.stat().st_size:,} bytes")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    summaries = rows(conn, """
        SELECT year, constituency_no, candidate_count, turnout, turnout_pct,
               rejected_ballots, rejected_ballots_pct, registered_electors,
               winner_candidate, winner_party_group, winner_votes, winner_vote_pct,
               runner_up_candidate, runner_up_party_group, runner_up_votes,
               margin_votes, margin_pct_points
        FROM constituency_summary ORDER BY year, constituency_no
    """)
    candidate_results = rows(conn, """
        SELECT year, constituency_no, candidate_name, party_raw, party_std, party_group,
               votes, vote_pct, swing_pct, candidate_rank, is_winner, is_runner_up
        FROM candidate_results ORDER BY year, constituency_no, candidate_rank
    """)
    member_rows = rows(conn, """
        SELECT constituency_no, period_label, election_year, member_name,
               party_raw, party_std, party_group
        FROM members_history ORDER BY constituency_no, election_year, member_name
    """)

    years = sorted({row["year"] for row in summaries})
    constituencies = sorted({row["constituency_no"] for row in summaries})

    period_by_year = {}
    periods_by_const = defaultdict(dict)
    for row in member_rows:
        key = (row["constituency_no"], row["election_year"])
        period_by_year[key] = row["period_label"]
        periods_by_const[str(row["constituency_no"])][row["period_label"]] = {
            "period": row["period_label"].split(":", 1)[0].strip() if row["period_label"] else "",
            "label": period_constituency_label(row["period_label"], f"NA-{row['constituency_no']}"),
        }

    summary_by_const = defaultdict(list)
    for row in summaries:
        period = period_by_year.get((row["constituency_no"], row["year"]))
        row["constituency_label"] = period_constituency_label(period, f"NA-{row['constituency_no']}")
        summary_by_const[str(row["constituency_no"])].append(row)

    party_history_by_const = defaultdict(list)
    for row in candidate_results:
        period = period_by_year.get((row["constituency_no"], row["year"]))
        row["constituency_label"] = period_constituency_label(period, f"NA-{row['constituency_no']}")
        party_history_by_const[str(row["constituency_no"])].append(row)

    constituency_detail = {}
    for number in constituencies:
        key = str(number)
        constituency_detail[key] = {
            "current_code": f"NA-{number}",
            "periods": list(periods_by_const[key].values()),
            "elections": summary_by_const[key],
            "party_history": party_history_by_const[key],
        }

    seat_rows = rows(conn, """
        SELECT year, winner_party_group AS party, COUNT(*) AS seats
        FROM constituency_summary
        GROUP BY year, winner_party_group ORDER BY year, seats DESC
    """)
    party_year = rows(conn, """
        SELECT cr.year, cr.party_group AS party,
               COUNT(*) AS contests,
               COUNT(DISTINCT lower(cr.candidate_name)) AS candidates,
               COUNT(DISTINCT cr.constituency_no) AS constituencies,
               SUM(cr.votes) AS votes,
               AVG(cr.vote_pct) AS mean_vote_pct,
               SUM(cr.is_winner) AS seats
        FROM candidate_results cr
        GROUP BY cr.year, cr.party_group
        ORDER BY cr.year, seats DESC, votes DESC
    """)
    party_order = [
        item[0] for item in conn.execute("""
            SELECT winner_party_group, COUNT(*) total
            FROM constituency_summary
            GROUP BY winner_party_group ORDER BY total DESC
        """).fetchall()
    ]

    raw_candidate_groups = defaultdict(list)
    base_display_names = defaultdict(Counter)
    for row in candidate_results:
        base_key = candidate_key(row["candidate_name"])
        if not base_key:
            continue
        row["source_type"] = "contest"
        raw_candidate_groups[base_key].append(row)
        base_display_names[base_key][row["candidate_name"]] += 1

    # If the same normalized name represents different parties in the same election,
    # treat it as an ambiguous common name and split the profile by affiliation.
    ambiguous_names = set()
    for base_key, timeline in raw_candidate_groups.items():
        parties_by_year = defaultdict(set)
        for item in timeline:
            parties_by_year[item["year"]].add(item.get("party_std") or item.get("party_group") or "Unknown")
        if any(len(parties) > 1 for parties in parties_by_year.values()):
            ambiguous_names.add(base_key)

    grouped_candidates = defaultdict(list)
    display_names = defaultdict(Counter)
    def resolved_key(base_key, item):
        if base_key not in ambiguous_names:
            return base_key
        party = item.get("party_std") or item.get("party_group") or "Unknown"
        return f"{base_key}::{candidate_key(party) or 'unknown'}"

    for base_key, timeline in raw_candidate_groups.items():
        for item in timeline:
            key = resolved_key(base_key, item)
            grouped_candidates[key].append(item)
            display_names[key][item["candidate_name"]] += 1

    # Add pre-2002 elected-member history, which is unavailable in the contest workbooks.
    for row in member_rows:
        if not row["election_year"] or row["election_year"] >= min(years):
            continue
        base_key = candidate_key(row["member_name"])
        if not base_key:
            continue
        member_item = {
            "party_std": row["party_std"], "party_group": row["party_group"]
        }
        key = resolved_key(base_key, member_item)
        display_names[key][row["member_name"]] += 1
        grouped_candidates[key].append({
            "year": row["election_year"],
            "constituency_no": row["constituency_no"],
            "constituency_label": period_constituency_label(row["period_label"], f"NA-{row['constituency_no']}"),
            "candidate_name": row["member_name"],
            "party_raw": row["party_raw"],
            "party_std": row["party_std"],
            "party_group": row["party_group"],
            "votes": None,
            "vote_pct": None,
            "swing_pct": None,
            "candidate_rank": 1,
            "is_winner": 1,
            "is_runner_up": 0,
            "source_type": "member_history",
        })

    candidate_profiles = {}
    candidate_index = []
    for key, timeline in grouped_candidates.items():
        timeline.sort(key=lambda item: (item["year"], item["constituency_no"], item.get("candidate_rank") or 99))
        prior_party = None
        switched_count = 0
        for item in timeline:
            party = item.get("party_std") or item.get("party_group") or "Unknown"
            item["party_switched"] = prior_party is not None and party != prior_party
            if item["party_switched"]:
                switched_count += 1
            prior_party = party
        parties = sorted({item.get("party_std") or item.get("party_group") or "Unknown" for item in timeline})
        name = display_names[key].most_common(1)[0][0]
        base_key = key.split("::", 1)[0]
        ambiguous_name = base_key in ambiguous_names
        if ambiguous_name:
            qualifier = timeline[0].get("party_std") or timeline[0].get("party_group") or "Unknown"
            name = f"{name} · {qualifier}"
        contests = sum(item["source_type"] == "contest" for item in timeline)
        wins = sum(bool(item.get("is_winner")) for item in timeline if item["source_type"] == "contest")
        constituencies_seen = sorted({item["constituency_label"] for item in timeline})
        profile = {
            "key": key,
            "name": name,
            "contests": contests,
            "wins": wins,
            "parties": parties,
            "switches": switched_count,
            "loyal": len(parties) <= 1,
            "ambiguous_name": ambiguous_name,
            "constituencies": constituencies_seen,
            "timeline": timeline,
        }
        candidate_profiles[key] = profile
        candidate_index.append({field: profile[field] for field in ("key", "name", "contests", "wins", "parties", "switches", "loyal", "constituencies")})

    candidate_index.sort(key=lambda item: (-item["contests"], item["name"].lower()))
    switch_leaders = sorted(
        (item for item in candidate_index if item["contests"] >= 2),
        key=lambda item: (-item["switches"], -item["contests"], item["name"].lower()),
    )[:40]

    meta = {
        "years": years,
        "constituencies": len(constituencies),
        "candidate_records": len(candidate_results),
        "candidate_profiles": len(candidate_profiles),
        "historical_member_records": len(member_rows),
        "generated_from": [f"Election{year}.xlsx" for year in years] + ["Members_of_Parliament_Cleaned.xlsx"],
    }
    dump("dashboard.json", {
        "meta": meta,
        "overview": summaries,
        "seat_counts": seat_rows,
        "party_year": party_year,
        "party_order": party_order,
        "constituencies": constituency_detail,
        "switch_leaders": switch_leaders,
    })
    dump("candidates.json", {"index": candidate_index, "profiles": candidate_profiles})
    conn.close()


if __name__ == "__main__":
    main()
