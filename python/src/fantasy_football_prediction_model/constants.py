"""Project-wide constants.

Everything here is a genuine constant: a fact about the NFL, a fact about the
nflverse data model, or a name used in the export contract. Tunable values
belong in ``configs/*.yml``, not in this module.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

#: Offensive positions this project models.
FANTASY_POSITIONS: Final[tuple[str, ...]] = ("QB", "RB", "WR", "TE")

#: Positions that may fill a standard flex slot.
FLEX_POSITIONS: Final[tuple[str, ...]] = ("RB", "WR", "TE")

#: Positions that may fill a superflex slot.
SUPERFLEX_POSITIONS: Final[tuple[str, ...]] = ("QB", "RB", "WR", "TE")

#: Raw source position strings mapped onto the four modelled positions.
#: nflverse mixes ``position``, ``position_group`` and depth-chart labels, and
#: historical rows contain long-retired designations such as HB and FL.
POSITION_ALIASES: Final[dict[str, str]] = {
    "QB": "QB",
    "RB": "RB",
    "HB": "RB",
    "FB": "RB",
    "TB": "RB",
    "WR": "WR",
    "SE": "WR",
    "FL": "WR",
    "SPLIT END": "WR",
    "TE": "TE",
    "H-BACK": "TE",
    "HB/TE": "TE",
}

# ---------------------------------------------------------------------------
# Season structure
# ---------------------------------------------------------------------------

#: Regular-season game count by era. Used only as a fallback when the
#: target-season schedule dataset cannot be loaded.
REGULAR_SEASON_GAMES_BY_ERA: Final[dict[range, int]] = {
    range(1978, 2021): 16,
    range(2021, 2100): 17,
}

#: Seasons whose structure distorts season-total modelling and which are
#: therefore flagged with a feature indicator rather than dropped.
ANOMALOUS_SEASONS: Final[dict[int, str]] = {
    2020: "COVID-19 season: no preseason, no fans, elevated in-season absences.",
    2021: "First 17-game regular season; season totals are not comparable to 2020 and earlier.",
}

# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

#: Current team abbreviations used by nflverse.
CURRENT_TEAMS: Final[tuple[str, ...]] = (
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
)  # fmt: skip

#: Historical abbreviations mapped to their current franchise code, so a
#: player's team history joins correctly across relocations and rebrands.
TEAM_ABBREVIATION_ALIASES: Final[dict[str, str]] = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LA",
    "LAR": "LA",
    "RAM": "LA",
    "RAI": "LV",
    "SDG": "LAC",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "JAC": "JAX",
    "WSH": "WAS",
    "WFT": "WAS",
    "GNB": "GB",
    "KAN": "KC",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "LVR": "LV",
}

#: Placeholder used for players without a current NFL team.
FREE_AGENT_TEAM: Final[str] = "FA"

#: Subtle brand accents. Primary colours only, used at low opacity so the UI
#: never resembles official league or club branding.
TEAM_PRIMARY_COLOURS: Final[dict[str, str]] = {
    "ARI": "#97233F", "ATL": "#A71930", "BAL": "#241773", "BUF": "#00338D",
    "CAR": "#0085CA", "CHI": "#0B162A", "CIN": "#FB4F14", "CLE": "#311D00",
    "DAL": "#003594", "DEN": "#FB4F14", "DET": "#0076B6", "GB": "#203731",
    "HOU": "#03202F", "IND": "#002C5F", "JAX": "#006778", "KC": "#E31837",
    "LA": "#003594", "LAC": "#0080C6", "LV": "#000000", "MIA": "#008E97",
    "MIN": "#4F2683", "NE": "#002244", "NO": "#D3BC8D", "NYG": "#0B2265",
    "NYJ": "#125740", "PHI": "#004C54", "PIT": "#FFB612", "SEA": "#002244",
    "SF": "#AA0000", "TB": "#D50A0A", "TEN": "#0C2340", "WAS": "#5A1414",
    "FA": "#6B7280",
}  # fmt: skip

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

#: The canonical player identifier for this project.
CANONICAL_ID_COLUMN: Final[str] = "gsis_id"

#: Secondary identifiers carried on the player dimension for cross-referencing.
SECONDARY_ID_COLUMNS: Final[tuple[str, ...]] = (
    "nflverse_id",
    "pfr_id",
    "espn_id",
    "sleeper_id",
    "sportradar_id",
    "yahoo_id",
    "cfbd_id",
)

#: Name suffixes stripped during name normalisation.
NAME_SUFFIXES: Final[tuple[str, ...]] = ("JR", "SR", "II", "III", "IV", "V")

# ---------------------------------------------------------------------------
# Projected statistics (the export contract's ``projectedStats`` keys)
# ---------------------------------------------------------------------------

#: Targets predicted for every position. ``games`` is predicted separately as
#: the availability component.
PROJECTION_TARGETS: Final[dict[str, tuple[str, ...]]] = {
    "QB": (
        "games",
        "pass_attempts",
        "completions",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "fumbles_lost",
    ),
    "RB": (
        "games",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "fumbles_lost",
    ),
    "WR": (
        "games",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "fumbles_lost",
    ),
    "TE": (
        "games",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "fumbles_lost",
    ),
}

#: Every statistic the export contract can carry, in display order.
ALL_PROJECTION_TARGETS: Final[tuple[str, ...]] = (
    "games",
    "pass_attempts",
    "completions",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost",
)

#: snake_case statistic name -> camelCase key in the JSON export contract.
STAT_TO_CAMEL_CASE: Final[dict[str, str]] = {
    "games": "games",
    "pass_attempts": "passAttempts",
    "completions": "completions",
    "passing_yards": "passingYards",
    "passing_tds": "passingTouchdowns",
    "interceptions": "interceptions",
    "carries": "carries",
    "rushing_yards": "rushingYards",
    "rushing_tds": "rushingTouchdowns",
    "targets": "targets",
    "receptions": "receptions",
    "receiving_yards": "receivingYards",
    "receiving_tds": "receivingTouchdowns",
    "fumbles_lost": "fumblesLost",
}

#: Component-model decomposition. Each entry is
#: ``target -> (per_game_rate, denominator_or_None, efficiency_rate)``.
#: ``games x per_game_rate`` yields the volume; volume x efficiency yields the
#: dependent statistic. Documented in docs/METHODOLOGY.md.
COMPONENT_DECOMPOSITION: Final[dict[str, tuple[str, str | None]]] = {
    "pass_attempts": ("pass_attempts_per_game", None),
    "completions": ("completion_pct", "pass_attempts"),
    "passing_yards": ("yards_per_attempt", "pass_attempts"),
    "passing_tds": ("passing_td_rate", "pass_attempts"),
    "interceptions": ("interception_rate", "pass_attempts"),
    "carries": ("carries_per_game", None),
    "rushing_yards": ("yards_per_carry", "carries"),
    "rushing_tds": ("rushing_td_rate", "carries"),
    "targets": ("targets_per_game", None),
    "receptions": ("catch_rate", "targets"),
    "receiving_yards": ("yards_per_target", "targets"),
    "receiving_tds": ("receiving_td_rate", "targets"),
    "fumbles_lost": ("fumbles_lost_per_game", None),
}

# ---------------------------------------------------------------------------
# Data-mode guard rails
# ---------------------------------------------------------------------------

#: Value written to every export produced from real nflverse data.
DATA_MODE_PRODUCTION: Final[str] = "production"

#: Value written to every export produced from synthetic test fixtures. The
#: web application shows a prominent banner whenever it sees this, and the
#: data-quality workflow refuses to accept it on ``main``.
DATA_MODE_FIXTURE: Final[str] = "fixture"

# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

CONFIDENCE_LABELS: Final[tuple[str, ...]] = ("low", "medium", "high")

# ---------------------------------------------------------------------------
# Physical plausibility bounds used by validation. Deliberately wide: these
# catch corruption and unit errors, not unusual-but-real seasons.
# ---------------------------------------------------------------------------

STAT_SANITY_BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "games": (0.0, 17.0),
    "pass_attempts": (0.0, 800.0),
    "completions": (0.0, 600.0),
    "passing_yards": (-100.0, 6500.0),
    "passing_tds": (0.0, 65.0),
    "interceptions": (0.0, 40.0),
    "carries": (0.0, 500.0),
    "rushing_yards": (-200.0, 2500.0),
    "rushing_tds": (0.0, 35.0),
    "targets": (0.0, 300.0),
    "receptions": (0.0, 200.0),
    "receiving_yards": (-100.0, 2200.0),
    "receiving_tds": (0.0, 30.0),
    "fumbles_lost": (0.0, 20.0),
}

#: Plausible human bounds for a modelled NFL player, used by validation.
MIN_PLAUSIBLE_AGE: Final[float] = 19.0
MAX_PLAUSIBLE_AGE: Final[float] = 48.0
