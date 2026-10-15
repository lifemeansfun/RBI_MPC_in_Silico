"""Revalidate the retained four-condition mock diagnostic and derive tables."""
import hashlib
import json
from pathlib import Path
import sys
import time
from src.backtest.backtest_runner import PROJECT_ROOT
from src.backtest.study_artifacts import strict_json
from src.reporting.study_report import build_study_report

if __name__ == '__main__':
    root = PROJECT_ROOT
    evidence = root/'results/upgrade_validation_round_001/root_oct08_20261008/full_mock_diagnostic_attempt_001'
    conditions = ('full','earlier_rounds','independent','masked')
    studies = {name:evidence/'evidence/mock_fullpath_oct08_001'/name for name in conditions}
    anchors = {name:strict_json(evidence/'anchors'/f'{name}.json')['manifest_hash'] for name in conditions}
    output = Path(sys.argv[1]).absolute()
    receipt = output.parent/(output.name+'_command.json')
    with receipt.open('x') as f:
        json.dump({'argv':sys.argv,'started_at_unix':time.time(),'studies':{k:str(v) for k,v in studies.items()},
                   'anchors':anchors,'reporter_sha256':hashlib.sha256((root/'src/reporting/study_report.py').read_bytes()).hexdigest(),
                   'scope':'saved mock evidence; no generation requested'},f,indent=2)
    result = build_study_report(studies,anchors,output)
    print(json.dumps({key:result[key] for key in ('evidence_scope','n_meetings','n_replicates','generation_evidence_counts','scientific_readiness')},indent=2))
