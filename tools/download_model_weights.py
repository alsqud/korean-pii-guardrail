#!/usr/bin/env python3
"""Download the pinned model snapshots after an explicit opt-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODEL_MANIFEST = REPOSITORY_ROOT / "source" / "korean_pii" / "model-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show or download the exact model revisions in model-manifest.json."
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="perform downloads; without this flag the command only prints the plan",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    models = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))["models"]

    for name, model in models.items():
        target = Path(
            os.environ.get(model["path_env"]) or model["default_path"]
        ).expanduser().resolve()
        print(name, model["model_id"], model["revision"], "->", target, flush=True)
        if not args.download:
            continue
        if target.exists():
            raise SystemExit(f"Existing directory left unchanged: {target}")

        from huggingface_hub import snapshot_download

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"{name}-download-", dir=target.parent))
        snapshot_download(
            repo_id=model["model_id"],
            revision=model["revision"],
            local_dir=str(staging),
            token=False,
            allow_patterns=[
                "*.json",
                "*.txt",
                "*.model",
                "*.safetensors",
                "README*",
                "LICENSE*",
            ],
        )

        weights = staging / "model.safetensors"
        expected_hash = model["model_safetensors_sha256"]
        if not weights.is_file() or sha256(weights) != expected_hash:
            raise SystemExit(f"Weight hash verification failed; inspect {staging}")
        if not (staging / "config.json").is_file():
            raise SystemExit(f"Missing config.json: {staging}")
        tokenizer_files = (
            "tokenizer.json",
            "vocab.txt",
            "vocab.json",
            "tokenizer.model",
            "sentencepiece.bpe.model",
        )
        if not any((staging / filename).is_file() for filename in tokenizer_files):
            raise SystemExit(f"Missing tokenizer files: {staging}")

        staging.rename(target)
        print("Downloaded and verified:", name, flush=True)

    if not args.download:
        print("Plan only. Add --download to fetch model snapshots.")


if __name__ == "__main__":
    main()
