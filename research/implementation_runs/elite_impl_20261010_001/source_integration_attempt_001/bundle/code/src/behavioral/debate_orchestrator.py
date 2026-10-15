"""A declared four-round simulator, not a reconstruction of actual MPC procedure.

Full deliberation exposes R1-R3 and each member's own state to the binding vote.
Earlier-round control runs the same calls but withholds R3 from R4. Independent
control runs only R1 and R4 (12 rather than 24 calls). Governor-last visibility,
peer identity and outgoing-member removal are explicit simulation interventions.
No heuristic or invented official/confidential forecast replaces evidence.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Literal, Optional, Sequence, Any

from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import (
    InitialStanceOutput, DeliberationOutput, FinalVoteOutput, MeetingCommitteeDecision,
    StrictRoundOutput, validate_member_output,
)
from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.infra.exceptions import LLMResponseMalformedError, GenerationProvenanceError
from src.infra.evidence import content_hash
from src.persona_engine.provenance import verify_personas
from src.rule_engine.engine import InstitutionalRuleEngine

ControlMode = Literal["full", "earlier_rounds", "independent"]


@dataclass(frozen=True)
class InformationVisibility:
    """Donor's information to other agents is blocked; own vote still counts."""
    peer_arguments: bool = True
    peer_identity: bool = True
    governor_ballots: bool = True
    own_state: bool = True
    ablated_member_id: Optional[str] = None

    def __post_init__(self):
        for key in ("peer_arguments", "peer_identity", "governor_ballots", "own_state"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"Visibility {key} must be a boolean")
        if self.ablated_member_id is not None and (not isinstance(self.ablated_member_id, str) or not self.ablated_member_id.strip()):
            raise ValueError("Ablated member identity must be nonempty text")


def planned_seed(seed_base: int, meeting_date: str, replicate_id: int, member_id: str, round_number: int) -> int:
    """Distinct member/round/replicate seeds; matched conditions intentionally share them."""
    encoded = json.dumps(["paired-member-round-v1", seed_base, meeting_date, replicate_id, member_id, round_number], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(encoded.encode()).digest()[:4], "big") & 0x7FFFFFFF


class DebateOrchestrator:
    def __init__(self, llm_client: Optional[LLMClient] = None, logger: Optional[TranscriptLogger] = None):
        self.client = llm_client or LLMClient()
        self.logger = logger or TranscriptLogger()

    def generation_settings(self, model: Optional[str] = None, temperature: Optional[float] = None) -> dict[str, Any]:
        """Freeze settings before a condition rather than resolving defaults per call.

        A scripted test client may not expose configuration; its unresolved values
        stay explicit None. Production LLMClient supplies the complete run settings.
        Served-model identity still comes from each generation receipt, not here.
        """
        run = getattr(getattr(self.client, "cfg", None), "run", None)
        schemas = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}
        return {"provider": getattr(self.client, "provider", "mock"),
                "model": model if model is not None else getattr(run, "dev_model", None),
                "temperature": temperature if temperature is not None else getattr(run, "temperature", None),
                "model_epoch": getattr(run, "model_epoch", None),
                "max_output_tokens": getattr(run, "max_output_tokens", None),
                "parser_version": "strict-json-v1",
                "round_schema_hashes": {str(number): content_hash(schema.model_json_schema()) for number, schema in schemas.items()}}

    def _validate_snapshot(self, snapshot: MacroMeetingSnapshot, *, source_root=None) -> MacroMeetingSnapshot:
        snapshot = type(snapshot).model_validate(snapshot.model_dump())
        if snapshot.input_track == "source_linked":
            snapshot.verify_sources(**({"root": source_root} if source_root is not None else {}))
        provider = getattr(self.client, "provider", "mock")
        if snapshot.input_track == "source_linked" or (provider == "mock" and snapshot.input_track != "counterfactual"):
            return snapshot
        if snapshot.input_track != "counterfactual":
            raise GenerationProvenanceError("Live research generation requires source-linked inputs")
        parent_data = snapshot.intervention.get("parent_snapshot")
        if not isinstance(parent_data, dict):
            raise GenerationProvenanceError("Live counterfactual requires retained source-linked parent")
        try:
            parent = type(snapshot).model_validate(parent_data)
        except ValueError as exc:
            raise GenerationProvenanceError("Counterfactual parent snapshot is invalid") from exc
        if provider != "mock" and parent.input_track != "source_linked":
            raise GenerationProvenanceError("Live counterfactual parent must be source-linked")
        if parent.input_track == "source_linked":
            parent.verify_sources(**({"root": source_root} if source_root is not None else {}))
        elif parent.input_track == "counterfactual":
            self._validate_snapshot(parent, source_root=source_root)
        parent_hash = hashlib.sha256(json.dumps(parent.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if parent_hash != snapshot.parent_snapshot_hash or parent_hash != snapshot.intervention.get("parent_snapshot_hash"):
            raise GenerationProvenanceError("Counterfactual parent hash mismatch")
        changed = snapshot.intervention.get("changed_fields")
        if not isinstance(changed, dict) or set(changed) - set(OBSERVABLE_FIELDS):
            raise GenerationProvenanceError("Counterfactual changed fields must be declared observables")
        expected = parent.model_dump(mode="json")
        expected.update(changed)
        expected.update(input_track="counterfactual", parent_snapshot_hash=parent_hash, intervention=snapshot.intervention)
        if expected != snapshot.model_dump(mode="json"):
            raise GenerationProvenanceError("Counterfactual differs from declared parent intervention")
        return snapshot

    @staticmethod
    def _replace_identity_tokens(text: str, substitutions: dict[str, str]) -> str:
        """Replace known identity text once, case-insensitively, without cascading.

        Names may occur inside free-form supplied themes and generated rationales.
        This is direct text masking, not proof that latent identity is unguessable.
        """
        if not substitutions:
            return text
        normalized = {key.casefold(): value for key, value in substitutions.items()}
        tokens = sorted(substitutions, key=len, reverse=True)
        pattern = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(token) for token in tokens) + r")(?![A-Za-z0-9])", re.IGNORECASE)
        return pattern.sub(lambda match: normalized[match.group().casefold()], text)

    @staticmethod
    def _anonymize_peer_entry(entry: dict[str, Any], personas: Sequence[MemberPersona]) -> dict[str, Any]:
        result = dict(entry)
        identities = {token for p in personas for token in (p.member_id, p.name)}
        roles = {p.role for p in personas}
        substitutions = {**{token: "[member identity hidden]" for token in identities},
                         **{role: "[role hidden]" for role in roles}}
        for key, value in result.items():
            if isinstance(value, str):
                result[key] = DebateOrchestrator._replace_identity_tokens(value, substitutions)
        return result

    @staticmethod
    def _round_context(
        outputs: dict[int, dict[str, StrictRoundOutput]], rounds: Sequence[int],
        recipient: MemberPersona, personas: Sequence[MemberPersona], visibility: InformationVisibility,
    ) -> str:
        """Construct every recipient's context from the same explicit visibility graph."""
        blocks = []
        for round_number in rounds:
            results = outputs.get(round_number, {})
            if visibility.own_state and recipient.member_id in results:
                own = results[recipient.member_id].model_dump(exclude={"fallback_triggered"})
                blocks.append(f"YOUR OWN ROUND {round_number} STATE:\n" + json.dumps(own, sort_keys=True))
            if not visibility.peer_arguments:
                continue
            peers = []
            for idx, p in enumerate(personas):
                if p.member_id in (recipient.member_id, visibility.ablated_member_id) or p.member_id not in results:
                    continue
                entry = results[p.member_id].model_dump(exclude={"fallback_triggered", "dissenting_on_rate", "dissenting_on_stance"})
                if visibility.peer_identity:
                    entry["role"] = p.role
                else:
                    for key in ("member_id", "member_name", "is_internal", "role"):
                        entry.pop(key, None)
                    entry["sender"] = f"peer_{idx + 1}"
                    entry = DebateOrchestrator._anonymize_peer_entry(entry, personas)
                peers.append(entry)
            blocks.append(f"VISIBLE PEER ROUND {round_number} ARGUMENTS:\n" + json.dumps(peers, sort_keys=True))
        return "\n\n".join(blocks)

    @staticmethod
    def _governor_ballot_context(
        votes: Sequence[FinalVoteOutput], personas: Sequence[MemberPersona], visibility: InformationVisibility,
    ) -> str:
        if not visibility.governor_ballots:
            return ""
        rows = []
        order = {p.member_id: idx + 1 for idx, p in enumerate(personas)}
        for vote in votes:
            if vote.member_id == visibility.ablated_member_id:
                continue
            row = vote.model_dump(exclude={"fallback_triggered", "dissenting_on_rate", "dissenting_on_stance"})
            # Ballot visibility is separate from argument visibility.
            if not visibility.peer_arguments:
                row.pop("official_statement_rationale", None)
            if not visibility.peer_identity:
                for key in ("member_id", "member_name", "is_internal"):
                    row.pop(key, None)
                row["sender"] = f"peer_{order[vote.member_id]}"
                row = DebateOrchestrator._anonymize_peer_entry(row, personas)
            rows.append(row)
        return "VISIBLE NON-GOVERNOR BINDING BALLOTS (SIMULATION CHOICE):\n" + json.dumps(rows, sort_keys=True)

    @staticmethod
    def _build_temporal_boundary_header(meeting_date: str) -> str:
        return (
            f"INFORMATION CUTOFF: use only supplied information available for {meeting_date}.\n"
            "This is a historical simulation. Do not use your knowledge of later outcomes. "
            "This instruction does not establish that the underlying model is uncontaminated."
        )

    async def _generate_round(
        self, persona: MemberPersona, snapshot: MacroMeetingSnapshot, round_number: int,
        context: str, *, model: Optional[str], temperature: Optional[float], seed: int,
        identity: dict[str, Any], mask_identity: bool = False, mask_date: bool = False,
        identity_aliases: Optional[dict[str, str]] = None,
        generation_settings: Optional[dict[str, Any]] = None,
    ) -> tuple[StrictRoundOutput, str]:
        schema = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}[round_number]
        examples = {
            1: {"member_id": persona.member_id, "member_name": persona.name, "proposed_rate_change_bps": 0,
                "proposed_stance": snapshot.prev_stance, "key_rationale": "Reason from supplied information."},
            2: {"member_id": persona.member_id, "round_number": 2, "current_rate_preference_bps": 0,
                "current_stance_preference": snapshot.prev_stance, "rebuttal_or_critique": "Assess visible evidence.", "open_to_compromise": False},
            3: {"member_id": persona.member_id, "round_number": 3, "current_rate_preference_bps": 0,
                "current_stance_preference": snapshot.prev_stance, "rebuttal_or_critique": "Update your preference from visible evidence.", "open_to_compromise": False},
            4: {"member_id": persona.member_id, "member_name": persona.name, "is_internal": persona.is_internal,
                "final_rate_vote_bps": 0, "final_stance_vote": snapshot.prev_stance,
                "dissenting_on_rate": False, "dissenting_on_stance": False,
                "official_statement_rationale": "Simulated signed rationale from supplied evidence."},
        }
        tasks = {1: "Initial independent preference", 2: "Rebuttal and cross-examination",
                 3: "Deliberation and updated preference", 4: "Binding simulator ballot"}
        user_prompt = (
            self._build_temporal_boundary_header(snapshot.meeting_date) + "\n\n" + snapshot.to_prompt_text(mask_date=mask_date) + "\n\n" + context +
            f"\n\nTASK: Round {round_number} — {tasks[round_number]}.\n"
            "Ground your reasoning only in supplied information. Missing information remains missing. "
            "Do not invent staff forecasts, colleagues' views or official/confidential data. "
            "Keep your own judgment; agreement and dissent are both permitted. "
            f"The simulator rate menu is {RATE_ACTIONS_BPS}; stance menu is {STANCE_ACTIONS}.\n"
            "OUTPUT STRICT JSON FORMAT ONLY, using these fields:\n" + json.dumps(examples[round_number], indent=2)
        )
        system_prompt = persona.build_system_prompt(mask_identity=mask_identity)
        aliases = identity_aliases or {}
        if mask_identity:
            user_prompt = self._replace_identity_tokens(user_prompt, aliases)
            system_prompt = self._replace_identity_tokens(system_prompt, aliases)
        if mask_date:
            user_prompt = re.sub(r"\b(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?\b", "[date masked]", user_prompt)
            system_prompt = re.sub(r"\b(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?\b", "[date masked]", system_prompt)
        expected = {"member_id": persona.member_id}
        if round_number in (1, 4):
            expected["member_name"] = persona.name
        if round_number == 4:
            expected["is_internal"] = persona.is_internal
        if round_number in (2, 3):
            expected["round_number"] = round_number
        if mask_identity:
            expected["member_id"] = aliases[persona.member_id]
            if "member_name" in expected:
                expected["member_name"] = aliases[persona.name]
        try:
            result = await self.client.generate_with_metadata(
                user_prompt=user_prompt, system_prompt=system_prompt, model=model,
                temperature=temperature, seed=seed, response_schema=schema,
                request_identity=identity, expected_identity=expected,
                **{key: value for key, value in (generation_settings or {}).items()
                   if key in ("max_output_tokens", "model_epoch", "parser_version")},
            )
            if result.parsed is None or result.validation_error:
                raise LLMResponseMalformedError("Generation did not yield a valid research round", context=identity)
            output = validate_member_output(result.parsed, member_id=expected["member_id"], member_name=expected.get("member_name"),
                                            is_internal=persona.is_internal, round_number=round_number)
            if mask_identity:
                output.member_id = persona.member_id
                if hasattr(output, "member_name"):
                    output.member_name = persona.name
            # Metadata preserves raw alias output; normalized payload restores the planned roster for joins.
            self.logger.save_round_transcript(
                meeting_date=snapshot.meeting_date, replicate_id=identity["replicate_id"],
                round_number=round_number, member_id=persona.member_id, payload=output.model_dump(),
                experiment_id=identity["experiment_id"], condition_id=identity["condition_id"],
                generation=result.to_dict(), prompt={"user_prompt": user_prompt, "system_prompt": system_prompt,
                                                     "identity_aliases": aliases if mask_identity else {}},
            )
            metadata = result.metadata
            evidence_type = metadata.get("evidence_type", "unreported") if isinstance(metadata, dict) else getattr(metadata, "evidence_type", "unreported")
            return output, evidence_type
        except BaseException as error:
            # Cancellation and terminal budget/provider failures propagate without additional submissions.
            try:
                self.logger.log_event("generation_failed", {**identity, "error_type": type(error).__name__, "error": str(error),
                                                             "failure_context": getattr(error, "context", {})})
            except BaseException as logging_error:
                error.add_note(f"Failure event could not be retained: {type(logging_error).__name__}: {logging_error}")
                raise error from logging_error
            raise

    async def run_meeting(
        self, snapshot: MacroMeetingSnapshot, personas: Sequence[MemberPersona], governor_id: str,
        replicate_id: int = 1, model: Optional[str] = None, temperature: Optional[float] = None,
        ablated_member_id: Optional[str] = None, *, experiment_id: str = "legacy",
        condition_id: Optional[str] = None, control_mode: ControlMode = "full",
        visibility: Optional[InformationVisibility] = None, seed: int = 42,
        fragmentation_policy: str = "reject",
        mask_identity: bool = False, mask_date: bool = False,
    ) -> MeetingCommitteeDecision:
        """Run a fail-closed condition. Sequential calls stop immediately on terminal failure."""
        snapshot = self._validate_snapshot(snapshot)
        personas = [MemberPersona.model_validate(p.model_dump()) for p in personas]
        if len(personas) != 6 or len({p.member_id for p in personas}) != 6:
            raise ValueError("Full-roster simulation requires exactly 6 distinct member personas")
        if any(not p.member_id.strip() or not p.name.strip() for p in personas):
            raise ValueError("Member identities and names must be nonempty")
        if governor_id not in {p.member_id for p in personas}:
            raise ValueError("Governor must be among the simulated personas")
        if getattr(self.client, "provider", "mock") != "mock":
            personas = verify_personas(personas, snapshot.information_cutoff)
        if control_mode not in ("full", "earlier_rounds", "independent"):
            raise ValueError("Unknown deliberation control mode")
        if type(replicate_id) is not int or replicate_id < 1 or type(seed) is not int:
            raise ValueError("Replicate must be a positive integer and seed an integer")
        if type(mask_identity) is not bool or type(mask_date) is not bool:
            raise ValueError("Identity and date masking must be boolean controls")
        if fragmentation_policy not in ("reject", "legacy_synthetic", "status_quo"):
            raise ValueError("Unknown fragmentation policy")
        if visibility is not None and not isinstance(visibility, InformationVisibility):
            raise ValueError("Visibility must use the declared InformationVisibility contract")
        visibility = visibility or InformationVisibility()
        if ablated_member_id is not None:
            if visibility.ablated_member_id not in (None, ablated_member_id):
                raise ValueError("Conflicting outgoing-member interventions")
            visibility = replace(visibility, ablated_member_id=ablated_member_id)
        if visibility.ablated_member_id is not None and visibility.ablated_member_id not in {p.member_id for p in personas}:
            raise ValueError("Ablated member must belong to the simulated roster")
        if control_mode == "independent":
            visibility = replace(visibility, peer_arguments=False, governor_ballots=False)
        declared_visibility = {**asdict(visibility), "mask_identity": mask_identity, "mask_date": mask_date}
        settings = self.generation_settings(model=model, temperature=temperature)
        snapshot_hash = content_hash(snapshot.model_dump(mode="json"))
        persona_hash = content_hash([p.model_dump(mode="json") for p in personas])
        frozen_identity = getattr(self.logger, "identity", {})
        condition_identity = {"experiment_id": experiment_id, "persona_hash": persona_hash,
                              "snapshot_hash": snapshot_hash, "generation_settings_hash": content_hash(settings)}
        for key, value in condition_identity.items():
            if key in frozen_identity and frozen_identity[key] != value:
                raise GenerationProvenanceError(f"Frozen logger {key} differs from planned condition")
        identity_aliases = {}
        if mask_identity:
            tokens = [token.casefold() for p in personas for token in (p.member_id, p.name)]
            if len(set(tokens)) != len(tokens):
                raise ValueError("Masked roster needs distinct member identities and names ignoring case")
            for idx, persona in enumerate(personas):
                identity_aliases[persona.member_id] = f"member_{idx + 1}"
                identity_aliases[persona.name] = f"Simulated Member {idx + 1}"
        if condition_id is None:
            # Visibility changes cannot accidentally overwrite the full condition's traces.
            baseline_visibility = InformationVisibility()
            suffix = "" if visibility == baseline_visibility and not mask_identity and not mask_date else "_" + hashlib.sha256(json.dumps(declared_visibility, sort_keys=True).encode()).hexdigest()[:12]
            condition_id = control_mode + suffix
        outputs: dict[int, dict[str, StrictRoundOutput]] = {}
        seeds: dict[str, int] = {}
        evidence_types: set[str] = set()
        rounds = (1, 4) if control_mode == "independent" else (1, 2, 3, 4)
        # A deterministic submission order prevents asyncio.gather from continuing a failed condition.
        ordered_personas = [p for p in personas if p.member_id != governor_id] + [p for p in personas if p.member_id == governor_id]
        for round_number in rounds:
            outputs[round_number] = {}
            for persona in ordered_personas:
                visible_rounds = [r for r in rounds if r < round_number]
                if round_number == 4 and control_mode == "earlier_rounds":
                    visible_rounds = [1, 2]
                context = self._round_context(outputs, visible_rounds, persona, personas, visibility)
                if round_number == 4 and persona.member_id == governor_id:
                    ballots = self._governor_ballot_context(list(outputs[4].values()), personas, visibility)
                    context += "\n\n" + ballots if ballots else ""
                request_seed = planned_seed(seed, snapshot.meeting_date, replicate_id, persona.member_id, round_number)
                seeds[f"{persona.member_id}:round_{round_number}"] = request_seed
                identity = {**getattr(self.logger, "identity", {}), "experiment_id": experiment_id, "condition_id": condition_id,
                            "meeting_date": snapshot.meeting_date, "replicate_id": replicate_id,
                            "member_id": persona.member_id, "round_number": round_number,
                            "snapshot_hash": snapshot_hash, "persona_hash": persona_hash,
                            "generation_settings_hash": content_hash(settings)}
                if mask_identity:
                    identity["output_member_id"] = identity_aliases[persona.member_id]
                output, evidence_type = await self._generate_round(
                    persona, snapshot, round_number, context, model=settings["model"], temperature=settings["temperature"],
                    seed=request_seed, identity=identity, mask_identity=mask_identity, mask_date=mask_date,
                    identity_aliases=identity_aliases, generation_settings=settings,
                )
                outputs[round_number][persona.member_id] = output
                evidence_types.add(evidence_type)
        final_votes = list(outputs[4].values())
        rate = InstitutionalRuleEngine.aggregate_rate_votes(
            {v.member_id: v.final_rate_vote_bps for v in final_votes}, governor_id,
            fragmentation_policy=fragmentation_policy, prior_action=0,
        )
        stance = InstitutionalRuleEngine.aggregate_stance_votes(
            {v.member_id: v.final_stance_vote for v in final_votes}, governor_id,
            fragmentation_policy=fragmentation_policy, prior_action=snapshot.prev_stance,
        )
        for vote in final_votes:
            vote.dissenting_on_rate = vote.member_id in rate.dissenting_members
            vote.dissenting_on_stance = vote.member_id in stance.dissenting_members
        decision = MeetingCommitteeDecision(
            meeting_date=snapshot.meeting_date, replicate_id=replicate_id,
            rate_decision_bps=rate.winning_action, stance_decision=stance.winning_action,
            rate_vote_tally=rate.vote_tally, stance_vote_tally=stance.vote_tally,
            tie_broken_by_governor_rate=rate.tie_broken_by_governor,
            tie_broken_by_governor_stance=stance.tie_broken_by_governor,
            dissenting_members_rate=rate.dissenting_members, dissenting_members_stance=stance.dissenting_members,
            member_votes=final_votes, prior_stance=snapshot.prev_stance,
            experiment_id=experiment_id, condition_id=condition_id, control_mode=control_mode,
            visibility=declared_visibility, seed_schedule=seeds, seed_base=seed, generation_count=len(seeds),
            governor_id=governor_id, snapshot_hash=snapshot_hash, persona_hash=persona_hash, generation_settings=settings,
            evidence_types=sorted(evidence_types), input_track=getattr(snapshot, "input_track", "legacy_unverified"),
            rate_resolution_policy=rate.resolution_policy, stance_resolution_policy=stance.resolution_policy,
            synthetic_resolution_rate=rate.synthetic_resolution, synthetic_resolution_stance=stance.synthetic_resolution,
            fragmentation_policy=fragmentation_policy,
        )
        self.logger.save_meeting_summary(snapshot.meeting_date, replicate_id, decision.model_dump(),
                                         experiment_id=experiment_id, condition_id=condition_id)
        return decision
