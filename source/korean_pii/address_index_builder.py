#!/usr/bin/env python3
"""Validate official Korean address ZIPs and build the runtime SQLite index."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zipfile
from pathlib import Path


SCHEMA_VERSION = "1"
MOIS_SOURCE_URL = "https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000052&nttId=130109"
ROAD_SOURCE_URL = "https://business.juso.go.kr/jst/jstAddressDownload?menu=7"
MOIS_KINDS = ("KIKcd_H", "KIKcd_B", "KIKmix")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def field(raw: bytes, start: int, end: int) -> str:
    return raw[start:end].decode("cp949").strip()


def select_mois_members(archive: zipfile.ZipFile) -> tuple[dict[str, str], str]:
    selected: dict[str, str] = {}
    dates = set()
    for kind in MOIS_KINDS:
        matches = [
            name for name in archive.namelist()
            if re.search(rf"(?:^|/){kind}\.(\d{{8}})$", name)
        ]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {kind}.YYYYMMDD text member; found {len(matches)}")
        selected[kind] = matches[0]
        dates.add(matches[0].rsplit(".", 1)[1])
    if len(dates) != 1:
        raise ValueError("MOIS members have inconsistent effective dates")
    return selected, dates.pop()


def nonempty_rows(archive: zipfile.ZipFile, member: str):
    with archive.open(member) as handle:
        next(handle, None)
        for raw in handle:
            raw = raw.rstrip(b"\r\n")
            if raw.strip():
                yield raw


def parse_admin(raw: bytes) -> tuple[str, ...]:
    if len(raw) < 120:
        raise ValueError("short administrative-dong row")
    return (
        field(raw, 0, 10), field(raw, 11, 41), field(raw, 42, 72),
        field(raw, 73, 103), field(raw, 104, 112), field(raw, 113, 121),
    )


def parse_legal(raw: bytes) -> tuple[str, ...]:
    if len(raw) < 152:
        raise ValueError("short legal-dong row")
    return (
        field(raw, 0, 10), field(raw, 11, 41), field(raw, 42, 72),
        field(raw, 73, 103), field(raw, 104, 134), field(raw, 135, 143),
        field(raw, 144, 152),
    )


def parse_mix(raw: bytes) -> tuple[str, ...]:
    # Same leading administrative fields as KIKcd_H, followed by legal code/name.
    if len(raw) < 163:
        raise ValueError("short administrative/legal mapping row")
    return (
        field(raw, 0, 10), field(raw, 11, 41), field(raw, 42, 72),
        field(raw, 73, 103), field(raw, 104, 114), field(raw, 115, 145),
        field(raw, 146, 154), field(raw, 155, 163),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mois-zip", type=Path, required=True)
    parser.add_argument("--road-zip", type=Path, required=True)
    parser.add_argument("--road-snapshot-date", required=True, help="YYYYMM or YYYYMMDD from the official download")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expect-mois-sha256")
    parser.add_argument("--expect-road-sha256")
    args = parser.parse_args()
    for path in (args.mois_zip, args.road_zip):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not re.fullmatch(r"\d{6}(?:\d{2})?", args.road_snapshot_date):
        raise ValueError("--road-snapshot-date must be YYYYMM or YYYYMMDD")

    hashes = {"mois_zip": sha256(args.mois_zip), "road_zip": sha256(args.road_zip)}
    if args.expect_mois_sha256 and hashes["mois_zip"] != args.expect_mois_sha256.lower():
        raise ValueError("MOIS ZIP SHA-256 mismatch")
    if args.expect_road_sha256 and hashes["road_zip"] != args.expect_road_sha256.lower():
        raise ValueError("road ZIP SHA-256 mismatch")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {args.output}")
    connection = sqlite3.connect(args.output)
    try:
        connection.executescript("""
            PRAGMA journal_mode=OFF;
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE administrative_dong(
                admin_code TEXT, province TEXT, district TEXT, admin_name TEXT,
                created TEXT, abolished TEXT
            );
            CREATE TABLE legal_dong(
                legal_code TEXT, province TEXT, district TEXT, town TEXT,
                village TEXT, created TEXT, abolished TEXT
            );
            CREATE TABLE admin_legal_map(
                admin_code TEXT, province TEXT, district TEXT, admin_name TEXT,
                legal_code TEXT, legal_name TEXT, created TEXT, abolished TEXT
            );
            CREATE TABLE road_name(
                region_code TEXT, road_code TEXT, road_part TEXT, road_name TEXT,
                province TEXT, district TEXT, admin_dong TEXT, abolished TEXT,
                created TEXT
            );
        """)
        with zipfile.ZipFile(args.mois_zip) as archive:
            members, effective_date = select_mois_members(archive)
            admin = [parse_admin(raw) for raw in nonempty_rows(archive, members["KIKcd_H"])]
            legal = [parse_legal(raw) for raw in nonempty_rows(archive, members["KIKcd_B"])]
            mapping = [parse_mix(raw) for raw in nonempty_rows(archive, members["KIKmix"])]
        with zipfile.ZipFile(args.road_zip) as archive:
            files = [name for name in archive.namelist() if not name.endswith("/")]
            if len(files) != 1:
                raise ValueError(f"expected exactly one road text member; found {len(files)}")
            roads = []
            with archive.open(files[0]) as handle:
                for line_number, raw in enumerate(handle, 1):
                    values = raw.rstrip(b"\r\n").decode("cp949").split("|")
                    if len(values) < 21:
                        raise ValueError(f"road row {line_number} has {len(values)} columns; expected >=21")
                    roads.append((
                        values[0], values[1], values[2], values[3], values[5],
                        values[6], values[9], values[10], values[19],
                    ))
        counts = {
            "administrative_rows": len(admin), "legal_rows": len(legal),
            "mapping_rows": len(mapping), "road_rows": len(roads),
            "active_administrative_rows": sum(not row[5] for row in admin),
            "active_legal_rows": sum(not row[6] for row in legal),
            "active_mapping_rows": sum(not row[7] for row in mapping),
            "active_road_rows": sum(row[7] == "0" for row in roads),
        }
        if counts["administrative_rows"] < 1000 or counts["legal_rows"] < 10000:
            raise ValueError(f"implausibly small MOIS dataset: {counts}")
        if counts["mapping_rows"] < 10000 or counts["road_rows"] < 100000:
            raise ValueError(f"implausibly small mapping/road dataset: {counts}")

        connection.executemany("INSERT INTO administrative_dong VALUES(?,?,?,?,?,?)", admin)
        connection.executemany("INSERT INTO legal_dong VALUES(?,?,?,?,?,?,?)", legal)
        connection.executemany("INSERT INTO admin_legal_map VALUES(?,?,?,?,?,?,?,?)", mapping)
        connection.executemany("INSERT INTO road_name VALUES(?,?,?,?,?,?,?,?,?)", roads)
        connection.executescript("""
            CREATE INDEX idx_admin_name ON administrative_dong(admin_name);
            CREATE INDEX idx_legal_town ON legal_dong(town);
            CREATE INDEX idx_legal_village ON legal_dong(village);
            CREATE INDEX idx_mapping_codes ON admin_legal_map(admin_code, legal_code);
            CREATE INDEX idx_road_name ON road_name(road_name);
        """)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "converter": "build_official_address_index.py",
            "sources": {
                "mois": {"url": MOIS_SOURCE_URL, "effective_date": effective_date,
                          "path": str(args.mois_zip.resolve()), "sha256": hashes["mois_zip"],
                          "members": members},
                "road": {"url": ROAD_SOURCE_URL, "snapshot_date": args.road_snapshot_date,
                          "path": str(args.road_zip.resolve()), "sha256": hashes["road_zip"],
                          "member": files[0]},
            },
            "counts": counts,
        }
        for key, value in {
            "schema_version": SCHEMA_VERSION,
            "manifest": json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        }.items():
            connection.execute("INSERT INTO metadata VALUES(?,?)", (key, value))
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
    except Exception:
        connection.close()
        args.output.unlink(missing_ok=True)
        raise
    finally:
        try:
            connection.close()
        except Exception:
            pass

    manifest["index"] = {"path": str(args.output.resolve()), "sha256": sha256(args.output)}
    manifest_path = args.manifest or args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
