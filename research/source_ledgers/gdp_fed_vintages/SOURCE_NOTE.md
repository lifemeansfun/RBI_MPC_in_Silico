# Fed target and GDP/GVA release-vintage preparation

This new directory preserves official Federal Reserve, MoSPI and PIB responses for the original 25 RBI MPC meetings, October 2020 through August 2024. It supplies source-linked **Fed target upper bounds** and **constant-2011-12-price quarterly GDP/GVA levels and year-on-year growth**. It does not replace the legacy macro panel or estimate an output gap.

## Available evidence and interfaces

- `meeting_fed_ledger.csv`: 25 rows. The input series is `us_fed_target_upper_pct`, with its numeric `value`, reference period, statement release timestamp, policy effective date, successor effective date, source URLs, local files, hashes and directive excerpt. It is distinct from the legacy `us_fed_funds_rate_pct`, the effective federal funds rate and the target range midpoint.
- `fed_release_vintages.csv` and `fed_ledger.json`: 33 dated policy directives from September 2020 through September 2024, preserving lower/upper target limits and corroborating statements. Every selected directive was released and effective before its meeting cutoff; its successor's effective date falls after meeting start.
- `meeting_gdp_ledger.csv`: 25 rows with `gdp_constant_2011_12_crore`, `gva_constant_2011_12_crore`, `gdp_growth_yoy_pct`, `gva_growth_yoy_pct`, `latest_reference_period`, documented release timestamps and per-series physical-page pointers.
- `meeting_gdp_observations.csv`: 100 long rows, one for each of those four series at each meeting, including table-row transcriptions and complete source provenance.
- `gdp_release_snapshots.csv`, `gdp_gva_release_vintages.csv` and `gdp_ledger.json`: 17 source-table vintages, May 2020 through May 2024; 440 individually source-linked observations. Historical comparison values remain attached to their own release vintage.
- `gdp_table_transcriptions.json`: curated constant-price table rows and the original PDF text rows where available. Image tables and widely spaced PDF text required OCR-assisted visual adjudication. OCR drops signs/decimal marks and merges cells; it is retained as assistance, not automatically accepted as data.
- `output_gap_readiness.csv`: 25 explicit missing-output-gap records. Sparse retained tables initially provide 13 distinct GDP quarters starting FY2017-18Q1. Longer available-vintage prehistory, intermediate revision completeness and a frozen seasonal/trend estimation method remain incomplete. No potential-output or gap value is fabricated.
- `source_catalog.json`, `discovered_source_catalog.json`, `retrieval_manifest.json`, `raw/` and `extracted/`: exact URLs, parent hyperlink provenance, original response bytes, SHA-256, retrieval times and response metadata. All 94 main acquisition responses succeeded. Original successful responses are retained, not downloaded over during reproduction.
- `visual_checks/`, `visual_qa.json`, `render_ocr_log.json` and `*_stdout.log`: 21 table-page renders; representative visual inspection; actual command/exit information, extraction/build/verification evidence, and the preserved initial Fed parser failure.

## Dates, vintages and selection limits

The conservative cutoff comes directly from the CPI meeting ledger: midnight IST at the first meeting day is excluded, so only the preceding day is available. The May 2 and 4, 2022 off-cycle meeting uses May 1 as its cutoff. Its Fed upper bound is therefore **0.50%**, from the [March 16 FOMC decision's implementation note](https://www.federalreserve.gov/newsevents/pressreleases/monetary20220316a1.htm), effective March 17; the May 4 Fed decision is unavailable at that cutoff.

The official [2020 FOMC historical calendar](https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm) and [2021-2024 calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) supply the statement/implementation hyperlinks. Fed release time comes from each statement's printed `For release` time, using America/New_York daylight/standard time. Policy effectiveness is recorded at **calendar-date precision** from the implementation directive; no exact implementation instant is inferred. All selected effective dates are earlier calendar dates than their RBI cutoffs, so that missing time precision does not change the meeting selection.

GDP release timestamps are the printed MoSPI PDF embargo endpoints, **5:30 pm IST** on their stated dates. These are documented release times, not independently measured first website availability. GDP/GVA rows describe estimated output in elapsed quarters; annual advance forecasts in the same releases are excluded. GDP at market prices and GVA at basic prices are separate series; nominal/current-price rows are excluded. Units for levels are rupees crore, not lakh crore.

GDP meeting selection means the latest **retained scheduled quarterly-release document** before the cutoff. Intermediate revisions, corrections and republished source replacements have not been exhaustively ruled out. Contemporary downloaded bytes, their printed dates and dated PIB attachments provide source evidence, but do not independently authenticate the first bytes served on the original release day. This limitation must stay visible when integrating inputs. Different documents' historical comparison columns cannot be pooled as a single unqualified coherent vintage.

The original [August 31, 2020 release](https://mospi.gov.in/sites/default/files/press_release/PRESS_NOTE-Q1_2020-21.pdf) gives FY2020-21Q1 GDP growth **-23.9%** and GVA growth **-22.8%**. The [February 26, 2021 release](https://www.mospi.gov.in/sites/default/files/press_release/PRESS%20NOTE%20SAE%2026-02-2021.pdf) subsequently prints that GDP quarter at **-24.4%**. The ledger retains both as distinct vintages and uses the pre-cutoff original where relevant. Legacy COVID growth or gap values are not archival proof.

The retained [corrigendum endpoint](https://mospi.gov.in/sites/default/files/press_release/CorrigendumPR05032024.pdf) includes `05032024` in its filename, but the document itself is dated **March 1, 2024**. It corrects annual **current-price** GNDI, NNDI and per-capita GNDI rows 25, 26 and 30, rather than the quarterly constant-price GDP/GVA rows used here. Its first website publication time is unknown. The initial catalog guess of March 5 is preserved in metadata-correction evidence; filename dates are not accepted as release-date proof.

## Reproduction and verification

From the repository root:

```sh
.venv/bin/python research/source_ledgers/gdp_fed_vintages/acquire_sources.py
.venv/bin/python research/source_ledgers/gdp_fed_vintages/extract_sources.py
.venv/bin/python research/source_ledgers/gdp_fed_vintages/build_fed_ledger.py
.venv/bin/python research/source_ledgers/gdp_fed_vintages/build_gdp_ledger.py
.venv/bin/python research/source_ledgers/gdp_fed_vintages/verify_artifacts.py
```

Acquisition makes network requests only to official allowed hosts. The remaining commands run offline in the existing Python environment; Poppler and Tesseract render/OCR the retained PDFs. The curated transcription JSON is an explicit source input, with its hash recorded by the builder.

`final_verification.json` records 94 source-body integrity checks, 25 aligned Fed and GDP meeting identities, 176 same-vintage published-growth-versus-level rounding checks (largest difference 0.0499984 percentage points), missing gaps, and preserved legacy-panel hash. Twelve intentional failure controls reject future release dates, future Fed effectiveness, changed hashes, nonfinite/changed values, unsupported series and current-price substitution. These are engineering/transcription/cutoff checks; they do not establish forecasting accuracy, empirical superiority, an output-gap estimate or completeness of the full open-economy benchmark.

`negative_acquisition_and_limitations.json` preserves the inaccessible web-tool Fed-2021 historical request, the successful official-calendar fallback, the rejected current 2025 historical-table candidate, the corrigendum dating correction and the withheld output gap. No paid/model generation, production-data modification, commit or push was performed.
