# Source-linked original historical labels

These inputs describe the 25 already exposed RBI MPC decisions from 9 October 2020 to 8 August 2024. They are retrospective scientific data. Reconstruction or repeated inspection does not make this panel an untouched evaluation.

`label_annotations.json` retains the scientific interpretation fields, committee-resolution excerpts, publication/decision/start dates, source paths and raw-source SHA-256 identities. Its provenance records the SHA-256 of the archival scientific truth from which the interpretation fields were exported. Every retained excerpt was checked against the corresponding primary-source bytes. This is a portable annotation export, not independent second coding. No numerical rate or stance outcome is imported from the legacy parquet.

`label_ledger.json` adds the published repo level before/after each meeting, the rate change derived from consecutive levels, the stance category derived from the committee's published clause, and the six literal rate-ballot cells. Source dates, selected clauses, rate ballots and attributed signed-statement votes are checked during every reconstruction. The complete April/May 2022 clause remains available: the committee remained accommodative while focusing on withdrawal of accommodation; the leading published category is `accommodative`.

`observed_targets.json` exposes chronological `{meeting_date, member_targets:{member_id:bool|null}}` records separately for literal rate No, disagreement with the committee's exact rate quantum, and formal stance dissent. For this original panel, the two rate channels both contain 150 observed targets, including ten positive events. They are separate definitions even though their targets coincide here. A No vote against a quantified resolution establishes disagreement; it does not identify every alternative magnitude. Narrative preferences that ultimately concur with the binding resolution are not relabeled as formal dissent.

Formal stance contains 144 observed targets, fifteen positives and six missing targets. Nineteen meetings have complete stance labels. Jayanth Varma's reservations in August 2022 and April, June, August, October and December 2023 remain `null`. The four reservations in the 2021–February 2022 committee summaries are resolved by an attributed, explicit signed-statement vote against the stance. The October 2020 disagreement over the duration/formulation of forward guidance stays separate from the accommodative stance category. Missingness never means a known negative, affirmative ballot or invented abstention.

`input_manifest.json` freezes the SHA-256 of 122 required scientific files: these annotations/labels/targets, the observation ledgers, 25 original minutes, the prior policy resolution/record, and the retained CPI, GDP/GVA and FOMC raw sources used by those ledgers. A separately retained manifest digest can anchor a copied source root:

```
0c618df1e00a4731c9a312799a65c472d1d5e6815bff4f19a66b2430de4cd757
```

From the project root, one offline command builds the scientific panel and labels into an explicit new destination:

```sh
.venv/bin/python research/verification/rebuild_scientific_inputs.py \
  --source-root . \
  --output-root /absolute/path/to/new-reconstruction \
  --expected-input-manifest-sha256 0c618df1e00a4731c9a312799a65c472d1d5e6815bff4f19a66b2430de4cd757
```

It writes `panel/{snapshots,truth,manifest}.json`, `labels/{label_ledger,observed_targets}.json` and `reconstruction_receipt.json`. The receipt records input hashes, code identity, runtime/dependency details and zero network/model calls. An optional `--reference-panel data/processed/vintage_v3` records byte and semantic comparisons; the reference is not used to construct scientific inputs. The rebuilt snapshots and archival truth are byte identical to `vintage_v3`; the manifest differs in its version and added label-ledger/input-manifest/observability metadata. Archival truth preserves known-positive lists for old-study replay. New observability-aware scoring must use the explicit member targets rather than interpreting a missing formal vote as a negative.

The standalone export command consumes only these annotations and retained primary sources:

```sh
.venv/bin/python research/source_ledgers/historical_labels_round002/export_labels.py \
  --source-root . --output-dir /absolute/path/to/new-label-export
```

Preserve the catalogue and source bytes as one scientific version. A new input version needs its own declared catalogue and outputs. A checksum ties transcriptions to retained bytes; it does not authenticate contemporaneous web availability or prove that no intermediate revision existed. Missing output gap, core/food CPI, IIP, liquidity, FX, oil and monsoon inputs stay missing. Engineering reconstruction is not empirical model replication, forecasting skill, cognitive diversity or causal policy evidence.

For a source-only scientific copy, include `src/`, this whole directory, `research/verification/rebuild_scientific_inputs.py`, `research/source_ledgers/prior_policy/`, all observation ledger/raw files named in `input_manifest.json`, and the 25 `data/raw/minutes_html/` files named there. `data/processed/macro_panel.parquet`, audit results, Git history, model credentials and prior assessments are unnecessary. Tests may additionally include `tests/test_vintage_rebuild.py` and archival `data/processed/vintage_v3/` for the optional equivalence check.
