"""Copy scientific/test inputs and retain an auditable offline pytest execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).absolute().parents[2]
INPUTS = ('src', 'tests', 'config', 'data', 'personas', 'research/source_ledgers', 'research/verification', 'templates')
FILES = ('requirements.txt', 'requirements-lock.txt', 'pytest.ini', 'scripts/create_review_snapshot.py')

def manifest(root):
    paths = [p for name in INPUTS for p in (root/name).rglob('*') if p.is_file()]
    paths += [root/name for name in FILES if (root/name).exists()]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if '__pycache__' not in p.parts and p.suffix != '.pyc'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    destination = args.destination.absolute()
    destination.mkdir(parents=True, exist_ok=False)
    checkout = destination/'checkout'
    checkout.mkdir()
    for name in INPUTS:
        if (ROOT/name).exists():
            shutil.copytree(ROOT/name, checkout/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in FILES:
        if (ROOT/name).exists():
            (checkout/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, checkout/name)
    before = manifest(checkout)
    (destination/'source_manifest_before.json').write_text(json.dumps(before, indent=2))
    command = [str(ROOT/'.venv/bin/python'), '-m', 'pytest', '-q', *(args.tests or ['tests']),
               '--basetemp', str(checkout/'isolated_test_outputs')]
    record = {'argv':command, 'cwd':str(checkout), 'started_at_unix':time.time(),
              'python':sys.version, 'platform':platform.platform(),
              'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (destination/'command.json').write_text(json.dumps(record, indent=2))
    env = os.environ.copy()
    env.update(PYTHONPATH=str(checkout), PYTHONDONTWRITEBYTECODE='1')
    # Tests construct explicit mock clients; avoid passing provider credentials.
    for key in list(env):
        if any(token in key.upper() for token in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN')):
            env.pop(key)
    with (destination/'pytest.log').open('w') as log:
        result = subprocess.run(command, cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT)
    after = manifest(checkout)
    (destination/'source_manifest_after.json').write_text(json.dumps(after, indent=2))
    record.update(exit_code=result.returncode, elapsed_seconds=time.time()-record['started_at_unix'],
                  frozen_files_unchanged=before==after)
    (destination/'result.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))
    print((destination/'pytest.log').read_text()[-7000:])
    return result.returncode if before==after else 2

if __name__ == '__main__':
    sys.exit(main())
