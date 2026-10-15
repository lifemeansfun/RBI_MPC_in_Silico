import hashlib, importlib.metadata, json, os, platform, shutil, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parents[3]
evidence = Path(__file__).resolve().parent
attempt = evidence / sys.argv[1]
attempt.mkdir(exist_ok=False)
checkout = attempt / 'checkout'
checkout.mkdir()
for name in ('src',):
    shutil.copytree(root / name, checkout / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
(checkout / 'tests').mkdir()
for name in ('test_monte_carlo_resolution.py', 'test_taylor_rule.py'):
    shutil.copy2(root / 'tests' / name, checkout / 'tests' / name)
shutil.copy2(root / 'pytest.ini', checkout / 'pytest.ini')

def hashes(path):
    return {str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in sorted(path.rglob('*')) if file.is_file() and '__pycache__' not in file.parts}
before = hashes(checkout)
(attempt / 'source_manifest_before.json').write_text(json.dumps(before, indent=2) + '\n')
python = str(root / '.venv/bin/python')
command = [python, '-m', 'pytest', '-q', 'tests/test_monte_carlo_resolution.py',
           'tests/test_taylor_rule.py', '--basetemp', str(checkout / 'isolated_test_outputs')]
env = dict(os.environ, PYTHONPATH=str(checkout), PYTHONDONTWRITEBYTECODE='1')
(attempt / 'command.json').write_text(json.dumps({'argv': command, 'cwd': str(checkout),
    'environment_controls': {'PYTHONPATH': str(checkout), 'PYTHONDONTWRITEBYTECODE': '1'},
    'validation_scope': 'synthetic ballots and real Taylor arithmetic, no provider calls'}, indent=2) + '\n')
version_command = [python, '-c', 'import sys,platform,importlib.metadata,json; print(json.dumps({"python":sys.version,"platform":platform.platform(),"packages":{name:importlib.metadata.version(name) for name in ("numpy","pydantic","pytest")}},indent=2))']
version = subprocess.run(version_command, capture_output=True, text=True, check=True)
(attempt / 'environment.json').write_text(version.stdout)
with (attempt / 'pytest.log').open('w') as log:
    proc = subprocess.run(command, cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT)
# Exclude generated outputs; check the original copied inputs exactly.
after = {name: hashlib.sha256((checkout / name).read_bytes()).hexdigest() for name in before}
(attempt / 'source_manifest_after.json').write_text(json.dumps(after, indent=2) + '\n')
result = {'returncode': proc.returncode, 'copied_inputs_unchanged': before == after,
          'original_input_count': len(before), 'provider_calls': 0,
          'source_code_hash': before['src/rational/monte_carlo.py'],
          'dedicated_tests_hash': before['tests/test_monte_carlo_resolution.py']}
(attempt / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
print((attempt / 'pytest.log').read_text())
sys.exit(proc.returncode if before == after else 1)
