"""On-disk parquet cache shared by every data adapter.

Design goals, in order:

1. **Never lose good data.** A failed refresh keeps the previous cached copy
   and logs loudly rather than leaving a hole.
2. **Offline reproducibility.** With ``FFPM_OFFLINE=true`` the pipeline runs
   entirely from this cache and errors clearly when an entry is missing.
3. **Provenance.** Every entry carries a sidecar JSON manifest recording when
   it was fetched, where from, its row/column shape and a content hash.

Cached files live under ``data/cache/<source>/<key>.parquet`` with the
manifest at ``<key>.manifest.json``. Nothing here is committed to git.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from fantasy_football_prediction_model.logging import DataUnavailableError, get_logger

logger = get_logger(__name__)

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def sanitise_key(key: str) -> str:
    """Turn an arbitrary cache key into a safe, stable filename stem."""
    cleaned = _SAFE_KEY.sub("-", key).strip("-")
    if not cleaned:
        raise ValueError(f"Cache key {key!r} reduces to an empty filename.")
    # Windows path limits bite quickly under OneDrive; hash long keys.
    if len(cleaned) > 120:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        cleaned = f"{cleaned[:100]}-{digest}"
    return cleaned


def frame_hash(frame: pl.DataFrame) -> str:
    """Return a stable content hash for a dataframe.

    Uses Polars' row hashing so the result does not depend on how the frame
    was constructed, only on its contents and column order.
    """
    if frame.is_empty():
        return hashlib.sha256(b"empty").hexdigest()[:32]
    try:
        row_hashes = frame.hash_rows(seed=0)
        payload = row_hashes.sort().to_numpy().tobytes()
    except (pl.exceptions.PolarsError, TypeError, ValueError):
        # Some exotic nested dtypes cannot be hashed directly; fall back to
        # a textual digest of the schema and a deterministic sample.
        payload = repr(frame.schema).encode("utf-8") + frame.head(200).write_csv().encode("utf-8")
    schema_part = ",".join(f"{name}:{dtype}" for name, dtype in frame.schema.items())
    digest = hashlib.sha256(schema_part.encode("utf-8") + payload)
    return digest.hexdigest()[:32]


@dataclass(slots=True)
class CacheEntry:
    """Provenance record for one cached dataset."""

    key: str
    source: str
    source_identifier: str
    fetched_at: str
    rows: int
    columns: int
    column_names: list[str]
    content_hash: str
    package_versions: dict[str, str] = field(default_factory=dict)
    seasons: list[int] = field(default_factory=list)
    notes: str = ""

    @property
    def fetched_datetime(self) -> datetime:
        return datetime.fromisoformat(self.fetched_at)

    def age(self) -> timedelta:
        return datetime.now(UTC) - self.fetched_datetime

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataCache:
    """Parquet-backed cache with sidecar provenance manifests."""

    def __init__(self, root: Path, *, ttl_hours: float = 24.0, offline: bool = False) -> None:
        self.root = Path(root)
        self.ttl = timedelta(hours=max(ttl_hours, 0.0))
        self.offline = offline
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------------

    def _dir(self, source: str) -> Path:
        path = self.root / sanitise_key(source)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def data_path(self, source: str, key: str) -> Path:
        return self._dir(source) / f"{sanitise_key(key)}.parquet"

    def manifest_path(self, source: str, key: str) -> Path:
        return self._dir(source) / f"{sanitise_key(key)}.manifest.json"

    # -- reads ---------------------------------------------------------------

    def exists(self, source: str, key: str) -> bool:
        return self.data_path(source, key).is_file()

    def read_manifest(self, source: str, key: str) -> CacheEntry | None:
        path = self.manifest_path(source, key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return CacheEntry(**payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Ignoring unreadable cache manifest %s: %s", path, exc)
            return None

    def is_fresh(self, source: str, key: str) -> bool:
        """True when a cached entry exists and is younger than the TTL."""
        if not self.exists(source, key):
            return False
        if self.ttl.total_seconds() == 0:
            return False
        entry = self.read_manifest(source, key)
        if entry is None:
            return False
        try:
            return entry.age() < self.ttl
        except ValueError:
            return False

    def read(self, source: str, key: str) -> pl.DataFrame | None:
        """Return the cached frame, or ``None`` when it is absent/corrupt."""
        path = self.data_path(source, key)
        if not path.is_file():
            return None
        try:
            return pl.read_parquet(path)
        except (pl.exceptions.PolarsError, OSError) as exc:
            logger.warning("Cached file %s could not be read (%s); it will be refetched.", path, exc)
            return None

    def require(self, source: str, key: str) -> pl.DataFrame:
        """Read a cached frame or raise a clear offline-mode error."""
        frame = self.read(source, key)
        if frame is None:
            raise DataUnavailableError(
                f"No cached data for '{source}/{key}' and the pipeline is running offline.",
                hint=(
                    "Run the same command once with network access and without --offline "
                    "(for example `ffpm data fetch-nfl`) to populate data/cache/, "
                    "or unset FFPM_OFFLINE."
                ),
            )
        return frame

    # -- writes --------------------------------------------------------------

    def write(
        self,
        source: str,
        key: str,
        frame: pl.DataFrame,
        *,
        source_identifier: str,
        seasons: list[int] | None = None,
        package_versions: dict[str, str] | None = None,
        notes: str = "",
    ) -> CacheEntry:
        """Persist a frame plus its provenance manifest.

        The parquet file is written to a temporary path and then moved, so an
        interrupted run cannot leave a truncated file that looks valid.
        """
        data_path = self.data_path(source, key)
        temp_path = data_path.with_suffix(".parquet.tmp")
        frame.write_parquet(temp_path, compression="zstd")
        temp_path.replace(data_path)

        entry = CacheEntry(
            key=key,
            source=source,
            source_identifier=source_identifier,
            fetched_at=datetime.now(UTC).isoformat(),
            rows=frame.height,
            columns=frame.width,
            column_names=list(frame.columns),
            content_hash=frame_hash(frame),
            package_versions=package_versions or {},
            seasons=sorted(seasons or []),
            notes=notes,
        )
        self.manifest_path(source, key).write_text(
            json.dumps(entry.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        logger.debug(
            "Cached %s/%s: %d rows x %d columns (%s)",
            source,
            key,
            frame.height,
            frame.width,
            entry.content_hash,
        )
        return entry

    # -- generic JSON side cache (used by the CFBD adapter) ------------------

    def json_path(self, source: str, key: str) -> Path:
        return self._dir(source) / f"{sanitise_key(key)}.json"

    def read_json(self, source: str, key: str) -> Any | None:
        path = self.json_path(source, key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cached JSON %s is unreadable (%s); it will be refetched.", path, exc)
            return None

    def write_json(self, source: str, key: str, payload: Any) -> Path:
        path = self.json_path(source, key)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp_path.replace(path)
        return path

    # -- housekeeping --------------------------------------------------------

    def entries(self) -> list[CacheEntry]:
        """Every readable manifest currently in the cache."""
        found: list[CacheEntry] = []
        for manifest in sorted(self.root.rglob("*.manifest.json")):
            source = manifest.parent.name
            key = manifest.name.removesuffix(".manifest.json")
            if entry := self.read_manifest(source, key):
                found.append(entry)
        return found

    def total_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())

    def clear(self, source: str | None = None) -> int:
        """Delete cached files. Returns the number of files removed."""
        target = self._dir(source) if source else self.root
        removed = 0
        for path in sorted(target.rglob("*")):
            if path.is_file():
                path.unlink()
                removed += 1
        return removed
