from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AddressGazetteer:
    """Official address lookup backed by a validated, explicitly configured index."""

    INDEX_ENV = "KOREAN_PII_ADDRESS_INDEX"
    LEGACY_ENVS = ("KOREAN_PII_LEGAL_DONG_ZIP", "KOREAN_PII_ROAD_NAME_ZIP")
    SCHEMA_VERSION = "1"

    def __init__(self, index_path: str | Path | None = None):
        self.index_path = Path(index_path) if index_path else None
        self.administrative_dong: set[str] = set()
        self.legal_dong: set[str] = set()
        self.roads: set[str] = set()
        self.road_combinations: set[tuple[str, str, str, str]] = set()
        self._loaded = False
        self._lock = threading.RLock()
        self._manifest: dict = {}
        self._index_sha256: str | None = None

    @classmethod
    def from_environment(cls) -> "AddressGazetteer":
        legacy = {name: os.getenv(name) for name in cls.LEGACY_ENVS if os.getenv(name)}
        index_path = os.getenv(cls.INDEX_ENV)
        if legacy and not index_path:
            names = ", ".join(sorted(legacy))
            raise ValueError(
                f"legacy address ZIP configuration ({names}) is unsupported by this experimental "
                f"policy; build an index and set {cls.INDEX_ENV}"
            )
        return cls(index_path)

    @property
    def configured(self) -> bool:
        return self.index_path is not None

    @property
    def status(self) -> dict:
        base = {
            "configured": self.configured,
            "loaded": self._loaded,
            "path": str(self.index_path.resolve()) if self.index_path else None,
            "reason": None if self.configured else f"{self.INDEX_ENV} is not configured",
            "administrative_name_count": len(self.administrative_dong),
            "legal_name_count": len(self.legal_dong),
            "road_name_count": len(self.roads),
            "road_combination_count": len(self.road_combinations),
            "index_sha256": self._index_sha256,
        }
        if self._manifest:
            base["sources"] = self._manifest.get("sources", {})
            base["source_counts"] = self._manifest.get("counts", {})
        return base

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            if not self.configured:
                return
            assert self.index_path is not None
            if not self.index_path.is_file():
                raise FileNotFoundError(f"configured address index is missing: {self.index_path}")
            connection = sqlite3.connect(f"file:{self.index_path.resolve()}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("configured address index failed integrity_check")
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
                if metadata.get("schema_version") != self.SCHEMA_VERSION:
                    raise ValueError("configured address index has unsupported schema_version")
                self._manifest = json.loads(metadata["manifest"])
                self.administrative_dong = {
                    row[0] for row in connection.execute(
                        "SELECT DISTINCT admin_name FROM administrative_dong "
                        "WHERE abolished='' AND admin_name<>''"
                    )
                }
                self.legal_dong = {
                    row[0] for row in connection.execute(
                        "SELECT DISTINCT town FROM legal_dong WHERE abolished='' AND town<>'' "
                        "UNION SELECT DISTINCT village FROM legal_dong WHERE abolished='' AND village<>''"
                    )
                }
                self.roads = {
                    row[0] for row in connection.execute(
                        "SELECT DISTINCT road_name FROM road_name WHERE abolished='0' AND road_name<>''"
                    )
                }
                self.road_combinations = {
                    (row[0], row[1], row[2], row[3])
                    for row in connection.execute(
                        "SELECT DISTINCT province, district, admin_dong, road_name "
                        "FROM road_name WHERE abolished='0' AND province<>'' AND district<>'' "
                        "AND admin_dong<>'' AND road_name<>''"
                    )
                }
                if not self.administrative_dong or not self.legal_dong or not self.roads:
                    raise ValueError("configured address index contains an empty required name set")
                self._index_sha256 = _sha256(self.index_path)
                self._loaded = True
            finally:
                connection.close()

    def contains(self, name: str) -> bool:
        self.load()
        return name in self.administrative_dong or name in self.legal_dong or name in self.roads

    def contains_road_combination(
        self, province: str, district: str, dong: str, road: str
    ) -> bool:
        self.load()
        return (province, district, dong, road) in self.road_combinations
