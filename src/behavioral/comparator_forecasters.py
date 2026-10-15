"""One-call, frozen, joint forecasts with or without supplied persona prompts.

These are comparator engineering contracts, not live evidence or budget-matched
deliberation. Raw generation remains in the runtime's original evidence schema;
alias-normalized predictions are a separately verified derived record.
"""
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.behavioral.debate_orchestrator import DebateOrchestrator, planned_seed
from src.infra.evidence import canonical_json, content_hash, file_hash, safe_component, write_immutable
from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError, LLMResponseMalformedError
from src.infra.generation_evidence import strict_json, validate_generation_evidence
from src.infra.llm_client import LLMClient, normalize_request_identity
from src.infra.transcript_logger import TranscriptLogger, read_transcript
from src.persona_engine.provenance import verify_personas
from src.rule_engine.engine import InstitutionalRuleEngine
from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS, RateActionBps, StanceType, validate_rate_action
from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS, iso_day
from src.schemas.persona_schema import MemberPersona

ROOT = Path(__file__).resolve().parents[2]
CONTROL_ID = "comparator_forecaster"
CONTRACT_VERSION = "joint_comparator_v1"
ControlMode = Literal["joint_persona", "macro_only"]
DEPENDENCIES = (
    "src/behavioral/comparator_forecasters.py", "src/behavioral/debate_orchestrator.py",
    "src/infra/llm_client.py", "src/infra/generation_evidence.py", "src/infra/cache.py",
    "src/infra/cost_governor.py", "src/infra/config_loader.py", "src/infra/evidence.py",
    "src/infra/transcript_logger.py", "src/persona_engine/provenance.py",
    "src/schemas/macro_schema.py", "src/schemas/persona_schema.py",
    "src/schemas/decision_space.py", "src/rule_engine/engine.py", "config/config.yaml",
)


class RosterMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    member_id: str = Field(min_length=1)
    member_name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    is_internal: bool

    @field_validator("member_id", "member_name", "role")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Roster text cannot be blank")
        return value


class ComparatorRoster(BaseModel):
    """Dated full-roster assumption; callers explicitly supply expanded members."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: str
    valid_from: str
    valid_through: str
    governor_id: str
    members: tuple[RosterMember, ...] = Field(min_length=6, max_length=6)
    stance_vocabulary_version: Literal["simulator_stance_v1"] = "simulator_stance_v1"

    _days = field_validator("valid_from", "valid_through")(iso_day)

    @model_validator(mode="after")
    def explicit_roster(self):
        safe_component(self.version)
        ids = [m.member_id for m in self.members]
        names = [m.member_name for m in self.members]
        for value in ids:
            safe_component(value)
        if len(set(ids)) != 6 or len(set(names)) != 6 or self.valid_from > self.valid_through:
            raise ValueError("Roster needs six distinct IDs/names and ordered date bounds")
        governors = [m for m in self.members if m.role.casefold() == "governor"]
        if len(governors) != 1 or governors[0].member_id != self.governor_id or not governors[0].is_internal:
            raise ValueError("Roster must identify exactly one internal Governor")
        return self


class ForecastBallot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)
    member_id: str = Field(min_length=1)
    member_name: str = Field(min_length=1)
    is_internal: bool
    rate_vote_bps: RateActionBps
    stance_vote: StanceType
    rate_choice_disagreement: bool
    formal_stance_dissent: bool
    rationale: str = Field(min_length=1)
    _rate = field_validator("rate_vote_bps", mode="before")(validate_rate_action)

    @field_validator("member_id", "member_name", "rationale")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Forecast text cannot be blank")
        return value


class JointForecastOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)
    member_id: Literal["comparator_forecaster"]
    round_number: Literal[1]
    fallback_triggered: Literal[False]
    rate_decision_bps: RateActionBps
    stance_decision: StanceType
    member_ballots: list[ForecastBallot] = Field(min_length=6, max_length=6)
    committee_rationale: str = Field(min_length=1)
    _rate = field_validator("rate_decision_bps", mode="before")(validate_rate_action)

    @field_validator("round_number", "fallback_triggered", mode="before")
    @classmethod
    def strict_literals(cls, value, info):
        expected = int if info.field_name == "round_number" else bool
        if type(value) is not expected:
            raise ValueError("No literal integer/boolean coercion")
        return value

    @field_validator("committee_rationale")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Committee rationale cannot be blank")
        return value


@dataclass(frozen=True)
class FrozenComparatorRequest:
    plan_json: str
    plan_hash: str
    artifact_path: str

    @property
    def plan(self) -> dict:
        return strict_json(self.plan_json)


def _roster(value: ComparatorRoster | dict) -> ComparatorRoster:
    # JSON round-trip also revalidates manually mutated frozen models/tuples.
    raw = value.model_dump(mode="json") if isinstance(value, ComparatorRoster) else value
    return ComparatorRoster.model_validate_json(canonical_json(raw))


def _normalize_forecast(output: dict, plan: dict) -> dict:
    parsed = JointForecastOutput.model_validate(output)
    roster = _roster(plan["roster"])
    aliases = plan["identity_aliases"]
    votes = []
    for declared, ballot in zip(roster.members, parsed.member_ballots):
        if (ballot.member_id != aliases.get(declared.member_id, declared.member_id)
                or ballot.member_name != aliases.get(declared.member_name, declared.member_name)
                or ballot.is_internal is not declared.is_internal):
            raise GenerationProvenanceError("Joint forecast changed the planned ordered roster/role")
        vote = ballot.model_dump()
        vote.update(member_id=declared.member_id, member_name=declared.member_name)
        votes.append(vote)
    rate = InstitutionalRuleEngine.aggregate_rate_votes(
        {v["member_id"]: v["rate_vote_bps"] for v in votes}, roster.governor_id,
        fragmentation_policy=plan["fragmentation_policy"], prior_action=0)
    stance = InstitutionalRuleEngine.aggregate_stance_votes(
        {v["member_id"]: v["stance_vote"] for v in votes}, roster.governor_id,
        fragmentation_policy=plan["fragmentation_policy"], prior_action=plan["snapshot"]["prev_stance"])
    if parsed.rate_decision_bps != rate.winning_action or parsed.stance_decision != stance.winning_action:
        raise GenerationProvenanceError("Committee forecast contradicts its declared ballot resolver")
    for ballot in votes:
        if (ballot["rate_choice_disagreement"] != (ballot["member_id"] in rate.dissenting_members)
                or ballot["formal_stance_dissent"] != (ballot["member_id"] in stance.dissenting_members)):
            raise GenerationProvenanceError("Forecast dissent channel contradicts predicted formal ballots")
    return {"meeting_date": plan["snapshot"]["meeting_date"],
            "replicate_id": plan["identity"]["replicate_id"],
            "rate_decision_bps": parsed.rate_decision_bps, "stance_decision": parsed.stance_decision,
            "dissenting_members_rate": rate.dissenting_members,
            "dissenting_members_stance": stance.dissenting_members,
            "member_ballots": votes, "committee_rationale": parsed.committee_rationale,
            "rate_resolution": asdict(rate), "stance_resolution": asdict(stance)}


def read_comparator_record(path: str | Path, *, expected_plan_hash: str,
                           transcript_path: str | Path | None = None) -> dict:
    """Validate derived results against an independently supplied frozen-plan hash.

    This checks consistency, not provider authenticity or an invoice. Original
    nested aliases remain in raw generation; normalized ballots are checked here.
    """
    record = strict_json(Path(path).read_text())
    fields = {"record_version", "plan_hash", "frozen_plan", "generation", "prediction", "usage",
              "transcript_path", "transcript_sha256", "artifact_content_hash"}
    if (not isinstance(record, dict) or set(record) != fields or record["record_version"] != CONTRACT_VERSION
            or not isinstance(expected_plan_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_plan_hash)):
        raise ArtifactIntegrityError("Comparator record schema/version or supplied plan anchor is invalid")
    recorded_hash = record.pop("artifact_content_hash")
    if content_hash(record) != recorded_hash or record["plan_hash"] != expected_plan_hash:
        raise ArtifactIntegrityError("Comparator record hash or external plan anchor differs")
    plan = record["frozen_plan"]
    if content_hash(plan) != expected_plan_hash or plan["contract_version"] != CONTRACT_VERSION:
        raise ArtifactIntegrityError("Comparator frozen plan changed")
    generation = record["generation"]
    parsed = validate_generation_evidence(generation)
    _bind_generation(generation, plan)
    expected = _normalize_forecast(parsed, plan)
    if canonical_json(expected) != canonical_json(record["prediction"]):
        raise ArtifactIntegrityError("Comparator prediction differs from validated raw generation")
    if record["usage"] != _usage(generation, plan):
        raise ArtifactIntegrityError("Comparator usage differs from original generation receipt")
    source = Path(transcript_path if transcript_path is not None else record["transcript_path"])
    if not source.is_file() or file_hash(source) != record["transcript_sha256"]:
        raise ArtifactIntegrityError("Comparator transcript missing or its retained bytes changed")
    identity = plan["identity"]
    transcript = read_transcript(source, {key:identity[key] for key in
                                 ("experiment_id", "condition_id", "meeting_date", "replicate_id", "member_id", "round_number")})
    if transcript["generation"] != generation:
        raise ArtifactIntegrityError("Comparator transcript differs from its retained generation")
    record["artifact_content_hash"] = recorded_hash
    return record


def _bind_generation(generation: dict, plan: dict) -> None:
    metadata = generation["metadata"]
    settings = plan["generation_settings"]
    if generation["request_identity"] != plan["identity"]:
        raise GenerationProvenanceError("Comparator generation returned a different request identity")
    for field in ("provider", "temperature", "seed", "max_output_tokens", "input_token_bound",
                  "model_epoch", "parser_version"):
        if metadata[field] != settings[field] or type(metadata[field]) is not type(settings[field]):
            raise GenerationProvenanceError(f"Comparator generation changed frozen {field}")
    if (metadata["requested_model"] != settings["model"]
            or metadata["user_prompt"] != plan["user_prompt"]
            or metadata["system_prompt"] != plan["system_prompt"]
            or metadata["schema_hash"] != content_hash(JointForecastOutput.model_json_schema())):
        raise GenerationProvenanceError("Comparator generation changed frozen model/prompt/schema")


def _usage(generation: dict, plan: dict) -> dict:
    metadata = generation["metadata"]
    return {"generation_records": 1,
            "actual_live_provider_submissions": int(metadata["evidence_type"] == "live_model"),
            "offline_fixture_generations": int(metadata["evidence_type"] == "mock"),
            "cache_replays": int(metadata["evidence_type"] == "cache_replay"),
            "input_tokens_recorded": metadata["input_tokens"],
            "output_tokens_recorded": metadata["output_tokens"],
            "token_usage_source": metadata["token_usage_source"],
            "estimated_cost_usd_from_recorded_usage": metadata["estimated_cost_usd"],
            "price_revision": metadata["price_revision"], "price_source": metadata["price_source"],
            "planned_input_token_bound": plan["generation_settings"]["input_token_bound"],
            "planned_output_token_bound": plan["generation_settings"]["max_output_tokens"],
            "budget_matched_to_panel": False,
            "reference_panel_call_counts": {"six_member_full": 24, "six_member_independent": 12},
            "comparison_scope": "one call with all initial inputs; no generated peer deliberation"}


class ComparatorForecaster:
    def __init__(self, client: LLMClient, logger: TranscriptLogger, *, source_root: str | Path = ROOT,
                 corpus_manifest_path: str | Path | None = None):
        self.client, self.logger = client, logger
        self.source_root = Path(source_root).resolve()
        self.corpus_manifest_path = Path(corpus_manifest_path) if corpus_manifest_path else None
        self._pending: dict[str, dict] = {}

    def _snapshot(self, snapshot):
        validated = MacroMeetingSnapshot.model_validate(snapshot.model_dump())
        provider = self.client.provider
        if validated.input_track == "source_linked":
            validated.verify_sources(self.source_root)
        elif validated.input_track == "counterfactual":
            raw = validated.intervention.get("parent_snapshot")
            if not isinstance(raw, dict):
                raise GenerationProvenanceError("Counterfactual requires retained parent")
            parent = self._snapshot(MacroMeetingSnapshot.model_validate(raw))
            parent_hash = content_hash(parent.model_dump(mode="json"))
            changed = validated.intervention.get("changed_fields")
            if (not isinstance(changed, dict) or set(changed) - set(OBSERVABLE_FIELDS)
                    or parent_hash != validated.parent_snapshot_hash
                    or parent_hash != validated.intervention.get("parent_snapshot_hash")):
                raise GenerationProvenanceError("Counterfactual parent/change hash differs")
            expected = parent.model_dump(mode="json")
            expected.update(changed)
            expected.update(input_track="counterfactual", parent_snapshot_hash=parent_hash,
                            intervention=validated.intervention)
            if expected != validated.model_dump(mode="json"):
                raise GenerationProvenanceError("Undeclared counterfactual change")
        elif provider != "mock":
            raise GenerationProvenanceError("Live comparator requires source-linked inputs")
        return validated

    def _validate_inputs(self, snapshot, roster, mode, personas):
        validated = self._snapshot(snapshot)
        declared = _roster(roster)
        if not declared.valid_from <= validated.meeting_date <= declared.valid_through:
            raise GenerationProvenanceError("Meeting is outside declared roster dates")
        if mode not in ("joint_persona", "macro_only"):
            raise GenerationProvenanceError("Unknown comparator mode")
        if mode == "macro_only":
            if personas:
                raise GenerationProvenanceError("Macro-only control must not receive personas")
            fitted = []
        else:
            fitted = [MemberPersona.model_validate(p.model_dump()) for p in personas]
            if [(p.member_id, p.name, p.role, p.is_internal) for p in fitted] != [
                    (p.member_id, p.member_name, p.role, p.is_internal) for p in declared.members]:
                raise GenerationProvenanceError("Personas must match the complete ordered dated roster")
            # Dated profiles are verified even in mock probes. Assumed/legacy
            # inputs are allowed only as explicitly labeled offline fixtures.
            if self.client.provider != "mock" or any(p.provenance_status == "dated_corpus" for p in fitted):
                verify_personas(fitted, validated.information_cutoff, source_root=self.source_root,
                                corpus_manifest_path=self.corpus_manifest_path)
        return validated, declared, fitted

    def _source_hashes(self, snapshot, personas):
        files = {}
        def add(path):
            path = Path(path).resolve()
            if not path.is_relative_to(self.source_root) or not path.is_file():
                raise GenerationProvenanceError("Comparator source file missing/outside declared source root")
            files[str(path.relative_to(self.source_root))] = file_hash(path)
        def observation(item):
            add(self.source_root / item.source_file)
            for child in item.input_evidence:
                observation(child)
        parent = snapshot
        while parent.input_track == "counterfactual":
            parent = MacroMeetingSnapshot.model_validate(parent.intervention["parent_snapshot"])
        if parent.input_track == "source_linked":
            for item in parent.observations:
                observation(item)
        for persona in personas:
            if persona.provenance_status != "dated_corpus":
                continue
            path = self.corpus_manifest_path or self.source_root / "personas" / f"calibration_{persona.calibration_cutoff}_v2" / "corpus_manifest.json"
            add(path)
            member = strict_json(path.read_text())["members"][persona.member_id]
            for row in member["corpus_sources"]:
                for key in ("source_file", "statement_file"):
                    add(self.source_root / row[key])
        return files

    def freeze(self, snapshot: MacroMeetingSnapshot, roster: ComparatorRoster, *, mode: ControlMode,
               personas: Sequence[MemberPersona] = (), experiment_id: str, condition_id: str,
               replicate_id: int, model: str, temperature: float, seed: int,
               max_output_tokens: int, input_token_bound: int | None = None,
               model_epoch: str | None = None, mask_date: bool = False, mask_identity: bool = False,
               fragmentation_policy: str = "reject") -> FrozenComparatorRequest:
        validated, declared, fitted = self._validate_inputs(snapshot, roster, mode, personas)
        if any(type(value) is not bool for value in (mask_date, mask_identity)):
            raise GenerationProvenanceError("Comparator masks must be booleans")
        if (type(replicate_id) is not int or replicate_id < 1 or type(seed) is not int
                or type(max_output_tokens) is not int or max_output_tokens <= 0
                or not isinstance(model, str) or not model.strip()
                or type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise GenerationProvenanceError("Invalid frozen generation settings")
        if fragmentation_policy not in ("reject", "legacy_synthetic", "status_quo"):
            raise GenerationProvenanceError("Unknown comparator fragmentation policy")
        safe_component(experiment_id)
        safe_component(condition_id)
        if self.logger.experiment_id != experiment_id or self.logger.condition_id != condition_id:
            raise GenerationProvenanceError("Comparator logger identity differs from planned experiment/condition")
        aliases = {}
        if mask_identity:
            tokens = [token.casefold() for m in declared.members for token in (m.member_id, m.member_name)]
            if len(set(tokens)) != len(tokens):
                raise GenerationProvenanceError("Masked roster needs distinct IDs/names ignoring case")
            reserved = {CONTROL_ID, *(f"member_{i}" for i in range(1, 7)),
                        *(f"simulated member {i}" for i in range(1, 7))}
            if set(tokens) & reserved:
                raise GenerationProvenanceError("Masked roster collides with comparator or alias identifiers")
            for index, member in enumerate(declared.members, 1):
                # Identical mapping to DebateOrchestrator.run_meeting.
                aliases[member.member_id] = f"member_{index}"
                aliases[member.member_name] = f"Simulated Member {index}"
        prompt_roster = [{"member_id": aliases.get(m.member_id, m.member_id),
                          "member_name": aliases.get(m.member_name, m.member_name),
                          "role": m.role, "is_internal": m.is_internal} for m in declared.members]
        user = (DebateOrchestrator._build_temporal_boundary_header(validated.meeting_date) + "\n\n"
                + validated.to_prompt_text(mask_date=mask_date) + "\n\n"
                + "ORDERED FULL ROSTER (six-member institutional assumption):\n" + canonical_json(prompt_roster)
                + "\nGovernor ID: " + aliases.get(declared.governor_id, declared.governor_id))
        if mode == "joint_persona":
            user += "\n\nSUPPLIED MEMBER PROMPTS (same initial persona information as the panel):\n"
            user += "\n\n".join(p.build_system_prompt(mask_identity=mask_identity) for p in fitted)
        else:
            user += "\n\nNo supplied person-specific preferences, scores, biography, themes or statements."
        user += ("\n\nMake a joint forecast using only these supplied initial inputs. Do not recall historical outcomes, "
                 "invent missing observations, official/confidential forecasts or generated peer exchanges. "
                 "Forecast committee exact rate change and stance, and one formal ballot per roster member in declared order. "
                 f"Rate menu: {RATE_ACTIONS_BPS}; stance menu ({declared.stance_vocabulary_version}): {STANCE_ACTIONS}. "
                 "Predicted rate_choice_disagreement means a ballot different from the predicted committee exact rate; "
                 "formal_stance_dissent means a formal stance ballot different from the predicted committee stance. "
                 "Reservations and guidance disagreements are distinct and are not these targets. "
                 "Use the same committee resolver: strict majority; Governor casting vote only for a two-option 3:3 equality; "
                 f"other fragmentation policy={fragmentation_policy}, status quo rate change=0 and stance={validated.prev_stance}. "
                 "The committee and dissent fields must be consistent with the predicted ballots. "
                 "Return only JSON matching this schema; no fallback:\n" + canonical_json(JointForecastOutput.model_json_schema()))
        system = "You are one joint committee forecaster in a simulation. Follow supplied evidence, roster, action menu and output contract."
        user = DebateOrchestrator._replace_identity_tokens(user, aliases)
        if mask_date:
            user = re.sub(r"\b(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?\b", "[date masked]", user)
            system = re.sub(r"\b(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?\b", "[date masked]", system)
        if input_token_bound is None:
            input_token_bound = len(canonical_json({"system": system, "user": user,
                                    "schema": JointForecastOutput.model_json_schema()}).encode()) + 8192
        if type(input_token_bound) is not int or input_token_bound < 0:
            raise GenerationProvenanceError("Input token reservation must be a nonnegative integer")
        model_epoch = model_epoch or self.client.cfg.run.model_epoch
        settings = {"provider": self.client.provider, "model": model, "temperature": temperature,
                    "seed": planned_seed(seed, validated.meeting_date, replicate_id, CONTROL_ID, 1),
                    "max_output_tokens": max_output_tokens, "input_token_bound": input_token_bound,
                    "model_epoch": model_epoch, "parser_version": "strict-json-v1"}
        if self.client.provider != "mock" and not model_epoch:
            raise GenerationProvenanceError("Live comparator requires an explicit model epoch")
        identity = normalize_request_identity({**self.logger.identity, "experiment_id": experiment_id,
                    "condition_id": condition_id, "meeting_date": validated.meeting_date,
                    "replicate_id": replicate_id, "member_id": CONTROL_ID, "round_number": 1,
                    "control_mode": mode, "roster_hash": content_hash(declared.model_dump(mode="json")),
                    "snapshot_hash": content_hash(validated.model_dump(mode="json")),
                    "persona_hash": content_hash([p.model_dump(mode="json") for p in fitted]),
                    "generation_settings_hash": content_hash(settings)}, required=True)
        # Frozen logger anchors must not silently be overwritten.
        if any(identity.get(key) != value for key, value in self.logger.identity.items()):
            raise GenerationProvenanceError("Frozen comparator logger fields conflict")
        plan = {"contract_version": CONTRACT_VERSION, "control_mode": mode, "identity": identity,
                "snapshot": validated.model_dump(mode="json"), "roster": declared.model_dump(mode="json"),
                "personas": [p.model_dump(mode="json") for p in fitted], "generation_settings": settings,
                "seed_base": seed, "mask_date": mask_date, "mask_identity": mask_identity,
                "fragmentation_policy": fragmentation_policy, "identity_aliases": aliases,
                "source_hashes": self._source_hashes(validated, fitted),
                "code_hashes": {name: file_hash(ROOT / name) for name in DEPENDENCIES},
                "user_prompt": user, "system_prompt": system, "budget_matched_to_panel": False}
        digest = content_hash(plan)
        path = self.logger.run_dir / condition_id / "comparator_requests" / validated.meeting_date / f"rep_{replicate_id}" / "frozen_request.json"
        write_immutable(path, {"plan": plan, "plan_hash": digest})
        frozen = FrozenComparatorRequest(canonical_json(plan), digest, str(path))
        self._pending[digest] = {"snapshot": snapshot, "roster": roster, "personas": personas,
                                 "provider": self.client.provider, "used": False,
                                 "run_settings": content_hash(self.client.cfg.run.model_dump()),
                                 "source_root": self.source_root, "corpus_manifest_path": self.corpus_manifest_path,
                                 "logger_identity": canonical_json(self.logger.identity),
                                 "logger_run_dir": str(self.logger.run_dir), "client": self.client,
                                 "cache_enabled": self.client.cache_enabled, "cache": self.client.cache,
                                 "governor": self.client.governor}
        return frozen

    def _assert_current(self, frozen, *, require_unused=True):
        plan = frozen.plan
        pending = self._pending.get(frozen.plan_hash)
        if (pending is None or (require_unused and pending["used"]) or content_hash(plan) != frozen.plan_hash
                or strict_json(Path(frozen.artifact_path).read_text()) != {"plan": plan, "plan_hash": frozen.plan_hash}):
            raise GenerationProvenanceError("Comparator plan missing, changed or already submitted")
        if (self.client is not pending["client"] or self.client.provider != pending["provider"]
                or content_hash(self.client.cfg.run.model_dump()) != pending["run_settings"]
                or self.client.cache_enabled != pending["cache_enabled"] or self.client.cache is not pending["cache"]
                or self.client.governor is not pending["governor"] or str(self.logger.run_dir) != pending["logger_run_dir"]
                or self.source_root != pending["source_root"] or self.corpus_manifest_path != pending["corpus_manifest_path"]
                or canonical_json(self.logger.identity) != pending["logger_identity"]
                or self.logger.experiment_id != plan["identity"]["experiment_id"]
                or self.logger.condition_id != plan["identity"]["condition_id"]):
            raise GenerationProvenanceError("Comparator runtime or logger changed after freeze")
        snapshot, roster, personas = self._validate_inputs(pending["snapshot"], pending["roster"],
                                                         plan["control_mode"], pending["personas"])
        if (snapshot.model_dump(mode="json") != plan["snapshot"] or roster.model_dump(mode="json") != plan["roster"]
                or [p.model_dump(mode="json") for p in personas] != plan["personas"]
                or self._source_hashes(snapshot, personas) != plan["source_hashes"]
                or {name: file_hash(ROOT / name) for name in DEPENDENCIES} != plan["code_hashes"]):
            raise GenerationProvenanceError("Comparator scientific inputs or code changed after freeze")
        return plan, pending

    async def generate(self, frozen: FrozenComparatorRequest) -> dict:
        result = None
        try:
            plan, pending = self._assert_current(frozen)
            pending["used"] = True  # No automatic retry, including after failure/cancellation.
            settings = plan["generation_settings"]
            result = await self.client.generate_with_metadata(
                user_prompt=plan["user_prompt"], system_prompt=plan["system_prompt"],
                response_schema=JointForecastOutput, request_identity=plan["identity"],
                expected_identity={"member_id": CONTROL_ID, "round_number": 1},
                **{key: value for key, value in settings.items() if key != "provider"})
            # Changes during an awaited call invalidate publication too. Retain
            # its receipt in the failure log, without another submission.
            self._assert_current(frozen, require_unused=False)
            if result.parsed is None or result.validation_error:
                raise LLMResponseMalformedError("Comparator yielded no valid structured forecast")
            generation = result.to_dict()
            parsed = validate_generation_evidence(generation)
            _bind_generation(generation, plan)
            prediction = _normalize_forecast(parsed, plan)
            identity = plan["identity"]
            transcript = self.logger.save_round_transcript(
                identity["meeting_date"], identity["replicate_id"], 1, CONTROL_ID, parsed,
                experiment_id=identity["experiment_id"], condition_id=identity["condition_id"],
                generation=generation, prompt={"user_prompt": plan["user_prompt"], "system_prompt": plan["system_prompt"],
                                                "identity_aliases": plan["identity_aliases"]})
            read_transcript(transcript)
            record = {"record_version": CONTRACT_VERSION, "plan_hash": frozen.plan_hash,
                      "frozen_plan": plan, "generation": generation, "prediction": prediction,
                      "usage": _usage(generation, plan), "transcript_path": str(transcript),
                      "transcript_sha256": file_hash(transcript)}
            record["artifact_content_hash"] = content_hash(record)
            path = Path(frozen.artifact_path).parent / "comparator_forecast.json"
            write_immutable(path, record)
            verified = read_comparator_record(path, expected_plan_hash=frozen.plan_hash)
            self.logger.log_event("comparator_completed", {"plan_hash": frozen.plan_hash,
                                  "evidence_type": generation["metadata"]["evidence_type"], "record": str(path)})
            return verified
        except BaseException as error:
            try:
                self.logger.log_event("comparator_failed", {"plan_hash": frozen.plan_hash,
                    "error_type": type(error).__name__, "error": str(error),
                    "failure_context": getattr(error, "context", {}),
                    "generation": result.to_dict() if result is not None else None})
            except BaseException as logging_error:
                error.add_note(f"Could not retain comparator failure: {logging_error}")
                raise error from logging_error
            raise
