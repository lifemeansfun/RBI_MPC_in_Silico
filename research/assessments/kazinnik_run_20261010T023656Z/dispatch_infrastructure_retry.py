"""Dispatch one bounded critique of an immutable isolated scientific snapshot."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
REVIEW = HERE / 'review_attempt_002'

def main():
    receipt = json.loads((REVIEW/'freeze_receipt.json').read_text())
    locations = json.loads((REVIEW/'output_location.json').read_text())
    source, output = Path(receipt['snapshot']), Path(locations['output'])
    output.mkdir(exist_ok=True)
    prompt = f'''Evaluate the supplied RBI MPC scientific implementation and proposed contribution critically. You are reviewing one immutable version, not advising a repair loop. Read only the supplied snapshot at {source}. Write all your output under {output}; input files are read-only. Paid generations and scientific repair are prohibited. This contract is neutral: positive, negative and incomplete conclusions are all valid.

Read WORKINGS.md for the scientific file map and current_protocol/FROZEN_QUESTION_AND_ANALYSIS.json for the locked question and its actual executable status. Read current_protocol/acceptance_criteria.json for criteria A-G. The acquired August full text and source acquisition/version evidence are in current_protocol/sources. Current implementation, source-linked inputs and saved raw diagnostic generations are supplied. Determine actual evidence types from the raw receipts, not from names or summaries.

First write context_declaration.json stating whether you have any parent chat, earlier reviews, scientific plans, memory-derived project findings or Git history in your initial context. Describe any unexpected injected project-specific information without reproducing hidden system instructions. If contaminated, stop, preserve the attempt and label it non-independent. This fresh ephemeral process disables memory/user configuration/project documents/plugins; OS policy blocks parent evidence, memory and sessions, and disallows writes to the input and parent tree. Record access restrictions and limitations actually observed. Do not attempt to bypass them or retrieve earlier assessments. Shared host, model family and the Python runtime remain limitations. The parent cannot inspect hidden provider-side prompt construction fully, so do not certify complete hidden-context auditability.

Use at most 20 minutes for scientific inspection and 5 minutes for writing. Maximum 20 file groups, four web-tool calls, two offline verification/recomputation commands and zero live/provider generations, retries, edits or model substitutions. Preserve commands, stdout/stderr, failures and environment. No full pytest suite: reuse the raw workings and perform only decisive central/source checks. If time limits or infrastructure prevent completion, state missing checks. Only this one final scientific critique is requested.

Independently check source availability/version and selected original-method anchors. Recompute a central quantitative fact from raw scientific evidence where feasible: source-cohort/ballot counts, raw mock predictions/consensus or reference equations. A missing live study has no empirical treatment effect to recompute; do not invent one. Evaluate whether the selected matched-prefix Governor-ballot visibility question identifies its conditional simulator-local estimand and whether it adds a consequential contribution relative to VERIFIED prior methods. Inspect missing history/roster/label handling, planned resources, uncertainty, failure rules, integration/provenance and claim scope.

Write REVIEW.md and evidence_judgments.json with evidence-linked PASS/FAIL/UNVERIFIED for each A-G criterion. Separate critical from optional findings; report central recomputation results, negative evidence, review limits, adaptation/contribution/publication-readiness separately, and exact smallest missing actions. A bounded incomplete package is an acceptable assessment deliverable but is not evidence that the research contribution was achieved. AI criticism is not journal certification. Provide no favorable-verdict completion condition and do not request subsequent repairs or repeated review.
'''
    (REVIEW/'review_prompt.txt').write_text(prompt)
    argv = ['/usr/bin/sandbox-exec', '-f', locations['profile'], '/opt/homebrew/bin/codex',
            '--no-daemon', '--search', '-c', 'memories.use_memories=false',
            '-c', 'memories.generate_memories=false', '-c', 'features.memories=false',
            '-c', 'project_doc_max_bytes=0', '-c', 'developer_instructions=""',
            '-c', 'features.apps=false', '-c', 'features.plugins=false',
            '-c', 'features.hooks=false', '-c', 'features.unbounded_connection_retries=false',
            '-c', 'shell_environment_policy.inherit="core"', '-a', 'never', 'exec',
            '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
            '-s', 'danger-full-access', '--add-dir', str(output), '--json',
            '--output-last-message', str(output/'final_message.md'), '-']
    ledger_path = HERE/'run_ledger.json'
    ledger = json.loads(ledger_path.read_text())
    if ledger['counters']['scientific_reviewer_dispatches'] != 1:
        raise RuntimeError('This infrastructure retry requires exactly one prior dispatch')
    started = time.time()
    command = {'argv': argv, 'cwd': str(source), 'started_unix': started,
               'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
               'snapshot_manifest_sha256': receipt['source_manifest_sha256'],
               'timeout_seconds': 1800, 'models_overridden': False,
               'paid_research_generation_calls_authorized': 0,
               'hidden_provider_context_completely_inspectable': False}
    (REVIEW/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    ledger['counters']['scientific_reviewer_dispatches'] += 1
    ledger['events'].append({'type':'final_scientific_reviewer_dispatch',
                             'attempt':2, 'started_utc': command['started_utc'],
                             'snapshot_manifest_sha256': receipt['source_manifest_sha256']})
    ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for key in list(env):
        if any(word in key.upper() for word in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN')):
            env.pop(key)
    timed_out = False
    with (REVIEW/'events.jsonl').open('w') as stdout, (REVIEW/'stderr.log').open('w') as stderr:
        process = subprocess.Popen(argv, cwd=source, env=env, stdin=subprocess.PIPE,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.communicate(prompt.encode(), timeout=1800)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    command.update(exit_code=process.returncode, timed_out=timed_out,
                   elapsed_seconds=time.time()-started,
                   ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    (REVIEW/'result.json').write_text(json.dumps(command, indent=2)+'\n')
    if output.exists():
        shutil.copytree(output, REVIEW/'output', dirs_exist_ok=True)
    manifest = json.loads((source/'FROZEN_MANIFEST.json').read_text())
    changed = [name for name, value in manifest.items()
               if not (source/name).is_file() or hashlib.sha256((source/name).read_bytes()).hexdigest()!=value]
    audit = {'frozen_inputs_changed': changed,
             'copied_output_files': len(list((REVIEW/'output').rglob('*'))) if (REVIEW/'output').exists() else 0,
             'review_completed': (REVIEW/'output/REVIEW.md').is_file(),
             'context_declaration_present': (REVIEW/'output/context_declaration.json').is_file(),
             'hidden_context_limit': 'Configured memory/context disabled and empirical OS access checks; full hidden prompt not independently inspectable.'}
    (REVIEW/'completion_integrity.json').write_text(json.dumps(audit, indent=2)+'\n')
    print(json.dumps({'result':command, 'integrity':audit}, indent=2))
    return process.returncode or (2 if timed_out or changed else 0)

if __name__ == '__main__':
    raise SystemExit(main())
