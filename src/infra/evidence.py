"""Canonical, finite, immutable evidence helpers shared by runtime components."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GenerationProvenanceError("Evidence must be finite JSON") from exc


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_component(value: Any) -> str:
    component = str(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", component) or component in {".", ".."}:
        raise GenerationProvenanceError(f"Unsafe artifact path component: {component!r}")
    return component


def write_immutable(path: str | Path, value: Any, *, replay: bool = False) -> Path:
    """Publish fsynced canonical bytes without replacing an existing artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical_json(value) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".evidence-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # A hard link publishes complete bytes atomically and fails on collisions.
            os.link(temporary, path)
        except FileExistsError as exc:
            if not replay or path.read_bytes() != raw:
                raise ArtifactIntegrityError(f"Immutable artifact already exists: {path}") from exc
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)
    return path
