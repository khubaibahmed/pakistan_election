# Pakistan Election Atlas

An interactive, constituency-level history of Pakistan National Assembly elections. The dashboard covers the 2002, 2008, 2013, 2018 and 2024 general elections and supplements them with the historical Members of Parliament constituency mapping.

Built with **Plotly.js**, Python, SQLite, and static GitHub Pages.

## Analytics included

- **Election-wise:** turnout, rejected ballots, winning margins, candidate counts and party seat totals.
- **Constituency-wise:** winner history, historical constituency labels and party finishing positions.
- **Party-wise:** seats, average candidate vote share, total votes and strongest constituencies.
- **Candidate-wise:** searchable histories across parties and constituencies. Party changes are red; consistent affiliation is green.

## Data

The tracked `source_data/` directory contains the five election workbooks and `Members_of_Parliament_Cleaned.xlsx`. The latter maps current constituency identifiers such as `NA-1` to historical constituency names and numbers.

National party seat totals are deliberately kept separate in `data/national_assembly_general_seats.csv`. The workbook sheets are aligned to 266 present-day constituency slots for longitudinal lookup, so counting those aligned sheets would not reproduce historical National Assembly totals. The chart uses the declared general-seat result before independents joined parties. Reserved seats, later defections and by-elections are excluded, and ties at seventh place are retained. Supplemental rows outside the top seven support audited Party-page histories, such as PTI's one seat in 2002 and its 2008 boycott. For 2024 only, PTI-backed winners are presented as an analytical subgroup of candidates who were legally returned as independents; the remaining independents are shown separately.

Candidate identity is based on normalized exact-name matching. Common names can refer to different people, so identity-level conclusions should be checked against authoritative biographical sources.

## Update for a future election

1. Add the new `ElectionYYYY.xlsx` workbook to `source_data/`, following the existing one-sheet-per-constituency format.
2. Add the year and file to `ELECTION_FILES` in `scripts/build_database.py`.
3. Update the cleaned Members of Parliament mapping if constituency boundaries or numbering changed.
4. Add the audited top-seven general-seat result (plus any ties) to `data/national_assembly_general_seats.csv`, preserving the same pre-join result stage and including the source URL and classification note.
5. Install dependencies with `python -m pip install -r requirements.txt`.
6. Run `python scripts/build_database.py` and then `python scripts/export_dashboard_data.py`.
7. Review the generated dashboard locally, then commit the source and generated JSON files.

GitHub Actions publishes the static site to GitHub Pages on every push to `main`.

## Local preview

Run `python -m http.server 8000` from the repository root and open `http://localhost:8000`.

## Technology

Static HTML, CSS, JavaScript, Plotly.js, Python, pandas, SQLite, and GitHub Pages. No server or visitor tracking is required.
