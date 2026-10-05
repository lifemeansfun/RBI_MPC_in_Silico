"""
Behavioral Track: Multi-Agent Deliberation and Voting Orchestrator.
Executes the 4-round deliberation cycle matching actual Reserve Bank of India MPC meetings:
Round 1: Independent Initial Stance (Parallel, private context)
Round 2: Rebuttal & Cross-Examination (Parallel, structured deliberation matrix)
Round 3: Deliberation & Compromise Testing (Parallel, consensus assessment)
Round 4: Final Binding Vote (Sequential statutory voting, Governor votes last)
Followed by statutory decision aggregation via InstitutionalRuleEngine (RBI Act §45ZL).

INCORPORATES COMPREHENSIVE DEFENSES:
- Strict Schema Validation & Action Snapping
- Bounded Retries & Model Fallback Rotation
- Defensive Heuristic Fallbacks on API Outage/Exhaustion
- Anti-Hallucination Negative Constraints grounded in official macro briefings
- Temporal Boundary Injections (Strictly preventing post-meeting look-ahead leakage)
- Anti-Sycophancy Dissent Mandate (Protecting external members' academic autonomy)
- Structured Deliberation Context Matrix to prevent context drift and hallucinated turns
"""

import asyncio
import re
import logging
from typing import Sequence, Optional

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import (
    InitialStanceOutput,
    DeliberationOutput,
    FinalVoteOutput,
    MeetingCommitteeDecision,
)
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.rule_engine.engine import InstitutionalRuleEngine

logger = logging.getLogger("rbi_mpc.debate")


class DebateOrchestrator:
    """Orchestrates 6 LLM agents through a structured 4-round MPC deliberation with defensive guardrails."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        logger: Optional[TranscriptLogger] = None,
    ):
        self.client = llm_client or LLMClient()
        self.logger = logger or TranscriptLogger()

    async def run_meeting(
        self,
        snapshot: MacroMeetingSnapshot,
        personas: Sequence[MemberPersona],
        governor_id: str,
        replicate_id: int = 1,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        ablated_member_id: Optional[str] = None,
    ) -> MeetingCommitteeDecision:
        """Executes full 4-round deliberation for a single meeting replicate.
        If ablated_member_id is provided, withholds that member's arguments from peer context (Experiment 1)."""
        if len(personas) != 6:
            raise ValueError(f"RBI MPC requires exactly 6 members; got {len(personas)}")

        meeting_date = snapshot.meeting_date
        macro_text = snapshot.to_prompt_text()
        fallbacks_count = 0

        # =========================================================================
        # ROUND 1: Independent Initial Stance
        # =========================================================================
        logger.info("[%s:Rep%d] Round 1: Gathering independent initial stances...", meeting_date, replicate_id)
        r1_tasks = [
            self._execute_round_1_stance(persona, snapshot, macro_text, model, temperature)
            for persona in personas
        ]
        r1_results: list[InitialStanceOutput] = await asyncio.gather(*r1_tasks)

        for persona, r1 in zip(personas, r1_results):
            if r1.fallback_triggered:
                fallbacks_count += 1
            self.logger.save_round_transcript(
                meeting_date=meeting_date,
                replicate_id=replicate_id,
                round_number=1,
                member_id=persona.member_id,
                payload=r1.model_dump(),
            )

        # Build Structured Round 1 Matrix to prevent context loss (with ablation filter)
        r1_matrix_lines = [
            "=== COMMITTEE DELIBERATION MATRIX (ROUND 1 INITIAL STANCES) ===",
            "| Member Name | Role | Proposed Rate Change | Stance Preference | Key Macro Rationale |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for p, r in zip(personas, r1_results):
            if ablated_member_id and p.member_id == ablated_member_id:
                continue
            r1_matrix_lines.append(
                f"| {p.name} | {p.role} | {r.proposed_rate_change_bps:+d} bps | `{r.proposed_stance}` | {r.key_rationale} |"
            )
            
        r1_matrix_lines.append("\n=== CONFIDENTIAL STAFF SECRETARIAT FORECAST (LATENT VARIABLES) ===")
        r1_matrix_lines.append(self._generate_staff_forecast(snapshot))
        
        r1_matrix_text = "\n".join(r1_matrix_lines)

        # =========================================================================
        # ROUND 2: Rebuttal & Cross-Examination
        # =========================================================================
        logger.info("[%s:Rep%d] Round 2: Cross-examination and rebuttal...", meeting_date, replicate_id)
        r2_tasks = [
            self._execute_round_2_rebuttal(persona, snapshot, macro_text, r1_matrix_text, model, temperature)
            for persona in personas
        ]
        r2_results: list[DeliberationOutput] = await asyncio.gather(*r2_tasks)

        for persona, r2 in zip(personas, r2_results):
            if r2.fallback_triggered:
                fallbacks_count += 1
            self.logger.save_round_transcript(
                meeting_date=meeting_date,
                replicate_id=replicate_id,
                round_number=2,
                member_id=persona.member_id,
                payload=r2.model_dump(),
            )

        # Build Structured Round 2 Matrix (with ablation filter)
        r2_matrix_lines = [
            "=== COMMITTEE DELIBERATION MATRIX (ROUND 2 CRITIQUES & REBUTTALS) ===",
            "| Member Name | Preferred Rate | Stance | Open to Compromise? | Rebuttal Focus |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for p, r2 in zip(personas, r2_results):
            if ablated_member_id and p.member_id == ablated_member_id:
                continue
            comp = "Yes" if r2.open_to_compromise else "No"
            r2_matrix_lines.append(
                f"| {p.name} | {r2.current_rate_preference_bps:+d} bps | `{r2.current_stance_preference}` | {comp} | {r2.rebuttal_or_critique} |"
            )
        r2_matrix_text = "\n".join(r2_matrix_lines)

        # =========================================================================
        # ROUND 3: Deliberation & Compromise Testing
        # =========================================================================
        logger.info("[%s:Rep%d] Round 3: Deliberation and compromise assessment...", meeting_date, replicate_id)
        r3_tasks = [
            self._execute_round_3_deliberation(
                persona, snapshot, macro_text, r1_matrix_text, r2_matrix_text, model, temperature
            )
            for persona in personas
        ]
        r3_results: list[DeliberationOutput] = await asyncio.gather(*r3_tasks)

        for persona, r3 in zip(personas, r3_results):
            if r3.fallback_triggered:
                fallbacks_count += 1
            self.logger.save_round_transcript(
                meeting_date=meeting_date,
                replicate_id=replicate_id,
                round_number=3,
                member_id=persona.member_id,
                payload=r3.model_dump(),
            )

        # Compact summary of the deliberation synthesis
        deliberation_digest = f"{r1_matrix_text}\n\n{r2_matrix_text}"

        # =========================================================================
        # ROUND 4: Final Binding Vote
        # Non-governors vote first; Governor votes last with awareness of colleagues
        # =========================================================================
        logger.info("[%s:Rep%d] Round 4: Casting binding votes...", meeting_date, replicate_id)
        final_votes: list[FinalVoteOutput] = []

        non_governors = [p for p in personas if p.member_id != governor_id]
        governor_persona = next(p for p in personas if p.member_id == governor_id)

        # Non-governors vote in parallel
        non_gov_tasks = [
            self._execute_round_4_vote(
                p, snapshot, macro_text, deliberation_digest, model, temperature
            )
            for p in non_governors
        ]
        non_gov_votes: list[FinalVoteOutput] = await asyncio.gather(*non_gov_tasks)
        final_votes.extend(non_gov_votes)

        # Build non-governor vote summary for the Governor
        prior_votes_lines = [
            "=== BINDING VOTES CAST BY COMMITTEE MEMBERS ===",
            "| Member Name | Rate Vote | Stance Vote | Formal Rationale Summary |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for v in non_gov_votes:
            prior_votes_lines.append(
                f"| {v.member_name} | {v.final_rate_vote_bps:+d} bps | `{v.final_stance_vote}` | {v.official_statement_rationale[:120]}... |"
            )
        prior_votes_text = "\n".join(prior_votes_lines)

        gov_context = f"{deliberation_digest}\n\n{prior_votes_text}"
        gov_vote = await self._execute_round_4_vote(
            governor_persona, snapshot, macro_text, gov_context, model, temperature
        )
        final_votes.append(gov_vote)

        for v in final_votes:
            if v.fallback_triggered:
                fallbacks_count += 1
            self.logger.save_round_transcript(
                meeting_date=meeting_date,
                replicate_id=replicate_id,
                round_number=4,
                member_id=v.member_id,
                payload=v.model_dump(),
            )

        # =========================================================================
        # INSTITUTIONAL RULE ENGINE AGGREGATION (§45ZL)
        # =========================================================================
        rate_votes = {v.member_id: v.final_rate_vote_bps for v in final_votes}
        stance_votes = {v.member_id: v.final_stance_vote for v in final_votes}

        rate_res = InstitutionalRuleEngine.aggregate_rate_votes(rate_votes, governor_id=governor_id)
        stance_res = InstitutionalRuleEngine.aggregate_stance_votes(stance_votes, governor_id=governor_id)

        # Verify dissent consistency
        for v in final_votes:
            v.dissenting_on_rate = (v.member_id in rate_res.dissenting_members)
            v.dissenting_on_stance = (v.member_id in stance_res.dissenting_members)

        decision = MeetingCommitteeDecision(
            meeting_date=meeting_date,
            replicate_id=replicate_id,
            rate_decision_bps=rate_res.winning_action,
            stance_decision=stance_res.winning_action,
            rate_vote_tally=rate_res.vote_tally,
            stance_vote_tally=stance_res.vote_tally,
            tie_broken_by_governor_rate=rate_res.tie_broken_by_governor,
            tie_broken_by_governor_stance=stance_res.tie_broken_by_governor,
            dissenting_members_rate=rate_res.dissenting_members,
            dissenting_members_stance=stance_res.dissenting_members,
            member_votes=final_votes,
            fallbacks_count=fallbacks_count,
        )

        self.logger.save_meeting_summary(
            meeting_date=meeting_date,
            replicate_id=replicate_id,
            summary=decision.model_dump(),
        )

        return decision

    # =========================================================================
    # ROUND IMPLEMENTATIONS WITH DEFENSIVE EXCEPTION HANDLING & ANTI-HALLUCINATION
    # =========================================================================

    def _generate_staff_forecast(self, snapshot: MacroMeetingSnapshot) -> str:
        """
        Generates synthetic unobservable latent variables (SPF & Greenbook proxy)
        to mitigate the Absence of Unobservable Latent Variables vulnerability.
        """
        # Simple rule-based generation of forward-looking expectations based on current gaps
        expected_cpi_1yr = snapshot.cpi_headline_yoy_pct - 0.25 * (snapshot.cpi_headline_yoy_pct - 4.0)
        expected_gdp_1yr = (snapshot.gva_growth_yoy_pct or 6.5) + 0.1 * (snapshot.output_gap_pct or 0.0)
        
        lines = [
            "- Survey of Professional Forecasters (SPF) 1-Year Ahead CPI Expectation: {:.2f}%".format(expected_cpi_1yr),
            "- SPF 1-Year Ahead Real GDP Growth Expectation: {:.2f}%".format(expected_gdp_1yr),
            "- Internal Systemic Liquidity Stress Index: {}".format("Elevated" if (snapshot.system_liquidity_cr or 0) < -50000 else "Normal"),
            "- Market-Implied Forward Rate Premium: {:.2f} bps".format((expected_cpi_1yr - 4.0) * 10),
            "(Note: This confidential data must be factored into your subsequent deliberations.)"
        ]
        return "\n".join(lines)

    def _build_temporal_boundary_header(self, meeting_date: str) -> str:
        """Constructs rigid temporal fence preventing look-ahead leakage."""
        year = meeting_date.split("-")[0]
        return (
            f"TEMPORAL BOUNDARY MANDATE:\n"
            f"Today is {meeting_date}. You have strictly ZERO knowledge of events after this date.\n"
            f"You MUST NOT mention any events, inflation prints, wars, or years occurring after {year}.\n"
            f"Any reference to future events violates the institutional simulation protocol."
        )

    def _build_dissent_protection_header(self, persona: MemberPersona) -> str:
        """Incentivizes independent statutory posture and prevents echo-chamber sycophancy."""
        if not persona.is_internal or persona.hawk_dove_score < 0:
            return (
                f"INSTITUTIONAL INDEPENDENCE MANDATE:\n"
                f"You are an independent statutory member ({persona.role}). Your core priority is: '{persona.voting_priority}'.\n"
                f"You are NOT evaluated on reaching artificial consensus. If the emerging committee stance departs\n"
                f"from your core economic convictions, you are duty-bound by statute to record a formal dissent."
            )
        return ""

    def _scan_lookahead_leakage(self, text: str, meeting_date: str) -> None:
        """Scans output text and logs warnings if future years are cited."""
        meeting_year = int(meeting_date.split("-")[0])
        found_years = re.findall(r"\b(202[0-9]|203[0-9])\b", text)
        for y_str in found_years:
            if int(y_str) > meeting_year:
                logger.warning(
                    "Potential look-ahead leakage detected for meeting %s: cited year %s in text.",
                    meeting_date, y_str
                )

    async def _execute_round_1_stance(
        self,
        persona: MemberPersona,
        snapshot: MacroMeetingSnapshot,
        macro_text: str,
        model: Optional[str],
        temp: Optional[float],
    ) -> InitialStanceOutput:
        temporal_rule = self._build_temporal_boundary_header(snapshot.meeting_date)
        user_prompt = f"""{temporal_rule}

{macro_text}

TASK: Round 1 — Initial Independent Stance.
Based strictly on the macroeconomic data and your authentic economic philosophy, formulate your initial policy stance.

ANTI-HALLUCINATION MANDATE:
1. Cite ONLY the numbers provided above (e.g. CPI {snapshot.cpi_headline_yoy_pct:.2f}%, Repo {snapshot.current_repo_rate_pct:.2f}%). Do NOT fabricate statistics.
2. Ground your reasoning in your persona mandate: {persona.voting_priority}.

OUTPUT STRICT JSON FORMAT ONLY:
{{
  "member_id": "{persona.member_id}",
  "member_name": "{persona.name}",
  "proposed_rate_change_bps": 0,  // integer: -50, -25, 0, 25, 35, 40, 50
  "proposed_stance": "withdrawal_of_accommodation", // one of: withdrawal_of_accommodation, neutral, accommodative
  "key_rationale": "2-3 sentences explaining your macroeconomic rationale."
}}"""
        try:
            _, parsed = await self.client.generate(
                user_prompt=user_prompt,
                system_prompt=persona.build_system_prompt(),
                model=model,
                temperature=temp,
                response_schema=InitialStanceOutput,
            )
            if parsed is not None:
                self._scan_lookahead_leakage(parsed.key_rationale, snapshot.meeting_date)
                return parsed
        except Exception as e:
            logger.warning("[%s] Round 1 generation failed (%s). Triggering defensive fallback.", persona.member_id, e)

        # Calibrated Heuristic Fallback
        fallback_rate = self._compute_defensive_rate_heuristic(persona, snapshot)
        return InitialStanceOutput(
            member_id=persona.member_id,
            member_name=persona.name,
            proposed_rate_change_bps=fallback_rate,
            proposed_stance=persona.stance_bias or snapshot.prev_stance,
            key_rationale="Cautious posture balancing inflation persistence against growth momentum.",
            fallback_triggered=True,
        )

    async def _execute_round_2_rebuttal(
        self,
        persona: MemberPersona,
        snapshot: MacroMeetingSnapshot,
        macro_text: str,
        deliberation_matrix: str,
        model: Optional[str],
        temp: Optional[float],
    ) -> DeliberationOutput:
        temporal_rule = self._build_temporal_boundary_header(snapshot.meeting_date)
        user_prompt = f"""{temporal_rule}

{macro_text}

{deliberation_matrix}

TASK: Round 2 — Committee Rebuttal and Cross-Examination.
Review your colleagues' initial stances above. Directly evaluate their arguments from your distinct policy perspective.

ANTI-HALLUCINATION MANDATE:
Do not invent facts or positions outside the deliberation matrix and official briefing.

OUTPUT STRICT JSON FORMAT ONLY:
{{
  "member_id": "{persona.member_id}",
  "round_number": 2,
  "current_rate_preference_bps": 0,
  "current_stance_preference": "withdrawal_of_accommodation",
  "rebuttal_or_critique": "Your critical evaluation of peers' arguments.",
  "open_to_compromise": false
}}"""
        try:
            _, parsed = await self.client.generate(
                user_prompt=user_prompt,
                system_prompt=persona.build_system_prompt(),
                model=model,
                temperature=temp,
                response_schema=DeliberationOutput,
            )
            if parsed is not None:
                self._scan_lookahead_leakage(parsed.rebuttal_or_critique, snapshot.meeting_date)
                return parsed
        except Exception as e:
            logger.warning("[%s] Round 2 generation failed (%s). Triggering defensive fallback.", persona.member_id, e)

        fallback_rate = self._compute_defensive_rate_heuristic(persona, snapshot)
        return DeliberationOutput(
            member_id=persona.member_id,
            round_number=2,
            current_rate_preference_bps=fallback_rate,
            current_stance_preference=persona.stance_bias or snapshot.prev_stance,
            rebuttal_or_critique="Reiterate importance of maintaining equilibrium monetary conditions.",
            open_to_compromise=False,
            fallback_triggered=True,
        )

    async def _execute_round_3_deliberation(
        self,
        persona: MemberPersona,
        snapshot: MacroMeetingSnapshot,
        macro_text: str,
        r1_matrix: str,
        r2_matrix: str,
        model: Optional[str],
        temp: Optional[float],
    ) -> DeliberationOutput:
        temporal_rule = self._build_temporal_boundary_header(snapshot.meeting_date)
        dissent_mandate = self._build_dissent_protection_header(persona)
        user_prompt = f"""{temporal_rule}

{dissent_mandate}

{macro_text}

{r1_matrix}

{r2_matrix}

TASK: Round 3 — Deliberation & Consensus Assessment.
Assess the emerging committee consensus. Indicate whether you are willing to compromise or hold your ground before the binding vote.

OUTPUT STRICT JSON FORMAT ONLY:
{{
  "member_id": "{persona.member_id}",
  "round_number": 3,
  "current_rate_preference_bps": 0,
  "current_stance_preference": "withdrawal_of_accommodation",
  "rebuttal_or_critique": "Final deliberation assessment.",
  "open_to_compromise": true
}}"""
        try:
            _, parsed = await self.client.generate(
                user_prompt=user_prompt,
                system_prompt=persona.build_system_prompt(),
                model=model,
                temperature=temp,
                response_schema=DeliberationOutput,
            )
            if parsed is not None:
                self._scan_lookahead_leakage(parsed.rebuttal_or_critique, snapshot.meeting_date)
                return parsed
        except Exception as e:
            logger.warning("[%s] Round 3 generation failed (%s). Triggering defensive fallback.", persona.member_id, e)

        fallback_rate = self._compute_defensive_rate_heuristic(persona, snapshot)
        return DeliberationOutput(
            member_id=persona.member_id,
            round_number=3,
            current_rate_preference_bps=fallback_rate,
            current_stance_preference=persona.stance_bias or snapshot.prev_stance,
            rebuttal_or_critique="Position maintained based on macroeconomic risk assessment.",
            open_to_compromise=False,
            fallback_triggered=True,
        )

    async def _execute_round_4_vote(
        self,
        persona: MemberPersona,
        snapshot: MacroMeetingSnapshot,
        macro_text: str,
        deliberation_history: str,
        model: Optional[str],
        temp: Optional[float],
    ) -> FinalVoteOutput:
        temporal_rule = self._build_temporal_boundary_header(snapshot.meeting_date)
        dissent_mandate = self._build_dissent_protection_header(persona)
        user_prompt = f"""{temporal_rule}

{dissent_mandate}

{macro_text}

{deliberation_history}

TASK: Round 4 — Binding Statutory Vote.
Cast your official, binding vote on the Policy Repo Rate change and Policy Stance.
Provide your signed statement paragraph for the official RBI MPC minutes.

OUTPUT STRICT JSON FORMAT ONLY:
{{
  "member_id": "{persona.member_id}",
  "member_name": "{persona.name}",
  "is_internal": {str(persona.is_internal).lower()},
  "final_rate_vote_bps": 0,
  "final_stance_vote": "withdrawal_of_accommodation",
  "dissenting_on_rate": false,
  "dissenting_on_stance": false,
  "official_statement_rationale": "Formal signed statement paragraph for official publication in the minutes."
}}"""
        try:
            _, parsed = await self.client.generate(
                user_prompt=user_prompt,
                system_prompt=persona.build_system_prompt(),
                model=model,
                temperature=temp,
                response_schema=FinalVoteOutput,
            )
            if parsed is not None:
                self._scan_lookahead_leakage(parsed.official_statement_rationale, snapshot.meeting_date)
                return parsed
        except Exception as e:
            logger.warning("[%s] Round 4 generation failed (%s). Triggering defensive fallback.", persona.member_id, e)

        fallback_rate = self._compute_defensive_rate_heuristic(persona, snapshot)
        fallback_stance = persona.stance_bias or snapshot.prev_stance
        return FinalVoteOutput(
            member_id=persona.member_id,
            member_name=persona.name,
            is_internal=persona.is_internal,
            final_rate_vote_bps=fallback_rate,
            final_stance_vote=fallback_stance,
            dissenting_on_rate=(fallback_rate != 0),
            dissenting_on_stance=(fallback_stance != "withdrawal_of_accommodation"),
            official_statement_rationale=f"I vote for a rate action of {fallback_rate:+d} bps and stance of {fallback_stance.replace('_', ' ')} based on calibrated macroeconomic vigilance.",
            fallback_triggered=True,
        )

    @staticmethod
    def _compute_defensive_rate_heuristic(persona: MemberPersona, snapshot: MacroMeetingSnapshot) -> int:
        """
        Calibrated economic heuristic used strictly as emergency fallback
        if external LLM API is unreachable or exhausted.
        """
        inflation_gap = snapshot.cpi_headline_yoy_pct - 4.00
        hawk_bias = persona.hawk_dove_score

        # Taylor-style directional bias adjusted by member hawk-dove orientation
        signal = 0.5 * inflation_gap + 0.25 * (snapshot.output_gap_pct or 0.0) + 0.5 * hawk_bias

        if signal > 1.2:
            return 50
        elif signal > 0.6:
            return 25
        elif signal < -0.8 and hawk_bias < -0.2:
            return -25
        return 0
