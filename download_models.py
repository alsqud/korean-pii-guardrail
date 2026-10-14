import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parent / "source/korean_pii/model-manifest.json"
    models = json.loads(manifest.read_text(encoding="utf-8"))["models"]
    for name, model in models.items():
        target = Path(os.environ.get(model["path_env"]) or model["default_path"]).expanduser().resolve()
        print(name, model["model_id"], model["revision"], "->", target, flush=True)
        if not args.download:
            continue
        if target.exists():
            raise SystemExit(f"Existing directory left unchanged: {target}")
        from huggingface_hub import snapshot_download
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=name + "-download-", dir=target.parent))
        snapshot_download(
            repo_id=model["model_id"],
            revision=model["revision"],
            local_dir=str(staging),
            token=False,
            allow_patterns=[chr(42) + ext for ext in [".json", ".txt", ".model", ".safetensors"]] + ["README" + chr(42), "LICENSE" + chr(42)],
        )
        weights = staging / "model.safetensors"
        if not weights.is_file() or sha256(weights) != model["model_safetensors_sha256"]:
            raise SystemExit(f"Weight hash verification failed; inspect {staging}")
        if not (staging / "config.json").is_file():
            raise SystemExit(f"Missing config.json: {staging}")
        if not any((staging / item).is_file() for item in ["tokenizer.json", "vocab.txt", "vocab.json", "tokenizer.model", "sentencepiece.bpe.model"]):
            raise SystemExit(f"Missing tokenizer files: {staging}")
        staging.rename(target)
        print("Downloaded; weight hash verified:", name, flush=True)
    if not args.download:
        print("Plan only: no network access or model changes. Use --download to download.")
if __name__ == "__main__":
    main()
