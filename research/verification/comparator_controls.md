# Frozen one-call comparator contracts

This is an engineering contract for two future comparative conditions. It supplies no paid model observations, forecast superiority result, validated persona construct or publication-grade verdict. Existing study manifests and `MeetingCommitteeDecision.control_mode` values are untouched; integration into a newly frozen study remains required.

`src/behavioral/comparator_forecasters.py` implements a single joint forecast of exact committee rate change, stance and all six formal member ballots. `joint_persona` receives the same macro prompt and the union of the six `MemberPersona.build_system_prompt` texts used for initial panel generation. `macro_only` receives that macro prompt and the explicit ordered membership, institutional roles and Governor identity, but rejects supplied persona profiles. Its structural roster information is a declared institutional assumption, not a learned person-specific preference. Neither condition receives generated peer arguments. Historical outcomes in compatibility snapshot fields stay out of both prompts.

The full six-member panel uses 24 calls and its independent control 12; these comparators use one generation request. Token bounds are reservations, actual recorded token counts retain their usage source, and cost from those counts remains an estimate under the recorded price revision. Cache replay is zero new model submissions and retains its original evidence type; deterministic mock JSON is fixture evidence. Conditions are expressly **not budget matched**. A scientific comparison must freeze its resource policy and report both prediction and resource outcomes rather than attribute a difference solely to deliberation.

## Additive interface

```python
roster = ComparatorRoster(
    version="explicit_roster_version", valid_from="YYYY-MM-DD",
    valid_through="YYYY-MM-DD", governor_id="declared_id",
    members=tuple(RosterMember(member_id=..., member_name=..., role=...,
                               is_internal=...) for ...),
    stance_vocabulary_version="simulator_stance_v1",
)
control = ComparatorForecaster(client, condition_logger,
                               source_root=scientific_source_root,
                               corpus_manifest_path=dated_corpus_manifest)
request = control.freeze(
    snapshot, roster, mode="joint_persona", personas=ordered_profiles,
    experiment_id=..., condition_id=..., replicate_id=1,
    model=..., temperature=..., seed=..., max_output_tokens=...,
    model_epoch=..., mask_date=False, mask_identity=False,
    fragmentation_policy="reject",
)
record = await control.generate(request)
```

For `macro_only`, pass an empty persona sequence. The logger must already carry the intended experiment and condition identities. Expanded rosters must be explicitly supplied with bounded dates and version; no original roster is silently reused. Only the current seven rate actions and the three stances in `simulator_stance_v1` are supported. A later stance such as `calibrated_tightening` or an unsupported ontology rejects until a separate versioned schema and scoring contract exist. This vocabulary limitation prevents claiming all expanded meetings are currently runnable.

Freeze writes immutable request bytes and hashes the supplied snapshots, roster, full persona profiles, source evidence files, dated corpus manifests and source statements, generation settings and relevant project code. Before generation it rechecks both retained object references and file hashes. Dated corpus profiles are verified even for a mock probe; live generation requires source-linked macro observations and verified, available persona corpora for `joint_persona`. Counterfactual inputs require a retained parent and exact declared changes. Normal calendar dates, exclusive release cutoffs, finite values and source hashes use the existing schemas and provenance validators.

Identity masking uses the panel's exact ordered mapping `member_i` / `Simulated Member i`. Named persona IDs and names are replaced throughout the supplied initial prompts. Source filenames and corpus IDs do not enter these prompts. Date masking uses the same macro availability-lag treatment and calendar-label replacement as the panel. Neither prompt instructions nor text masks establish absence of latent model contamination or unguessable identity.

## Targets, failure and replay semantics

The structured response predicts committee exact rate/stance and six member ballots in the declared order. `rate_choice_disagreement` means predicted exact member rate differs from the predicted committee rate; `formal_stance_dissent` means the predicted formal stance ballot differs from committee stance. Reservations, argument disagreements, guidance disagreement and literal Yes/No ballot cells are distinct constructs, not these flags. Unknown real labels must still remain unknown during observed-target scoring.

Committee predictions and both dissent flags must agree with the same declared institutional resolver as the panel. Ordinary majority and binary 3:3 Governor casting remain distinct from synthetic fragmentation. Default fragmentation rejects unresolved ballots. Explicit `status_quo` or `legacy_synthetic` policies retain their synthetic resolution fields. This consistency constraint means the control forecasts simulated ballots and an aggregate committee outcome, rather than independently guessing two contradictory targets.

Generation uses the actual `LLMClient.generate_with_metadata`, normalized `request_identity`, canonical request payload and immutable `GenerationResult`/`GenerationMetadata`; this code does not invent a `GenerationRequest` type or a synthetic live receipt. There is one submission attempt, with no automatic repair, model substitution or retry. Budget, uncertain-charge, malformed output, provenance and cancellation failures propagate. Failure events retain the raw generation or the runtime's error context. A consumed plan cannot be resubmitted after failure; a new attempt needs a distinct declared identity and preserved prior evidence.

The original transcript retains nested alias outputs without modifying the runtime evidence schema. The derived comparator record separately normalizes member IDs and validates every normalized ballot against the anchored original generation. `read_comparator_record(path, expected_plan_hash=...)` requires an externally retained frozen-plan hash and checks raw schema, request/prompt/model/settings identity, committee resolution, dissent channels, derived prediction, recorded usage and complete retained transcript bytes. An explicit `transcript_path=...` maps an archived/copied transcript location while still requiring its exact stored hash and generation identity. Hash validation checks internal consistency; it does not authenticate a provider invoice or turn a replay into fresh live evidence.

## Verification scope

Dedicated tests in `tests/test_comparator_forecasters.py` run scripted JSON through the actual offline runtime. They probe both controls, paired masks and raw alias replay, zero additional submission on frozen input/source/settings mutations, invalid roster/date/ontology, wrong exact committee outcomes, channel contradictions, unresolved and synthetic ballots, strict malformed fields, rehashed corruption and terminal budget/cancellation errors. Tests use isolated output destinations. Commands, source hashes, raw logs, environment and any failed attempts are retained under distinct `results/upgrade_validation_round_002/comparator_controls_*` paths.

Scientific work still requires calibration-frozen controls and dated roster/persona selection, aligned same-information new studies, meeting-level paired uncertainty, meaningful positive and negative examples, actual repeated live generation with resource receipts, and a pre-outcome prospective freeze if claiming untouched evaluation. Passing these tests closes only the new control contract's engineering checks.
