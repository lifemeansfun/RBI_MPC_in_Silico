"""Checkpoint evidence tied to complete scientific identities and artifact hashes."""

import json
from datetime import date
from pathlib import Path

from src.infra.evidence import canonical_json, content_hash, file_hash, safe_component, write_immutable
from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError
from src.infra.generation_evidence import strict_json

REQUIRED_IDENTITY_FIELDS = frozenset({
    "experiment_id", "condition_id", "meeting_date", "replicate_id", "code_hash",
    "config_hash", "data_hash", "persona_hash", "intervention_hash", "seed_schedule_version",
})


def validate_identity(identity: dict) -> dict:
    if not isinstance(identity, dict) or REQUIRED_IDENTITY_FIELDS - identity.keys():
        raise GenerationProvenanceError(f"Checkpoint identity requires {sorted(REQUIRED_IDENTITY_FIELDS)}")
    if any(value is None or value == "" for value in identity.values()):
        raise GenerationProvenanceError("Checkpoint identity contains missing values")
    if type(identity["replicate_id"]) is not int or identity["replicate_id"] < 0:
        raise GenerationProvenanceError("replicate_id must be a nonnegative integer")
    for key in ("experiment_id", "condition_id", "seed_schedule_version"):
        if not isinstance(identity[key], str) or not identity[key].strip():
            raise GenerationProvenanceError(f"{key} must be a nonempty string")
    try:
        if date.fromisoformat(identity["meeting_date"]).isoformat() != identity["meeting_date"]:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise GenerationProvenanceError("Checkpoint meeting_date must be an actual ISO date") from exc
    for key in (key for key in identity if key.endswith("_hash")):
        value = identity[key]
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise GenerationProvenanceError(f"{key} must be a SHA256 digest")
    # Canonical roundtrip detaches nested values from the caller.
    return json.loads(canonical_json(identity))


class CheckpointStore:
    def __init__(self, output_root: str | Path):
        self.output_root = Path(output_root).resolve()

    def path_for(self, identity: dict) -> Path:
        identity = validate_identity(identity)
        return (self.output_root / safe_component(identity["experiment_id"])
                / safe_component(identity["condition_id"]) / "checkpoints"
                / f"{safe_component(identity['meeting_date'])}_rep_{identity['replicate_id']}_{content_hash(identity)}.json")

    def save(self, identity: dict, payload: dict, artifacts: dict[str, str | Path], *, replay: bool = False) -> Path:
        identity = validate_identity(identity)
        if not artifacts:
            raise ArtifactIntegrityError("Checkpoint requires referenced evidence artifacts")
        records = {}
        for label, raw_path in artifacts.items():
            path = Path(raw_path).resolve()
            if not path.is_file():
                raise ArtifactIntegrityError(f"Missing checkpoint artifact: {path}")
            # Portable references: the evidence root and its artifacts can be copied together.
            try:
                relative = path.relative_to(self.output_root)
            except ValueError as exc:
                raise ArtifactIntegrityError("Checkpoint artifact must lie inside output_root") from exc
            records[label] = {"path": str(relative), "sha256": file_hash(path)}
        document = {"checkpoint_version": 1, "identity": identity, "payload": payload,
                    "artifacts": records}
        document["content_hash"] = content_hash(document)
        return write_immutable(self.path_for(identity), document, replay=replay)

    def load(self, expected_identity: dict) -> dict | None:
        expected = validate_identity(expected_identity)
        path = self.path_for(expected)
        if not path.exists():
            return None
        try:
            document = strict_json(path.read_text(encoding="utf-8"))
            digest = document.pop("content_hash")
            if content_hash(document) != digest or document["identity"] != expected or document["checkpoint_version"] != 1:
                raise ArtifactIntegrityError("Checkpoint content/identity mismatch")
            if not isinstance(document["artifacts"], dict) or not document["artifacts"]:
                raise ArtifactIntegrityError("Checkpoint has no evidence")
            for artifact in document["artifacts"].values():
                evidence_path = (self.output_root / artifact["path"]).resolve()
                if not evidence_path.is_relative_to(self.output_root):
                    raise ArtifactIntegrityError("Checkpoint artifact escapes evidence root")
                if not evidence_path.is_file() or file_hash(evidence_path) != artifact["sha256"]:
                    raise ArtifactIntegrityError(f"Checkpoint artifact missing/corrupt: {evidence_path}")
            document["content_hash"] = digest
            return document
        except (ValueError, TypeError, KeyError, OSError, GenerationProvenanceError) as exc:
            raise ArtifactIntegrityError(f"Corrupt checkpoint: {path}") from exc

    write = save
