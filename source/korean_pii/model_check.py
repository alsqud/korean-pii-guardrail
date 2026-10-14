from __future__ import annotations

import argparse
import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inspect_models(verify_hashes: bool = False) -> dict:
    manifest = json.loads(files("korean_pii").joinpath("model-manifest.json").read_text())
    results, all_ok = {}, True
    for name, spec in manifest["models"].items():
        root = Path(os.getenv(spec["path_env"], spec["default_path"])).expanduser()
        config_path, weight_path = root / "config.json", root / "model.safetensors"
        tokenizer_present = any((root / item).is_file() for item in (
            "tokenizer.json", "vocab.txt", "sentencepiece.bpe.model", "spiece.model",
        ))
        current = {
            "model_id": spec["model_id"], "revision": spec["revision"],
            "license": spec["license"], "path": str(root),
            "config_present": config_path.is_file(), "safetensors_present": weight_path.is_file(),
            "tokenizer_present": tokenizer_present, "remote_code_declared": None,
            "hash_checked": verify_hashes,
        }
        if config_path.is_file():
            current["remote_code_declared"] = bool(json.loads(config_path.read_text()).get("auto_map"))
        if verify_hashes and weight_path.is_file():
            current["actual_sha256"] = _digest(weight_path)
            current["hash_matches"] = current["actual_sha256"] == spec["model_safetensors_sha256"]
        ok = current["config_present"] and current["safetensors_present"] and tokenizer_present and current["remote_code_declared"] is False
        if verify_hashes:
            ok = ok and current.get("hash_matches", False)
        current["ok"] = ok
        all_ok = all_ok and ok
        results[name] = current
    return {"status": "ok" if all_ok else "failed", "download_performed": False, "models": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline-only approved-model inspection; never downloads")
    parser.add_argument("--verify-hashes", action="store_true")
    args = parser.parse_args()
    result = inspect_models(args.verify_hashes)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "ok" else 2)


if __name__ == "__main__":
    main()
