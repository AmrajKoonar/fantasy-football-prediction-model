"""Typer CLI entry point: ``ffpm``."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from fantasy_football_prediction_model.config import get_settings, load_settings
from fantasy_football_prediction_model.features.rookie import load_dotenv_file
from fantasy_football_prediction_model.logging import configure_logging, get_logger

# Load repo-root `.env` once at import so CFBD_API_KEY is visible without shell export.
load_dotenv_file()

app = typer.Typer(
    name="ffpm",
    help="Fantasy Football Prediction Model — reproducible NFL projection pipeline.",
    no_args_is_help=True,
    add_completion=False,
)
data_app = typer.Typer(help="Data ingestion and dataset construction.")
research_app = typer.Typer(help="Feature research and coverage audits.")
model_app = typer.Typer(help="Backtesting, training and evaluation.")
project_app = typer.Typer(help="Projection generation and web export.")
pipeline_app = typer.Typer(help="End-to-end pipeline orchestration.")

app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(model_app, name="model")
app.add_typer(project_app, name="project")
app.add_typer(pipeline_app, name="pipeline")

console = Console()
logger = get_logger(__name__)


def _settings(
    config: Path | None,
    target_season: int | None,
    offline: bool | None,
    log_level: str | None,
):
    load_dotenv_file()
    settings = load_settings(config_dir=str(config) if config else None)
    load_dotenv_file(settings.repo_root)
    if target_season is not None:
        # Rebuild is heavy; document override via env for production.
        import os

        os.environ["FFPM_TARGET_SEASON"] = str(target_season)
        settings = get_settings()
    if offline is not None:
        import os

        os.environ["FFPM_OFFLINE"] = "true" if offline else "false"
        settings = get_settings()
    level = log_level or settings.project_config.logging.level
    configure_logging(
        level,
        log_dir=settings.repo_root / settings.project_config.logging.log_dir,
        file_logging=settings.project_config.logging.file_logging,
    )
    settings.ensure_directories()
    return settings


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


@data_app.command("fetch-nfl")
def data_fetch_nfl(
    start_season: int | None = typer.Option(None, "--start-season"),
    end_season: int | None = typer.Option(None, "--end-season"),
    force_refresh: bool = typer.Option(False, "--force-refresh"),
    offline: bool = typer.Option(False, "--offline"),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Download and cache nflverse datasets."""
    settings = _settings(config, None, offline, log_level)
    from fantasy_football_prediction_model.data.ingestion import ingest

    seasons = None
    if start_season is not None and end_season is not None:
        seasons = list(range(start_season, end_season + 1))
    elif start_season is not None:
        seasons = list(range(start_season, settings.feature_end_season + 1))
    result = ingest(settings, force_refresh=force_refresh, seasons=seasons)
    console.print(
        f"[green]Ingested nflverse data[/green]: {result.player_seasons.height} player-seasons."
    )


@data_app.command("fetch-rookies")
def data_fetch_rookies(
    offline: bool = typer.Option(False, "--offline"),
    force_refresh: bool = typer.Option(False, "--force-refresh"),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Fetch optional CollegeFootballData rookie enrichment and build join tables."""
    settings = _settings(config, None, offline, log_level)
    load_dotenv_file(settings.repo_root)
    from fantasy_football_prediction_model.data_sources.college_football_data import SIGNUP_URL
    from fantasy_football_prediction_model.features.rookie import (
        build_rookie_projection_rows,
        fetch_college_seasons,
    )

    result = fetch_college_seasons(settings, force_refresh=force_refresh)
    mode = str(result.get("mode", "reduced"))
    console.print(f"Rookie data mode: [cyan]{mode}[/cyan]")
    if mode == "full":
        seasons = result.get("seasons") or []
        stats = result.get("stats")
        n_stats = getattr(stats, "height", 0) or 0
        console.print(
            f"[green]Fetched CFBD college data for seasons {seasons} "
            f"({n_stats} player-season rows). Cached under data/cache/collegefootballdata/.[/green]"
        )
        usage = result.get("usage_report") or {}
        console.print(
            f"Local CFBD usage this month: {usage.get('current_month_requests', 0)} "
            f"(machine-local count only)."
        )
    else:
        console.print(
            f"[yellow]No CFBD_API_KEY — reduced rookie mode (nflverse draft/combine only). "
            f"Get a free key at {SIGNUP_URL} and put CFBD_API_KEY=... in .env[/yellow]"
        )

    rookies, enrich_mode = build_rookie_projection_rows(settings)
    console.print(
        f"Draft rookies for {settings.target_season}: [cyan]{rookies.height}[/cyan] "
        f"(enrichment mode={enrich_mode}). Wrote data/processed/rookie_enrichment.parquet"
    )


@data_app.command("audit")
def data_audit(
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Write a data-coverage audit report."""
    settings = _settings(config, None, None, log_level)
    try:
        from fantasy_football_prediction_model.data.ingestion import ingest, write_coverage_reports

        data = ingest(settings, force_refresh=False)
        paths = write_coverage_reports(data)
        console.print(f"[green]Coverage reports:[/green] {paths}")
    except Exception as exc:
        console.print(f"[yellow]Coverage audit unavailable:[/yellow] {exc}")


@data_app.command("audit-rosters")
def data_audit_rosters(
    season: int | None = typer.Option(None, "--season", help="Target season to audit."),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Validate 2026 roster context against the offseason transaction patch."""
    settings = _settings(config, season, offline, log_level)
    target = season or settings.target_season
    from fantasy_football_prediction_model.data.transactions import (
        default_transactions_path,
        run_roster_audit,
    )

    txn_path = settings.repo_root / settings.project_config.overrides.offseason_transactions_file
    if not txn_path.is_file():
        txn_path = default_transactions_path(settings.repo_root)
    if not txn_path.is_file():
        console.print(f"[red]Missing transactions file:[/red] {txn_path}")
        raise typer.Exit(code=1)

    import polars as pl

    processed = settings.path("processed_dir")
    projection_features = None
    season_features = None
    proj_path = processed / "projection_features.parquet"
    season_path = processed / "season_features.parquet"
    if proj_path.is_file():
        projection_features = pl.read_parquet(proj_path)
    if season_path.is_file():
        season_features = pl.read_parquet(season_path)

    draft_or_rookies = None
    rookie_path = settings.path("processed_dir") / "rookie_enrichment.parquet"
    draft_cache = settings.path("cache_dir") / "draft_picks.parquet"
    if rookie_path.is_file():
        draft_or_rookies = pl.read_parquet(rookie_path)
    elif draft_cache.is_file():
        draft_or_rookies = pl.read_parquet(draft_cache)

    result = run_roster_audit(
        transactions_path=txn_path,
        evaluation_dir=settings.path("evaluation_dir"),
        target_season=target,
        feature_end_season=settings.feature_end_season,
        projection_features=projection_features,
        season_features=season_features,
        draft_or_rookies=draft_or_rookies,
        fail_on_p1_conflict=True,
    )
    console.print(result.report_text)
    if not result.ok:
        raise typer.Exit(code=1)


@data_app.command("transactions")
def data_transactions(
    season: int | None = typer.Option(None, "--season"),
    as_of: str | None = typer.Option(None, "--as-of", help="Filter to this as_of_date."),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Show every applied offseason transaction and its source."""
    import polars as pl

    settings = _settings(config, season, None, log_level)
    target = season or settings.target_season
    from fantasy_football_prediction_model.data.transactions import (
        default_transactions_path,
        load_offseason_transactions,
        transactions_as_of,
    )

    txn_path = settings.repo_root / settings.project_config.overrides.offseason_transactions_file
    if not txn_path.is_file():
        txn_path = default_transactions_path(settings.repo_root)
    if not txn_path.is_file():
        console.print(f"[red]Missing transactions file:[/red] {txn_path}")
        raise typer.Exit(code=1)

    frame = load_offseason_transactions(txn_path).filter(pl.col("effective_season") == target)
    if as_of:
        frame = frame.filter(pl.col("as_of_date").cast(str) == as_of)
    file_as_of = transactions_as_of(frame)
    console.print(
        f"[bold]Offseason transactions[/bold] season={target} as_of={file_as_of or as_of or 'n/a'} "
        f"rows={frame.height} file={txn_path}"
    )
    show_cols = [
        c
        for c in (
            "priority",
            "player_name",
            "position",
            "old_team",
            "new_team",
            "transaction_type",
            "roster_status",
            "expected_depth_chart_rank",
            "starter_confidence",
            "role_uncertainty",
            "source",
            "notes",
            "player_id",
        )
        if c in frame.columns
    ]
    if frame.is_empty():
        console.print("[yellow]No transactions matched.[/yellow]")
        return
    preview = frame.select(show_cols).sort(["priority", "position", "player_name"])
    # Avoid Rich/Windows codepage issues with Polars table glyphs.
    console.print(preview.write_csv())


@data_app.command("build-dataset")
def data_build_dataset(
    config: Path | None = typer.Option(None, "--config"),
    offline: bool = typer.Option(False, "--offline"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Build player-season feature tables and modelling pairs."""
    settings = _settings(config, None, offline, log_level)
    from fantasy_football_prediction_model.data.ingestion import ingest
    from fantasy_football_prediction_model.features.common import build_feature_table

    data = ingest(settings, force_refresh=False)
    result = build_feature_table(data, settings)
    out = settings.path("processed_dir")
    out.mkdir(parents=True, exist_ok=True)
    result.season_features.write_parquet(out / "season_features.parquet")
    result.pairs.write_parquet(out / "modelling_pairs.parquet")
    result.projection_rows.write_parquet(out / "projection_features.parquet")
    console.print(
        f"[green]Wrote feature tables[/green] "
        f"({result.season_features.height} seasons, {result.pairs.height} pairs)."
    )


# ---------------------------------------------------------------------------
# research
# ---------------------------------------------------------------------------


@research_app.command("features")
def research_features(
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Measure feature coverage, stability and next-season relationships."""
    settings = _settings(config, None, None, log_level)
    from fantasy_football_prediction_model.features.research import run_feature_research

    paths = run_feature_research(settings)
    console.print(f"[green]Feature research artifacts:[/green] {paths}")


@research_app.command("coverage")
def research_coverage(
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Alias for data coverage audit plus feature coverage CSV."""
    data_audit(config=config, log_level=log_level)
    research_features(config=config, log_level=log_level)


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


@model_app.command("backtest")
def model_backtest(
    config: Path | None = typer.Option(None, "--config"),
    position: str | None = typer.Option(None, "--position"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Rolling-origin backtest of baselines and candidate models."""
    settings = _settings(config, None, None, log_level)
    pairs_path = settings.path("processed_dir") / "modelling_pairs.parquet"
    if not pairs_path.is_file():
        console.print(
            "[red]Missing modelling_pairs.parquet. Run `ffpm data build-dataset` first.[/red]"
        )
        raise typer.Exit(code=1)
    import polars as pl

    from fantasy_football_prediction_model.evaluation.backtesting import run_backtest
    from fantasy_football_prediction_model.evaluation.reports import write_backtest_artifacts

    pairs = pl.read_parquet(pairs_path)
    positions = [position] if position else None
    result = run_backtest(pairs, settings, positions=positions, candidate_limit=2)
    paths = write_backtest_artifacts(result, settings.path("evaluation_dir"))
    console.print(f"[green]Backtest complete.[/green] Artifacts: {paths}")


@model_app.command("train")
def model_train(
    config: Path | None = typer.Option(None, "--config"),
    position: str | None = typer.Option(None, "--position"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Train final models for the configured target season."""
    settings = _settings(config, None, None, log_level)
    pairs_path = settings.path("processed_dir") / "modelling_pairs.parquet"
    if not pairs_path.is_file():
        console.print("[red]Missing modelling pairs. Run build-dataset first.[/red]")
        raise typer.Exit(1)
    import polars as pl

    from fantasy_football_prediction_model.constants import PROJECTION_TARGETS
    from fantasy_football_prediction_model.models.preprocessing import select_feature_columns
    from fantasy_football_prediction_model.models.registry import LocalModelRegistry
    from fantasy_football_prediction_model.models.training import train_position_target

    pairs = pl.read_parquet(pairs_path)
    registry = LocalModelRegistry(settings.path("model_dir"))
    positions = [position] if position else settings.positions
    for pos in positions:
        frame = pairs.filter(pl.col("position") == pos)
        features = select_feature_columns(
            frame,
            settings.features.candidate_features(pos),
            min_coverage=settings.features.selection.min_coverage,
            always_keep=settings.features.selection.always_keep,
            max_features=settings.features.selection.max_features_per_model,
        )
        for target in list(PROJECTION_TARGETS.get(pos, ())):
            col = f"outcome_{target}"
            if col not in frame.columns or not features:
                console.print(f"[yellow]Skip {pos}/{target}: missing column or features[/yellow]")
                continue
            console.print(f"Training {pos}/{target}...")
            model = train_position_target(
                frame,
                position=pos,
                target_column=col,
                feature_columns=features,
                algorithm="HistGradientBoostingRegressor",
                preprocessing=settings.model.preprocessing,
                random_seed=settings.seed,
            )
            registry.register(
                model,
                model_version=settings.project_config.project.model_version,
                training_seasons=sorted(frame.get_column("target_season").unique().to_list()),
                feature_end_season=settings.feature_end_season,
                projection_season=settings.target_season,
            )
    console.print("[green]Training complete.[/green]")


@model_app.command("evaluate")
def model_evaluate(
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Summarise the latest backtest artifacts."""
    settings = _settings(config, None, None, log_level)
    summary = settings.path("evaluation_dir") / "backtest-summary.csv"
    if not summary.is_file():
        console.print("[yellow]No backtest-summary.csv found. Run model backtest first.[/yellow]")
        raise typer.Exit(0)
    console.print(summary.read_text(encoding="utf-8")[:2000])


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------


@project_app.command("generate")
def project_generate(
    fixture: bool = typer.Option(False, "--fixture", help="Generate labelled synthetic data."),
    target_season: int | None = typer.Option(None, "--target-season"),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Generate season projections (fixture or production)."""
    settings = _settings(config, target_season, None, log_level)
    from fantasy_football_prediction_model.exports.csv import write_projection_csv
    from fantasy_football_prediction_model.projections.generate import generate_projections

    bundle = generate_projections(settings, fixture=fixture)
    art = settings.path("projection_dir")
    write_projection_csv(bundle, art / "projections.csv")
    # Stash bundle path marker
    marker = art / "last_bundle_mode.txt"
    marker.write_text(bundle.data_mode, encoding="utf-8")
    # Persist players via export-web typically; here save a pickle-free JSON sidecar count.
    (art / "player_count.txt").write_text(str(len(bundle.players)), encoding="utf-8")
    # Keep in-memory path for chained commands via temp json
    from fantasy_football_prediction_model.exports.web import export_web_data

    export_web_data(bundle, settings, allow_fixture=True)
    mode_colour = "yellow" if fixture else "green"
    console.print(
        f"[{mode_colour}]Generated {len(bundle.players)} projections "
        f"(dataMode={bundle.data_mode})[/{mode_colour}]"
    )


@project_app.command("validate")
def project_validate(
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Validate committed web JSON against Pydantic schemas."""
    settings = _settings(config, None, None, log_level)
    from fantasy_football_prediction_model.schemas import (
        ExportMetadata,
        ProjectionsFile,
        RankingsFile,
    )

    web = settings.path("web_data_dir")
    errors = 0
    for name, model in (
        ("metadata.json", ExportMetadata),
        ("projections.json", ProjectionsFile),
        ("rankings.json", RankingsFile),
    ):
        path = web / name
        if not path.is_file():
            console.print(f"[red]Missing {path}[/red]")
            errors += 1
            continue
        try:
            model.model_validate_json(path.read_text(encoding="utf-8"))
            console.print(f"[green]OK[/green] {name}")
        except Exception as exc:
            console.print(f"[red]INVALID {name}:[/red] {exc}")
            errors += 1
    meta_path = web / "metadata.json"
    if meta_path.is_file():
        meta = ExportMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
        if meta.data_mode == "fixture":
            console.print(
                "[yellow]WARNING: dataMode=fixture. Do not deploy as production.[/yellow]"
            )
        elif settings.project_config.overrides.apply_offseason_transactions:
            import polars as pl

            from fantasy_football_prediction_model.data.transactions import run_roster_audit

            txn_path = (
                settings.repo_root / settings.project_config.overrides.offseason_transactions_file
            )
            proj_path = settings.path("processed_dir") / "projection_features.parquet"
            if txn_path.is_file() and proj_path.is_file():
                result = run_roster_audit(
                    transactions_path=txn_path,
                    evaluation_dir=settings.path("evaluation_dir"),
                    target_season=settings.target_season,
                    feature_end_season=settings.feature_end_season,
                    projection_features=pl.read_parquet(proj_path),
                    fail_on_p1_conflict=True,
                )
                if not result.ok:
                    console.print("[red]Roster audit failed (P1 conflicts).[/red]")
                    console.print(result.report_text)
                    errors += 1
                else:
                    console.print(
                        f"[green]OK[/green] roster audit "
                        f"(as_of={result.as_of_date}, p1_conflicts=0)"
                    )
    raise typer.Exit(code=1 if errors else 0)


@project_app.command("export-web")
def project_export_web(
    fixture: bool = typer.Option(False, "--fixture"),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Regenerate and export web JSON (defaults to reusing generate)."""
    project_generate(fixture=fixture, target_season=None, config=config, log_level=log_level)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------


@pipeline_app.command("run-all")
def pipeline_run_all(
    fixture: bool = typer.Option(
        False, "--fixture", help="Skip live downloads; emit fixture projections."
    ),
    offline: bool = typer.Option(False, "--offline"),
    config: Path | None = typer.Option(None, "--config"),
    log_level: str | None = typer.Option(None, "--log-level"),
) -> None:
    """Run the full pipeline, or fixture export when ``--fixture`` is set."""
    settings = _settings(config, None, offline, log_level)
    if fixture:
        project_generate(fixture=True, config=config, log_level=log_level)
        project_validate(config=config, log_level=log_level)
        return
    try:
        data_fetch_nfl(config=config, offline=offline, log_level=log_level)
        data_fetch_rookies(config=config, offline=offline, log_level=log_level)
        data_build_dataset(config=config, offline=offline, log_level=log_level)
        research_features(config=config, log_level=log_level)
        model_backtest(config=config, log_level=log_level)
        model_train(config=config, log_level=log_level)
        project_generate(fixture=False, config=config, log_level=log_level)
        project_validate(config=config, log_level=log_level)
    except Exception as exc:
        console.print(f"[red]Pipeline failed:[/red] {exc}")
        console.print(
            "[yellow]Hint:[/yellow] use `ffpm pipeline run-all --fixture` for local UI/CI data."
        )
        raise typer.Exit(1) from exc


@pipeline_app.command("status")
def pipeline_status(
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show which artifacts exist on disk."""
    settings = _settings(config, None, None, None)
    table = Table(title="Pipeline status")
    table.add_column("Artifact")
    table.add_column("Present")
    checks = {
        "modelling_pairs.parquet": settings.path("processed_dir") / "modelling_pairs.parquet",
        "projection_features.parquet": settings.path("processed_dir")
        / "projection_features.parquet",
        "web/projections.json": settings.path("web_data_dir") / "projections.json",
        "web/metadata.json": settings.path("web_data_dir") / "metadata.json",
        "backtest-summary.csv": settings.path("evaluation_dir") / "backtest-summary.csv",
        "model registry": settings.path("model_dir") / "registry.json",
    }
    for label, path in checks.items():
        table.add_row(label, "yes" if path.exists() else "no")
    console.print(table)


if __name__ == "__main__":
    app()
