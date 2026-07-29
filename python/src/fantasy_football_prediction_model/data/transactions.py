"""2026 offseason transaction patch: load, apply, audit.

Historical season-t teams are never rewritten. This module only patches
target-season week-1 / projection context (``next_team``, ``projected_team``,
roster status, depth cues) and supports vacated-opportunity audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from fantasy_football_prediction_model.constants import CANONICAL_ID_COLUMN
from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

TRANSACTION_COLUMNS: tuple[str, ...] = (
    "player_id",
    "player_name",
    "position",
    "old_team",
    "new_team",
    "transaction_type",
    "transaction_status",
    "roster_status",
    "expected_depth_chart_rank",
    "starter_confidence",
    "role_uncertainty",
    "active_roster",
    "projection_eligible",
    "priority",
    "effective_season",
    "as_of_date",
    "source",
    "notes",
)

SAME_TEAM_TYPES = frozenset(
    {"re_signed", "extended", "revised_contract", "franchise_tagged", "new_contract"}
)


@dataclass
class TransactionApplyResult:
    week1_teams: pl.DataFrame | None
    applied: pl.DataFrame
    unresolved: pl.DataFrame
    as_of_date: str | None
    warnings: list[str] = field(default_factory=list)


def default_transactions_path(repo_root: Path) -> Path:
    return repo_root / "data" / "manual" / "2026_offseason_transactions.csv"


def load_offseason_transactions(path: Path) -> pl.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Offseason transactions file not found: {path}")
    frame = pl.read_csv(path, infer_schema_length=2000)
    missing = [c for c in ("player_id", "new_team", "effective_season") if c not in frame.columns]
    if missing:
        raise ValueError(f"Transactions file missing required columns: {missing}")
    # Normalise types.
    frame = frame.with_columns(
        pl.col("player_id").cast(pl.Utf8).str.strip_chars(),
        pl.col("new_team").cast(pl.Utf8).str.strip_chars().str.to_uppercase(),
        pl.col("effective_season").cast(pl.Int64),
    )
    if "old_team" in frame.columns:
        frame = frame.with_columns(
            pl.col("old_team").cast(pl.Utf8).str.strip_chars().str.to_uppercase()
        )
    if "active_roster" in frame.columns:
        frame = frame.with_columns(
            pl.col("active_roster")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes"])
            .alias("active_roster_bool")
        )
    else:
        frame = frame.with_columns(pl.lit(True).alias("active_roster_bool"))
    if "projection_eligible" in frame.columns:
        frame = frame.with_columns(
            pl.col("projection_eligible")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes"])
            .alias("projection_eligible_bool")
        )
    else:
        frame = frame.with_columns(pl.lit(True).alias("projection_eligible_bool"))
    return frame


def transactions_as_of(frame: pl.DataFrame) -> str | None:
    if "as_of_date" not in frame.columns or frame.is_empty():
        return None
    values = [v for v in frame.get_column("as_of_date").drop_nulls().to_list() if v]
    return str(sorted(values)[-1]) if values else None


def _normalise_destination(team_expr: pl.Expr) -> pl.Expr:
    """Map retirement sentinels to FA for week-1 / projection team columns."""
    return pl.when(team_expr.is_in(["RET", "RETIRED"])).then(pl.lit("FA")).otherwise(team_expr)


def apply_transactions_to_week1(
    week1_teams: pl.DataFrame | None,
    transactions: pl.DataFrame,
    *,
    target_season: int,
    prior_season: int | None = None,
) -> TransactionApplyResult:
    """Patch week-1 teams for ``target_season`` only.

    Historical seasons are left untouched. When the target season has no
    nflverse week-1 rows yet, prior-season week-1 assignments are carried
    forward as a seed and then overwritten by this patch so leavers are never
    left on their old team.
    """
    season_tx = transactions.filter(pl.col("effective_season") == target_season)
    unresolved = season_tx.filter(
        pl.col("player_id").is_null() | (pl.col("player_id").str.len_chars() == 0)
    )
    resolved = season_tx.filter(pl.col("player_id").is_not_null() & (pl.col("player_id") != ""))
    warnings: list[str] = []
    as_of = transactions_as_of(season_tx)
    seed_season = prior_season if prior_season is not None else target_season - 1

    if week1_teams is None or week1_teams.is_empty():
        id_col = CANONICAL_ID_COLUMN
        built = resolved.select(
            pl.col("player_id").alias(id_col),
            pl.lit(target_season).alias("season"),
            _normalise_destination(pl.col("new_team")).alias("week1_team"),
        )
        warnings.append("week1_teams was empty; built target-season rows from transactions only.")
        return TransactionApplyResult(built, resolved, unresolved, as_of, warnings)

    id_col = CANONICAL_ID_COLUMN if CANONICAL_ID_COLUMN in week1_teams.columns else "gsis_id"
    hist = week1_teams.filter(pl.col("season") != target_season)
    target = week1_teams.filter(pl.col("season") == target_season)

    if target.is_empty():
        prior = week1_teams.filter(pl.col("season") == seed_season)
        if not prior.is_empty():
            target = prior.select(
                id_col,
                pl.lit(target_season).alias("season"),
                pl.col("week1_team"),
            )
            warnings.append(
                f"No {target_season} week-1 roster rows; seeded from {seed_season} then "
                "applied the offseason transaction patch."
            )
        else:
            warnings.append(
                f"No {target_season} or {seed_season} week-1 rows; using transaction patch only."
            )

    patch = resolved.select(
        pl.col("player_id").alias(id_col),
        pl.lit(target_season).alias("season"),
        _normalise_destination(pl.col("new_team")).alias("week1_team"),
    )

    if not target.is_empty():
        keep = target.join(patch.select(id_col), on=id_col, how="anti")
        target = pl.concat(
            [keep.select(id_col, "season", "week1_team"), patch],
            how="diagonal_relaxed",
        )
    else:
        target = patch

    combined = pl.concat([hist, target], how="diagonal_relaxed").unique(
        subset=[id_col, "season"], keep="last"
    )
    logger.info(
        "Applied %d offseason team patches for season %d (unresolved=%d, as_of=%s).",
        resolved.height,
        target_season,
        unresolved.height,
        as_of,
    )
    return TransactionApplyResult(combined, resolved, unresolved, as_of, warnings)


def apply_transactions_to_projection_frame(
    frame: pl.DataFrame,
    transactions: pl.DataFrame,
    *,
    target_season: int,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Patch projection feature rows for 2026 context without rewriting season-t team."""
    season_tx = transactions.filter(pl.col("effective_season") == target_season)
    resolved = season_tx.filter(pl.col("player_id").is_not_null() & (pl.col("player_id") != ""))
    if resolved.is_empty():
        return frame, {"applied": 0, "as_of_date": transactions_as_of(season_tx)}

    id_col = "gsis_id" if "gsis_id" in frame.columns else CANONICAL_ID_COLUMN
    patch_exprs: list[pl.Expr] = [
        pl.col("player_id").alias(id_col),
        _normalise_destination(pl.col("new_team")).alias("txn_new_team"),
    ]
    patch_exprs.append(
        pl.col("roster_status").alias("txn_roster_status")
        if "roster_status" in resolved.columns
        else pl.lit(None).alias("txn_roster_status")
    )
    patch_exprs.append(
        pl.col("expected_depth_chart_rank").alias("txn_depth_rank")
        if "expected_depth_chart_rank" in resolved.columns
        else pl.lit(None).alias("txn_depth_rank")
    )
    patch_exprs.append(
        pl.col("starter_confidence").alias("txn_starter_confidence")
        if "starter_confidence" in resolved.columns
        else pl.lit(None).alias("txn_starter_confidence")
    )
    patch_exprs.append(
        pl.col("role_uncertainty").alias("txn_role_uncertainty")
        if "role_uncertainty" in resolved.columns
        else pl.lit(None).alias("txn_role_uncertainty")
    )
    patch_exprs.append(
        pl.col("active_roster_bool")
        if "active_roster_bool" in resolved.columns
        else pl.lit(True).alias("active_roster_bool")
    )
    patch_exprs.append(
        pl.col("projection_eligible_bool")
        if "projection_eligible_bool" in resolved.columns
        else pl.lit(True).alias("projection_eligible_bool")
    )
    patch_exprs.append(
        pl.col("priority") if "priority" in resolved.columns else pl.lit(None).alias("priority")
    )
    patch_exprs.append(
        pl.col("notes") if "notes" in resolved.columns else pl.lit(None).alias("notes")
    )
    patch = resolved.select(patch_exprs).unique(subset=[id_col], keep="last")

    joined = frame.join(patch, on=id_col, how="left")
    # Preserve historical season-t `team`; update projection context only.
    if "next_team" in joined.columns:
        joined = joined.with_columns(
            pl.coalesce([pl.col("txn_new_team"), pl.col("next_team")]).alias("next_team")
        )
    else:
        joined = joined.with_columns(pl.col("txn_new_team").alias("next_team"))

    if "projected_team" in joined.columns:
        joined = joined.with_columns(
            pl.coalesce(
                [pl.col("txn_new_team"), pl.col("projected_team"), pl.col("next_team")]
            ).alias("projected_team")
        )
    else:
        joined = joined.with_columns(
            pl.coalesce([pl.col("txn_new_team"), pl.col("next_team")]).alias("projected_team")
        )

    if "team" in joined.columns:
        joined = joined.with_columns(
            (pl.col("txn_new_team").is_not_null() & (pl.col("txn_new_team") != pl.col("team")))
            .fill_null(False)
            .cast(pl.Int8)
            .alias("team_changed")
        )

    if "depth_chart_rank" in joined.columns:
        joined = joined.with_columns(
            pl.coalesce(
                [
                    pl.col("txn_depth_rank").cast(pl.Float64, strict=False),
                    pl.col("depth_chart_rank"),
                ]
            ).alias("depth_chart_rank")
        )

    joined = joined.with_columns(
        pl.col("txn_roster_status").alias("offseason_roster_status"),
        pl.col("txn_starter_confidence").alias("starter_confidence"),
        pl.col("txn_role_uncertainty").alias("role_uncertainty"),
        pl.col("active_roster_bool").alias("offseason_active_roster"),
        pl.col("projection_eligible_bool").alias("projection_eligible"),
        pl.col("priority").alias("offseason_priority"),
    )

    applied = int(joined.get_column("txn_new_team").is_not_null().sum())
    return joined, {
        "applied": applied,
        "as_of_date": transactions_as_of(season_tx),
        "retired": int(
            joined.filter(pl.col("offseason_roster_status") == "retired").height
            if "offseason_roster_status" in joined.columns
            else 0
        ),
        "unsigned": int(
            joined.filter(pl.col("offseason_roster_status") == "unsigned").height
            if "offseason_roster_status" in joined.columns
            else 0
        ),
    }


def compute_vacated_opportunity_audit(
    season_features: pl.DataFrame,
    transactions: pl.DataFrame,
    *,
    feature_season: int,
) -> pl.DataFrame:
    """Team-level vacated volume from players who left for 2026."""
    season_tx = transactions.filter(pl.col("effective_season") == feature_season + 1)
    leavers = season_tx.filter(
        ~pl.col("transaction_type").is_in(list(SAME_TEAM_TYPES))
        | (pl.col("new_team") != pl.col("old_team"))
    )
    if "player_id" not in leavers.columns:
        return pl.DataFrame()
    leavers = leavers.filter(pl.col("player_id").is_not_null() & (pl.col("player_id") != ""))
    if leavers.is_empty() or season_features.is_empty():
        return pl.DataFrame()

    id_col = "gsis_id" if "gsis_id" in season_features.columns else CANONICAL_ID_COLUMN
    base = season_features.filter(pl.col("season") == feature_season)
    if base.is_empty():
        return pl.DataFrame()
    joined = base.join(
        leavers.select(
            pl.col("player_id").alias(id_col),
            pl.col("old_team").alias("vacate_from_team"),
            pl.col("new_team").alias("vacate_to_team"),
            pl.col("transaction_type"),
            pl.col("priority"),
        ),
        on=id_col,
        how="inner",
    )
    # Only count when they left that team's 2025 roster context.
    joined = joined.filter(
        pl.col("vacate_from_team").is_not_null()
        & (pl.col("team") == pl.col("vacate_from_team"))
        & (pl.col("vacate_to_team") != pl.col("vacate_from_team"))
    )
    metrics = []
    for col, alias in (
        ("pass_attempts", "vacated_pass_attempts"),
        ("carries", "vacated_carries"),
        ("targets", "vacated_targets"),
        ("receptions", "vacated_receptions"),
        ("receiving_air_yards", "vacated_air_yards"),
        ("rz_targets", "vacated_red_zone_targets"),
        ("inside_five_carries", "vacated_inside_five_carries"),
        ("routes", "vacated_routes"),
        ("offense_snaps", "vacated_snaps"),
        ("fantasy_points_ppr", "vacated_fantasy_points"),
    ):
        if col in joined.columns:
            metrics.append(pl.col(col).sum().alias(alias))
    if not metrics:
        return pl.DataFrame()
    return (
        joined.group_by("vacate_from_team")
        .agg([pl.len().alias("leavers"), *metrics])
        .rename({"vacate_from_team": "team"})
    )


def write_transaction_audits(
    evaluation_dir: Path,
    *,
    transactions: pl.DataFrame,
    apply_result: TransactionApplyResult | None = None,
    projection_conflicts: pl.DataFrame | None = None,
    vacated: pl.DataFrame | None = None,
    rookies_missing: pl.DataFrame | None = None,
) -> dict[str, Path]:
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    unsigned = transactions.filter(pl.col("roster_status") == "unsigned")
    retired = transactions.filter(pl.col("roster_status") == "retired")
    paths["unsigned"] = evaluation_dir / "unsigned-player-audit.csv"
    paths["retired"] = evaluation_dir / "retired-player-audit.csv"
    unsigned.write_csv(paths["unsigned"])
    retired.write_csv(paths["retired"])

    if apply_result is not None and not apply_result.unresolved.is_empty():
        path = evaluation_dir / "2026-roster-conflicts.csv"
        apply_result.unresolved.write_csv(path)
        paths["conflicts"] = path
    elif projection_conflicts is not None:
        path = evaluation_dir / "2026-roster-conflicts.csv"
        projection_conflicts.write_csv(path)
        paths["conflicts"] = path

    if vacated is not None and not vacated.is_empty():
        path = evaluation_dir / "vacated-opportunity-audit.csv"
        vacated.write_csv(path)
        paths["vacated"] = path

    if rookies_missing is not None:
        path = evaluation_dir / "rookie-roster-audit.csv"
        rookies_missing.write_csv(path)
        paths["rookies"] = path

    return paths


PRIORITY_ROOKIES: tuple[tuple[str, str, str, int, str], ...] = (
    ("Fernando Mendoza", "QB", "LV", 1, "P1"),
    ("Jeremiyah Love", "RB", "ARI", 3, "P1"),
    ("Carnell Tate", "WR", "TEN", 4, "P1"),
    ("Jordyn Tyson", "WR", "NO", 8, "P1"),
    ("Ty Simpson", "QB", "LAR", 13, "P1"),
    ("Kenyon Sadiq", "TE", "NYJ", 16, "P1"),
    ("Makai Lemon", "WR", "PHI", 20, "P1"),
    ("KC Concepcion", "WR", "CLE", 24, "P1"),
    ("Omar Cooper Jr.", "WR", "NYJ", 30, "P1"),
    ("Jadarian Price", "RB", "SEA", 32, "P1"),
    ("De'Zhaun Stribling", "WR", "SF", 33, "P1"),
    ("Denzel Boston", "WR", "CLE", 39, "P2"),
    ("Germie Bernard", "WR", "PIT", 47, "P1"),
    ("Eli Stowers", "TE", "PHI", 54, "P2"),
    ("Carson Beck", "QB", "ARI", 65, "P1"),
    ("Sam Roush", "TE", "BAL", 69, "P2"),
    ("Antonio Williams", "WR", "WAS", 71, "P1"),
    ("Oscar Delp", "TE", "NO", 73, "P2"),
    ("Drew Allar", "QB", "PIT", 76, "P1"),
    ("Ja'Kobi Lane", "WR", "BAL", 80, "P2"),
    ("Chris Brazzell II", "WR", "CAR", 83, "P2"),
    ("Kaelon Black", "RB", "SF", 90, "P2"),
    ("Cade Klubnik", "QB", "NYJ", 110, "P2"),
    ("Mike Washington Jr.", "RB", "LV", 122, "P2"),
    ("Nicholas Singleton", "RB", "TEN", 165, "P2"),
)


def audit_priority_rookies(draft_or_rookies: pl.DataFrame | None) -> pl.DataFrame:
    """Return priority rookies with present/missing flags against draft enrichment."""
    rows = []
    names_present: set[str] = set()
    if draft_or_rookies is not None and not draft_or_rookies.is_empty():
        for col in ("display_name", "pfr_player_name", "player_name", "name"):
            if col in draft_or_rookies.columns:
                names_present = {
                    re_sub_name(v) for v in draft_or_rookies.get_column(col).drop_nulls().to_list()
                }
                break
    for name, position, team, pick, priority in PRIORITY_ROOKIES:
        rows.append(
            {
                "player_name": name,
                "position": position,
                "team": team,
                "pick": pick,
                "priority": priority,
                "present_in_draft_data": re_sub_name(name) in names_present,
            }
        )
    return pl.DataFrame(rows)


def re_sub_name(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def detect_projection_conflicts(
    frame: pl.DataFrame,
    transactions: pl.DataFrame,
    *,
    target_season: int,
) -> pl.DataFrame:
    """Find P1 players whose projection team disagrees with the patch."""
    season_tx = transactions.filter(
        (pl.col("effective_season") == target_season) & (pl.col("priority") == "P1")
    )
    if season_tx.is_empty():
        return pl.DataFrame()
    id_col = "gsis_id" if "gsis_id" in frame.columns else CANONICAL_ID_COLUMN
    team_col = (
        "projected_team"
        if "projected_team" in frame.columns
        else "next_team"
        if "next_team" in frame.columns
        else "team"
    )
    cols = [id_col, team_col]
    if "display_name" in frame.columns:
        cols.append("display_name")
    joined = frame.select(cols).join(
        season_tx.select(
            pl.col("player_id").alias(id_col),
            pl.col("player_name"),
            pl.col("new_team"),
            pl.col("priority"),
            pl.col("roster_status"),
        ),
        on=id_col,
        how="inner",
    )
    conflicts = joined.with_columns(
        _normalise_destination(pl.col("new_team")).alias("expected_team")
    ).filter(pl.col(team_col).cast(pl.Utf8) != pl.col("expected_team"))
    return conflicts


@dataclass
class RosterAuditResult:
    """Structured result from ``ffpm data audit-rosters``."""

    ok: bool
    as_of_date: str | None
    report_text: str
    paths: dict[str, Path]
    p1_conflicts: int
    warnings: list[str] = field(default_factory=list)


def run_roster_audit(
    *,
    transactions_path: Path,
    evaluation_dir: Path,
    target_season: int,
    feature_end_season: int,
    projection_features: pl.DataFrame | None = None,
    season_features: pl.DataFrame | None = None,
    draft_or_rookies: pl.DataFrame | None = None,
    fail_on_p1_conflict: bool = True,
) -> RosterAuditResult:
    """Compare the manual patch with projection context and write audit CSVs."""
    transactions = load_offseason_transactions(transactions_path)
    season_tx = transactions.filter(pl.col("effective_season") == target_season)
    as_of = transactions_as_of(season_tx)
    warnings: list[str] = []

    pre_apply_stuck = pl.DataFrame()
    working_features = projection_features
    if projection_features is not None and not projection_features.is_empty():
        pre_apply_stuck = detect_projection_conflicts(
            projection_features, transactions, target_season=target_season
        )
        id_col = "gsis_id" if "gsis_id" in projection_features.columns else CANONICAL_ID_COLUMN
        team_col = (
            "projected_team"
            if "projected_team" in projection_features.columns
            else "next_team"
            if "next_team" in projection_features.columns
            else "team"
        )
        movers = season_tx.filter(
            (pl.col("old_team") != pl.col("new_team"))
            & (~pl.col("transaction_type").is_in(list(SAME_TEAM_TYPES)))
        )
        if not movers.is_empty() and team_col in projection_features.columns:
            stuck = projection_features.join(
                movers.select(
                    pl.col("player_id").alias(id_col),
                    pl.col("player_name"),
                    pl.col("old_team"),
                    pl.col("new_team"),
                    pl.col("priority"),
                    pl.col("roster_status"),
                ),
                on=id_col,
                how="inner",
            ).filter(pl.col(team_col) == pl.col("old_team"))
            if not stuck.is_empty():
                extra = stuck.select(
                    [
                        c
                        for c in (
                            id_col,
                            team_col,
                            "player_name",
                            "new_team",
                            "priority",
                            "roster_status",
                            "old_team",
                        )
                        if c in stuck.columns
                    ]
                )
                pre_apply_stuck = (
                    pl.concat([pre_apply_stuck, extra], how="diagonal_relaxed")
                    if not pre_apply_stuck.is_empty()
                    else extra
                )
        working_features, _ = apply_transactions_to_projection_frame(
            projection_features, transactions, target_season=target_season
        )
        if not pre_apply_stuck.is_empty():
            warnings.append(
                f"{pre_apply_stuck.height} players were still on 2025 teams in "
                "projection_features.parquet before the patch was applied. Rebuild "
                "with `ffpm data build-dataset` so vacated/competition features refresh."
            )

    conflicts = pl.DataFrame()
    if working_features is not None and not working_features.is_empty():
        conflicts = detect_projection_conflicts(
            working_features, transactions, target_season=target_season
        )
        id_col = "gsis_id" if "gsis_id" in working_features.columns else CANONICAL_ID_COLUMN
        team_col = (
            "projected_team"
            if "projected_team" in working_features.columns
            else "next_team"
            if "next_team" in working_features.columns
            else "team"
        )
        inactive = season_tx.filter(
            pl.col("roster_status").is_in(["unsigned", "retired"])
            | (pl.col("active_roster_bool") == False)  # noqa: E712
        )
        if not inactive.is_empty():
            # Prefix audit columns — patched features already carry priority/status.
            joined = working_features.join(
                inactive.select(
                    pl.col("player_id").alias(id_col),
                    pl.col("player_name").alias("audit_player_name"),
                    pl.col("roster_status").alias("audit_roster_status"),
                    pl.col("priority").alias("audit_priority"),
                    pl.col("old_team").alias("audit_old_team"),
                ),
                on=id_col,
                how="inner",
            )
            bad = joined.filter(
                pl.col(team_col).is_not_null()
                & (~pl.col(team_col).is_in(["FA", "UNKNOWN", "RET", "RETIRED"]))
                & (pl.col(team_col) == pl.col("audit_old_team"))
            )
            if not bad.is_empty():
                conflicts = (
                    pl.concat([conflicts, bad], how="diagonal_relaxed")
                    if not conflicts.is_empty()
                    else bad
                )

    vacated = pl.DataFrame()
    if season_features is not None and not season_features.is_empty():
        vacated = compute_vacated_opportunity_audit(
            season_features, transactions, feature_season=feature_end_season
        )

    rookies = audit_priority_rookies(draft_or_rookies)
    missing_rookies = rookies.filter(~pl.col("present_in_draft_data"))
    if missing_rookies.height:
        warnings.append(
            f"{missing_rookies.height} priority rookies missing from draft/enrichment data."
        )

    paths = write_transaction_audits(
        evaluation_dir,
        transactions=season_tx,
        projection_conflicts=conflicts if not conflicts.is_empty() else None,
        vacated=vacated if not vacated.is_empty() else None,
        rookies_missing=rookies,
    )
    if not pre_apply_stuck.is_empty():
        evaluation_dir.mkdir(parents=True, exist_ok=True)
        pre_path = evaluation_dir / "2026-roster-pre-apply-drift.csv"
        pre_apply_stuck.write_csv(pre_path)
        paths["pre_apply_drift"] = pre_path

    p1_conflicts = 0
    if not conflicts.is_empty() and "priority" in conflicts.columns:
        p1_conflicts = int(conflicts.filter(pl.col("priority") == "P1").height)
    elif not conflicts.is_empty():
        p1_conflicts = conflicts.height

    lines = [
        f"Roster audit for season {target_season}",
        f"Transaction as_of_date: {as_of or 'unknown'}",
        f"Manual transactions: {season_tx.height}",
        f"Unsigned: {season_tx.filter(pl.col('roster_status') == 'unsigned').height}",
        f"Retired: {season_tx.filter(pl.col('roster_status') == 'retired').height}",
        f"Pre-apply drift rows (informational): {pre_apply_stuck.height}",
        f"Post-apply conflicts: {conflicts.height}",
        f"P1 conflicts (post-apply): {p1_conflicts}",
        f"Vacated opportunity teams: {vacated.height if not vacated.is_empty() else 0}",
        f"Priority rookies missing: {missing_rookies.height}",
        "",
        "Report files:",
    ]
    for key, path in sorted(paths.items()):
        lines.append(f"  - {key}: {path}")
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in warnings)

    ok = not (fail_on_p1_conflict and p1_conflicts > 0)
    if not ok:
        lines.append("")
        lines.append("FAILED: unresolved P1 roster conflicts after applying the patch.")

    report_text = "\n".join(lines) + "\n"
    report_path = evaluation_dir / "2026-roster-audit-report.txt"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    paths["report"] = report_path

    return RosterAuditResult(
        ok=ok,
        as_of_date=as_of,
        report_text=report_text,
        paths=paths,
        p1_conflicts=p1_conflicts,
        warnings=warnings,
    )
