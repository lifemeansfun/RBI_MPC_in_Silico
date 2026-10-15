"""Freeze an allowlisted scientific input copy for a fresh critical reviewer.

This builder does not establish agent-context or operating-system isolation.
The review dispatcher must separately disable memories/history, inspect inherited
context, audit actual access and preserve unsuccessful dispatches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).absolute().parents[1]
DEFAULT_STUDY = Path('results/upgrade_validation_round_001/root_oct08_20261008/full_mock_diagnostic_attempt_001')
TREE_ALLOWLIST = (
    'src', 'tests', 'config',
    'data/raw', 'data/processed/statements_v2',
    'data/processed/vintage_v2', 'data/processed/vintage_v3',
    'personas/2020_2024_roster', 'personas/calibration_2023-04-30_v2',
    'research/source_ledgers/cpi_vintages',
    'research/source_ledgers/gdp_fed_vintages',
    'research/source_ledgers/prior_policy',
    'research/source_ledgers/historical_labels_round002',
    'research/source_ledgers/expanded_panel_oct08',
    'research/source_ledgers/expanded_panel_oct08_doublecode',
    'research/source_ledgers/expanded_panel_oct09_adjudication',
    'research/source_ledgers/institutions',
    'research/source_ledgers/literature',
    'research/source_ledgers/output_gap_round002',
)
FILE_ALLOWLIST = (
    'requirements.txt', 'requirements-lock.txt', 'pytest.ini', 'Makefile',
    'data/processed/macro_panel.parquet',
    'Kazinnik_paper.pdf', 'kazinnik_extracted.txt',
    'scripts/reproduce_offline.py', 'scripts/create_review_snapshot.py',
    'research/verification/rebuild_scientific_inputs.py',
    'research/verification/run_isolated_pytest.py',
    'research/verification/comparator_controls.md',
    'research/verification/rolling_panel_contract.md',
)
BLOCKED_COMPONENTS = frozenset((
    '.git', '.venv', '.cache', '__pycache__', '.pytest_cache', 'node_modules',
    'implementation_plans', 'peer_reviews', 'memory', 'memories',
    'methodology_audit', 'main_paper', 'manuscript', 'checkout',
    'isolated_test_outputs', 'credentials', 'secrets',
))
BLOCKED_NAMES = frozenset((
    'AGENTS.md', 'CLAUDE.md', 'PERSONA_REVIEW.md', '.DS_Store',
    'REVIEW.md', 'context.txt', 'memory_summary.md', 'MEMORY.md',
    'AI_Project_Elite_Research_Goal.md',
))
EXTENSIONS = frozenset((
    '.py', '.json', '.yaml', '.yml', '.toml', '.ini', '.txt', '.md',
    '.csv', '.parquet', '.html', '.htm', '.pdf', '.xlsx', '.xls',
    '.png', '.svg', '.rst',
))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(path: Path) -> bool:
    if path.is_absolute() or '..' in path.parts:
        return False
    if any(part.lower() in BLOCKED_COMPONENTS for part in path.parts):
        return False
    if any(part.startswith('.') for part in path.parts):
        return False
    if path.name in BLOCKED_NAMES or path.name.startswith('.env'):
        return False
    if any(word in path.name.lower() for word in ('manuscript', 'credential', 'secret', 'api_key',
                                                 'access_token', 'auth_token', 'chat_history')):
        return False
    return path.suffix.lower() in EXTENSIONS or path.name == 'Makefile'


def _regular_source_file(source: Path, path: Path) -> bool:
    """File allowlists must not cross a symlink in an intermediate directory."""
    relative = path.relative_to(source)
    current = source
    for component in relative.parts:
        current = current/component
        if current.is_symlink():
            return False
    return path.is_file()


def _walk_files(source: Path, relative: Path):
    base = source / relative
    if not base.exists():
        return
    if base.is_symlink():
        raise ValueError(f'An allowlisted root is a symlink: {relative}')
    for directory, subdirs, files in os.walk(base, followlinks=False):
        current = Path(directory)
        subdirs[:] = sorted(name for name in subdirs
                            if name.lower() not in BLOCKED_COMPONENTS
                            and not name.startswith('.') and not (current/name).is_symlink())
        for name in sorted(files):
            path = current/name
            rel = path.relative_to(source)
            if safe_relative(rel) and path.is_file() and not path.is_symlink():
                yield rel


def selected_inputs(source: Path, study_root: Path | None = DEFAULT_STUDY) -> list[Path]:
    """Select scientific roots; never recursively walk arbitrary parent results."""
    selected = set()
    for name in TREE_ALLOWLIST:
        selected.update(_walk_files(source, Path(name)))
    for name in FILE_ALLOWLIST:
        path = source/name
        if _regular_source_file(source, path) and safe_relative(Path(name)):
            selected.add(Path(name))
    # Original numerical tables are inputs for the reviewer to assess, with no
    # supplied previous interpretation or report text.
    selected.update(_walk_files(source, Path('results/tables')))
    if study_root is not None:
        rel = Path(study_root)
        if rel.is_absolute():
            try:
                rel = rel.relative_to(source)
            except ValueError as exc:
                raise ValueError('Study inputs must be inside the supplied source') from exc
        if '..' in rel.parts or not rel.parts or rel.parts[0] != 'results':
            raise ValueError('Study inputs must be a relative scientific results bundle')
        if any(part.lower() in BLOCKED_COMPONENTS for part in rel.parts):
            raise ValueError('Forbidden context cannot be supplied as a scientific study')
        # An arbitrary validation/checkouts directory is not a scientific study.
        if not _regular_source_file(source, source/rel/'protocol.json') or not (source/rel/'anchors').is_dir():
            raise ValueError('Scientific study requires protocol.json and an anchors directory')
        for subdir in ('anchors', 'evidence'):
            selected.update(_walk_files(source, rel/subdir))
        for name in ('protocol.json', 'baseline_predictions.json', 'baseline_selection.json'):
            if _regular_source_file(source, source/rel/name):
                selected.add(rel/name)
    return sorted(selected)


def workings(study_root: Path | None, runtime: Path | None) -> str:
    evidence = str(study_root) if study_root is not None else 'No saved study bundle was supplied.'
    runtime_note = (f'The shared runtime is `{runtime}`; use this exact path without resolving its symlink. '
                    'The snapshot `.venv` is a runtime-only link, not a copy of parent project evidence.'
                    if runtime else 'No shared runtime link was supplied.')
    return f'''# Project workings and scientific file map

The project simulates RBI Monetary Policy Committee ballots using dated macroeconomic briefings, member personas, conversational rounds and categorical aggregation. Numerical reaction-function comparators and simulated interventions are separate tracks. Establish evidence types from the actual generation records and assess scientific claims independently.

- Information availability and source-linked inputs: `src/data_pipeline/`, `src/schemas/macro_schema.py`, `data/processed/vintage_v3/`, and `research/source_ledgers/`.
- Standalone historical labels, explicit unknown targets and clean reconstruction: `research/source_ledgers/historical_labels_round002/`, `research/verification/rebuild_scientific_inputs.py`.
- Expanded-source labels and separate annotation pass: `research/source_ledgers/expanded_panel_oct08/`, `expanded_panel_oct08_doublecode/`, `expanded_panel_oct09_adjudication/` under the same ledger directory.
- Persona construction and provenance: `src/persona_engine/`, `src/schemas/persona_schema.py`, `personas/`. Any temporal input packet helpers are source artifacts, not proof of a persona construct.
- Deliberation, comparator forecast controls, ballots and resolutions: `src/behavioral/`, `src/schemas/debate_schema.py`, `src/rule_engine/`.
- Provider settings, evidence, budgets, failure handling and checkpointing: `src/infra/`, `config/config.yaml`.
- Numerical comparators and metrics: `src/rational/`, `src/validation/`, `src/backtest/`.
- Simulator interventions and attribution: `src/scenarios/`, `src/attribution/`.
- Reporting and independent probes: `src/reporting/`, `tests/`.
- Retained scientific study: `{evidence}`. Protocol, anchors, frozen inputs, prompts, responses, predictions and producer summaries are supplied; inspect their identities and evidence scope.
- Original numerical tables: `results/tables/`. These do not receive an authenticity endorsement from inclusion.
- Related-work inputs, when present: `Kazinnik_paper.pdf`, `kazinnik_extracted.txt`, `research/source_ledgers/literature/`.

Offline source reconstruction and anchored replay: `make reproduce OUT=<new-directory>` (no provider generation). Use an unused output location. `make test OUT=<new-directory>` copies the supplied scientific sources and tests and writes all outputs there. For direct pytest, set basetemp inside this supplied snapshot. Retained studies replay under their declared historical producer contracts; current channel endpoints are reported separately. Reconstruction/replay is not independent live-model replication.

This copy excludes parent chat, previous critical reviews, implementation plans, memories, Git history, credentials and manuscript artifacts. Read only the supplied scientific snapshot. Do not seek earlier assessments. {runtime_note} A copied input directory and access instructions do not create operating-system isolation or prove that a new agent has no injected context. Record your inherited-context declaration and commands, failed probes, limitations and independently reached verdict in your new output directory. Paid or live provider generations are outside this review's scope. You may verify primary literature and official sources online.
'''


def create_snapshot(record_dir: Path, source: Path = ROOT, *,
                    snapshot_dir: Path | None = None,
                    study_root: Path | None = DEFAULT_STUDY,
                    share_runtime: bool = True) -> dict:
    source = source.absolute()
    record_dir = record_dir.absolute()
    record_dir.mkdir(parents=True, exist_ok=False)
    started = time.time()
    record = {'version': 2, 'started_at_unix': started,
              'python': sys.version, 'platform': platform.platform(),
              'builder_sha256': digest(Path(__file__)), 'status': 'started'}
    (record_dir/'command.json').write_text(json.dumps(record, indent=2)+'\n')
    target = None
    try:
        paths = selected_inputs(source, study_root)
        before = {str(p): digest(source/p) for p in paths}
        if snapshot_dir is None:
            target = Path(tempfile.mkdtemp(prefix='rbi_scientific_snapshot_'))
        else:
            target = snapshot_dir.absolute()
            target.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for relative in paths:
            destination = target/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/relative, destination)
            hashes[str(relative)] = digest(destination)
        runtime = source/'.venv/bin/python' if share_runtime and (source/'.venv/bin/python').exists() else None
        if runtime:
            (target/'.venv').symlink_to(source/'.venv', target_is_directory=True)
        (target/'WORKINGS.md').write_text(workings(study_root, runtime))
        hashes['WORKINGS.md'] = digest(target/'WORKINGS.md')
        after_paths = selected_inputs(source, study_root)
        after = {str(p): digest(source/p) for p in after_paths}
        if before != after or any(hashes[p] != value for p, value in before.items()):
            raise RuntimeError('Scientific source set changed during snapshot creation; preserve and reject this copy')
        # Keep parent checkout identity outside the blind input directory.
        def git(*args):
            completed = subprocess.run(['git', *args], cwd=source, text=True, capture_output=True)
            return completed.stdout.strip() if completed.returncode == 0 else None
        input_manifest = {'version': 2, 'input_hashes': hashes,
                          'scope': 'Copied scientific inputs; no previous critical verdict is supplied'}
        manifest_bytes = (json.dumps(input_manifest, indent=2, sort_keys=True)+'\n').encode()
        (target/'INPUT_MANIFEST.json').write_bytes(manifest_bytes)
        record.update(status='frozen', source_commit=git('rev-parse','HEAD'),
                      source_branch=git('branch','--show-current'),
                      snapshot=str(target), input_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                      input_hashes=hashes, input_count=len(hashes),
                      source_files_unchanged=True,
                      allowlisted_trees=list(TREE_ALLOWLIST), allowlisted_files=list(FILE_ALLOWLIST),
                      study_root=str(study_root) if study_root else None,
                      shared_runtime=str(runtime) if runtime else None,
                      isolation='Copied inputs only; reviewer context and actual access require separate auditing',
                      excluded=['critical reviews','implementation plans','chat','memory','Git history',
                                'credentials','manuscript','copied validation checkouts','runtime caches'])
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__, error=str(exc),
                      snapshot=str(target) if target else None)
    record['elapsed_seconds'] = time.time()-started
    (record_dir/'snapshot_manifest.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    if record['status'] != 'frozen':
        raise RuntimeError(f'Snapshot rejected; retained failure at {record_dir}')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-dir',type=Path,required=True)
    parser.add_argument('--snapshot-dir',type=Path)
    parser.add_argument('--study-root',type=Path,default=DEFAULT_STUDY)
    args = parser.parse_args()
    result = create_snapshot(args.record_dir, snapshot_dir=args.snapshot_dir, study_root=args.study_root)
    print(json.dumps({k:result[k] for k in ('snapshot','input_count','input_manifest_sha256','status')},indent=2))
