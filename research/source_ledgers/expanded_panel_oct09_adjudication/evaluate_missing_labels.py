"""Retain missing-label diagnostics without inventing observations or predictions."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from src.validation.observed_labels import adjudicated_targets, evaluate_observed_dissent

HERE = Path(__file__).absolute().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    output = args.output_dir.absolute()
    output.mkdir(parents=True,exist_ok=False)
    source = HERE/'adjudicated_labels.json'
    panel = json.loads(source.read_text())
    results = {}
    for channel,strict in [('literal_rate_no',False),('rate_choice_disagreement',False),
                           ('formal_stance_disagreement',False),('formal_stance_disagreement',True)]:
        name = channel+('_strict_sensitivity' if strict else '')
        targets = adjudicated_targets(panel,channel,strict_stance=strict)
        predictions = [{'meeting_date':t['meeting_date'],'predicted_dissenters':[]} for t in targets]
        (output/(name+'_inputs.json')).write_text(json.dumps({'targets':targets,'predictions':predictions},indent=2))
        results[name] = evaluate_observed_dissent(predictions,targets)
    (output/'summary.json').write_text(json.dumps({'baseline':'always no dissent, no fitting',
        'scope':'offline exposed source-label diagnostic, zero model calls', 'channels':results},indent=2))
    module = HERE.parents[2]/'src/validation/observed_labels.py'
    (output/'command.json').write_text(json.dumps({'argv':sys.argv,'time_unix':time.time(),
        'python':sys.version,'platform':platform.platform(),
        'label_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'evaluator_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),
        'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2))
    print(json.dumps({k:{f:v[f] for f in ['observed_targets','unknown_targets','complete_meetings','observed_case','completion_bounds']} for k,v in results.items()},indent=2))

if __name__=='__main__':
    main()
