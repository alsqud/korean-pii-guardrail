# Third-party model and redistribution notes

Base model weights are not bundled in this source ZIP. Runtime snapshots must match the pinned revisions and SHA-256 values in `source/korean_pii/model-manifest.json`.

| Component | Pinned revision | Declared license |
|---|---|---|
| FrameByFrame/korean-pii-e5-base | `a308c54b4407819624a5661e31e162a269f39818` | MIT |
| infobank-corp/koredact-bert-base | `c8385f52505893cadd8a9adcc5958fce10ca3ead` | CC-BY-SA-4.0 |
| atonlee/koelectra-ko-pii-ner | `1e75c01e707232401883cf364151bbe2e560c708` | Apache-2.0 |
| seongyeon1/ko-pii-ner-roberta-base | `95a3af685dccf4bb3f7fff6fc81146fed71500bb` | CC-BY-SA-4.0 |

The bundled LoRA adapter uses the Seongyeon base architecture. Its derivative-work and redistribution obligations require review before customer or public distribution. This note is not legal advice and does not replace the upstream license texts.

The wrapper source itself has no approved public license in this delivery. Do not publish it or describe it as open source until the owner selects and records a license. Runtime dependencies also require their own license and notice inventory.
