"""Player identity resolution.

Joining on names is the single most common source of silent corruption in
public NFL data: there are two Michael Thomases, two Josh Allens, suffixes
drift between sources, and apostrophes are inconsistently encoded.

This module builds a canonical player dimension keyed on the GSIS identifier
and resolves every other source onto it. Name matching exists only as an
explicitly-reported last resort for sources that publish no identifier (PFR
snap counts, the combine), and it never merges two players on a name alone -
it requires a name match plus corroborating evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import polars as pl

from fantasy_football_prediction_model.constants import (
    CANONICAL_ID_COLUMN,
    FANTASY_POSITIONS,
    FREE_AGENT_TEAM,
    NAME_SUFFIXES,
    POSITION_ALIASES,
    TEAM_ABBREVIATION_ALIASES,
)
from fantasy_football_prediction_model.logging import DataQualityError, get_logger

logger = get_logger(__name__)

_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")
_SUFFIX_PATTERN = re.compile(
    r"\s+(" + "|".join(suffix.lower() for suffix in NAME_SUFFIXES) + r")$"
)


# ---------------------------------------------------------------------------
# Scalar normalisers
# ---------------------------------------------------------------------------


def normalise_name(name: str | None) -> str:
    """Return a comparable form of a player name.

    Lower-cases, strips accents, removes punctuation (so ``Ja'Marr`` matches
    ``JaMarr``), collapses whitespace and drops generational suffixes.

    >>> normalise_name("Ja'Marr Chase")
    'jamarr chase'
    >>> normalise_name("Odell Beckham Jr.")
    'odell beckham'
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = ascii_only.lower().strip()
    without_punctuation = _PUNCTUATION.sub("", lowered)
    collapsed = _WHITESPACE.sub(" ", without_punctuation).strip()
    # Suffixes can stack ("Jr" after "III" is rare but appears in bad rows).
    previous = None
    while previous != collapsed:
        previous = collapsed
        collapsed = _SUFFIX_PATTERN.sub("", collapsed).strip()
    return collapsed


def slugify_name(name: str, *, suffix: str | None = None) -> str:
    """Return a URL slug for a player page.

    ``suffix`` disambiguates players who normalise to the same slug; the
    resolver passes a short identifier fragment when that happens.

    >>> slugify_name("Ja'Marr Chase")
    'jamarr-chase'
    """
    base = normalise_name(name).replace(" ", "-")
    base = re.sub(r"-+", "-", base).strip("-")
    if not base:
        base = "unknown-player"
    return f"{base}-{suffix}" if suffix else base


def normalise_team(team: str | None) -> str:
    """Map any historical or alternate team abbreviation onto the current one."""
    if not team:
        return FREE_AGENT_TEAM
    cleaned = str(team).strip().upper()
    if cleaned in {"", "NA", "NONE", "NULL", "FA", "UFA", "RFA", "RET"}:
        return FREE_AGENT_TEAM
    return TEAM_ABBREVIATION_ALIASES.get(cleaned, cleaned)


def normalise_position(position: str | None) -> str | None:
    """Map a source position string onto QB / RB / WR / TE, or ``None``."""
    if not position:
        return None
    cleaned = str(position).strip().upper()
    if cleaned in FANTASY_POSITIONS:
        return cleaned
    return POSITION_ALIASES.get(cleaned)


def short_name(name: str) -> str:
    """``"Ja'Marr Chase"`` -> ``"J. Chase"``; used in compact table cells."""
    parts = [part for part in str(name).split() if part]
    if len(parts) < 2:
        return str(name)
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def compute_age(birth_date: date | datetime | str | None, as_of: date) -> float | None:
    """Age in years, to one decimal place, at a reference date."""
    if birth_date is None:
        return None
    if isinstance(birth_date, str):
        try:
            birth_date = datetime.fromisoformat(birth_date.split("T")[0]).date()
        except ValueError:
            return None
    if isinstance(birth_date, datetime):
        birth_date = birth_date.date()
    if not isinstance(birth_date, date):
        return None
    days = (as_of - birth_date).days
    if days <= 0:
        return None
    return round(days / 365.25, 2)


# ---------------------------------------------------------------------------
# Polars expression helpers
# ---------------------------------------------------------------------------


def normalise_name_expr(column: str) -> pl.Expr:
    """Vectorised :func:`normalise_name` for a Polars column."""
    suffix_regex = r"\s+(" + "|".join(s.lower() for s in NAME_SUFFIXES) + r")$"
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .fill_null("")
        .str.to_lowercase()
        # Strip accents by decomposing then removing combining marks.
        .str.replace_all(r"[àáâãäå]", "a")
        .str.replace_all(r"[èéêë]", "e")
        .str.replace_all(r"[ìíîï]", "i")
        .str.replace_all(r"[òóôõö]", "o")
        .str.replace_all(r"[ùúûü]", "u")
        .str.replace_all(r"[ñ]", "n")
        .str.replace_all(r"[ç]", "c")
        .str.replace_all(r"[^a-z0-9 ]+", "")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
        .str.replace_all(suffix_regex, "")
        .str.strip_chars()
        .alias(f"{column}_normalised")
    )


def normalise_team_expr(column: str, alias: str | None = None) -> pl.Expr:
    """Vectorised :func:`normalise_team`."""
    expr = pl.col(column).cast(pl.Utf8).str.to_uppercase().str.strip_chars()
    expr = expr.replace(TEAM_ABBREVIATION_ALIASES)
    return (
        pl.when(expr.is_null() | expr.is_in(["", "NA", "NONE", "NULL", "UFA", "RFA", "RET"]))
        .then(pl.lit(FREE_AGENT_TEAM))
        .otherwise(expr)
        .alias(alias or column)
    )


def normalise_position_expr(column: str, alias: str | None = None) -> pl.Expr:
    """Vectorised :func:`normalise_position`. Unmapped values become null."""
    expr = pl.col(column).cast(pl.Utf8).str.to_uppercase().str.strip_chars()
    return expr.replace_strict(POSITION_ALIASES, default=None).alias(alias or column)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IdentityIssue:
    """One unresolved or suspicious identity, written to the audit report."""

    issue_type: str
    severity: str
    source: str
    identifier: str
    name: str
    detail: str
    season: int | None = None


@dataclass(slots=True)
class IdentityReport:
    """Outcome of building and applying the player dimension."""

    total_players: int = 0
    duplicate_ids: list[str] = field(default_factory=list)
    duplicate_slugs: list[str] = field(default_factory=list)
    ambiguous_names: list[str] = field(default_factory=list)
    issues: list[IdentityIssue] = field(default_factory=list)
    corrections_applied: int = 0

    def add(
        self,
        issue_type: str,
        *,
        severity: str,
        source: str,
        identifier: str,
        name: str,
        detail: str,
        season: int | None = None,
    ) -> None:
        self.issues.append(
            IdentityIssue(
                issue_type=issue_type,
                severity=severity,
                source=source,
                identifier=identifier,
                name=name,
                detail=detail,
                season=season,
            )
        )

    def errors(self) -> list[IdentityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    def to_frame(self) -> pl.DataFrame:
        if not self.issues:
            return pl.DataFrame(
                schema={
                    "issue_type": pl.Utf8,
                    "severity": pl.Utf8,
                    "source": pl.Utf8,
                    "identifier": pl.Utf8,
                    "name": pl.Utf8,
                    "detail": pl.Utf8,
                    "season": pl.Int64,
                }
            )
        return pl.DataFrame([issue.__dict__ for issue in self.issues])


class PlayerIdentityResolver:
    """Builds the canonical player dimension and resolves sources onto it."""

    def __init__(
        self,
        players: pl.DataFrame,
        *,
        ff_playerids: pl.DataFrame | None = None,
        corrections: pl.DataFrame | None = None,
    ) -> None:
        self.report = IdentityReport()
        self.dimension = self._build_dimension(players, ff_playerids, corrections)
        self._name_index = self._build_name_index()

    # -- construction --------------------------------------------------------

    @staticmethod
    def _first_available(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
        for name in candidates:
            if name in frame.columns:
                return name
        return None

    def _build_dimension(
        self,
        players: pl.DataFrame,
        ff_playerids: pl.DataFrame | None,
        corrections: pl.DataFrame | None,
    ) -> pl.DataFrame:
        """Create one row per canonical player."""
        id_column = self._first_available(players, ("gsis_id", "player_id", "gsis_it_id"))
        if id_column is None:
            raise DataQualityError(
                "The nflverse players table has no GSIS identifier column.",
                hint=(
                    "Expected one of gsis_id / player_id. Check "
                    "https://nflreadr.nflverse.com/articles/dictionary_players.html "
                    "for the current schema and update data/identities.py."
                ),
            )

        name_column = self._first_available(
            players, ("display_name", "full_name", "player_name", "football_name")
        )
        if name_column is None:
            raise DataQualityError(
                "The nflverse players table has no display-name column.",
                hint="Expected display_name or full_name.",
            )

        selections: list[pl.Expr] = [
            pl.col(id_column).cast(pl.Utf8).alias(CANONICAL_ID_COLUMN),
            pl.col(name_column).cast(pl.Utf8).alias("display_name"),
        ]

        optional_map = {
            "position": ("position", "position_group"),
            "birth_date": ("birth_date", "birthdate"),
            "height": ("height",),
            "weight": ("weight",),
            "draft_year": ("draft_year", "entry_year"),
            "draft_round": ("draft_round", "rookie_draft_round"),
            "draft_pick": ("draft_number", "draft_pick", "draft_overall"),
            "draft_team": ("draft_club", "draft_team"),
            "rookie_year": ("rookie_year", "rookie_season"),
            "entry_year": ("entry_year",),
            "latest_team": ("latest_team", "team_abbr", "team"),
            "status": ("status", "current_status"),
            "college": ("college_name", "college"),
            "pfr_id": ("pfr_id", "pfr_player_id"),
            "espn_id": ("espn_id",),
            "sleeper_id": ("sleeper_id",),
            "sportradar_id": ("smart_id", "sportradar_id"),
            "yahoo_id": ("yahoo_id",),
            "nflverse_id": ("nfl_id", "gsis_it_id", "esb_id"),
            "headshot_url": ("headshot", "headshot_url"),
        }
        for target, candidates in optional_map.items():
            source = self._first_available(players, candidates)
            if source is None:
                selections.append(pl.lit(None).alias(target))
            elif target in {"height", "weight", "draft_year", "draft_round", "draft_pick",
                            "rookie_year", "entry_year"}:
                selections.append(pl.col(source).cast(pl.Float64, strict=False).alias(target))
            else:
                selections.append(pl.col(source).cast(pl.Utf8).alias(target))

        dimension = (
            players.select(selections)
            .filter(pl.col(CANONICAL_ID_COLUMN).is_not_null())
            .filter(pl.col(CANONICAL_ID_COLUMN).str.strip_chars() != "")
        )

        dimension = dimension.with_columns(
            normalise_name_expr("display_name"),
            normalise_position_expr("position", "fantasy_position"),
            pl.col("birth_date").str.slice(0, 10).str.to_date(strict=False).alias("birth_date"),
        )
        if "latest_team" in dimension.columns:
            dimension = dimension.with_columns(normalise_team_expr("latest_team"))

        dimension = self._deduplicate(dimension)

        if ff_playerids is not None:
            dimension = self._merge_ff_playerids(dimension, ff_playerids)

        if corrections is not None and not corrections.is_empty():
            dimension = self._apply_id_corrections(dimension, corrections)

        dimension = self._assign_slugs(dimension)
        self.report.total_players = dimension.height
        return dimension

    def _deduplicate(self, dimension: pl.DataFrame) -> pl.DataFrame:
        """Collapse duplicate GSIS ids, keeping the most complete record."""
        duplicated = (
            dimension.group_by(CANONICAL_ID_COLUMN)
            .len()
            .filter(pl.col("len") > 1)
            .get_column(CANONICAL_ID_COLUMN)
            .to_list()
        )
        if duplicated:
            self.report.duplicate_ids = sorted(duplicated)[:200]
            logger.warning(
                "Found %d duplicated GSIS ids in the players table; keeping the most "
                "complete row for each.",
                len(duplicated),
            )
            for player_id in duplicated[:50]:
                self.report.add(
                    "duplicate_gsis_id",
                    severity="warning",
                    source="nflverse.players",
                    identifier=player_id,
                    name="",
                    detail="Multiple rows share this GSIS id; the most populated row was kept.",
                )
            completeness = pl.sum_horizontal(
                [pl.col(column).is_not_null().cast(pl.Int32) for column in dimension.columns]
            ).alias("_completeness")
            dimension = (
                dimension.with_columns(completeness)
                .sort(["_completeness"], descending=True)
                .unique(subset=[CANONICAL_ID_COLUMN], keep="first", maintain_order=True)
                .drop("_completeness")
            )
        return dimension

    def _merge_ff_playerids(
        self, dimension: pl.DataFrame, ff_playerids: pl.DataFrame
    ) -> pl.DataFrame:
        """Fill missing secondary identifiers from the ffverse crosswalk."""
        if "gsis_id" not in ff_playerids.columns:
            logger.warning("ff_playerids has no gsis_id column; skipping the crosswalk merge.")
            return dimension

        wanted = {
            "sleeper_id": "sleeper_id",
            "espn_id": "espn_id",
            "yahoo_id": "yahoo_id",
            "pfr_id": "pfr_id",
            "sportradar_id": "sportradar_id",
            "cfbd_id": "cfb_id",
        }
        available = {
            target: source for target, source in wanted.items() if source in ff_playerids.columns
        }
        if not available:
            return dimension.with_columns(pl.lit(None, dtype=pl.Utf8).alias("cfbd_id"))

        crosswalk = ff_playerids.select(
            pl.col("gsis_id").cast(pl.Utf8).alias(CANONICAL_ID_COLUMN),
            *[pl.col(source).cast(pl.Utf8).alias(f"{target}_ff") for target, source in
              available.items()],
        ).unique(subset=[CANONICAL_ID_COLUMN], keep="first")

        merged = dimension.join(crosswalk, on=CANONICAL_ID_COLUMN, how="left")
        for target in available:
            ff_column = f"{target}_ff"
            if target in merged.columns:
                merged = merged.with_columns(
                    pl.coalesce([pl.col(target), pl.col(ff_column)]).alias(target)
                )
            else:
                merged = merged.with_columns(pl.col(ff_column).alias(target))
            merged = merged.drop(ff_column)
        if "cfbd_id" not in merged.columns:
            merged = merged.with_columns(pl.lit(None, dtype=pl.Utf8).alias("cfbd_id"))
        return merged

    def _apply_id_corrections(
        self, dimension: pl.DataFrame, corrections: pl.DataFrame
    ) -> pl.DataFrame:
        """Apply operator-supplied factual identifier corrections."""
        required = {"player_id", "field", "new_value"}
        missing = sorted(required - set(corrections.columns))
        if missing:
            logger.warning(
                "Identifier corrections file is missing columns %s; ignoring it.", missing
            )
            return dimension

        applied = 0
        for row in corrections.iter_rows(named=True):
            player_id = str(row.get("player_id") or "").strip()
            field_name = str(row.get("field") or "").strip()
            new_value = row.get("new_value")
            if not player_id or field_name not in dimension.columns:
                self.report.add(
                    "invalid_correction",
                    severity="warning",
                    source="manual.player-id-corrections",
                    identifier=player_id,
                    name=str(row.get("player_name") or ""),
                    detail=f"Unknown field '{field_name}' or empty player id; skipped.",
                )
                continue
            dtype = dimension.schema[field_name]
            literal = pl.lit(new_value).cast(dtype, strict=False)
            dimension = dimension.with_columns(
                pl.when(pl.col(CANONICAL_ID_COLUMN) == player_id)
                .then(literal)
                .otherwise(pl.col(field_name))
                .alias(field_name)
            )
            applied += 1

        self.report.corrections_applied = applied
        if applied:
            logger.info("Applied %d manual identifier corrections.", applied)
        return dimension

    def _assign_slugs(self, dimension: pl.DataFrame) -> pl.DataFrame:
        """Assign unique, stable URL slugs.

        When two players share a slug (Michael Thomas the receiver and Michael
        Thomas the safety), every colliding slug gets a deterministic suffix
        from its GSIS id. Nobody keeps the bare slug, so a player's URL never
        depends on which of them happened to be published first.
        """
        with_slug = dimension.with_columns(
            pl.col("display_name_normalised")
            .str.replace_all(" ", "-")
            .str.replace_all(r"-+", "-")
            .str.strip_chars("-")
            .alias("_base_slug")
        ).with_columns(
            pl.when(pl.col("_base_slug") == "")
            .then(pl.lit("unknown-player"))
            .otherwise(pl.col("_base_slug"))
            .alias("_base_slug")
        )

        counts = with_slug.group_by("_base_slug").len().rename({"len": "_slug_count"})
        with_slug = with_slug.join(counts, on="_base_slug", how="left")

        colliding = (
            with_slug.filter(pl.col("_slug_count") > 1).get_column("_base_slug").unique().to_list()
        )
        if colliding:
            self.report.duplicate_slugs = sorted(colliding)
            logger.info(
                "%d player-name slugs collide and were disambiguated with an id suffix.",
                len(colliding),
            )

        with_slug = with_slug.with_columns(
            pl.when(pl.col("_slug_count") > 1)
            .then(
                pl.col("_base_slug")
                + "-"
                + pl.col(CANONICAL_ID_COLUMN).str.replace_all("-", "").str.slice(-4)
            )
            .otherwise(pl.col("_base_slug"))
            .alias("slug")
        )

        # A suffix collision would be pathological, but assert it away.
        remaining = (
            with_slug.group_by("slug").len().filter(pl.col("len") > 1).get_column("slug").to_list()
        )
        if remaining:
            with_slug = with_slug.with_columns(
                pl.when(pl.col("slug").is_in(remaining))
                .then(
                    pl.col("slug")
                    + "-"
                    + pl.col(CANONICAL_ID_COLUMN).str.replace_all("-", "").str.slice(0, 4)
                )
                .otherwise(pl.col("slug"))
                .alias("slug")
            )

        return with_slug.drop(["_base_slug", "_slug_count"]).with_columns(
            pl.col("display_name")
            .map_elements(short_name, return_dtype=pl.Utf8)
            .alias("short_name")
        )

    # -- name-based resolution ----------------------------------------------

    def _build_name_index(self) -> dict[tuple[str, str], str]:
        """``(normalised name, position) -> gsis_id`` for unambiguous pairs.

        Pairs that map to more than one player are deliberately excluded and
        recorded, so a name-only source can never merge two real players.
        """
        grouped = (
            self.dimension.filter(pl.col("fantasy_position").is_not_null())
            .group_by(["display_name_normalised", "fantasy_position"])
            .agg(
                pl.col(CANONICAL_ID_COLUMN).alias("ids"),
                pl.len().alias("count"),
            )
        )
        index: dict[tuple[str, str], str] = {}
        ambiguous: list[str] = []
        for row in grouped.iter_rows(named=True):
            key = (row["display_name_normalised"], row["fantasy_position"])
            if row["count"] == 1:
                index[key] = row["ids"][0]
            else:
                ambiguous.append(f"{row['display_name_normalised']} ({row['fantasy_position']})")
                self.report.add(
                    "ambiguous_name",
                    severity="info",
                    source="nflverse.players",
                    identifier=",".join(row["ids"][:5]),
                    name=row["display_name_normalised"],
                    detail=(
                        f"{row['count']} players share this name and position. Name-based "
                        "joins will not resolve them; a canonical id is required."
                    ),
                )
        self.report.ambiguous_names = sorted(ambiguous)
        if ambiguous:
            logger.info(
                "%d name+position combinations are ambiguous and are excluded from "
                "name-based matching.",
                len(ambiguous),
            )
        return index

    def resolve_by_name(
        self, name: str, position: str | None = None, *, team: str | None = None
    ) -> str | None:
        """Resolve a name to a canonical id, or ``None`` when it is not safe.

        Requires a position to corroborate the name. When the position is not
        supplied, the name must be unique across every modelled position.
        """
        normalised = normalise_name(name)
        if not normalised:
            return None

        if position:
            mapped = normalise_position(position)
            if mapped:
                return self._name_index.get((normalised, mapped))

        matches = {
            player_id
            for (candidate_name, _), player_id in self._name_index.items()
            if candidate_name == normalised
        }
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1 and team:
            normalised_team = normalise_team(team)
            narrowed = (
                self.dimension.filter(
                    pl.col(CANONICAL_ID_COLUMN).is_in(list(matches))
                    & (pl.col("latest_team") == normalised_team)
                )
                .get_column(CANONICAL_ID_COLUMN)
                .to_list()
            )
            if len(narrowed) == 1:
                return narrowed[0]
        return None

    def attach_ids_by_name(
        self,
        frame: pl.DataFrame,
        *,
        name_column: str,
        position_column: str | None = None,
        team_column: str | None = None,
        source: str,
        id_column: str = CANONICAL_ID_COLUMN,
    ) -> pl.DataFrame:
        """Add a canonical id column to a name-keyed source.

        Rows that cannot be resolved keep a null id and are recorded in the
        identity report. They are never dropped silently, and never guessed.
        """
        if name_column not in frame.columns:
            raise KeyError(f"Column '{name_column}' not present in the {source} frame.")

        resolved: list[str | None] = []
        unresolved_names: dict[str, int] = {}
        for row in frame.iter_rows(named=True):
            player_id = self.resolve_by_name(
                row.get(name_column) or "",
                row.get(position_column) if position_column else None,
                team=row.get(team_column) if team_column else None,
            )
            resolved.append(player_id)
            if player_id is None:
                label = str(row.get(name_column) or "").strip() or "<blank>"
                unresolved_names[label] = unresolved_names.get(label, 0) + 1

        for name, count in sorted(unresolved_names.items(), key=lambda item: -item[1])[:200]:
            self.report.add(
                "unresolved_name",
                severity="warning",
                source=source,
                identifier="",
                name=name,
                detail=f"{count} row(s) could not be matched to a canonical player id.",
            )

        if unresolved_names:
            total = sum(unresolved_names.values())
            logger.info(
                "%s: %d of %d rows (%.1f%%) could not be resolved to a canonical player id.",
                source,
                total,
                frame.height,
                100 * total / max(frame.height, 1),
            )

        return frame.with_columns(pl.Series(id_column, resolved, dtype=pl.Utf8))

    # -- lookups -------------------------------------------------------------

    def lookup(self, player_id: str) -> dict[str, object] | None:
        rows = self.dimension.filter(pl.col(CANONICAL_ID_COLUMN) == player_id)
        return rows.row(0, named=True) if rows.height else None

    def known_ids(self) -> set[str]:
        return set(self.dimension.get_column(CANONICAL_ID_COLUMN).to_list())

    def assert_ids_known(
        self, player_ids: list[str], *, context: str, severity: str = "error"
    ) -> list[str]:
        """Record any ids absent from the dimension. Returns the unknown ids."""
        unknown = sorted(set(player_ids) - self.known_ids())
        for player_id in unknown[:200]:
            self.report.add(
                "unknown_player_id",
                severity=severity,
                source=context,
                identifier=player_id,
                name="",
                detail="Player id is not present in the canonical player dimension.",
            )
        return unknown

    def write_report(self, path: Path) -> Path:
        """Write the unresolved-identity audit report."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.report.to_frame().write_csv(path)
        logger.info(
            "Wrote %d identity issue(s) to %s.", len(self.report.issues), path
        )
        return path
