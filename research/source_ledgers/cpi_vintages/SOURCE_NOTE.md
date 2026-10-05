# CPI release ledger: source acquisition preparation

This directory preserves authoritative MoSPI and PIB release documents for the 25 MPC meetings in the local minutes corpus, October 2020 through August 2024. It records All India **Combined CPI (General)** and **Combined Consumer Food Price Index (CFPI)** year-on-year inflation, base 2012=100. CFPI is the published food index series; this work does not construct core inflation or replace the legacy macro panel.

## Cutoff and source selection

Meeting start and decision dates come from the retained minutes titles, including comma/“and” lists. The conservative information cutoff includes only releases strictly before midnight IST at the first meeting day: the entire preceding calendar day is available. The off-cycle title “May 2 and 4, 2022” therefore uses a May 1 cutoff and a May 4 decision date. The title for September 28–30, 2022 gives a September 30 decision date.

For every meeting, the selected original monthly release predates that cutoff and its explicitly stated next scheduled release date falls on or after meeting start. The reference month also agrees with the latest month discussed in the minutes preparation table. This establishes the latest **scheduled monthly release represented by the acquired evidence**. An exhaustive search for unexpected intermediate corrections or re-releases has not been completed.

PDF times come from the printed embargo endpoint (5:30 pm); PIB HTML times come from “Posted On”. These are recorded as India local time, with the evidence and UTC conversion retained in the JSON. They are documented release times, not independently measured first website availability. Minutes publication occurs later and is used to corroborate meeting titles/context, not to establish contemporaneous data availability.

## Retained evidence

- `meeting_cpi_ledger.csv`: 25 meeting rows, conservative cutoff, current provisional CPI/CFPI, release time/basis, next scheduled release, source URL, local path and SHA-256.
- `release_vintages.csv`: 50 source-table rows, comprising each selected current provisional month and its previous final month. This is a sparse ledger of these source tables, not a complete monthly vintage database.
- `cpi_release_ledger.json`: source records, excerpts, full CPI/CFPI summary rows, meeting provenance, checks and limitations.
- `source_catalog.json` and `retrieval_manifest.json`: exact URLs found through web search/open, acquisition status, retrieval time, response metadata and hashes.
- `raw/`: 26 successfully retained original documents (21 PDFs and 5 HTML pages), their metadata, and the failed April 2023 PDF endpoint response.
- `extracted/`: offline source text and structured tables, with original source paths and hashes.
- `visual_checks/`: 21 first-page renders and five table contact sheets inspected for current/final labels, column order and numeric transcription. The originals remain unchanged.
- `ledger_checks.json`, `final_verification.json` and `*_stdout.log`: actual build, acquisition, extraction, rendering and integrity checks.

The [MoSPI April 2023 dashboard URL](https://mospi.gov.in/dashboard/assets/pdf_data/PR%20April%202023.pdf) returned HTML rather than PDF. The failed bytes and hash are preserved; the dated [PIB release of May 12, 2023](https://www.pib.gov.in/PressReleasePage.aspx?PRID=1923709&lang=2&reg=48) supplies the April 2023 table. No required reference month is missing. The February 2024 PIB HTML release is additionally corroborated by its retained PDF attachment.

The provisional/final distinction changes actual inputs. The original [December 2021 release](https://mospi.gov.in/sites/default/files/press_release/CPI%20Press%20Release%20December%2020211641988826767.pdf) reports provisional CPI **5.59%**; a later [December 2022 release](https://www.mospi.gov.in/sites/default/files/press_release/CPI_PR_December_2022.pdf) displays December 2021 at **5.66%** in its retrospective comparison. The [June 2023 original release](https://www.mospi.gov.in/sites/default/files/press_release/CPI_PR_12july23.pdf) gives CPI **4.81%** and CFPI **4.49%**, while the later [June 2024 comparison](https://mospi.gov.in/sites/default/files/press_release/CPI_PR_12july24.pdf) shows **4.87%** and **4.55%** for June 2023. The meeting ledger retains the original provisional values rather than substituting those later comparisons.

## Reproduction

From the repository root, using the existing environment:

```sh
.venv/bin/python research/source_ledgers/cpi_vintages/acquire_sources.py
.venv/bin/python research/source_ledgers/cpi_vintages/extract_sources.py
.venv/bin/python research/source_ledgers/cpi_vintages/build_ledger.py
.venv/bin/python research/source_ledgers/cpi_vintages/render_source_checks.py
.venv/bin/python research/source_ledgers/cpi_vintages/verify_artifacts.py
```

Acquisition uses only catalog URLs and preserves already retained successful bytes when their saved hashes match. Extraction, ledger building and integrity checks run offline. Rendering uses the installed `pdftoppm`; extraction uses `pdfplumber`, HTML extraction uses BeautifulSoup, and contact sheets use Pillow. Commands and environment versions are recorded in the scripts/logs/check outputs. Scripts write only inside this directory; they read the minutes preparation table, raw minutes and legacy panel for provenance and preservation checks.

## Remaining limits

The files were retrieved from currently hosted release endpoints on October 5, 2026. SHA-256 proves which bytes were used in this preparation; no independently archived contemporaneous hashes establish that those bytes were unchanged since initial publication. Printed release schedules and PIB posting records support the timing, but actual first availability and all unscheduled correction notices have not been independently audited. COVID-era release footnotes remain in the source documents and require attention in later measurement decisions. This ledger covers CPI and CFPI only. Core CPI, other macro series, labels, personas, information firewalls and evaluation validity remain unvalidated by this work. No existing input data or production code was changed.
