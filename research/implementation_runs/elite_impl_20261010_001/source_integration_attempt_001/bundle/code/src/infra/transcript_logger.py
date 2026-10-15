"""Verbatim evidence with immutable condition/meeting/replicate artifact paths."""

import fcntl
import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.infra.evidence import canonical_json, content_hash, file_hash, safe_component, write_immutable
from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError
from src.infra.generation_evidence import strict_json, validate_generation_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_transcript(path: str | Path, expected_identity: dict | None = None) -> dict:
    """Validate copied evidence before deterministic replay, including raw identity."""
    try:
        document = strict_json(Path(path).read_text(encoding="utf-8"))
        recorded_hash = document.pop("artifact_content_hash")
        if content_hash(document) != recorded_hash:
            raise ArtifactIntegrityError("Transcript content hash mismatch")
        identity = document["artifact_identity"]
        core = {"experiment_id", "condition_id", "meeting_date", "replicate_id"}
        if not isinstance(identity, dict) or core - identity.keys() or any(identity[key] is None for key in core):
            raise ArtifactIntegrityError("Transcript identity is incomplete")
        if type(identity["replicate_id"]) is not int or identity["replicate_id"] < 0:
            raise ArtifactIntegrityError("Transcript replicate identity is invalid")
        if date.fromisoformat(identity["meeting_date"]).isoformat() != identity["meeting_date"]:
            raise ArtifactIntegrityError("Transcript meeting date is invalid")
        for field in ("experiment_id", "condition_id", "member_id"):
            if field in identity:
                if not isinstance(identity[field], str) or not identity[field].strip():
                    raise ArtifactIntegrityError("Transcript study/member identity is invalid")
                safe_component(identity[field])
        if "round_number" in identity and (type(identity["round_number"]) is not int or identity["round_number"] < 1 or "member_id" not in identity):
            raise ArtifactIntegrityError("Transcript round identity is invalid")
        if any(identity.get(key) != value or type(identity.get(key)) is not type(value) for key, value in (expected_identity or {}).items()):
            raise ArtifactIntegrityError("Transcript differs from expected scientific identity")
        generation = document.get("generation")
        if "round_number" in identity:
            if generation is None:
                raise ArtifactIntegrityError("Round transcript has no generation evidence")
            if any(generation["request_identity"].get(key) != value for key, value in identity.items() if value is not None):
                raise ArtifactIntegrityError("Transcript and generation identity differ")
            prompt = document.get("prompt") or {}
            if not isinstance(prompt, dict):
                raise ArtifactIntegrityError("Transcript prompt evidence must be a mapping")
            aliases = prompt.get("identity_aliases", {})
            parsed = validate_generation_evidence(generation, identity_aliases=aliases)
            payload = {key: value for key, value in document.items()
                       if key not in {"artifact_identity", "generation", "prompt"}}
            normalized = dict(parsed) if parsed is not None else None
            if normalized is not None:
                request_identity = generation["request_identity"]
                if normalized.get("member_id") == request_identity.get("output_member_id"):
                    normalized["member_id"] = request_identity["member_id"]
                if "member_name" in normalized and "member_name" in payload:
                    original_name = payload["member_name"]
                    if isinstance(original_name, str) and aliases.get(original_name) == normalized["member_name"]:
                        normalized["member_name"] = original_name
            if canonical_json(normalized) != canonical_json(payload):
                raise ArtifactIntegrityError("Transcript payload differs from validated generation")
        document["artifact_content_hash"] = recorded_hash
        return document
    except (OSError, TypeError, ValueError, KeyError, GenerationProvenanceError) as exc:
        raise ArtifactIntegrityError(f"Missing/corrupt transcript evidence: {path}") from exc


class TranscriptLogger:
    def __init__(self, run_id: Optional[str] = None, *, output_root: str | Path | None = None,
                 condition_id: str = "baseline", identity: dict | None = None):
        self.run_id = run_id or (datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:12])
        self.output_root = Path(output_root) if output_root else PROJECT_ROOT / "runs" / "corrected_v1"
        self.condition_id = safe_component(condition_id)
        self.identity = json.loads(canonical_json(identity or {}))
        self.experiment_id = self.identity.get("experiment_id")
        self.run_dir = self.output_root
        if self.experiment_id:
            self.run_dir /= safe_component(self.experiment_id)
        self.run_dir /= safe_component(self.run_id)
        self.transcripts_dir = self.run_dir / self.condition_id / "transcripts"
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.run_dir / "run.jsonl"
        manifest = {"logger_version": 2, "run_id": self.run_id,
                    "condition_id": self.condition_id, "identity": self.identity}
        # Opening an existing logger identity is allowed; changing identity is not.
        write_immutable(self.run_dir / f"manifest_{self.condition_id}.json", manifest, replay=True)

    def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
                  "condition_id": self.condition_id, "identity": self.identity,
                  "event_type": event_type, "data": data}
        record["content_hash"] = content_hash(record)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.write(canonical_json(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _directory(self, meeting_date, replicate_id, experiment_id, condition_id):
        if type(replicate_id) is not int or replicate_id < 0:
            raise ArtifactIntegrityError("replicate_id must be a nonnegative integer")
        condition = safe_component(condition_id or self.condition_id)
        experiment = experiment_id or self.experiment_id
        if experiment and self.experiment_id and experiment != self.experiment_id:
            raise ArtifactIntegrityError("Logger experiment differs from immutable run identity")
        if experiment and not self.experiment_id:
            # An additive explicit experiment keeps even a legacy logger isolated.
            directory = self.output_root / safe_component(experiment) / safe_component(self.run_id) / condition / "transcripts"
        elif condition == self.condition_id:
            directory = self.transcripts_dir
        else:
            directory = self.run_dir / condition / "transcripts"
        return directory / safe_component(meeting_date) / f"rep_{replicate_id}"

    def _payload(self, payload, generation, prompt, meeting_date, replicate_id,
                 experiment_id, condition_id, round_number=None, member_id=None):
        result = dict(payload)
        bound = {**self.identity, "experiment_id": experiment_id or self.experiment_id,
                 "condition_id": condition_id or self.condition_id, "meeting_date": meeting_date,
                 "replicate_id": replicate_id}
        if round_number is not None:
            bound.update(round_number=round_number, member_id=member_id)
        result["artifact_identity"] = bound
        if generation is not None:
            result["generation"] = generation.to_dict() if hasattr(generation, "to_dict") else generation
            request = result["generation"].get("request_identity", {})
            required = {"experiment_id", "condition_id", "meeting_date", "replicate_id", "member_id", "round_number"}
            if round_number is not None and (required - request.keys()):
                raise ArtifactIntegrityError("Round transcript requires complete generation identity")
            if any(key in request and request[key] != value for key, value in bound.items() if value is not None):
                raise ArtifactIntegrityError("Transcript identity differs from generation request")
        if prompt is not None:
            result["prompt"] = prompt
        result["artifact_content_hash"] = content_hash(result)
        return result

    def save_round_transcript(self, meeting_date: str, replicate_id: int, round_number: int,
                              member_id: str, payload: dict[str, Any], *, experiment_id=None,
                              condition_id=None, generation=None, prompt=None, replay=False) -> Path:
        if type(round_number) is not int or round_number < 1:
            raise ArtifactIntegrityError("round_number must be a positive integer")
        directory = self._directory(meeting_date, replicate_id, experiment_id, condition_id)
        result = self._payload(payload, generation, prompt, meeting_date, replicate_id,
                               experiment_id, condition_id, round_number, member_id)
        return write_immutable(directory / f"round_{round_number}_{safe_component(member_id)}.json", result, replay=replay)

    def save_meeting_summary(self, meeting_date: str, replicate_id: int, summary: dict[str, Any], *,
                             experiment_id=None, condition_id=None, generation=None, prompt=None,
                             replay=False) -> Path:
        directory = self._directory(meeting_date, replicate_id, experiment_id, condition_id)
        result = self._payload(summary, generation, prompt, meeting_date, replicate_id,
                               experiment_id, condition_id)
        return write_immutable(directory / "meeting_outcome.json", result, replay=replay)

    def replay_artifact(self, source_path: str | Path, expected_identity: dict | None = None) -> Path:
        """Recreate validated source evidence in an empty output tree without generation."""
        document = read_transcript(source_path, expected_identity)
        identity = document["artifact_identity"]
        directory = self._directory(identity["meeting_date"], identity["replicate_id"],
                                    identity["experiment_id"], identity["condition_id"])
        if "round_number" in identity:
            filename = f"round_{identity['round_number']}_{safe_component(identity['member_id'])}.json"
        else:
            filename = "meeting_outcome.json"
        result = write_immutable(directory / filename, document, replay=True)
        self.log_event("artifact_replayed", {"evidence_type": "deterministic_artifact_replay",
                                             "source_path": str(Path(source_path).resolve()),
                                             "source_sha256": file_hash(source_path),
                                             "destination": str(result), "artifact_identity": identity})
        return result
