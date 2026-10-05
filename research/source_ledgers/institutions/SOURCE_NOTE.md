# MPC institutional source

The [Department of Financial Services copy of the RBI Act](https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/The-Reserve-Bank-of-India-Act--1934.pdf) was acquired on 5 October 2026. Original bytes, SHA-256, retrieval time and the failed India Code acquisition are retained in `source_record.json`. The downloaded PDF's pages 89 and 90 were extracted and visually inspected; the relevant provisions and subsection labels are legible and correspond to the extracted text. Page 5 is a contents-page match rather than the operative provisions.

Section 45ZI(5) sets a four-member quorum with the Governor or, in his absence, the Deputy Governor member. Subsection (6) identifies who presides. Subsections (7)-(8) specify one vote per member, decision by majority of members present and voting, and the Governor's second/casting vote in equality. Subsections (10)-(11) require recorded member votes and explanatory statements. Section 45ZL governs minutes publication on the fourteenth day after a meeting.

These provisions support the majority/casting components of a model. They do not, by themselves, prescribe exactly six present members at every simulated meeting, a governor-weighted median for fragmented categorical ballots, or visibility of colleagues' final ballots before the Governor votes. Such choices need to be identified and tested as simulation assumptions, with unresolved cases handled explicitly.

The source's page 90 itself prints a cross-reference to subsection (11) of section 45ZL. It is preserved verbatim in the extracted source; no correction or authoritative interpretation of that cross-reference is asserted here. This is research source verification, not a legal opinion or a claim that every implementing regulation has been reviewed.

Reproduce acquisition in a new directory/version using `fetch_rbi_act.py`; the script refuses to replace an existing successful source record. It uses the project environment's `requests` and `pdfplumber`. The source PDF is retained exactly as fetched.
