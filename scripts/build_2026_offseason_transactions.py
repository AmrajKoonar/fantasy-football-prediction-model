"""Build data/manual/2026_offseason_transactions.csv from verified patch rows."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-07-29"
SEASON = 2026
OUT = ROOT / "data/manual/2026_offseason_transactions.csv"

# (player_name, position, old_team, new_team, type, status, priority, depth, starter_conf, role_unc, notes)
# new_team FA for unsigned; RET for retired destination sentinel with roster_status=retired
MOVES: list[tuple] = [
    # QB moves
    ("Malik Willis", "QB", "GB", "MIA", "signed", "active", "P1", 1, "medium", "high", "Miami QB competition"),
    ("Geno Smith", "QB", "LV", "NYJ", "trade", "active", "P1", 1, "high", "medium", "Jets offense context"),
    ("Justin Fields", "QB", "NYJ", "KC", "trade", "active", "P1", 2, "low", "high", "Do not replace Mahomes as QB1"),
    ("Tua Tagovailoa", "QB", "MIA", "ATL", "signed", "active", "P1", 1, "medium", "high", "Compete with Penix/Rush"),
    ("Kirk Cousins", "QB", "ATL", "LV", "signed", "active", "P1", 1, "medium", "high", "Compete with Mendoza"),
    ("Kyler Murray", "QB", "ARI", "MIN", "signed", "active", "P1", 1, "high", "medium", "Minnesota offense"),
    ("Tyrod Taylor", "QB", "NYJ", "GB", "signed", "active", "P2", 2, "low", "medium", "GB depth"),
    ("Andy Dalton", "QB", "CAR", "PHI", "trade", "active", "P2", 2, "low", "low", "PHI backup"),
    ("Kenny Pickett", "QB", "LV", "CAR", "signed", "active", "P2", 2, "low", "medium", "CAR QB room"),
    ("Zach Wilson", "QB", "MIA", "NO", "signed", "active", "P2", 2, "low", "medium", "NO QB room"),
    ("Gardner Minshew", "QB", "KC", "ARI", "signed", "active", "P1", 1, "medium", "high", "Compete with Carson Beck"),
    ("Sam Howell", "QB", "PHI", "DAL", "signed", "active", "P2", 2, "low", "low", "DAL depth"),
    ("Jake Browning", "QB", "CIN", "TB", "signed", "active", "P2", 2, "low", "low", "TB depth"),
    ("Cooper Rush", "QB", "BAL", "ATL", "signed", "active", "P2", 3, "low", "high", "ATL camp competition"),
    ("Trevor Siemian", "QB", "ATL", "FA", "released", "unsigned", "P3", None, "low", "high", "Released ATL"),
    # QB same-team
    ("Aaron Rodgers", "QB", "PIT", "PIT", "re_signed", "active", "P1", 1, "high", "medium", "Expected PIT starter"),
    ("Daniel Jones", "QB", "IND", "IND", "re_signed", "active", "P1", 1, "medium", "medium", "IND competition"),
    ("Matthew Stafford", "QB", "LAR", "LAR", "extended", "active", "P1", 1, "high", "low", "LAR starter"),
    ("Joe Flacco", "QB", "CIN", "CIN", "re_signed", "active", "P3", 2, "low", "low", "CIN depth"),
    ("Trey Lance", "QB", "LAC", "LAC", "re_signed", "active", "P3", 2, "low", "low", "LAC depth"),
    # RB moves
    ("David Montgomery", "RB", "DET", "HOU", "trade", "active", "P1", 1, "medium", "medium", "HOU backfield"),
    ("Kenneth Walker III", "RB", "SEA", "KC", "signed", "active", "P1", 1, "medium", "high", "Major KC option"),
    ("Rico Dowdle", "RB", "CAR", "PIT", "signed", "active", "P1", 1, "medium", "medium", "PIT backfield"),
    ("Travis Etienne Jr.", "RB", "JAX", "NO", "signed", "active", "P1", 1, "medium", "medium", "NO backfield"),
    ("Rachaad White", "RB", "TB", "WAS", "signed", "active", "P1", 1, "medium", "medium", "WAS backfield"),
    ("Jerome Ford", "RB", "CLE", "WAS", "signed", "active", "P2", 2, "low", "medium", "Compete with White"),
    ("Isiah Pacheco", "RB", "KC", "DET", "signed", "active", "P1", 1, "medium", "medium", "DET backfield"),
    ("Tyler Allgeier", "RB", "ATL", "ARI", "signed", "active", "P1", 2, "medium", "high", "With Jeremiyah Love"),
    ("Brian Robinson Jr.", "RB", "SF", "ATL", "signed", "active", "P1", 2, "medium", "medium", "Behind/alongside Bijan"),
    ("Ty Chandler", "RB", "MIN", "NO", "signed", "active", "P2", 2, "low", "medium", "Crowded NO"),
    ("AJ Dillon", "RB", "PHI", "CAR", "signed", "active", "P2", 2, "low", "medium", "CAR backfield"),
    ("Kenny Gainwell", "RB", "PIT", "TB", "signed", "active", "P2", 1, "medium", "medium", "After White departure"),
    ("Keaton Mitchell", "RB", "BAL", "LAC", "signed", "active", "P2", 2, "low", "medium", "Change-of-pace"),
    ("Emanuel Wilson", "RB", "GB", "SEA", "signed", "active", "P2", 2, "low", "medium", "After Walker departure"),
    ("Michael Carter", "RB", "ARI", "TEN", "signed", "active", "P2", 2, "low", "medium", "TEN backfield"),
    ("Dameon Pierce", "RB", "KC", "PHI", "signed", "active", "P2", 2, "low", "medium", "PHI backfield"),
    ("Ameer Abdullah", "RB", "IND", "JAX", "signed", "active", "P3", 3, "low", "low", "Receiving back depth"),
    ("Chris Rodriguez Jr.", "RB", "WAS", "JAX", "signed", "active", "P2", 2, "low", "medium", "After Etienne departure"),
    ("Emari Demercado", "RB", "ARI", "KC", "signed", "active", "P2", 2, "low", "medium", "With Walker"),
    ("Evan Hull", "RB", "IND", "HOU", "signed", "active", "P3", 3, "low", "low", "HOU depth"),
    ("De'Von Achane", "RB", "MIA", "MIA", "extended", "active", "P1", 1, "high", "medium", "Primary MIA skill"),
    ("Breece Hall", "RB", "NYJ", "NYJ", "re_signed", "active", "P1", 1, "high", "medium", "Jets lead back"),
    ("J.K. Dobbins", "RB", "DEN", "DEN", "re_signed", "active", "P1", 1, "medium", "medium", "DEN backfield"),
    ("Javonte Williams", "RB", "DAL", "DAL", "re_signed", "active", "P1", 1, "medium", "medium", "DAL backfield"),
    ("Aaron Jones", "RB", "MIN", "MIN", "revised_contract", "active", "P1", 1, "medium", "high", "QB change competition"),
    # WR moves
    ("Jaylen Waddle", "WR", "MIA", "DEN", "trade", "active", "P1", 1, "high", "medium", "DEN context"),
    ("A.J. Brown", "WR", "PHI", "NE", "trade", "active", "P1", 1, "high", "medium", "NE offense"),
    ("DJ Moore", "WR", "CHI", "BUF", "trade", "active", "P1", 1, "high", "medium", "BUF targets"),
    ("Michael Pittman Jr.", "WR", "IND", "PIT", "trade", "active", "P1", 1, "high", "medium", "PIT targets"),
    ("Mike Evans", "WR", "TB", "SF", "signed", "active", "P1", 1, "medium", "high", "Age uncertainty"),
    ("Jauan Jennings", "WR", "SF", "MIN", "signed", "active", "P1", 2, "medium", "medium", "With Kyler Murray"),
    ("Christian Kirk", "WR", "HOU", "SF", "signed", "active", "P1", 2, "medium", "medium", "Crowded SF"),
    ("Darnell Mooney", "WR", "ATL", "NYG", "signed", "active", "P1", 1, "medium", "medium", "NYG targets"),
    ("Wan'Dale Robinson", "WR", "NYG", "TEN", "signed", "active", "P1", 1, "medium", "medium", "TEN receiving"),
    ("Jahan Dotson", "WR", "PHI", "ATL", "signed", "active", "P2", 2, "low", "medium", "ATL competition"),
    ("Romeo Doubs", "WR", "GB", "NE", "signed", "active", "P1", 2, "medium", "medium", "With AJ Brown"),
    ("Jalen Nailor", "WR", "MIN", "LV", "signed", "active", "P2", 2, "low", "medium", "LV offense"),
    ("Marquise Brown", "WR", "KC", "PHI", "signed", "active", "P1", 1, "medium", "high", "After AJ Brown exit"),
    ("Dontayvion Wicks", "WR", "GB", "PHI", "trade", "active", "P2", 2, "low", "medium", "PHI competition"),
    ("Skyy Moore", "WR", "SF", "GB", "signed", "active", "P2", 3, "low", "low", "GB depth"),
    ("Greg Dortch", "WR", "ARI", "DET", "signed", "active", "P2", 3, "low", "low", "DET slot/return"),
    ("Kalif Raymond", "WR", "DET", "CHI", "signed", "active", "P2", 3, "low", "low", "CHI depth"),
    ("Tim Patrick", "WR", "JAX", "NYJ", "signed", "active", "P2", 2, "low", "medium", "Jets WR"),
    ("Nick Westbrook-Ikhine", "WR", "MIA", "IND", "signed", "active", "P2", 2, "low", "medium", "After Pittman exit"),
    ("Tutu Atwell", "WR", "LAR", "MIA", "signed", "active", "P2", 2, "low", "high", "Rebuilt MIA"),
    ("Jalen Tolbert", "WR", "DAL", "MIA", "signed", "active", "P2", 2, "low", "high", "Rebuilt MIA"),
    ("Kendrick Bourne", "WR", "SF", "ARI", "signed", "active", "P2", 2, "low", "high", "ARI QB uncertainty"),
    ("Calvin Austin III", "WR", "PIT", "NYG", "signed", "active", "P2", 2, "low", "medium", "NYG competition"),
    ("JuJu Smith-Schuster", "WR", "KC", "NYG", "signed", "active", "P2", 2, "low", "medium", "NYG competition"),
    ("Braxton Berrios", "WR", "HOU", "NYG", "signed", "active", "P3", 3, "low", "low", "Slot/return depth"),
    ("Van Jefferson", "WR", "TEN", "WAS", "signed", "active", "P2", 2, "low", "medium", "After Deebo exit"),
    ("Dyami Brown", "WR", "JAX", "WAS", "signed", "active", "P2", 2, "low", "medium", "WAS targets"),
    ("Marquez Valdes-Scantling", "WR", "PIT", "DAL", "signed", "active", "P2", 3, "low", "low", "Vertical role"),
    ("Alec Pierce", "WR", "IND", "IND", "re_signed", "active", "P1", 1, "high", "medium", "Role up after Pittman"),
    ("George Pickens", "WR", "DAL", "DAL", "franchise_tagged", "active", "P1", 1, "high", "low", "Tagged 2026"),
    ("Drake London", "WR", "ATL", "ATL", "extended", "active", "P1", 1, "high", "medium", "Primary ATL WR"),
    ("Jalen Coker", "WR", "CAR", "CAR", "extended", "active", "P2", 2, "medium", "medium", "Breakout possible"),
    ("Rashid Shaheed", "WR", "SEA", "SEA", "re_signed", "active", "P1", 2, "high", "low", "SEA WR"),
    ("Jaxon Smith-Njigba", "WR", "SEA", "SEA", "extended", "active", "P1", 1, "high", "low", "Primary SEA WR"),
    # TE moves
    ("David Njoku", "TE", "CLE", "LAC", "signed", "active", "P1", 1, "high", "medium", "Chargers TE"),
    ("Isaiah Likely", "TE", "BAL", "NYG", "signed", "active", "P1", 1, "medium", "medium", "NYG receiving"),
    ("Chig Okonkwo", "TE", "TEN", "WAS", "signed", "active", "P1", 1, "medium", "medium", "After Ertz exit"),
    ("Noah Fant", "TE", "CIN", "NO", "signed", "active", "P1", 1, "medium", "medium", "NO TE room"),
    ("Charlie Kolar", "TE", "BAL", "LAC", "signed", "active", "P2", 2, "low", "medium", "With Njoku"),
    ("Tyler Conklin", "TE", "LAC", "DET", "signed", "active", "P2", 2, "low", "medium", "DET TE"),
    ("Daniel Bellinger", "TE", "NYG", "TEN", "signed", "active", "P2", 2, "low", "medium", "After Okonkwo exit"),
    ("Foster Moreau", "TE", "NO", "HOU", "signed", "active", "P2", 2, "low", "low", "HOU TE"),
    ("Kylen Granson", "TE", "PHI", "TEN", "signed", "active", "P2", 2, "low", "medium", "TEN TE"),
    ("Stone Smartt", "TE", "NYJ", "PHI", "signed", "active", "P2", 3, "low", "low", "PHI depth"),
    ("Johnny Mundt", "TE", "JAX", "PHI", "signed", "active", "P3", 3, "low", "low", "PHI depth"),
    ("Harrison Bryant", "TE", "HOU", "SEA", "signed", "active", "P2", 2, "low", "low", "SEA TE"),
    ("Austin Hooper", "TE", "NE", "ATL", "signed", "active", "P2", 2, "low", "medium", "Behind Pitts"),
    ("Robert Tonyan", "TE", "KC", "PIT", "signed", "active", "P3", 3, "low", "low", "PIT depth"),
    ("Travis Kelce", "TE", "KC", "KC", "re_signed", "active", "P1", 1, "medium", "high", "Age/games uncertainty"),
    ("Kyle Pitts", "TE", "ATL", "ATL", "new_contract", "active", "P1", 1, "high", "medium", "Major ATL option"),
    ("Dallas Goedert", "TE", "PHI", "PHI", "re_signed", "active", "P1", 1, "high", "low", "Established PHI TE"),
    ("Darnell Washington", "TE", "PIT", "PIT", "extended", "active", "P1", 1, "medium", "medium", "Role certainty up"),
    ("Brenton Strange", "TE", "JAX", "JAX", "extended", "active", "P1", 1, "medium", "medium", "Role certainty up"),
    ("Dalton Schultz", "TE", "HOU", "HOU", "extended", "active", "P1", 1, "high", "low", "Primary HOU TE"),
    ("Dawson Knox", "TE", "BUF", "BUF", "extended", "active", "P2", 1, "medium", "medium", "BUF TE competition"),
    ("Cade Otton", "TE", "TB", "TB", "re_signed", "active", "P1", 1, "high", "low", "Primary TB TE"),
    ("Tyler Higbee", "TE", "LAR", "LAR", "re_signed", "active", "P2", 1, "medium", "medium", "LAR TE"),
    ("Greg Dulcich", "TE", "MIA", "MIA", "re_signed", "active", "P2", 1, "medium", "high", "Rebuilt MIA pass game"),
    ("Mo Alie-Cox", "TE", "IND", "IND", "re_signed", "active", "P3", 2, "low", "low", "IND depth"),
    # Unsigned FA
    ("Jimmy Garoppolo", "QB", "LAR", "FA", "unsigned", "unsigned", "P3", None, "low", "high", "Unsigned as of patch"),
    ("Joshua Dobbs", "QB", "NE", "FA", "unsigned", "unsigned", "P3", None, "low", "high", "Unsigned as of patch"),
    ("Joe Mixon", "RB", "HOU", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove HOU workload"),
    ("Nick Chubb", "RB", "HOU", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove HOU workload"),
    ("Najee Harris", "RB", "LAC", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove LAC workload"),
    ("Kareem Hunt", "RB", "KC", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove KC workload"),
    ("Austin Ekeler", "RB", "WAS", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove WAS workload"),
    ("Antonio Gibson", "RB", "NE", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove NE workload"),
    ("Raheem Mostert", "RB", "LV", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove LV workload"),
    ("Zamir White", "RB", "LV", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove LV workload"),
    ("Alexander Mattison", "RB", "MIA", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove MIA workload"),
    ("Khalil Herbert", "RB", "NYJ", "FA", "unsigned", "unsigned", "P3", None, "low", "high", "Remove NYJ workload"),
    ("Cam Akers", "RB", "SEA", "FA", "unsigned", "unsigned", "P3", None, "low", "high", "Remove SEA workload"),
    ("Tyreek Hill", "WR", "MIA", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Injury/availability uncertain"),
    ("Stefon Diggs", "WR", "NE", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove NE targets"),
    ("Deebo Samuel Sr.", "WR", "WAS", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove WAS targets"),
    ("Keenan Allen", "WR", "LAC", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove LAC targets"),
    ("DeAndre Hopkins", "WR", "BAL", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Retirement uncertainty"),
    ("Tyler Lockett", "WR", "LV", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove LV targets"),
    ("Brandin Cooks", "WR", "BUF", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove BUF targets"),
    ("Gabe Davis", "WR", "BUF", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove BUF targets"),
    ("Curtis Samuel", "WR", "BUF", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove BUF targets"),
    ("Hunter Renfrow", "WR", "CAR", "FA", "unsigned", "unsigned", "P3", None, "low", "high", "Remove CAR targets"),
    ("Jonnu Smith", "TE", "PIT", "FA", "unsigned", "unsigned", "P1", None, "low", "high", "Remove PIT targets"),
    ("Darren Waller", "TE", "MIA", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Availability uncertain"),
    ("Zach Ertz", "TE", "WAS", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove WAS targets"),
    ("Taysom Hill", "TE", "NO", "FA", "unsigned", "unsigned", "P2", None, "low", "high", "Remove hybrid usage"),
    ("Will Dissly", "TE", "LAC", "FA", "unsigned", "unsigned", "P3", None, "low", "high", "Remove LAC TE"),
    # Retired
    ("Russell Wilson", "QB", "NYG", "RET", "retired", "retired", "P1", None, "low", "high", "Exclude all 2026 projections"),
    ("Adam Thielen", "WR", "PIT", "RET", "retired", "retired", "P1", None, "low", "high", "Vacate PIT targets"),
]

NAME_ALIASES = {
    "Travis Etienne Jr.": ["Travis Etienne"],
    "Brian Robinson Jr.": ["Brian Robinson"],
    "Michael Pittman Jr.": ["Michael Pittman"],
    "AJ Dillon": ["A.J. Dillon"],
    "DJ Moore": ["D.J. Moore"],
}


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def build_lookup(players: pl.DataFrame) -> dict[str, list[dict]]:
    lookup: dict[str, list[dict]] = {}
    for row in players.select(
        ["gsis_id", "display_name", "position", "latest_team", "status"]
    ).to_dicts():
        if not row["gsis_id"]:
            continue
        lookup.setdefault(key(row["display_name"] or ""), []).append(row)
    return lookup


def resolve(name: str, position: str, lookup: dict[str, list[dict]]) -> str | None:
    candidates = [name, *NAME_ALIASES.get(name, [])]
    for cand in candidates:
        hits = lookup.get(key(cand), [])
        fant = [h for h in hits if h["position"] in {position, "HB", "FB"}]
        use = fant or hits
        if not use:
            continue
        act = [h for h in use if h["status"] == "ACT"]
        return str((act or use)[0]["gsis_id"])
    return None


def main() -> None:
    players = pl.read_parquet(ROOT / "data/cache/nflverse/players.parquet")
    lookup = build_lookup(players)
    rows = []
    missing = []
    for (
        name,
        position,
        old_team,
        new_team,
        txn_type,
        roster_status,
        priority,
        depth,
        starter_conf,
        role_unc,
        notes,
    ) in MOVES:
        gsis = resolve(name, position, lookup)
        if not gsis:
            missing.append(name)
        rows.append(
            {
                "player_id": gsis or "",
                "player_name": name,
                "position": position,
                "old_team": old_team,
                "new_team": new_team,
                "transaction_type": txn_type,
                "transaction_status": "confirmed",
                "roster_status": roster_status,
                "expected_depth_chart_rank": depth if depth is not None else "",
                "starter_confidence": starter_conf,
                "role_uncertainty": role_unc,
                "active_roster": "true" if roster_status == "active" else "false",
                "projection_eligible": "false" if roster_status == "retired" else "true",
                "priority": priority,
                "effective_season": SEASON,
                "as_of_date": AS_OF,
                "source": "manual_offseason_patch",
                "notes": notes,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")
    if missing:
        print("MISSING IDS:", ", ".join(missing))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
