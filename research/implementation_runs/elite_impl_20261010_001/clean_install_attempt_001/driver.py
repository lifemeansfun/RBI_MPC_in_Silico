"""One bounded isolated install and zero-generation portable verification."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
INTEGRATION = OUT.parent / "source_integration_attempt_001"
PORTABLE = INTEGRATION / "portable_bundle"
CODE = PORTABLE / "code"
LIMIT_BYTES = 2 * 1024 ** 3
LIMIT_SECONDS = 1200
START = time.monotonic()
ENV = os.environ.copy()
for key in list(ENV):
    if any(token in key.upper() for token in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN", "CREDENTIAL")):
        ENV.pop(key)
ENV.update(PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
           TMPDIR=str(OUT / "temporary"), PIP_CACHE_DIR=str(OUT / "pip_cache"))
ENV.pop("PYTHONPATH", None)
(OUT / "temporary").mkdir()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(path):
    return {str(p.relative_to(path)): sha(p) for p in path.rglob("*")
            if p.is_file() and not p.is_symlink()}


def used_bytes():
    return sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file() and not p.is_symlink())


record = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "driver_sha256": sha(__file__), "driver_python": sys.version,
    "platform": platform.platform(), "max_new_directory_bytes": LIMIT_BYTES,
    "max_total_installation_and_checks_seconds": LIMIT_SECONDS,
    "installation_attempt_limit": 1, "pip_retry_limit": 0,
    "provider_calls": 0, "provider_spend_usd": 0,
    "credential_environment_removed": True, "dotenv_disabled": True,
    "lock_sha256": sha(ROOT / "requirements-lock.txt"),
    "portable_lock_sha256": sha(CODE / "requirements-lock.txt"),
    "portable_protocol_sha256": sha(PORTABLE / "protocol.json"),
    "commands": [], "clean_install_passed": False,
    "versions_reconciled": False, "fresh_portable_checks_passed": False,
    "status": "prepared", "maximum_observed_new_directory_bytes": 0,
}


def save():
    record["elapsed_seconds"] = time.monotonic() - START
    (OUT / "run_control.json").write_text(json.dumps(record, indent=2) + "\n")


def stop(process):
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def run(label, argv, *, cwd=ROOT, env=None):
    if time.monotonic() - START >= LIMIT_SECONDS:
        record["status"] = "total_runtime_limit_reached"
        save()
        return False
    command = {"label": label, "argv": [str(x) for x in argv], "cwd": str(cwd),
               "started_at": datetime.now(timezone.utc).isoformat(), "log": label + ".log"}
    record["commands"].append(command)
    save()
    start = time.monotonic()
    with (OUT / command["log"]).open("x") as log:
        process = subprocess.Popen(command["argv"], cwd=cwd, env=env or ENV,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            try:
                code = process.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                size = used_bytes()
                record["maximum_observed_new_directory_bytes"] = max(record["maximum_observed_new_directory_bytes"], size)
                if time.monotonic() - START >= LIMIT_SECONDS or size >= LIMIT_BYTES:
                    command["termination_reason"] = "runtime_limit" if time.monotonic() - START >= LIMIT_SECONDS else "disk_limit"
                    stop(process)
                    code = process.returncode
                    record["status"] = "stopped_at_declared_limit"
                    break
    size = used_bytes()
    record["maximum_observed_new_directory_bytes"] = max(record["maximum_observed_new_directory_bytes"], size)
    command.update(exit_code=code, elapsed_seconds=time.monotonic() - start,
                   log_sha256=sha(OUT / command["log"]))
    if size >= LIMIT_BYTES:
        command["termination_reason"] = "disk_limit"
        record["status"] = "stopped_at_declared_limit"
    save()
    return code == 0 and "termination_reason" not in command


def finish(status):
    record["status"] = status
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["new_directory_bytes"] = used_bytes()
    record["lock_unchanged"] = record["lock_sha256"] == sha(ROOT / "requirements-lock.txt")
    record["portable_code_and_inputs_unchanged"] = before == inventory(PORTABLE)
    (OUT / "portable_manifest_after.json").write_text(json.dumps(inventory(PORTABLE), indent=2) + "\n")
    save()
    print(json.dumps(record, indent=2))


before = inventory(PORTABLE)
(OUT / "portable_manifest_before.json").write_text(json.dumps(before, indent=2) + "\n")
save()
if record["lock_sha256"] != record["portable_lock_sha256"]:
    finish("lock_identity_mismatch")
    sys.exit(1)

venv = OUT / "freshenv"
if not run("001_create_venv", [sys.executable, "-m", "venv", str(venv)]):
    finish("venv_creation_failed")
    sys.exit(1)
fresh = venv / "bin/python"
install = [fresh, "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
           "--no-cache-dir", "--retries", "0", "--timeout", "30", "-r", ROOT / "requirements-lock.txt"]
record["installation_attempts"] = 1
if not run("002_install_locked_requirements", install):
    # Retain the unresolved installation and stop; never replace pins or retry.
    finish("installation_failed_or_declared_limit_reached")
    sys.exit(1)

metadata_code = """from importlib.metadata import version,PackageNotFoundError
import json,sys,platform
from pathlib import Path
lock=Path(sys.argv[1]); packages={}; mismatches=[]
for line in lock.read_text().splitlines():
    if '==' not in line or line.startswith('#'):continue
    name,expected=line.split('==',1)
    try:actual=version(name)
    except PackageNotFoundError:actual=None
    packages[name]=actual
    if actual!=expected:mismatches.append({'package':name,'locked':expected,'installed':actual})
result={'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'installed_locked_packages':packages,'lock_mismatches':mismatches}
Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\\n')
print(json.dumps(result,indent=2))
raise SystemExit(1 if mismatches else 0)
"""
if not run("003_reconcile_versions", [fresh, "-c", metadata_code,
                                        ROOT / "requirements-lock.txt", OUT / "fresh_environment.json"]):
    finish("installed_version_reconciliation_failed")
    sys.exit(1)
record["versions_reconciled"] = True
if not run("004_pip_check", [fresh, "-m", "pip", "--isolated", "--disable-pip-version-check", "check"]):
    finish("installed_dependency_check_failed")
    sys.exit(1)

portable_env = dict(ENV, PYTHONPATH=str(CODE))
protocol = PORTABLE / "protocol.json"
if not run("005_fresh_portable_validation", [fresh, "-m", "src.backtest.run_frozen_study",
            "--protocol", protocol, "--output-root", OUT / "fresh_portable_validation"], cwd=CODE, env=portable_env):
    finish("fresh_portable_validation_failed")
    sys.exit(1)
if not run("006_fresh_independent_replay", [fresh, "-m", "src.backtest.run_frozen_study",
            "--protocol", protocol, "--execution", "replay", "--retained-root", INTEGRATION / "portable_evidence",
            "--output-root", OUT / "fresh_portable_replay"], cwd=CODE, env=portable_env):
    finish("fresh_independent_replay_failed")
    sys.exit(1)
record["fresh_portable_checks_passed"] = True
record["clean_install_passed"] = True
finish("clean_install_and_fresh_portable_checks_passed")
