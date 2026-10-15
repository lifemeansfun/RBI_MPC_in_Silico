# Consecutive post-reconstitution RBI MPC source expansion

This source preparation retains the **13 consecutive decision meetings, numbers 51–63**, beginning with 7–9 October 2024 and ending with 5–7 October 2026, as observed by **8 October 2026**. It contains 13 decision-day resolutions, 12 published minutes, 78 meeting/member label records, and 72 individual statements from the available minutes. It is a **retrospective, exposed panel**, not prospective evidence, an untouched test, a model experiment, or an independently validated simulation.

Selection used the official fiscal-year monetary policy indexes and consecutive meeting numbering, without reference to model predictions. All available decision meetings in this interval are represented, including four cuts, eight holds, and the October 2026 increase. The 2024–25 fiscal index also supplied three earlier meetings; those six raw resolution/minutes documents are retained as out-of-panel context, not silently added to the 13-meeting panel. The August 2024 resolution corroborates the initial 6.50% repo level.

The official [2025–26 calendar](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=60062) initially scheduled the August meeting for 5–7 August 2025. The subsequent [RBI rescheduling notice](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=60612) moved it to **4–6 August**. The ledger uses the actual dates in the retained minutes and resolution, not the superseded schedule. The [2026–27 calendar](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422) is retained, including the future December 2026 and February 2027 meetings. Those future meetings remain missing and outside this as-of panel.

The [7 October 2026 resolution](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63742) is retained; it explicitly schedules the minutes for **21 October 2026**. The ledger does not fabricate an October individual statement corpus or substitute that resolution for unpublished full minutes. Member rate choices are supported by its explicit unanimous resolution and six-member attendance list; only the two explicitly named minority stance preferences are ascribed to members. Other October stance preferences stay missing.

## Label distinctions

The published rate vote cells, rate magnitudes, formal stance vote evidence, stated stance preferences, prior reservations and guidance qualifications are separate fields. Every excerpt links to retained source bytes and their SHA-256. Names are normalized to stable member identifiers, while the actual changing six-member roster remains meeting-specific.

- The [June 2025 minutes](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=60686) have a three-column rate table. **All six cells say “Yes” to reducing the rate**, but Saugata Bhattacharya chooses **25 bps** while five members choose **50 bps**. The ledger preserves his published Yes and his distinct magnitude disagreement. It does not rewrite his source vote as No or infer unanimity on the magnitude from the Yes column.
- The [April 2025 minutes](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=60279), paragraph 28, describe Bhattacharya's prior reservations, then his concurrence with the accommodative stance and his qualification about predetermined easing guidance. This is a positive reservation/guidance annotation and **not a final stance disagreement**.
- The September/October and December 2025, February 2026, and October 2026 documents preserve stated accommodative/neutral preferences distinct from committee stance. A phrase such as “of the view,” “support,” or “propose” is not automatically rewritten as an individually recorded formal stance vote. Only explicit ascribed stance-voting evidence is marked as a confirmed formal ballot: **20 confirmed neutral vote records and 58 unknown formal records** under this conservative rule. Unknown does not mean agreement or disagreement. Stance preferences are retained separately, with source excerpts.
- Reservation and guidance flags are positive annotations for the clear April case. **Other members/meetings are unassessed, not coded negative.** Candidate excerpts containing “reservation” or “guidance” are provided for subsequent coding. Lexical retrieval is not exhaustive interpretation. The complete 72 available individual statements are retained for further adjudication.

This is one source collector's transparent extraction. Independent double coding, resolution of every guidance/reservation construct, and external inter-coder validation have not been performed. The label ledger is useful new scientific input, but these remaining checks should precede confirmatory empirical claims.

## Availability and information firewalls

Meeting start, decision, resolution publication, and minutes publication dates are separate. A conservative model-information cutoff excludes midnight IST on the first meeting day; only earlier days qualify. The same meeting's resolution, minutes, formal ballots and statements occur after that cutoff and belong to outcome/evaluation evidence. **They must not be inserted into same-meeting model inputs or personas.** The source collection does not implement an information firewall, construct expanded macro data, or make these meetings ready for a live forecast study.

Official HTML documents report calendar publication dates. Exact first-posting times remain unknown, so no midnight posting timestamp is invented. All 12 observed minutes dates match the corresponding documented fourteen-day schedule; this source consistency check does not establish every statutory operational detail. Currently served bytes are preserved with hashes. No independently archived contemporaneous byte hash proves that an endpoint was unchanged since initial publication. Current footer/site dates do not establish source vintage.

## Artifacts and reproduction

- `source_catalog.json`: 34 official documents, dates, source kind, retained HTML path, SHA-256, extracted text, and published rate table cells. This includes the 25 in-panel documents, six pre-panel context documents, two calendars and one rescheduling notice.
- `raw/` and `extracted/`: exact acquired HTML and whitespace-normalized article bodies. Raw bytes are authoritative; normalized extraction is used for substring checks.
- `meeting_label_ledger.json`, `meeting_ledger.csv`, `member_ballot_ledger.csv`: meeting and member schema, choices, separate labels, evidence and ambiguity notes.
- `member_statements.jsonl`: 72 full available statements, publication provenance and a same-meeting input prohibition.
- `availability_ledger.json`: observed resolution/minutes statuses and explicitly missing future meetings.
- `acquisition_log.json`, `acquisition_stdout.log`, `build_stdout.log`, `verification_stdout.log`, `source_qa.json`: actual execution evidence, environment, hashes, checks and gaps.
- `build_failed_001.log`: preserved first offline build failure. The check exposed that the April 2025 Governor states policy should be accommodative without using the literal word “stance” in that paragraph. The retrieval aid was widened to include named stance terms; the curated substantive label was not tuned to model performance.
- `discovery_log.json`: preserved exploratory request/tool failures before the bounded acquisition script. No failed discovery was silently treated as evidence of non-existence.

Commands run from the repository root using its existing Python environment:

```sh
.venv/bin/python research/source_ledgers/expanded_panel_oct08/acquire_sources.py > research/source_ledgers/expanded_panel_oct08/acquisition_stdout.log 2>&1
.venv/bin/python research/source_ledgers/expanded_panel_oct08/build_ledger.py > research/source_ledgers/expanded_panel_oct08/build_stdout.log 2>&1
.venv/bin/python research/source_ledgers/expanded_panel_oct08/verify_artifacts.py > research/source_ledgers/expanded_panel_oct08/verification_stdout.log 2>&1
```

Acquisition performs a maximum of two attempts per request with a 30-second timeout. It uses official RBI GET endpoints and official form POST navigation for fiscal-year indexes. The bounded acquisition run retained all 34 sources without a failed request; exploratory failures are recorded separately. Offline building and verification make no network/model calls. The scripts write only beneath this directory. No production pipeline, model configuration, legacy corpus, existing labels or existing experiment result was edited.

This batch has the identity `expanded_panel_oct08` and as-of date 2026-10-08. Preserve it. A later acquisition must use a distinct directory/batch identity and should not overwrite these source/label records. Re-running network acquisition later can encounter changed bytes or later documents; it does not reproduce historical first availability. The offline commands are the relevant reproducibility path for this retained evidence.
