
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT_DIR / "source_data"

ELECTION_FILES: dict[int, Path] = {
    2002: BASE_DIR / "Election2002.xlsx",
    2008: BASE_DIR / "Election2008.xlsx",
    2013: BASE_DIR / "Election2013.xlsx",
    2018: BASE_DIR / "Election2018.xlsx",
    2024: BASE_DIR / "Election2024.xlsx",
}
MEMBERS_FILE = BASE_DIR / "Members_of_Parliament_Cleaned.xlsx"
OUTPUT_DB = ROOT_DIR / "data" / "pakistan_elections.sqlite"

YEARS = [2002, 2008, 2013, 2018, 2024]

SUMMARY_LABELS = {
    "valid ballots": "valid_ballots",
    "total valid votes": "valid_ballots",
    "valid votes": "valid_ballots",
    "rejected ballots": "rejected_ballots",
    "turnout": "turnout",
    "majority": "majority",
    "registered electors": "registered_electors",
}

MAJOR_PARTY_GROUPS = {
    "PML(N)",
    "PML(Q)",
    "PPP",
    "PTI",
    "MMA",
    "JUI(F)",
    "ANP",
    "MQM",
    "Independents",
    "PPPP",
}


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\[[^\]]*\]", "", text)  # remove footnotes like [a]
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_num(value) -> float:
    text = clean_text(value)
    if not text:
        return np.nan
    text = text.replace(",", "").replace("†", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else np.nan


def norm_key(value) -> str:
    text = clean_text(value).lower()
    text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = re.sub(r"[()]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_constituency_no(sheet_name: str) -> int | None:
    match = re.search(r"NA\s*-?\s*(\d+)", str(sheet_name), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def metric_from_labels(*labels: Iterable[str]) -> str | None:
    for label in labels:
        key = norm_key(label)
        if key in SUMMARY_LABELS:
            return SUMMARY_LABELS[key]
    return None


def is_transition_row(*labels) -> bool:
    text = " | ".join(clean_text(label) for label in labels if clean_text(label))
    key = norm_key(text)
    return (
        "gain from" in key
        or re.search(r"\bhold\b", key) is not None
        or "win new seat" in key
        or key == "swing"
    )


def standardise_party(party: str) -> str | None:
    raw = clean_text(party)
    if not raw:
        return None

    text = raw
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)

    key = norm_key(text)
    key_np = re.sub(r"[^a-z0-9]+", " ", key).strip()

    if key_np in {"pti", "pakistan tehreek e insaf"}:
        return "PTI"

    if key_np in {"ppp", "pakistan peoples party", "pakistan people party"}:
        return "PPP"

    if key_np in {"pppp", "pakistan peoples party parliamentarians"}:
        return "PPPP"

    if key_np in {"pml n", "pmln", "pakistan muslim league n"} or "muslim league n" in key_np:
        return "PML(N)"

    # User requested PML and PML(Q) to be treated as the same party.
    if (
        key_np in {"pml q", "pmlq", "pakistan muslim league q", "pakistan muslim league", "pml"}
        or "muslim league q" in key_np
    ):
        return "PML(Q)"

    if key_np in {"mma", "muttahida majlis e amal"}:
        return "MMA"

    if key_np in {"jui f", "juif", "jui-f"} or "ulema e islam f" in key_np or "ulema islam f" in key_np:
        return "JUI(F)"

    if key_np in {"anp", "awami national party"}:
        return "ANP"

    # User requested all MQM variants to be merged in party-based analysis.
    if key_np.startswith("mqm") or "muttahida qaumi movement" in key_np:
        return "MQM"

    if key_np in {
        "ind",
        "independent",
        "independents",
        "independant",
        "independants",
        "independent politician",
    }:
        return "Independent"

    compact_aliases = {
        "bnp m": "BNP(M)",
        "bnp a": "BNP(A)",
        "jui s": "JUI(S)",
        "jup n": "JUP(N)",
        "ppp s": "PPP(S)",
        "ppp sb": "PPP(SB)",
        "qwp s": "QWP(S)",
        "pml j": "PML(J)",
        "pml z": "PML(Z)",
        "pml f": "PML(F)",
        "ml q": "PML(Q)",
    }
    if key_np in compact_aliases:
        return compact_aliases[key_np]

    return text


def party_group(party_std: str | None) -> str:
    if party_std == "PML(N)":
        return "PML(N)"
    if party_std == "PML(Q)":
        return "PML(Q)"
    if party_std == "PPP":
        return "PPP"
    if party_std == "PTI":
        return "PTI"
    if party_std == "MMA":
        return "MMA"
    if party_std == "JUI(F)":
        return "JUI(F)"
    if party_std == "ANP":
        return "ANP"
    if party_std == "MQM":
        return "MQM"
    if party_std == "Independent":
        return "Independents"
    if party_std == "PPPP":
        return "PPPP"
    return "Other"


def read_election_workbooks() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidate_rows: list[dict] = []
    summary_rows: list[dict] = []
    constituency_rows: list[dict] = []

    for year, workbook_path in ELECTION_FILES.items():
        xl = pd.ExcelFile(workbook_path)

        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            constituency_no = parse_constituency_no(sheet)

            if constituency_no is None:
                continue

            party_col = "Party.1" if "Party.1" in df.columns else ("Party" if "Party" in df.columns else df.columns[0])
            pct_col = "%" if "%" in df.columns else next((col for col in df.columns if "%" in str(col)), None)
            swing_col = "±%" if "±%" in df.columns else None

            current_candidates: list[dict] = []
            metrics: dict[str, float] = {}
            metrics_pct: dict[str, float] = {}

            for _, row in df.iterrows():
                stat_label = clean_text(row.get("Party"))
                party_raw = clean_text(row.get(party_col))
                candidate_name = clean_text(row.get("Candidate"))
                votes = clean_num(row.get("Votes"))
                vote_pct = clean_num(row.get(pct_col)) if pct_col else np.nan
                swing_pct = clean_num(row.get(swing_col)) if swing_col else np.nan

                summary_metric = metric_from_labels(stat_label, candidate_name, party_raw)
                if summary_metric:
                    metric_row = {
                        "year": year,
                        "constituency_no": constituency_no,
                        "sheet_name": sheet,
                        "metric_name": summary_metric,
                        "metric_value": votes,
                        "metric_pct": vote_pct,
                    }
                    summary_rows.append(metric_row)
                    metrics[summary_metric] = votes
                    metrics_pct[f"{summary_metric}_pct"] = vote_pct
                    continue

                if is_transition_row(stat_label, party_raw, candidate_name):
                    continue

                # The workbook uses "Others" as an aggregated bucket, not as a real candidate.
                if norm_key(party_raw) == "others":
                    continue

                if not candidate_name or pd.isna(votes):
                    continue

                party_std = standardise_party(party_raw)
                result_row = {
                    "year": year,
                    "constituency_no": constituency_no,
                    "sheet_name": sheet,
                    "candidate_name": candidate_name,
                    "party_raw": party_raw or None,
                    "party_std": party_std,
                    "party_group": party_group(party_std),
                    "votes": int(votes) if float(votes).is_integer() else float(votes),
                    "vote_pct": vote_pct,
                    "swing_pct": swing_pct,
                }
                current_candidates.append(result_row)
                candidate_rows.append(result_row)

            current_candidates = sorted(current_candidates, key=lambda item: (-item["votes"], item["candidate_name"]))
            for rank, row in enumerate(current_candidates, start=1):
                row["candidate_rank"] = rank
                row["is_winner"] = 1 if rank == 1 else 0
                row["is_runner_up"] = 1 if rank == 2 else 0

            winner = current_candidates[0] if len(current_candidates) >= 1 else {}
            runner_up = current_candidates[1] if len(current_candidates) >= 2 else {}

            constituency_rows.append(
                {
                    "year": year,
                    "constituency_no": constituency_no,
                    "sheet_name": sheet,
                    "candidate_count": len(current_candidates),
                    "winner_candidate": winner.get("candidate_name"),
                    "winner_party_raw": winner.get("party_raw"),
                    "winner_party_std": winner.get("party_std"),
                    "winner_party_group": winner.get("party_group"),
                    "winner_votes": winner.get("votes", np.nan),
                    "winner_vote_pct": winner.get("vote_pct", np.nan),
                    "runner_up_candidate": runner_up.get("candidate_name"),
                    "runner_up_party_raw": runner_up.get("party_raw"),
                    "runner_up_party_std": runner_up.get("party_std"),
                    "runner_up_party_group": runner_up.get("party_group"),
                    "runner_up_votes": runner_up.get("votes", np.nan),
                    "runner_up_vote_pct": runner_up.get("vote_pct", np.nan),
                    "margin_votes": (
                        winner.get("votes", np.nan) - runner_up.get("votes", np.nan)
                        if len(current_candidates) >= 2
                        else np.nan
                    ),
                    "margin_pct_points": (
                        winner.get("vote_pct", np.nan) - runner_up.get("vote_pct", np.nan)
                        if len(current_candidates) >= 2
                        else np.nan
                    ),
                    **metrics,
                    **metrics_pct,
                }
            )

    candidate_results = pd.DataFrame(candidate_rows).sort_values(
        ["year", "constituency_no", "candidate_rank", "candidate_name"]
    ).reset_index(drop=True)

    summary_metrics = pd.DataFrame(summary_rows).sort_values(
        ["year", "constituency_no", "metric_name"]
    ).reset_index(drop=True)

    constituency_summary = pd.DataFrame(constituency_rows).sort_values(
        ["year", "constituency_no"]
    ).reset_index(drop=True)

    return candidate_results, summary_metrics, constituency_summary


def read_members_workbook() -> pd.DataFrame:
    df = pd.read_excel(MEMBERS_FILE, sheet_name="Members")
    rows: list[dict] = []
    for _, row in df.iterrows():
        constituency_no = parse_constituency_no(row.get("Const"))
        member_name = clean_text(row.get("Member"))
        if constituency_no is None or not member_name:
            continue
        election_year_num = clean_num(row.get("Election"))
        party_raw = clean_text(row.get("Party"))
        party_std = standardise_party(party_raw)
        rows.append(
            {
                "constituency_no": constituency_no,
                "sheet_name": f"NA{constituency_no}",
                "period_label": clean_text(row.get("Period")),
                "election_year": int(election_year_num) if pd.notna(election_year_num) else None,
                "member_name": member_name,
                "party_raw": party_raw or None,
                "party_std": party_std,
                "party_group": party_group(party_std),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["constituency_no", "election_year", "member_name"]
    ).reset_index(drop=True)


def build_party_dimension(candidate_results: pd.DataFrame, members_history: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat(
        [
            candidate_results[["party_raw", "party_std", "party_group"]],
            members_history[["party_raw", "party_std", "party_group"]],
        ],
        ignore_index=True,
    ).drop_duplicates()

    combined["is_major_analysis_party"] = combined["party_group"].isin(MAJOR_PARTY_GROUPS).astype(int)
    combined = combined.sort_values(["party_group", "party_std", "party_raw"], na_position="last").reset_index(drop=True)
    return combined


def save_to_sqlite(
    election_sources: pd.DataFrame,
    constituencies: pd.DataFrame,
    party_dim: pd.DataFrame,
    candidate_results: pd.DataFrame,
    summary_metrics: pd.DataFrame,
    constituency_summary: pd.DataFrame,
    members_history: pd.DataFrame,
    output_db: Path = OUTPUT_DB,
) -> None:
    if output_db.exists():
        output_db.unlink()

    with sqlite3.connect(output_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")

        conn.executescript(
            """
            CREATE TABLE election_sources (
                year INTEGER PRIMARY KEY,
                source_file TEXT NOT NULL
            );

            CREATE TABLE constituencies (
                constituency_no INTEGER PRIMARY KEY,
                constituency_code TEXT NOT NULL UNIQUE
            );

            CREATE TABLE party_dimension (
                party_dim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                party_raw TEXT,
                party_std TEXT,
                party_group TEXT NOT NULL,
                is_major_analysis_party INTEGER NOT NULL CHECK (is_major_analysis_party IN (0, 1))
            );

            CREATE TABLE candidate_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                constituency_no INTEGER NOT NULL,
                sheet_name TEXT NOT NULL,
                candidate_name TEXT NOT NULL,
                party_raw TEXT,
                party_std TEXT,
                party_group TEXT NOT NULL,
                votes INTEGER NOT NULL,
                vote_pct REAL,
                swing_pct REAL,
                candidate_rank INTEGER NOT NULL,
                is_winner INTEGER NOT NULL CHECK (is_winner IN (0, 1)),
                is_runner_up INTEGER NOT NULL CHECK (is_runner_up IN (0, 1)),
                FOREIGN KEY (year) REFERENCES election_sources(year),
                FOREIGN KEY (constituency_no) REFERENCES constituencies(constituency_no)
            );

            CREATE TABLE summary_metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                constituency_no INTEGER NOT NULL,
                sheet_name TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                metric_pct REAL,
                FOREIGN KEY (year) REFERENCES election_sources(year),
                FOREIGN KEY (constituency_no) REFERENCES constituencies(constituency_no)
            );

            CREATE TABLE constituency_summary (
                summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                constituency_no INTEGER NOT NULL,
                sheet_name TEXT NOT NULL,
                candidate_count INTEGER,
                valid_ballots REAL,
                valid_ballots_pct REAL,
                rejected_ballots REAL,
                rejected_ballots_pct REAL,
                turnout REAL,
                turnout_pct REAL,
                majority REAL,
                majority_pct REAL,
                registered_electors REAL,
                registered_electors_pct REAL,
                winner_candidate TEXT,
                winner_party_raw TEXT,
                winner_party_std TEXT,
                winner_party_group TEXT,
                winner_votes REAL,
                winner_vote_pct REAL,
                runner_up_candidate TEXT,
                runner_up_party_raw TEXT,
                runner_up_party_std TEXT,
                runner_up_party_group TEXT,
                runner_up_votes REAL,
                runner_up_vote_pct REAL,
                margin_votes REAL,
                margin_pct_points REAL,
                FOREIGN KEY (year) REFERENCES election_sources(year),
                FOREIGN KEY (constituency_no) REFERENCES constituencies(constituency_no)
            );

            CREATE TABLE members_history (
                member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                constituency_no INTEGER NOT NULL,
                sheet_name TEXT NOT NULL,
                period_label TEXT,
                election_year INTEGER,
                member_name TEXT NOT NULL,
                party_raw TEXT,
                party_std TEXT,
                party_group TEXT NOT NULL,
                FOREIGN KEY (constituency_no) REFERENCES constituencies(constituency_no)
            );

            CREATE INDEX idx_candidate_results_year_constituency
                ON candidate_results(year, constituency_no);

            CREATE INDEX idx_candidate_results_party_group
                ON candidate_results(party_group);

            CREATE INDEX idx_summary_metrics_year_metric
                ON summary_metrics(year, metric_name);

            CREATE INDEX idx_constituency_summary_year_constituency
                ON constituency_summary(year, constituency_no);

            CREATE INDEX idx_members_history_constituency_year
                ON members_history(constituency_no, election_year);

            CREATE VIEW vw_major_party_candidates AS
            SELECT *
            FROM candidate_results
            WHERE party_group <> 'Other';

            CREATE VIEW vw_major_party_seats AS
            SELECT
                year,
                winner_party_group AS party_group,
                COUNT(*) AS seats_won
            FROM constituency_summary
            WHERE winner_party_group IN (
                'PML(N)', 'PML(Q)', 'PPP', 'PTI', 'MMA', 'JUI(F)', 'ANP', 'MQM', 'Independents', 'PPPP'
            )
            GROUP BY year, winner_party_group
            ORDER BY year, seats_won DESC;

            CREATE VIEW vw_repeat_contestants AS
            SELECT
                constituency_no,
                candidate_name,
                COUNT(DISTINCT year) AS times_contested,
                GROUP_CONCAT(DISTINCT year) AS years_contested
            FROM candidate_results
            GROUP BY constituency_no, candidate_name;
            """
        )

        election_sources.to_sql("election_sources", conn, if_exists="append", index=False)
        constituencies.to_sql("constituencies", conn, if_exists="append", index=False)
        party_dim.to_sql("party_dimension", conn, if_exists="append", index=False)
        candidate_results.to_sql("candidate_results", conn, if_exists="append", index=False)
        summary_metrics.to_sql("summary_metrics", conn, if_exists="append", index=False)
        constituency_summary.to_sql("constituency_summary", conn, if_exists="append", index=False)
        members_history.to_sql("members_history", conn, if_exists="append", index=False)


def plot_metric_scatter(
    df: pd.DataFrame,
    metric: str,
    title: str,
    ylabel: str,
    years: list[int] | None = None,
    x_tick_step: int = 10,
) -> None:
    if years is None:
        years = YEARS

    plt.figure(figsize=(18, 6))
    markers = ["o", "s", "^", "D", "x"]

    for i, year in enumerate(years):
        subset = df[df["year"] == year].sort_values("constituency_no")
        plt.scatter(
            subset["constituency_no"],
            subset[metric],
            s=18,
            marker=markers[i % len(markers)],
            alpha=0.85,
            label=str(year),
        )

    plt.title(title)
    plt.xlabel("Constituency number")
    plt.ylabel(ylabel)
    plt.xlim(0, 266)
    plt.xticks(np.arange(0, 271, x_tick_step))
    plt.grid(axis="y", alpha=0.25)
    plt.legend(ncol=len(years), frameon=True)
    plt.tight_layout()
    plt.show()


def plot_party_scatter(
    df: pd.DataFrame,
    party_col: str,
    title: str,
    years: list[int] | None = None,
    x_tick_step: int = 10,
) -> None:
    if years is None:
        years = YEARS

    parties = sorted([p for p in df[party_col].dropna().unique() if str(p).strip()])
    code_map = {party: idx for idx, party in enumerate(parties, start=1)}

    plot_df = df.copy()
    plot_df["party_code"] = plot_df[party_col].map(code_map)

    plt.figure(figsize=(18, max(6, min(12, len(parties) * 0.35))))
    markers = ["o", "s", "^", "D", "x"]

    for i, year in enumerate(years):
        subset = plot_df[plot_df["year"] == year].sort_values("constituency_no")
        plt.scatter(
            subset["constituency_no"],
            subset["party_code"],
            s=20,
            marker=markers[i % len(markers)],
            alpha=0.85,
            label=str(year),
        )

    plt.title(title)
    plt.xlabel("Constituency number")
    plt.ylabel("Party")
    plt.xlim(0, 266)
    plt.xticks(np.arange(0, 271, x_tick_step))
    plt.yticks(list(code_map.values()), list(code_map.keys()))
    plt.grid(axis="x", alpha=0.10)
    plt.legend(ncol=len(years), frameon=True)
    plt.tight_layout()
    plt.show()


def build_database(output_db: Path = OUTPUT_DB) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidate_results, summary_metrics, constituency_summary = read_election_workbooks()
    members_history = read_members_workbook()

    election_sources = pd.DataFrame(
        {"year": list(ELECTION_FILES.keys()), "source_file": [path.name for path in ELECTION_FILES.values()]}
    ).sort_values("year")

    constituencies = pd.DataFrame(
        {
            "constituency_no": sorted(
                set(candidate_results["constituency_no"].dropna().astype(int).tolist())
                | set(members_history["constituency_no"].dropna().astype(int).tolist())
            )
        }
    )
    constituencies["constituency_code"] = constituencies["constituency_no"].map(lambda x: f"NA{x}")

    party_dim = build_party_dimension(candidate_results, members_history)

    save_to_sqlite(
        election_sources=election_sources,
        constituencies=constituencies,
        party_dim=party_dim,
        candidate_results=candidate_results,
        summary_metrics=summary_metrics,
        constituency_summary=constituency_summary,
        members_history=members_history,
        output_db=output_db,
    )

    return candidate_results, summary_metrics, constituency_summary, members_history


def main() -> None:
    candidate_results, summary_metrics, constituency_summary, members_history = build_database(OUTPUT_DB)

    print(f"Database written to: {OUTPUT_DB}")
    print(f"candidate_results: {candidate_results.shape}")
    print(f"summary_metrics: {summary_metrics.shape}")
    print(f"constituency_summary: {constituency_summary.shape}")
    print(f"members_history: {members_history.shape}")

if __name__ == "__main__":
    main()
