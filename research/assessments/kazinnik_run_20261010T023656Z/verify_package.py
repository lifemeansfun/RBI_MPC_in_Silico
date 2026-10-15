"""Verify this bounded assessment's retained artifacts; no model/research execution."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest = json.loads((HERE / 'DELIVERY_MANIFEST.json').read_text())
    errors = []
    required = ['FINAL_ASSESSMENT.md', 'REVIEW_ADJUDICATION.md',
                'criterion_evidence_table.json', 'FROZEN_QUESTION_AND_ANALYSIS.json',
                'PAPER_TO_PROJECT_MATRIX.md', 'SOURCE_VERSION_RECORD.md',
                'run_ledger.json', 'REPRODUCTION.md', 'frozen_archive_receipt.json',
                'FROZEN_SCIENTIFIC_INPUT.zip']
    for name in required:
        if name not in manifest['files_sha256']:
            errors.append('Required completed-phase artifact absent from manifest: ' + name)
    for name, expected in manifest['files_sha256'].items():
        path = HERE / name
        if not path.is_file() or digest(path) != expected:
            errors.append('Delivery artifact missing/changed: ' + name)
    initial = json.loads((HERE / 'initial_scientific_sha256.json').read_text())
    for name, expected in initial.items():
        path = ROOT / name
        if not path.is_file() or digest(path) != expected:
            errors.append('Preserved scientific file changed: ' + name)
    env = json.loads((HERE / 'raw/activation_environment.json').read_text())
    for args, expected in ((['git', 'branch', '--show-current'], 'project_upgrade_codex'),
                           (['git', 'rev-parse', 'HEAD'], env['head']),
                           (['git', 'rev-parse', 'main'], env['main'])):
        actual = subprocess.check_output(args, cwd=ROOT, text=True).strip()
        if actual != expected:
            errors.append('Preserved branch/commit differs: ' + ' '.join(args))
    ledger = json.loads((HERE / 'run_ledger.json').read_text())
    counts, bounds = ledger['counters'], ledger['bounds']
    if counts['repair_cycles'] > bounds['repair_cycles']:
        errors.append('Repair cycle allowance exceeded')
    if counts['scientific_reviewer_dispatches'] > bounds['scientific_reviewer_dispatches']:
        errors.append('Scientific review allowance exceeded')
    if counts['provider_generation_calls'] != 0 or counts['provider_cost_usd'] != 0:
        errors.append('This incomplete-run delivery must not invent live generations/spending')
    protocol = json.loads((HERE / 'FROZEN_QUESTION_AND_ANALYSIS.json').read_text())
    if 'INCOMPLETE' not in protocol['status']:
        errors.append('Incomplete executable protocol was mislabeled')
    source = HERE / 'sources/FOMC_In_Silico_2025-08-31.pdf'
    if digest(source) != 'bb87d87e450d7a73206ab8845afc21d595dd6a3965c4a23b647f53f28ca70914':
        errors.append('Inspected August source identity changed')
    archive = json.loads((HERE / 'frozen_archive_receipt.json').read_text())
    if digest(HERE/'FROZEN_SCIENTIFIC_INPUT.zip') != archive['sha256']:
        errors.append('Scientific archive identity changed')
    criteria = json.loads((HERE/'criterion_evidence_table.json').read_text())
    if criteria['terminal_status'] != 2 or criteria['primary_empirical_effect'] is not None:
        errors.append('Unrun primary result/status mislabeled')
    report = {'artifact_integrity': 'PASS' if not errors else 'FAIL',
              'scope': 'Delivery hashes, preserved files/branches, accounting and evidence labels only. No scientific readiness claim.',
              'delivery_files': len(manifest['files_sha256']),
              'preserved_scientific_files': len(initial), 'errors': errors}
    print(json.dumps(report, indent=2))
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
