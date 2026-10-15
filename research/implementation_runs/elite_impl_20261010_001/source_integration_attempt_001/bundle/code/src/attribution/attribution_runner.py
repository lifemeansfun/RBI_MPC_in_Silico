"""Declared removal sensitivities identify effects inside this simulator only."""

from typing import Sequence, Optional
from dataclasses import dataclass, field

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import MeetingCommitteeDecision
from src.schemas.decision_space import STANCE_ACTIONS
from src.behavioral.debate_orchestrator import DebateOrchestrator, InformationVisibility
from src.infra.evidence import content_hash
from src.scenarios.scenario_runner import apply_snapshot_intervention


@dataclass
class AttributionResult:
    experiment_id: str
    experiment_name: str
    baseline_decision_bps: int
    ablated_decision_bps: int
    baseline_stance: str
    ablated_stance: str
    outcome_shifted: bool
    marginal_contribution_bps: int
    description: str
    estimand_scope: str = "simulator_local"
    donor_behavior: str = "not_applicable"
    condition_id: str = ""
    replicate_id: int = 1
    member_rate_changes_bps: dict[str, int] = field(default_factory=dict)
    member_stance_changed: dict[str, bool] = field(default_factory=dict)
    study_experiment_id: str = ""
    baseline_condition_id: str = ""
    evidence_types: list[str] = field(default_factory=list)


class AttributionRunner:
    @staticmethod
    def _paired_generation_settings(orchestrator, baseline, snapshot, personas, governor_id,
                                    model, temperature, seed):
        """Reject a mismatched intervention before any new generation is submitted.

        Historical decisions remain readable, but without frozen input/settings
        identities they cannot qualify as a paired mechanism experiment.
        """
        if not baseline.snapshot_hash or not baseline.persona_hash or not baseline.generation_settings or not baseline.governor_id:
            raise ValueError("Attribution baseline lacks frozen paired input and generation identities")
        validated_snapshot = type(snapshot).model_validate(snapshot.model_dump())
        if content_hash(validated_snapshot.model_dump(mode="json")) != baseline.snapshot_hash:
            raise ValueError("Attribution snapshot differs from the frozen baseline")
        if content_hash([p.model_dump(mode="json") for p in personas]) != baseline.persona_hash:
            raise ValueError("Attribution personas differ from the frozen baseline")
        if governor_id != baseline.governor_id:
            raise ValueError("Attribution Governor differs from the frozen baseline")
        selected_seed = baseline.seed_base if seed is None else seed
        if type(selected_seed) is not int or selected_seed != baseline.seed_base:
            raise ValueError("Attribution seed differs from the paired baseline schedule")
        frozen = baseline.generation_settings
        selected_model = frozen["model"] if model is None else model
        selected_temperature = frozen["temperature"] if temperature is None else temperature
        current = orchestrator.generation_settings(selected_model, selected_temperature)
        if current != frozen:
            raise ValueError("Attribution generation settings differ from the frozen baseline")
        return {"model": selected_model, "temperature": selected_temperature, "seed": selected_seed}

    @staticmethod
    def _condition_settings(baseline):
        graph = {key: value for key, value in baseline.visibility.items() if key in InformationVisibility.__dataclass_fields__}
        return {"visibility": InformationVisibility(**graph),
                "mask_identity": baseline.visibility.get("mask_identity", False),
                "mask_date": baseline.visibility.get("mask_date", False),
                "fragmentation_policy": baseline.fragmentation_policy}

    @staticmethod
    def ablate_casting_vote(meeting_outcome: MeetingCommitteeDecision, governor_id: str,
                            prior_stance: Optional[str] = None) -> AttributionResult:
        """Remove actual binary casting; status-quo resolution is a synthetic policy.

        Retain the actual pre-meeting stance. A fragmented menu outcome must never
        masquerade as a statutory casting vote, even when its winner is Governor's.
        """
        if meeting_outcome.member_votes and governor_id not in {v.member_id for v in meeting_outcome.member_votes}:
            raise ValueError("Casting removal requires a Governor ballot")
        if meeting_outcome.governor_id is not None and governor_id != meeting_outcome.governor_id:
            raise ValueError("Casting removal Governor differs from the recorded baseline")
        for tie, tally, synthetic in (
            (meeting_outcome.tie_broken_by_governor_rate, meeting_outcome.rate_vote_tally, meeting_outcome.synthetic_resolution_rate),
            (meeting_outcome.tie_broken_by_governor_stance, meeting_outcome.stance_vote_tally, meeting_outcome.synthetic_resolution_stance),
        ):
            if tie and (synthetic or len(tally) != 2 or len(set(tally.values())) != 1 or any(n <= 0 for n in tally.values())):
                raise ValueError("Casting flag must represent binary equality, not synthetic fragmentation")
        if prior_stance is not None and prior_stance not in STANCE_ACTIONS:
            raise ValueError("Casting removal prior stance must use the declared stance domain")
        if prior_stance is not None and meeting_outcome.prior_stance is not None and prior_stance != meeting_outcome.prior_stance:
            raise ValueError("Casting removal prior stance contradicts the recorded baseline")
        prev = meeting_outcome.prior_stance if prior_stance is None else prior_stance
        if meeting_outcome.tie_broken_by_governor_stance and prev not in STANCE_ACTIONS:
            raise ValueError("Casting removal requires the actual prior stance")
        rate = 0 if meeting_outcome.tie_broken_by_governor_rate else meeting_outcome.rate_decision_bps
        stance = prev if meeting_outcome.tie_broken_by_governor_stance else meeting_outcome.stance_decision
        return AttributionResult(
            experiment_id="EXP_2_CASTING_VOTE", experiment_name="Governor Casting-Vote Removal (§45ZI(8))",
            baseline_decision_bps=meeting_outcome.rate_decision_bps, ablated_decision_bps=rate,
            baseline_stance=meeting_outcome.stance_decision, ablated_stance=stance,
            outcome_shifted=(rate != meeting_outcome.rate_decision_bps or stance != meeting_outcome.stance_decision),
            marginal_contribution_bps=meeting_outcome.rate_decision_bps - rate,
            description="Simulator-local numerical casting removal; unresolved equality uses synthetic status quo (0 bps and actual prior stance). Ballots are held fixed.",
            donor_behavior="all_ballots_held_fixed", replicate_id=meeting_outcome.replicate_id,
            condition_id="casting_removed",
            study_experiment_id=meeting_outcome.experiment_id, baseline_condition_id=meeting_outcome.condition_id,
            evidence_types=meeting_outcome.evidence_types if meeting_outcome.member_votes else ["constructed_rule_probe"],
        )

    @staticmethod
    def mute_macro_input(baseline_snapshot: MacroMeetingSnapshot, muted_factor: str) -> MacroMeetingSnapshot:
        if muted_factor == "monsoon":
            return apply_snapshot_intervention(baseline_snapshot, {"monsoon_departure_lpa_pct": 0.0},
                                               "mute_monsoon", {"neutral_departure_pct": 0.0})
        if muted_factor == "food_inflation":
            if baseline_snapshot.cpi_food_yoy_pct is None:
                raise ValueError("Food muting requires an observed food-inflation baseline")
            headline = baseline_snapshot.cpi_headline_yoy_pct
            if headline is not None:
                headline -= (baseline_snapshot.cpi_food_yoy_pct - 4.0) * 0.458
            return apply_snapshot_intervention(baseline_snapshot, {"cpi_headline_yoy_pct": headline, "cpi_food_yoy_pct": 4.0},
                                               "mute_food_inflation", {"assumed_food_reference_pct": 4.0, "food_headline_weight": 0.458})
        raise ValueError(f"Unknown muting factor: {muted_factor}")

    @staticmethod
    def _result(base, treatment, experiment_id, experiment_name, description, donor_behavior="not_applicable"):
        baseline_votes = {v.member_id: v for v in base.member_votes}
        treatment_votes = {v.member_id: v for v in treatment.member_votes}
        if set(baseline_votes) != set(treatment_votes) or len(baseline_votes) != len(base.member_votes) or len(treatment_votes) != len(treatment.member_votes):
            raise ValueError("Attribution requires exactly aligned unique member ballots")
        if base.meeting_date != treatment.meeting_date or base.replicate_id != treatment.replicate_id:
            raise ValueError("Attribution requires paired meeting and replicate identity")
        if base.seed_schedule != treatment.seed_schedule:
            raise ValueError("Attribution requires the same declared paired seed schedule")
        if (base.experiment_id != treatment.experiment_id or base.governor_id != treatment.governor_id
                or base.persona_hash != treatment.persona_hash or base.generation_settings != treatment.generation_settings):
            raise ValueError("Attribution requires matching frozen experiment, roster and generation settings")
        return AttributionResult(
            experiment_id=experiment_id, experiment_name=experiment_name,
            baseline_decision_bps=base.rate_decision_bps, ablated_decision_bps=treatment.rate_decision_bps,
            baseline_stance=base.stance_decision, ablated_stance=treatment.stance_decision,
            outcome_shifted=(base.rate_decision_bps != treatment.rate_decision_bps or base.stance_decision != treatment.stance_decision),
            marginal_contribution_bps=base.rate_decision_bps - treatment.rate_decision_bps,
            description=description, donor_behavior=donor_behavior,
            replicate_id=treatment.replicate_id, condition_id=treatment.condition_id,
            member_rate_changes_bps={m: treatment_votes[m].final_rate_vote_bps - v.final_rate_vote_bps for m, v in baseline_votes.items()},
            member_stance_changed={m: treatment_votes[m].final_stance_vote != v.final_stance_vote for m, v in baseline_votes.items()},
            study_experiment_id=base.experiment_id, baseline_condition_id=base.condition_id,
            evidence_types=sorted(set(base.evidence_types + treatment.evidence_types)),
        )

    @classmethod
    async def run_leave_one_out_ablation(
        cls, orchestrator: DebateOrchestrator, baseline_decision: MeetingCommitteeDecision,
        snapshot: MacroMeetingSnapshot, personas: Sequence[MemberPersona], governor_id: str,
        ablated_member_id: str, model: Optional[str] = None, temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> AttributionResult:
        paired = cls._paired_generation_settings(orchestrator, baseline_decision, snapshot, personas,
                                                governor_id, model, temperature, seed)
        treatment = await orchestrator.run_meeting(
            snapshot=snapshot, personas=personas, governor_id=governor_id,
            replicate_id=baseline_decision.replicate_id, **paired,
            ablated_member_id=ablated_member_id, experiment_id=baseline_decision.experiment_id,
            condition_id=f"{baseline_decision.condition_id}_outgoing_removed_{ablated_member_id}",
            control_mode=baseline_decision.control_mode,
            **cls._condition_settings(baseline_decision),
        )
        own_state_retained = baseline_decision.visibility.get("own_state", True)
        return cls._result(
            baseline_decision, treatment, f"EXP_1_LEAVE_OUT_{ablated_member_id.upper()}",
            f"Outgoing Information Removal ({ablated_member_id})",
            f"Simulator-local removal of {ablated_member_id}'s outgoing R1-R3 arguments, identities and Governor-visible R4 ballot. The donor's vote still counts, own-state visibility matches baseline ({own_state_retained}); all members may respond endogenously.",
            donor_behavior="own_state_retained_endogenous_ballot" if own_state_retained else "own_state_withheld_in_both_conditions_endogenous_ballot",
        )

    @classmethod
    async def run_macro_muting_ablation(
        cls, orchestrator: DebateOrchestrator, baseline_decision: MeetingCommitteeDecision,
        snapshot: MacroMeetingSnapshot, personas: Sequence[MemberPersona], governor_id: str,
        muted_factor: str, model: Optional[str] = None, temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> AttributionResult:
        paired = cls._paired_generation_settings(orchestrator, baseline_decision, snapshot, personas,
                                                governor_id, model, temperature, seed)
        treatment = await orchestrator.run_meeting(
            snapshot=cls.mute_macro_input(snapshot, muted_factor), personas=personas, governor_id=governor_id,
            replicate_id=baseline_decision.replicate_id, **paired,
            experiment_id=baseline_decision.experiment_id,
            condition_id=f"{baseline_decision.condition_id}_mute_{muted_factor}",
            control_mode=baseline_decision.control_mode,
            **cls._condition_settings(baseline_decision),
        )
        return cls._result(baseline_decision, treatment, f"EXP_3_MUTE_{muted_factor.upper()}",
                           f"Macro Input Sensitivity ({muted_factor})",
                           f"Simulator-local sensitivity to an explicitly synthetic {muted_factor} intervention; unrelated fields are preserved.")
