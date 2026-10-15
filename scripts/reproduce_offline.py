"""Offline scientific reconstruction and anchored saved-evidence verification.

No provider generation is issued. Mock results and deterministic replay cannot
establish independent live replication or empirical readiness. All outputs go
under an explicit new root; a failed step leaves its commands and raw log intact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).absolute().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from src.backtest.study_artifacts import strict_json
from src.reporting.study_report import build_study_report

DEFAULT_EVIDENCE = ROOT/'results/upgrade_validation_round_001/root_oct08_20261008/full_mock_diagnostic_attempt_001'


def scientific_manifest(root):
    # Freeze the actual reconstruction/report dependency graph. Independent new
    # source acquisitions are not inputs to this saved-study reproduction.
    catalog = root/'research/source_ledgers/historical_labels_round002/input_manifest.json'
    paths = [catalog,*(root/name for name in strict_json(catalog)['files'])]
    for module in list(sys.modules.values()):
        path = getattr(module,'__file__',None)
        if path:
            path = Path(path).resolve()
            if path.suffix=='.py' and path.is_relative_to(root) and path.relative_to(root).parts[0] in ('src','scripts','research'):
                paths.append(path)
    for name in ('src/data_pipeline/vintage_panel.py','src/data_pipeline/statement_extractor.py',
                 'src/schemas/macro_schema.py','src/schemas/decision_space.py',
                 'research/source_ledgers/historical_labels_round002/export_labels.py',
                 'research/verification/rebuild_scientific_inputs.py',
                 'research/verification/run_isolated_pytest.py'):
        paths.append(root/name)
    paths += [root/name for name in ('config/config.yaml','requirements.txt','requirements-lock.txt')]
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths)) if p.exists()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--evidence-root',type=Path,default=DEFAULT_EVIDENCE)
    parser.add_argument('--run-tests',action='store_true',help='Also run the full suite in an isolated copied checkout')
    args = parser.parse_args()
    output = args.output_root.absolute()
    output.mkdir(parents=True,exist_ok=False)
    before = scientific_manifest(ROOT)
    (output/'source_manifest_before.json').write_text(json.dumps(before,indent=2))
    record = {'argv':sys.argv,'started_at_unix':time.time(),'python':sys.version,'platform':platform.platform(),
              'scope':'offline source reconstruction and saved-evidence verification; no independent live replication',
              'provider_generation_requested':False,'steps':[]}
    (output/'command.json').write_text(json.dumps(record,indent=2))
    env = os.environ.copy();env.update(PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
    for key in list(env):
        if any(token in key.upper() for token in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN')):
            env.pop(key)
    python = str(ROOT/'.venv/bin/python')
    def run(name,command):
        step = {'name':name,'argv':command,'cwd':str(ROOT),'started_at_unix':time.time()}
        with (output/(name+'_command.json')).open('x') as stream:json.dump(step,stream,indent=2)
        with (output/(name+'.log')).open('x') as stream:
            result = subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        step.update(exit_code=result.returncode,elapsed_seconds=time.time()-step['started_at_unix'])
        record['steps'].append(step)
        if result.returncode:
            raise RuntimeError(f'{name} failed; retained raw log at {output/(name+".log")}')
    try:
        run('rebuild_inputs',[python,'research/verification/rebuild_scientific_inputs.py','--output-root',str(output/'rebuilt_inputs')])
        if args.run_tests:
            run('isolated_tests',[python,'research/verification/run_isolated_pytest.py',str(output/'isolated_tests')])
        evidence = args.evidence_root.absolute()
        anchor_dir = evidence/'anchors'
        require_names = ('full','earlier_rounds','independent','masked')
        anchors = {name:strict_json(anchor_dir/(name+'.json'))['manifest_hash'] for name in require_names}
        studies = {name:evidence/'evidence/mock_fullpath_oct08_001'/name for name in require_names}
        # This verifies historical producer contracts and computes current channel
        # thresholds separately, without altering retained producer artifacts.
        summary = build_study_report(studies,anchors,output/'verified_report')
        record.update(status='passed',verified_generation_counts=summary['generation_evidence_counts'],
                      evidence_scope=summary['evidence_scope'],scientific_readiness=summary['scientific_readiness'])
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__,error=str(exc))
    after = scientific_manifest(ROOT)
    (output/'source_manifest_after.json').write_text(json.dumps(after,indent=2))
    record.update(elapsed_seconds=time.time()-record['started_at_unix'],scientific_source_files_unchanged=before==after)
    if before!=after:
        record.update(status='failed',concurrent_source_changes=[p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)])
    (output/'result.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record,indent=2))
    return 0 if record['status']=='passed' else 1

if __name__=='__main__':
    sys.exit(main())
