# Integration contract proposal

This is a design proposal from read-only implementation inspection. It is not an implemented fix, completed review, or scientific validation. The comprehensive implementation plan will incorporate the independent review's findings when that report is available.

## Generation and evidence

Keep the existing `generate(...) -> (raw_text, parsed)` adapter while adding `generate_with_metadata(...) -> GenerationResult`. An immutable result should carry raw text, parsed output, validation error, request identity and metadata. Metadata should distinguish requested, routed and provider-reported served model; retain response id, seed, full temperature, bounded output limit, schema/parser version and hash, prompt hash, cache key, cache replay status, source request id, attempt count, finish reason and token/cost accounting. Unreported provider fields remain unreported.

Bind each request to experiment, condition, meeting, replicate, member and round. The parser must validate output identity against the requested sender rather than treating a valid JSON object as a valid member response. Research failures must remain failures. A heuristic demo response is a separately labeled condition, never a replacement live-model observation.

Cache canonical JSON containing every generation-affecting setting, schema and parser identity, routed model and model-epoch marker. Preserve full temperature precision. A permitted alternate-model response belongs to that model's own cache key. A replay retains its source metadata and does not count as an independent stochastic observation.

## Budget and interruption

Before each provider submission, reserve a conservative model-specific maximum cost in a durable transactional ledger. Proposed interface: `reserve(attempt_id, provider, routed_model, input_token_bound, max_output_tokens, price_revision)`, `commit(reservation_id, usage)`, and `mark_uncertain(reservation_id, reason)`. Releasing a reservation requires evidence that submission did not occur or the provider confirmed no billable charge. Unknown prices or unbounded generation must fail before submission.

Concurrent processes must share the same ledger and cap. A timeout can leave a request running remotely; retain that reservation and halt the condition rather than automatically making another unaccounted request. Exhaustion, uncertain charge, invalid ledger, cancellation and invalid experiment identity propagate through round, meeting and panel boundaries. Exact billing guarantees require verified prices and defensible token bounds; describe estimates honestly.

## Artifacts, replicas and temporal inputs

Use an immutable experiment identity containing code/config/data/persona/intervention hashes and seed-schedule version. Store artifacts under distinct experiment/run/condition/meeting/replicate paths. Create without clobbering: a conflicting write fails; an identical replay is explicit. Checkpoints require the complete expected identity and artifact digests, not just the date.

Different independent replicates receive different planned seeds. Matched intervention pairs may deliberately share a seed schedule while retaining different condition ids. Provider seeds are requested settings, not a promise of bitwise determinism.

The data contract must distinguish decision, publication and information-cutoff dates. Each observable needs reference period, release/vintage metadata, source bytes and hash. Historical truth is held separately from promptable observables. Persona corpus selection uses statement publication availability at the declared calibration cutoff. Missing evidence remains missing.

## Ownership for parallel implementation

- Runtime implementer: `src/infra/` and new infrastructure tests.
- Deliberation implementer: behavioral protocol, debate schema, voting rule, scenarios/attribution and their new tests.
- Root: temporal data/personas, macro/persona schemas, rational inputs, metrics/backtests, reporting/reproduction, configuration, dependency files, Makefile, existing mixed tests and research protocol/documentation.
- Source collector: new CPI source-ledger artifacts only.

Agree on additive public interfaces before concurrent edits. Preserve existing datasets, profiles, results, checkpoints and transcripts; corrected artifacts use new destinations.

## Discriminating verification

Probe schema/output-limit/temperature cache separation; alternate-model provenance; cross-process reservations at the cap; restart after an unresolved submission; zero provider calls after budget refusal; terminal-error propagation through every round; malformed values and impersonated identities; disconnected deliberation context; condition/replicate artifact collisions; stale checkpoint rejection; and replay labeling. Verify end-to-end behavior as well as individual components. Scientific evaluation needs its own frozen inputs, baselines, outcome joins, uncertainty analysis and negative-result record.
