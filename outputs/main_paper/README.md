# Original main branch research manuscript

Prepared on 6 October 2026 from commit `7f2436bc4f32d6021b1e885eb49286c850de9139` of `lifemeansfun/RBI_MPC_in_Silico`. The working branch's subsequent upgrades do not supply manuscript results. Authors and a specific journal are intentionally omitted.

**Preservation note, 15 October 2026:** this is the original-main manuscript, not an upgraded empirical manuscript. The current DOCX and provenance include an 8 October wording correction clarifying 3,000 derivative comparisons at 1,000 Taylor parameter settings. The original QA receipt below certifies the pre-correction DOCX retained under `revisions/oct08_before_count_precision/`; it does not certify the current DOCX's page layout. The temporary source/render directories no longer exist. Preserve this historical receipt, and perform a fresh render and page inspection before treating the current document as final. No external submitted file/version is authenticated by this directory.

The pre-correction DOCX was rendered as 18 pages, with approximately 5,784 words of prose and abstract, seven tables, two figures, four rendered equations and 14 linked primary references. The word count excludes tables and references. Equations are MathJax images rather than editable Word equations.

## Historical evidence and checks for the pre-correction revision

- The builder recomputed the principal rate, direction, stance, MAE and dissent metrics directly from the frozen CSV and JSON artifacts and checked them against retained audit values.
- Four source input SHA256 values matched the original audit. The source commit, hashes, recomputed quantities and authoring environment are recorded in `manuscript_provenance.json`.
- A separate read-only fact-check agent verified all eight Table 2 performance rows, all six Table 3 dissent rows, all eight Appendix A meeting records and dissent sets, all 21 Appendix B Taylor coefficients, and the two shocks and six ablations against the frozen artifacts. This is an independent document fact check, not an independent empirical replication.
- `check_manuscript.py` passed document hash, table, image, reference, metadata, heading, border, repeated-header, row-height and pagination checks. Its machine-readable result is `manuscript_qa.json`.
- The pre-correction DOCX was rendered with the documents skill renderer. All 18 page images in `/private/tmp/rbi_main_paper_2026_10_06/qa_delivery` were visually inspected at original resolution. Equations, figures, tables, text, page numbers and the continued Appendix C table were readable without clipping or overlap.

No research simulation, new provider call or prospective evaluation was run during manuscript preparation. Software test counts cited in the paper are attributed to the retained original methodology audit; those suites were not rerun for document preparation. Null results, baseline ties, contamination and provenance limitations remain explicit in the paper.

## Authoring files

- `manuscript_source.json`: manuscript prose, structure and references.
- `build_manuscript.py`: metrics checks, figures, tables and DOCX generation.
- `render_equations.cjs`: MathJax equation generation.
- `check_manuscript.py`: structural checks after rendering; rewrites `manuscript_qa.json` on success.
- `manuscript_provenance.json`: frozen source and final document identities.
- `manuscript_qa.json`: historical pre-correction document check result.

## Commands used

Run from the project root. Temporary dependency and source directories below are local build inputs and may not persist indefinitely. A fresh source archive must use the exact commit above. Python and Node are the Codex bundled runtimes, not the research project's Python environment.

```sh
task_python='/Users/manishharigovind/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
task_node='/Users/manishharigovind/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
task_build='/private/tmp/rbi_main_paper_2026_10_06'
task_renderer='/Users/manishharigovind/.codex/plugins/cache/openai-primary-runtime/documents/26.909.12148/skills/documents/render_docx.py'

NODE_PATH="$task_build/node_assets/node_modules" "$task_node" \
  outputs/main_paper/render_equations.cjs "$task_build/assets"

PYTHONPATH="$task_build/pylibs" "$task_python" \
  outputs/main_paper/build_manuscript.py \
  --source "$task_build/source" --assets "$task_build/assets"

"$task_python" "$task_renderer" \
  outputs/main_paper/RBI_MPC_In_Silico_Research_Manuscript.docx \
  --output_dir "$task_build/qa_delivery" --emit_pdf

"$task_python" outputs/main_paper/check_manuscript.py \
  --render-dir "$task_build/qa_delivery"
```

Visual inspection is required after rebuilding. Structural checks alone do not certify page layout or the empirical validity of the research. The renderer's PDF and page images are internal QA artifacts; the requested deliverable is the DOCX.
