"""Retain one actual 23-call prefix, then generate isolated Governor branches.

This adapter is additive: the legacy meeting/replay contract is unchanged. A
prefix consists of all six R1-R3 outputs and the five non-Governor R4 ballots.
H withholds final information; B/N expose the same three-field tuples and vary
only their declared binding status. Final rationales never enter that channel.
Mock evidence remains engineering evidence; seeds do not establish pairing.
"""

from dataclasses import dataclass
import hashlib
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from src.behavioral.debate_orchestrator import DebateOrchestrator, InformationVisibility, planned_seed
from src.infra.evidence import canonical_json, content_hash, file_hash, safe_component, write_immutable
from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError
from src.infra.generation_evidence import strict_json
from src.infra.transcript_logger import read_transcript
from src.persona_engine.provenance import verify_personas
from src.rule_engine.engine import InstitutionalRuleEngine
from src.schemas.debate_schema import (
    InitialStanceOutput, DeliberationOutput, FinalVoteOutput, validate_member_output,
)
from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona

Condition = Literal["H", "B", "N"]
PREFIX_VERSION = "actual-paired-prefix-v1"
BRANCH_VERSION = "governor-final-information-v1"
_SCHEMAS = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}
_PAYLOAD_EXCLUSIONS = {"artifact_identity", "generation", "prompt", "artifact_content_hash"}


def _sealed(document: dict) -> dict:
    return {**document, "artifact_content_hash": content_hash(document)}


def _raw_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_seal(document: dict) -> None:
    if not isinstance(document, dict) or document.get("artifact_content_hash") != content_hash(
        {key: value for key, value in document.items() if key != "artifact_content_hash"}
    ):
        raise ArtifactIntegrityError("Paired artifact content hash mismatch")


def prefix_identity(experiment_id: str, meeting_date: str, replicate_id: int) -> str:
    return "prefix_" + content_hash({"experiment_id": experiment_id, "meeting_date": meeting_date,
                                     "replicate_id": replicate_id})[:24]


def branch_identity(prefix_id: str, condition: str, branch_draw_id: str) -> str:
    return "branch_" + content_hash({"prefix_id": prefix_id, "condition": condition,
                                     "branch_draw_id": branch_draw_id})[:24]


@dataclass(frozen=True)
class FrozenPrefix:
    """Immutable serialized handle; the disk artifact is checked at every branch.

    ``to_dict`` has no machine-specific locator. Reload retained evidence with
    ``from_path``; a mapping supplied to branching needs an ``artifact_path``
    locator in addition to those same scientific fields.
    """
    artifact_path: str
    document_json: str

    @classmethod
    def from_path(cls, path: str | Path) -> "FrozenPrefix":
        path = Path(path).resolve()
        document = strict_json(path.read_text(encoding="utf-8"))
        _check_seal(document)
        return cls(str(path), canonical_json(document))

    def to_dict(self) -> dict:
        return strict_json(self.document_json)

    @property
    def prefix_id(self) -> str:
        return self.to_dict()["prefix_id"]

    @property
    def artifact_content_hash(self) -> str:
        return self.to_dict()["artifact_content_hash"]


class PairedPrefixOrchestrator:
    def __init__(self, orchestrator: DebateOrchestrator):
        if not isinstance(orchestrator, DebateOrchestrator):
            raise TypeError("Paired adapter requires an existing DebateOrchestrator")
        self.orchestrator = orchestrator

    @staticmethod
    def _verification_context(context: Mapping | None) -> dict:
        if context is None:
            return {}
        if not isinstance(context, Mapping) or set(context) - {"source_root", "corpus_manifest_path"}:
            raise GenerationProvenanceError("Unknown persona verification context")
        result = {}
        for key, value in context.items():
            if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
                raise GenerationProvenanceError("Persona verification context needs absolute paths")
            result[key] = str(Path(value).resolve())
        return result

    def _inputs(self, snapshot, personas, governor_id, context, source_root=None):
        if bool(getattr(self.orchestrator.client, "cache_enabled", False)):
            raise GenerationProvenanceError("Paired generation requires cache disabled")
        root = Path(source_root).resolve() if source_root is not None else None
        snapshot = self.orchestrator._validate_snapshot(snapshot, source_root=root)
        personas = [MemberPersona.model_validate(p.model_dump()) for p in personas]
        ids = [p.member_id for p in personas]
        if len(personas) != 6 or len(set(ids)) != 6 or governor_id not in ids:
            raise ValueError("Paired prefix requires six distinct members including Governor")
        for persona in personas:
            safe_component(persona.member_id)
            if not persona.name.strip():
                raise ValueError("Member names must be nonempty")
        if context or getattr(self.orchestrator.client, "provider", "mock") != "mock":
            personas = verify_personas(personas, snapshot.information_cutoff, **context)
        return snapshot, personas

    def _directory(self, document: Mapping, condition_id: str) -> Path:
        return self.orchestrator.logger._directory(document["meeting_date"], document["replicate_id"],
                                                    document["experiment_id"], condition_id)

    def _request(self, document: Mapping, member_id: str, round_number: int, condition_id: str, **extra):
        identity = {**getattr(self.orchestrator.logger, "identity", {}),
                    "experiment_id": document["experiment_id"], "condition_id": condition_id,
                    "meeting_date": document["meeting_date"], "replicate_id": document["replicate_id"],
                    "member_id": member_id, "round_number": round_number,
                    "prefix_id": document["prefix_id"], "snapshot_hash": document["snapshot_hash"],
                    "persona_hash": document["persona_hash"],
                    "generation_settings_hash": document["generation_settings_hash"], **extra}
        for key in ("experiment_id", "snapshot_hash", "persona_hash", "generation_settings_hash"):
            frozen = getattr(self.orchestrator.logger, "identity", {})
            if key in frozen and frozen[key] != identity[key]:
                raise GenerationProvenanceError(f"Frozen logger {key} differs from paired inputs")
        return identity

    def _transcript(self, path: Path, identity: dict, settings: dict, seed: int) -> dict:
        transcript = read_transcript(path)
        generation = transcript["generation"]
        request = generation["request_identity"]
        if any(request.get(key) != value or type(request.get(key)) is not type(value)
               for key, value in identity.items()):
            raise ArtifactIntegrityError("Paired transcript request identity differs")
        metadata = generation["metadata"]
        for field, value in (("provider", settings["provider"]), ("routed_model", settings["model"]),
                             ("temperature", settings["temperature"]), ("seed", seed),
                             ("max_output_tokens", settings["max_output_tokens"]),
                             ("model_epoch", settings["model_epoch"]),
                             ("parser_version", settings["parser_version"])):
            if metadata[field] != value or type(metadata[field]) is not type(value):
                raise ArtifactIntegrityError(f"Paired transcript {field} differs from frozen settings")
        if metadata["schema_hash"] != settings["round_schema_hashes"][str(identity["round_number"])]:
            raise ArtifactIntegrityError("Paired transcript round schema differs")
        expected_track = "mock" if settings["provider"] == "mock" else "live_model"
        if metadata["cache_replay"] or metadata["evidence_type"] != expected_track:
            raise GenerationProvenanceError("Paired output must be fresh declared mock/live generation")
        if transcript["prompt"].get("user_prompt") != metadata["user_prompt"] or transcript["prompt"].get("system_prompt") != metadata["system_prompt"]:
            raise ArtifactIntegrityError("Paired transcript prompt differs from actual request")
        return transcript

    async def generate_shared_prefix(
        self, snapshot: MacroMeetingSnapshot, personas: Sequence[MemberPersona], governor_id: str, *,
        experiment_id: str, replicate_id: int, seed: int = 42, model: str | None = None,
        temperature: float | None = None, persona_verification_context: Mapping | None = None,
        source_root: str | Path | None = None,
    ) -> FrozenPrefix:
        safe_component(experiment_id)
        if type(replicate_id) is not int or replicate_id < 1 or type(seed) is not int:
            raise ValueError("Replicate must be positive integer and seed an integer")
        context = self._verification_context(persona_verification_context)
        snapshot, personas = self._inputs(snapshot, personas, governor_id, context, source_root)
        settings = self.orchestrator.generation_settings(model=model, temperature=temperature)
        document = {"artifact_version": PREFIX_VERSION, "experiment_id": experiment_id,
                    "meeting_date": snapshot.meeting_date, "replicate_id": replicate_id,
                    "prefix_id": prefix_identity(experiment_id, snapshot.meeting_date, replicate_id),
                    "governor_id": governor_id, "roster_ids": [p.member_id for p in personas],
                    "snapshot_hash": content_hash(snapshot.model_dump(mode="json")),
                    "persona_hash": content_hash([p.model_dump(mode="json") for p in personas]),
                    "generation_settings": settings, "generation_settings_hash": content_hash(settings),
                    "persona_verification_context": context, "seed_base": seed,
                    "source_verification_root": str(Path(source_root).resolve()) if source_root is not None else None,
                    "condition_id": "shared_prefix", "generation_count": 23,
                    "allowed_labels": [{"vote": rate, "stance": stance}
                                       for rate in RATE_ACTIONS_BPS for stance in STANCE_ACTIONS]}
        # An attempt is immutable even if it fails; a rerun needs a new identity.
        self._request(document, governor_id, 1, "shared_prefix")
        directory = self._directory(document, "shared_prefix")
        write_immutable(directory / "prefix_attempt.json", _sealed({**document, "status": "started"}))
        outputs, hashes, transcripts, seeds, evidence_types = {}, {}, {}, {}, set()
        ordered = [p for p in personas if p.member_id != governor_id] + [p for p in personas if p.member_id == governor_id]
        try:
            for round_number in (1, 2, 3, 4):
                outputs[round_number] = {}
                for persona in ordered:
                    if round_number == 4 and persona.member_id == governor_id:
                        continue
                    round_context = self.orchestrator._round_context(outputs, range(1, round_number), persona,
                                                                      personas, InformationVisibility())
                    request_seed = planned_seed(seed, snapshot.meeting_date, replicate_id, persona.member_id, round_number)
                    key = f"{persona.member_id}:round_{round_number}"
                    seeds[key] = request_seed
                    identity = self._request(document, persona.member_id, round_number, "shared_prefix")
                    output, evidence = await self.orchestrator._generate_round(
                        persona, snapshot, round_number, round_context, model=settings["model"],
                        temperature=settings["temperature"], seed=request_seed, identity=identity,
                        generation_settings=settings,
                    )
                    path = directory / f"round_{round_number}_{persona.member_id}.json"
                    transcript = self._transcript(path, identity, settings, request_seed)
                    payload = output.model_dump(mode="json")
                    if payload != {k: v for k, v in transcript.items() if k not in _PAYLOAD_EXCLUSIONS}:
                        raise ArtifactIntegrityError("Prefix output differs from retained actual generation")
                    outputs[round_number][persona.member_id] = output
                    hashes[key] = content_hash(payload)
                    transcripts[key] = {"path": path.name, "sha256": file_hash(path),
                                        "artifact_content_hash": transcript["artifact_content_hash"],
                                        "raw_output_hash": _raw_hash(transcript["generation"]["raw_text"]),
                                        "raw_output_hash_kind": "sha256_utf8_v1"}
                    evidence_types.add(evidence)
            document.update(outputs={str(r): {member: out.model_dump(mode="json") for member, out in rows.items()}
                                     for r, rows in outputs.items()}, output_hashes=hashes, transcripts=transcripts,
                            seed_schedule=seeds, evidence_types=sorted(evidence_types),
                            non_governor_votes=self._votes(list(outputs[4].values())), status="complete")
            path = write_immutable(directory / "shared_prefix.json", _sealed(document))
            frozen = FrozenPrefix.from_path(path)
            self._validate_prefix(frozen, snapshot, personas, context)
            return frozen
        except BaseException as error:
            self._failure(directory / "prefix_failure.json", document, error)
            raise

    @staticmethod
    def _votes(ballots) -> list[dict]:
        return [{"agent_id": ballot.member_id, "vote": ballot.final_rate_vote_bps,
                 "stance": ballot.final_stance_vote} for ballot in ballots]

    @staticmethod
    def _handle(prefix: FrozenPrefix | Mapping) -> FrozenPrefix:
        if isinstance(prefix, FrozenPrefix):
            return prefix
        if isinstance(prefix, Mapping) and "artifact_path" in prefix:
            return FrozenPrefix(str(Path(prefix["artifact_path"]).resolve()),
                                canonical_json({k: v for k, v in prefix.items() if k != "artifact_path"}))
        raise ArtifactIntegrityError("Prefix needs a retained artifact_path locator")

    def _validate_prefix(self, prefix, snapshot, personas, context):
        document = prefix.to_dict()
        disk = strict_json(Path(prefix.artifact_path).read_text(encoding="utf-8"))
        _check_seal(document)
        _check_seal(disk)
        if canonical_json(disk) != canonical_json(document):
            raise ArtifactIntegrityError("Prefix handle differs from retained frozen artifact")
        if document["artifact_version"] != PREFIX_VERSION or document["status"] != "complete" or document["generation_count"] != 23:
            raise ArtifactIntegrityError("Incomplete or unknown paired prefix")
        if document["prefix_id"] != prefix_identity(document["experiment_id"], document["meeting_date"], document["replicate_id"]):
            raise ArtifactIntegrityError("Prefix identity differs from planned study")
        if (document["meeting_date"] != snapshot.meeting_date or document["snapshot_hash"] != content_hash(snapshot.model_dump(mode="json"))
                or document["persona_hash"] != content_hash([p.model_dump(mode="json") for p in personas])
                or document["roster_ids"] != [p.member_id for p in personas]):
            raise GenerationProvenanceError("Prefix snapshot, roster or persona verification context differs")
        if document["persona_verification_context"] != context:
            # Relocation changes locators, never the persona fit/source identity.
            # Re-run the actual byte/availability verifier even for mock fixtures.
            if not document["persona_verification_context"] or not context:
                raise GenerationProvenanceError("Relocated persona context needs frozen manifest evidence")
            verify_personas(personas, snapshot.information_cutoff, **context)
        settings = document["generation_settings"]
        current = self.orchestrator.generation_settings(model=settings["model"], temperature=settings["temperature"])
        if current != settings or content_hash(settings) != document["generation_settings_hash"]:
            raise GenerationProvenanceError("Prefix generation settings have changed")
        if document["allowed_labels"] != [{"vote": rate, "stance": stance} for rate in RATE_ACTIONS_BPS for stance in STANCE_ACTIONS]:
            raise ArtifactIntegrityError("Prefix action menu differs from frozen protocol")
        expected_keys = {f"{p.member_id}:round_{r}" for r in (1, 2, 3, 4) for p in personas
                         if r != 4 or p.member_id != document["governor_id"]}
        if (set(document["outputs"]) != {"1", "2", "3", "4"}
                or any(set(document[field]) != expected_keys for field in ("output_hashes", "transcripts", "seed_schedule"))):
            raise ArtifactIntegrityError("Prefix output/receipt roster is incomplete")
        outputs, evidence = {}, set()
        directory = Path(prefix.artifact_path).parent.resolve()
        for round_number in (1, 2, 3, 4):
            expected_members = {p.member_id for p in personas if round_number != 4 or p.member_id != document["governor_id"]}
            if set(document["outputs"][str(round_number)]) != expected_members:
                raise ArtifactIntegrityError("Prefix round roster differs")
            outputs[round_number] = {}
            for persona in personas:
                if persona.member_id not in expected_members:
                    continue
                key = f"{persona.member_id}:round_{round_number}"
                payload = document["outputs"][str(round_number)][persona.member_id]
                output = validate_member_output(_SCHEMAS[round_number].model_validate(payload), member_id=persona.member_id,
                                                member_name=persona.name, is_internal=persona.is_internal,
                                                round_number=round_number)
                if content_hash(payload) != document["output_hashes"][key]:
                    raise ArtifactIntegrityError("Frozen prefix actual output hash mismatch")
                record = document["transcripts"][key]
                if record.get("raw_output_hash_kind") != "sha256_utf8_v1":
                    raise ArtifactIntegrityError("Frozen prefix raw output hash kind differs")
                path = (directory / record["path"]).resolve()
                if path.parent != directory or path.name != f"round_{round_number}_{persona.member_id}.json" or file_hash(path) != record["sha256"]:
                    raise ArtifactIntegrityError("Frozen prefix transcript bytes/path differ")
                seed = planned_seed(document["seed_base"], snapshot.meeting_date, document["replicate_id"], persona.member_id, round_number)
                if type(document["seed_schedule"][key]) is not int or document["seed_schedule"][key] != seed:
                    raise ArtifactIntegrityError("Frozen prefix seed audit differs")
                transcript = self._transcript(path, self._request(document, persona.member_id, round_number, "shared_prefix"), settings, seed)
                if (transcript["artifact_content_hash"] != record["artifact_content_hash"]
                        or _raw_hash(transcript["generation"]["raw_text"]) != record["raw_output_hash"]
                        or payload != {k: v for k, v in transcript.items() if k not in _PAYLOAD_EXCLUSIONS}):
                    raise ArtifactIntegrityError("Frozen prefix output differs from actual receipt")
                outputs[round_number][persona.member_id] = output
                evidence.add(transcript["generation"]["metadata"]["evidence_type"])
        if document["non_governor_votes"] != self._votes(list(outputs[4].values())) or document["evidence_types"] != sorted(evidence):
            raise ArtifactIntegrityError("Prefix ballot projection or evidence label differs")
        return document, outputs

    @staticmethod
    def _final_information(ballots, condition: Condition) -> str:
        # Deliberately project fields; never model_dump a final ballot here.
        tuples = [{"member_id": v.member_id, "final_rate_vote_bps": v.final_rate_vote_bps,
                   "final_stance_vote": v.final_stance_vote} for v in ballots]
        status = {"H": "withheld", "B": "binding ballots", "N": "nonbinding preferences"}[condition]
        return "NON-GOVERNOR FINAL INFORMATION (SIMULATION CHOICE):\n" + canonical_json(
            {"status": status, "tuples": None if condition == "H" else tuples})

    @staticmethod
    def _agreement(ballots) -> dict:
        pairs = list(combinations(ballots, 2))
        counts = {"rate": sum(a.final_rate_vote_bps == b.final_rate_vote_bps for a, b in pairs),
                  "stance": sum(a.final_stance_vote == b.final_stance_vote for a, b in pairs),
                  "joint": sum((a.final_rate_vote_bps, a.final_stance_vote) == (b.final_rate_vote_bps, b.final_stance_vote) for a, b in pairs)}
        return {kind: {"agreeing_pairs": count, "total_pairs": len(pairs), "value": count / len(pairs)}
                for kind, count in counts.items()}

    @staticmethod
    def _aggregation(ballots, governor_id, prior_stance):
        from dataclasses import asdict
        results = {}
        for kind, aggregate, values, prior in (
            ("rate", InstitutionalRuleEngine.aggregate_rate_votes, {v.member_id: v.final_rate_vote_bps for v in ballots}, 0),
            ("stance", InstitutionalRuleEngine.aggregate_stance_votes, {v.member_id: v.final_stance_vote for v in ballots}, prior_stance),
        ):
            # The strict six valid ballots were already retained. Fragmentation is
            # a separate institutional question, never a lost behavioral outcome.
            try:
                result = aggregate(values, governor_id, fragmentation_policy="reject", prior_action=prior)
            except ValueError as error:
                if "No majority or Governor-resolvable binary equality" not in str(error):
                    raise
                results[kind] = {"status": "unresolved", "reason": str(error)}
            else:
                results[kind] = {"status": "resolved", **asdict(result)}
        return results

    @staticmethod
    def _failure(path, identity, error):
        try:
            write_immutable(path, _sealed({**identity, "status": "failed", "error_type": type(error).__name__,
                                           "error": str(error), "failure_context": getattr(error, "context", {})}))
        except BaseException as logging_error:
            error.add_note(f"Paired failure artifact could not be retained: {type(logging_error).__name__}: {logging_error}")

    async def run_governor_branch(
        self, prefix: FrozenPrefix | Mapping, snapshot: MacroMeetingSnapshot, personas: Sequence[MemberPersona], *,
        condition: Condition, branch_draw_id: str | int, persona_verification_context: Mapping | None = None,
        source_root: str | Path | None = None,
    ) -> dict[str, Any]:
        if condition not in ("H", "B", "N"):
            raise ValueError("Governor branch condition must be H, B or N")
        if isinstance(branch_draw_id, str):
            draw = safe_component(branch_draw_id)
        elif type(branch_draw_id) is int and branch_draw_id > 0:
            draw = str(branch_draw_id)
        else:
            raise ValueError("Branch draw identity must be nonempty safe text or positive integer")
        prefix = self._handle(prefix)
        supplied = prefix.to_dict()
        branch_id = branch_identity(supplied["prefix_id"], condition, draw)
        condition_id = f"branch_{condition}_draw_{draw}"
        identity = {"artifact_version": BRANCH_VERSION, "experiment_id": supplied["experiment_id"],
                    "meeting_date": supplied["meeting_date"], "replicate_id": supplied["replicate_id"],
                    "prefix_id": supplied["prefix_id"], "prefix_hash": supplied["artifact_content_hash"],
                    "governor_id": supplied["governor_id"], "roster_ids": supplied["roster_ids"],
                    "condition": condition, "condition_id": condition_id, "branch_draw_id": draw,
                    "branch_id": branch_id, "generation_count": 1}
        directory = self._directory(identity, condition_id)
        # Reserve before submitting, so repeated draws cannot spend or overwrite.
        write_immutable(directory / "branch_attempt.json", _sealed({**identity, "status": "started"}))
        try:
            context = supplied["persona_verification_context"] if persona_verification_context is None else self._verification_context(persona_verification_context)
            root = source_root if source_root is not None else supplied.get("source_verification_root")
            snapshot, personas = self._inputs(snapshot, personas, supplied["governor_id"], context, root)
            document, outputs = self._validate_prefix(prefix, snapshot, personas, context)
            governor = next(p for p in personas if p.member_id == document["governor_id"])
            ballots = list(outputs[4].values())
            common = self.orchestrator._round_context(outputs, (1, 2, 3), governor, personas, InformationVisibility())
            branch_context = common + "\n\n" + self._final_information(ballots, condition)
            # Draw-specific seeds audit request separation, never substitute for
            # retaining the shared actual outputs or for model independence.
            request_seed = int(content_hash({"seed_base": document["seed_base"], "branch_id": branch_id})[:8], 16) & 0x7FFFFFFF
            settings = document["generation_settings"]
            request = self._request(document, governor.member_id, 4, condition_id,
                                    branch_id=branch_id, branch_draw_id=draw, branch_condition=condition,
                                    prefix_hash=document["artifact_content_hash"])
            output, evidence = await self.orchestrator._generate_round(
                governor, snapshot, 4, branch_context, model=settings["model"], temperature=settings["temperature"],
                seed=request_seed, identity=request, generation_settings=settings,
            )
            path = directory / f"round_4_{governor.member_id}.json"
            transcript = self._transcript(path, request, settings, request_seed)
            ballots.append(output)
            summary = _sealed({**identity, "status": "complete", "input_track": snapshot.input_track,
                               "member_votes": [v.model_dump(mode="json") for v in ballots], "votes": self._votes(ballots),
                               "pair_agreement": self._agreement(ballots),
                               "aggregation": self._aggregation(ballots, governor.member_id, snapshot.prev_stance),
                               "evidence_types": sorted(set(document["evidence_types"]) | {evidence}),
                               "seed": request_seed, "governor_output_hash": content_hash(output.model_dump(mode="json")),
                               "governor_transcript": {"path": path.name, "sha256": file_hash(path),
                                                       "artifact_content_hash": transcript["artifact_content_hash"],
                                                       "raw_output_hash": _raw_hash(transcript["generation"]["raw_text"]),
                                                       "raw_output_hash_kind": "sha256_utf8_v1"}})
            write_immutable(directory / "branch_outcome.json", summary)
            return summary
        except BaseException as error:
            self._failure(directory / "branch_failure.json", identity, error)
            raise
