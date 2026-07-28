"""Run manifests: what data produced what output.

A manifest is the audit trail that makes a published projection defensible.
It records the exact datasets used, their content hashes and fetch times, the
configuration, the package versions and the git commit, so a projection can be
traced back to its inputs months later.

Manifests are small JSON files and *are* committed, unlike the data itself.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import polars as pl

from fantasy_football_prediction_model.logging import get_logger

logger = get_logger(__name__)

TRACKED_PACKAGES = (
    "nflreadpy",
    "polars",
    "pyarrow",
    "numpy",
    "scikit-learn",
    "scipy",
    "pandas",
    "pydantic",
    "shap",
    "lightgbm",
    "xgboost",
)


def package_versions() -> dict[str, str]:
    """Installed versions of every package that can change model output."""
    versions: dict[str, str] = {"python": platform.python_version()}
    for package in TRACKED_PACKAGES:
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def git_commit(repo_root: Path) -> str | None:
    """Current commit SHA, or ``None`` outside a git checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_is_dirty(repo_root: Path) -> bool | None:
    """Whether the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def dataset_hash(frames: dict[str, pl.DataFrame | None]) -> str:
    """One hash covering every input dataset.

    Combines each frame's shape and content hash in a stable order, so the
    result changes if and only if some input changed.
    """
    from fantasy_football_prediction_model.data_sources.local_cache import frame_hash

    digest = hashlib.sha256()
    for name in sorted(frames):
        frame = frames[name]
        if frame is None:
            digest.update(f"{name}:absent".encode())
            continue
        digest.update(f"{name}:{frame.height}x{frame.width}:{frame_hash(frame)}".encode())
    return digest.hexdigest()


@dataclass(slots=True)
class DatasetRecord:
    """Provenance for one dataset used by a run."""

    name: str
    status: str
    rows: int = 0
    columns: int = 0
    seasons: list[int] = field(default_factory=list)
    content_hash: str = ""
    fetched_at: str | None = None
    source_identifier: str = ""
    licence: str = ""
    required: bool = False
    note: str = ""


@dataclass(slots=True)
class RunManifest:
    """Everything needed to reproduce or audit one pipeline run."""

    run_id: str
    command: str
    started_at: str
    finished_at: str | None = None
    data_mode: str = "production"
    target_season: int = 0
    feature_end_season: int = 0
    data_start_season: int = 0
    schema_version: str = ""
    model_version: str = ""
    projection_release: str = ""
    random_seed: int = 0
    git_commit: str | None = None
    git_dirty: bool | None = None
    dataset_hash: str = ""
    packages: dict[str, str] = field(default_factory=dict)
    datasets: list[DatasetRecord] = field(default_factory=list)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, command: str, *, repo_root: Path, data_mode: str = "production") -> RunManifest:
        started = datetime.now(UTC)
        return cls(
            run_id=started.strftime("%Y%m%dT%H%M%SZ"),
            command=command,
            started_at=started.isoformat(),
            data_mode=data_mode,
            git_commit=git_commit(repo_root),
            git_dirty=git_is_dirty(repo_root),
            packages=package_versions(),
        )

    def record_dataset(self, record: DatasetRecord) -> None:
        self.datasets.append(record)

    def record_stage(
        self, stage: str, status: str, *, detail: str = "", duration_seconds: float | None = None
    ) -> None:
        self.stages.append(
            {
                "stage": stage,
                "status": status,
                "detail": detail,
                "duration_seconds": duration_seconds,
            }
        )

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, directory: Path, *, name: str | None = None) -> Path:
        """Write the manifest and refresh the ``latest`` pointer."""
        directory.mkdir(parents=True, exist_ok=True)
        filename = name or f"run-{self.run_id}.json"
        path = directory / filename
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str) + "\n"
        path.write_text(payload, encoding="utf-8")
        (directory / "latest.json").write_text(payload, encoding="utf-8")
        logger.info("Wrote run manifest to %s.", path)
        return path

    @staticmethod
    def read_latest(directory: Path) -> dict[str, Any] | None:
        path = directory / "latest.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read the latest manifest at %s: %s", path, exc)
            return None
