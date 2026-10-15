# Third-party model, visibility, and redistribution notes

Base model weights, LoRA weights, and address-database files are not bundled in this repository or its release wheel. Runtime model snapshots must match the pinned revisions and SHA-256 values in `source/korean_pii/model-manifest.json`.

| Component | Pinned revision | Declared license |
|---|---|---|
| FrameByFrame/korean-pii-e5-base | `a308c54b4407819624a5661e31e162a269f39818` | MIT |
| infobank-corp/koredact-bert-base | `c8385f52505893cadd8a9adcc5958fce10ca3ead` | CC-BY-SA-4.0 |
| atonlee/koelectra-ko-pii-ner | `1e75c01e707232401883cf364151bbe2e560c708` | Apache-2.0 |
| seongyeon1/ko-pii-ner-roberta-base | `95a3af685dccf4bb3f7fff6fc81146fed71500bb` | CC-BY-SA-4.0 |

Downloading or redistributing any model snapshot is a separate action governed by that model's upstream license. In particular, the two CC-BY-SA-4.0 model snapshots require their attribution and share-alike obligations to be reviewed for the intended deployment. This note is not legal advice and does not replace the upstream license texts.

## Repository source license status

This repository is publicly visible, but the wrapper source does not currently carry an open-source license. Default copyright rules therefore apply. Public visibility permits viewing and GitHub-hosted forking under GitHub's Terms of Service; it does not grant general permission to reproduce, modify, distribute, or create derivative works. See GitHub's [repository licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

Do not describe this repository as open source. Product use by the owner's team or organization must follow a separate internal authorization. External reuse requires explicit permission from the copyright holder or a future recorded license.

Runtime dependencies are installed separately and require their own license and notice inventory for the intended distribution.
