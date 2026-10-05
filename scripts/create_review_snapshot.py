"""Create a review input copy without prior reviews, credentials, or Git history.

This isolates supplied context, not the reviewer's operating-system permissions.
The reviewer must still be instructed to use only the returned snapshot.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_NAMES = {".git", ".venv", ".cache", "__pycache__", ".pytest_cache", ".env", ".env.local", ".DS_Store"}


def included(path: Path) -> bool:
    parts = path.parts
    if any(part in EXCLUDED_NAMES or part.startswith(".coverage") for part in parts):
        return False
    if path.name in {"README.md", "audit_methodology.py", "AGENTS.md"}:
        return False
    if parts[0] == "research":
        return len(parts) == 1 or parts[1] in {"protocols", "study", "source_ledgers"}
    if parts[0] == "results" and any("methodology_audit" in part or "peer_review" in part for part in parts):
        return False
    return True


def create_snapshot(record_dir: Path, source: Path = ROOT) -> dict:
    record_dir.mkdir(parents=True, exist_ok=True)
    record = record_dir / "snapshot_manifest.json"
    if record.exists():
        raise FileExistsError(f"Review input record already exists: {record}")
    target = Path(tempfile.mkdtemp(prefix="rbi_blind_review_"))
    hashes = {}
    for directory, subdirs, files in os.walk(source):
        current = Path(directory)
        subdirs[:] = sorted(name for name in subdirs if included((current / name).relative_to(source)) and not (current / name).is_symlink())
        for name in sorted(files):
            path = current / name
            relative = path.relative_to(source)
            if not included(relative) or not path.is_file() or path.is_symlink():
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            hashes[str(relative)] = hashlib.sha256(destination.read_bytes()).hexdigest()
    # Sharing a runtime saves installation; project files and caches are separate.
    if (source / ".venv").is_dir():
        (target / ".venv").symlink_to(source / ".venv", target_is_directory=True)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=source, text=True).strip()
    manifest = {
        "source_commit": git("rev-parse", "HEAD"),
        "source_branch": git("branch", "--show-current"),
        "source_dirty_state": git("status", "--porcelain"),
        "snapshot": str(target),
        "identity": "Source commit plus input hashes; temporary snapshot path is local provenance only.",
        "isolation": "Fresh agent with no conversation history; copied inputs; shared Python runtime; shared host permissions.",
        "excluded": ["prior reviews and implementation plans", "Git history", "credentials", "runtime caches", "README review synthesis", "prior audit results and runner"],
        "input_hashes": hashes,
    }
    record.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-dir", type=Path, required=True)
    args = parser.parse_args()
    result = create_snapshot(args.record_dir)
    print(json.dumps({"snapshot": result["snapshot"], "files": len(result["input_hashes"]), "record": str(args.record_dir / "snapshot_manifest.json")}))
