# Long-document generalization evaluation

This directory uses purpose-based names so reviewers do not need to know the internal experiment history.

The immutable `doc_id` values inside the sealed JSONL retain their original audit provenance. They are not module or user-facing artifact names.

- `long_document_test_set.jsonl`: sealed synthetic long-document test set
- `test_set_seal.json`: proof that truth and criteria were fixed before prediction
- `test_set_validation.json`: structural validation of the sealed set
- `raw_and_masked_predictions.jsonl`: raw spans, selected spans, and actual masked text
- `run_metadata.json`: runtime, hardware, policy, model, and dictionary metadata
- `evaluation_summary.json`: complete machine-readable evaluation
- `per_type_results.csv`: results for each of the 13 supported PII types
- `item_level_results.csv`: full, partial, and miss outcome per gold item
- `general_information_false_positives.csv`: decoy/general-information outcomes
- `overlap_analysis.csv`: raw and selected span collisions
- `headline_metrics.csv`: compact headline metrics
- `pre_deployment_equivalence.json`: packaged-code equivalence before activation
- `post_deployment_equivalence.json`: packaged-code equivalence after activation

Audit the committed evidence without loading models:

```bash
python evaluation/audit_release_results.py
```

Re-run inference in a fully configured model environment:

```bash
PYTHONPATH=source python evaluation/run_hybrid_pipeline.py \
  --fixture evaluation/long_document_generalization/long_document_test_set.jsonl \
  --output /tmp/hybrid_pipeline_predictions.jsonl
```

Verify that the packaged public API still reproduces the committed outputs:

```bash
PYTHONPATH=source python evaluation/verify_packaged_output.py \
  --fixture evaluation/long_document_generalization/long_document_test_set.jsonl \
  --expected evaluation/long_document_generalization/raw_and_masked_predictions.jsonl \
  --output /tmp/packaged_output_equivalence.json
```

The set is synthetic and independently sealed, but it is not a substitute for monitored production traffic or a separately governed real-data evaluation.
