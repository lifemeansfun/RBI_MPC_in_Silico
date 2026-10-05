# CPI context preparation from local MPC minutes

[minutes_cpi_context_preparation.csv](minutes_cpi_context_preparation.csv) maps all 25 local minutes documents to their title-derived decision dates and the latest observed headline CPI period described in their common resolution. It preserves the existing panel date/value alongside the source context. All 25 raw HTML hashes match `data/raw/manifest.csv`; all raw document titles match the manifest titles. Paragraph numbers refer to the document's printed numbering. The HTML line and filename identify the retained local source; the URL identifies the manifest's RBI source.

This is a preparation index, **not a vintage-validated dataset**. The minutes were published after the decision and describe observed inflation retrospectively. Their language distinguishes observations from forecasts, but does not independently prove when the public CPI release became available, whether values were revised, or which figure was available at a specific pre-meeting cutoff. Neither the CPI release timestamps nor archived first-release precision have been verified here. Every row explicitly marks both release-timestamp verification and vintage validation as false. Before building a prediction panel, retrieve the original MoSPI release and its timestamp for each series/month, define the decision's information cutoff, and retain original and revised versions separately.

Two resolution passages give a rounded value for a combined period: July-August 2020 at 6.7% (2020-10-09, paragraph 8), and May-June 2022 at 7.0% (2022-08-05, paragraph 8; paragraph 18 corroborates the combined period). Their standalone latest-month CPI cells are deliberately blank. The latest reference month records the last month in the stated period, without assigning the period's value to that month. April 2024's resolution also groups January-February, but paragraphs 16 and 53 explicitly establish February at 5.1%, so that individual-month cell is populated. Rounded source values retain their reported precision; no extra decimals are inferred. Where a CPI paragraph omits the reference year, the CSV labels the year as inferred from its past-month narrative and the decision-year context.

Decision dates were parsed from each raw title, using the final meeting day and handling ranges and comma/and lists. The title “April 3, 5 and 6, 2023” yields 2023-04-06; “May 2 and 4, 2022” yields 2022-05-04. The original panel uses 2022-05-18 for the latter, which is the minutes' publication date rather than the titled decision date. The September 28-30, 2022 title yields 2022-09-30, although the manifest's coarse `meeting_date` field incorrectly says `2022-10`. These discrepancies are recorded without changing either original input.

Reproduce from the project root using the existing environment:

```sh
.venv/bin/python research/review_process/data_preparation/build_cpi_context_preparation.py
```

The script makes no network calls and writes only its own preparation directory. [preparation_checks.json](preparation_checks.json) records the source/output hashes and verification counts. The mapping is manually adjudicated from the numbered text; the script checks source hashes, titles, paragraph pointers, value/month presence and the explicit February 2024 corroboration. Existing code, raw files and historical macro panel remain unchanged.
